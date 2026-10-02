"""`video_bokeh.library.check` says whether a depth estimator will run here."""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path
from types import SimpleNamespace

import huggingface_hub
import huggingface_hub.constants
import pytest
import torch

from video_bokeh.library import check
from video_bokeh.library.depth import ESTIMATORS

# Estimators of the user's own, the way a plugin would live outside this package. Their
# checkpoints are fake Hugging Face repos laid out by `fake_cache` below.
_PLUGINS = """
import numpy as np


class Ready:
    hf_model_id = "test-org/small"

    def load(self, device):
        pass

    def infer(self, images):
        return [np.zeros((im.height, im.width), np.float32) for im in images]


class Sharded(Ready):
    hf_model_id = "test-org/sharded"


class Huge(Ready):
    hf_model_id = "test-org/huge"


class OnTheHub(Ready):
    hf_model_id = "test-org/not-cached"


class Gated(Ready):
    hf_model_id = "test-org/gated"


class Unknown(Ready):
    hf_model_id = ""


class NoEnvironment(Ready):
    @classmethod
    def environment_problem(cls):
        return "no interpreter at /nowhere: run setup.sh"


class OutOfProcess(Unknown):
    # Holds its weights in another process, the way Depth Anything 3 does.
    def peak_memory(self):
        return 123_456_789


class Chatty(Unknown):
    # Prints after its figures, from an exit handler, the way a library might.
    def load(self, device):
        import atexit

        print("loading my own way")
        atexit.register(print, "goodbye from an exit handler")


class Crashes(Unknown):
    def load(self, device):
        raise MemoryError("out of memory, the way a large model on a small GPU fails")


class Heavy(Unknown):
    def load(self, device):
        # A gigabyte, touched, so it is resident rather than merely reserved, and well
        # above what importing torch leaves behind as a peak.
        self._ballast = np.ones(1_000_000_000 // 8)
"""


def _write_safetensors_header(path: Path, shapes: dict[str, list[int]]) -> None:
    """A safetensors file's header alone, which is all the check reads."""
    header = {
        name: {"dtype": "F32", "shape": shape, "data_offsets": [0, 0]}
        for name, shape in shapes.items()
    }
    raw = json.dumps(header).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack("<Q", len(raw)) + raw)


def _snapshot(cache: Path, repo: str) -> Path:
    folder = cache / f"models--{repo.replace('/', '--')}"
    (folder / "refs").mkdir(parents=True)
    (folder / "refs" / "main").write_text("abc123")
    return folder / "snapshots" / "abc123"


@pytest.fixture
def plugins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    (tmp_path / "check_plugins.py").write_text(_PLUGINS, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    return "check_plugins"


@pytest.fixture
def fake_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cache = tmp_path / "hf-cache"
    small = _snapshot(cache, "test-org/small")
    _write_safetensors_header(small / "model.safetensors", {"w": [100, 10], "b": [10]})

    sharded = _snapshot(cache, "test-org/sharded")
    (sharded / "model.safetensors.index.json").parent.mkdir(parents=True)
    (sharded / "model.safetensors.index.json").write_text(
        json.dumps(
            {
                # Two tensors in the first shard, so a shard named twice in the map
                # must still be counted once.
                "weight_map": {
                    "a": "model-00001-of-00002.safetensors",
                    "c": "model-00001-of-00002.safetensors",
                    "b": "model-00002-of-00002.safetensors",
                },
            },
        ),
    )
    _write_safetensors_header(
        sharded / "model-00001-of-00002.safetensors",
        {"a": [7], "c": [3]},
    )
    _write_safetensors_header(sharded / "model-00002-of-00002.safetensors", {"b": [5]})

    # Four tebibytes of float32, more than any machine this runs on has.
    huge = _snapshot(cache, "test-org/huge")
    _write_safetensors_header(huge / "model.safetensors", {"w": [2**40]})

    monkeypatch.setattr(huggingface_hub.constants, "HF_HUB_CACHE", str(cache))
    return cache


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The Hub, the one network boundary. It knows `test-org/not-cached`, in two dtypes,
    and fails for anything else the way it does offline.
    """
    asked: list[str] = []

    def _metadata(repo: str) -> SimpleNamespace:
        asked.append(repo)
        if repo != "test-org/not-cached":
            raise OSError("offline")
        return SimpleNamespace(parameter_count={"F32": 40, "F16": 2})

    monkeypatch.setattr(huggingface_hub, "get_safetensors_metadata", _metadata)
    return asked


CPU = torch.device("cpu")


@pytest.mark.usefixtures("fake_cache")
def test_weights_come_from_the_cached_checkpoint(plugins: str, hub: list[str]) -> None:
    report = check.assess(f"{plugins}:Ready", check.describe_device("cpu"))
    assert report.weights == check.Weights(params=1010, cached=True)
    assert report.weights.bytes == 1010 * 4
    assert report.verdict == "ready"
    assert hub == []


@pytest.mark.usefixtures("fake_cache", "hub")
def test_a_sharded_checkpoint_counts_every_shard(plugins: str) -> None:
    report = check.assess(f"{plugins}:Sharded", check.describe_device("cpu"))
    assert report.weights == check.Weights(params=15, cached=True)


@pytest.mark.usefixtures("fake_cache")
def test_a_checkpoint_the_hub_cannot_describe_has_unknown_weights(
    plugins: str,
    hub: list[str],
) -> None:
    """Offline, gated or missing: the check says unknown instead of failing."""
    report = check.assess(f"{plugins}:Gated", check.describe_device("cpu"))
    assert hub == ["test-org/gated"]
    assert report.weights is None
    assert report.verdict == "ready"


@pytest.mark.usefixtures("fake_cache")
def test_the_hub_is_asked_only_for_what_is_not_cached(
    plugins: str,
    hub: list[str],
) -> None:
    report = check.assess(f"{plugins}:OnTheHub", check.describe_device("cpu"))
    assert report.weights == check.Weights(params=42, cached=False)
    assert hub == ["test-org/not-cached"]


@pytest.mark.usefixtures("fake_cache", "hub")
def test_an_estimator_with_no_checkpoint_has_unknown_weights(plugins: str) -> None:
    report = check.assess(f"{plugins}:Unknown", check.describe_device("cpu"))
    assert report.weights is None
    assert report.verdict == "ready"


@pytest.mark.usefixtures("fake_cache", "hub")
def test_a_missing_environment_is_the_verdict_and_says_why(plugins: str) -> None:
    report = check.assess(f"{plugins}:NoEnvironment", check.describe_device("cpu"))
    assert report.verdict == "environment missing"
    assert report.environment_problem == "no interpreter at /nowhere: run setup.sh"


@pytest.mark.usefixtures("fake_cache", "hub")
def test_weights_larger_than_the_device_are_the_verdict(plugins: str) -> None:
    report = check.assess(f"{plugins}:Huge", check.describe_device("cpu"))
    assert report.verdict == "weights exceed memory"


def test_the_device_reports_its_memory() -> None:
    device = check.describe_device("cpu")
    assert device.resolved == CPU
    assert device.total > 0
    assert device.absent_reason is None


@pytest.mark.skipif(torch.cuda.is_available(), reason="needs a machine without CUDA")
def test_a_device_that_is_not_there_is_said_to_be_absent() -> None:
    """Stage A falls back to the CPU without a word; the check must not."""
    device = check.describe_device("cuda")
    assert device.resolved == CPU
    assert device.absent_reason is not None
    assert "cuda" in device.absent_reason


@pytest.mark.usefixtures("fake_cache", "hub")
def test_the_command_reports_every_estimator_and_the_caveat(
    plugins: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = check.main(
        [
            "--model",
            f"{plugins}:Ready",
            "--model",
            f"{plugins}:NoEnvironment",
            "--device",
            "cpu",
        ],
    )
    out = capsys.readouterr().out
    assert code == 1, "one estimator is not ready"
    assert f"{plugins}:Ready" in out
    assert "environment missing" in out
    assert "run setup.sh" in out
    assert "necessary, not sufficient" in out


@pytest.mark.usefixtures("fake_cache", "hub")
def test_every_registered_estimator_is_checked_by_default(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIDEO_BOKEH_DA3_PYTHON", sys.executable)
    check.main(["--device", "cpu"])
    out = capsys.readouterr().out
    assert all(name in out for name in ESTIMATORS)


def test_measuring_reports_time_and_memory(plugins: str) -> None:
    measured = check.measure(f"{plugins}:Ready", CPU)
    assert measured.load_s >= 0
    assert measured.per_image_s > 0
    assert measured.memory is not None
    assert measured.memory > 0


def test_each_estimator_is_measured_in_a_fresh_process(plugins: str) -> None:
    """The peak resident set never falls inside a process, so a heavy estimator
    measured first would otherwise lend its peak to every one after it.
    """
    before = check.measure(f"{plugins}:Ready", CPU)
    heavy = check.measure(f"{plugins}:Heavy", CPU)
    after = check.measure(f"{plugins}:Ready", CPU)
    assert before.memory is not None
    assert heavy.memory is not None
    assert after.memory is not None
    # The light one is what it was before the heavy one ran, and the heavy one is
    # heavier: compared with itself, not with a margin that depends on the platform's
    # import-time peak, which was 871 MB on a CI runner.
    assert after.memory < before.memory + 200_000_000
    assert heavy.memory > after.memory + 200_000_000


def test_an_estimator_holding_its_weights_elsewhere_reports_that_process(
    plugins: str,
) -> None:
    assert check.measure(f"{plugins}:OutOfProcess", CPU).memory == 123_456_789


@pytest.mark.usefixtures("fake_cache", "hub")
def test_an_estimator_that_fails_to_measure_leaves_the_others_reported(
    plugins: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Running out of memory is what --measure is for, so it is a row, not a crash."""
    code = check.main(
        [
            "--model",
            f"{plugins}:Crashes",
            "--model",
            f"{plugins}:Ready",
            "--device",
            "cpu",
            "--measure",
        ],
    )
    out = capsys.readouterr().out
    assert code == 1
    crashed = next(line for line in out.splitlines() if "Crashes" in line)
    ready = next(
        line for line in out.splitlines() if line.startswith(f"{plugins}:Ready")
    )
    assert "failed" in crashed
    assert " s " in ready
    assert "MemoryError" in out


def test_a_mistyped_estimator_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Refused before anything is checked, the way Stage A refuses it."""
    with pytest.raises(SystemExit) as excinfo:
        check.main(["--model", "da2-huge", "--device", "cpu"])
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "da2-huge" in err
    assert "da2-large" in err


@pytest.mark.usefixtures("fake_cache", "hub")
def test_a_local_checkpoint_directory_is_counted(tmp_path: Path) -> None:
    """transformers takes a directory in place of a Hub id, so a plugin may too."""
    local = tmp_path / "my-checkpoint"
    _write_safetensors_header(local / "model.safetensors", {"w": [3, 3]})
    estimator = type("Local", (), {"hf_model_id": str(local)})
    assert check.weights_of(estimator) == check.Weights(params=9, cached=True)


@pytest.mark.usefixtures("fake_cache", "hub")
def test_an_id_the_hub_would_refuse_reads_as_unknown_weights() -> None:
    estimator = type("Odd", (), {"hf_model_id": "not a/valid/repo id"})
    assert check.weights_of(estimator) is None


def test_an_estimator_that_prints_is_still_measured(plugins: str) -> None:
    measured = check.measure(f"{plugins}:Chatty", CPU)
    assert measured.per_image_s > 0


@pytest.mark.usefixtures("fake_cache", "hub")
def test_the_command_succeeds_when_every_estimator_is_ready(plugins: str) -> None:
    code = check.main(
        [
            "--model",
            f"{plugins}:Ready",
            "--model",
            f"{plugins}:Unknown",
            "--device",
            "cpu",
        ],
    )
    assert code == 0


@pytest.mark.usefixtures("fake_cache", "hub")
def test_a_load_that_had_weights_to_fetch_is_labelled(
    plugins: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Its load time includes the download, which a reader must not take for loading."""
    check.main(
        [
            "--model",
            f"{plugins}:OnTheHub",
            "--model",
            f"{plugins}:Ready",
            "--device",
            "cpu",
            "--measure",
        ],
    )
    lines = capsys.readouterr().out.splitlines()
    on_the_hub = next(line for line in lines if "OnTheHub" in line)
    cached = next(line for line in lines if line.startswith(f"{plugins}:Ready"))
    assert "(download)" in on_the_hub
    assert "(download)" not in cached
