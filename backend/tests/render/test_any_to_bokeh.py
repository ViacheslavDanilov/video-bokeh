"""Stage C through any-to-bokeh, with a fake standing in for its CUDA-only demo script."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from video_bokeh.core._streams import write_alpha_tiff, write_disparity_png
from video_bokeh.core._worker import WorkerError
from video_bokeh.render import RENDERERS
from video_bokeh.render import any_to_bokeh as a2b_module
from video_bokeh.render import run as cli
from video_bokeh.render.any_to_bokeh import AnyToBokeh

# Thirteen: the real demo fails on twelve or fewer, so a shorter fixture would test a
# fake that accepts what the real script rejects.
FRAMES, SIZE = 13, 32

# Reads the CSV the way the real demo does and writes one mp4 per row into output/ in its
# working directory, at the demo's fixed 1024x576. Frame t of row i is grey level
# 40 + 100 * i + 8 * t, so a test can tell which output went where. It records what it
# was given in $FAKE_LOG, and the name of the VAE encoder's forward it ran with.
_FAKE_DEMO = """
import argparse, csv, json, os
import imageio.v2 as imageio
import numpy as np
from models.vae import Encoder

p = argparse.ArgumentParser()
p.add_argument("--val_csv_path")
p.add_argument("--unet_path")
p.add_argument("--vae_path")
a = p.parse_args()
assert os.path.isdir(a.unet_path) and os.path.isdir(a.vae_path), (a.unet_path, a.vae_path)
rows = list(csv.DictReader(open(a.val_csv_path)))
drop_last = os.environ.get("FAKE_DROP_LAST") == "1"
os.makedirs("output", exist_ok=True)
for i, row in enumerate(rows):
    frames = sorted(os.listdir(row["aif_folder"]))
    short = drop_last and i == len(rows) - 1
    writer = imageio.get_writer(f"output/{i}.mp4", fps=20, codec="libx264", quality=8)
    for t in range(len(frames) - short):
        writer.append_data(np.full((576, 1024, 3), 40 + 100 * i + 8 * t, np.uint8))
    writer.close()
log = {
    "rows": rows,
    "disp": [sorted(os.listdir(r["disp_folder"])) for r in rows],
    "encoder": Encoder.forward.__name__,
}
json.dump(log, open(os.environ["FAKE_LOG"], "w"))
if os.environ.get("FAKE_FAIL"):
    raise SystemExit("CUDA error: no kernel image is available")
"""


def _write_sequence(seq: Path, frames: int = FRAMES) -> None:
    for t in range(1, frames + 1):
        stem = f"{t:02d}"
        (seq / "all_in_focus").mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (SIZE, SIZE), (100, 120, 140)).save(
            seq / "all_in_focus" / f"{stem}.png",
        )
        mask = np.zeros((SIZE, SIZE), np.float32)
        mask[8:24, 8:24] = 1.0
        (seq / "alpha").mkdir(exist_ok=True)
        write_alpha_tiff(seq / "alpha" / f"{stem}.tif", [mask])
        (seq / "disparity").mkdir(exist_ok=True)
        disparity = np.tile(np.linspace(0.0, 1.0, SIZE, dtype=np.float32), (SIZE, 1))
        write_disparity_png(seq / "disparity" / f"{stem}.png", disparity)


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    root = tmp_path / "dataset"
    for name in ("0001", "0002"):
        _write_sequence(root / "sequences" / name)
    return root


@pytest.fixture
def fake_a2b(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "any-to-bokeh"
    (root / "test").mkdir(parents=True)
    (root / "test" / "inference_demo.py").write_text(_FAKE_DEMO, encoding="utf-8")
    (root / "models").mkdir()
    (root / "models" / "vae.py").write_text(
        "class Encoder:\n    def forward(self, sample, cache_flag=False):\n"
        "        return sample\n",
        encoding="utf-8",
    )
    (root / "pipelines").mkdir()
    (root / "pipelines" / "any2bokeh_pipe.py").write_text(
        "class StableVideoDiffusionPipeline:\n    def decode_latents(self):\n"
        "        pass\n",
        encoding="utf-8",
    )
    for sub in ("unet", "vae"):
        (root / "checkpoints" / sub).mkdir(parents=True)
    monkeypatch.setenv("VIDEO_BOKEH_A2B_ROOT", str(root))
    monkeypatch.setenv("VIDEO_BOKEH_A2B_PYTHON", sys.executable)
    monkeypatch.setenv("FAKE_LOG", str(tmp_path / "fake_log.json"))
    return root


def _sequences(dataset: Path) -> list[Path]:
    return sorted((dataset / "sequences").iterdir())


def test_registered() -> None:
    assert RENDERERS["any-to-bokeh"] is AnyToBokeh


@pytest.mark.usefixtures("fake_a2b")
def test_writes_a_bokeh_frame_per_frame_at_the_sequence_size(dataset: Path) -> None:
    AnyToBokeh().render(_sequences(dataset), strength=16, focus_disparity=None)

    for i, seq in enumerate(_sequences(dataset)):
        names = sorted(p.name for p in (seq / "bokeh").iterdir())
        assert names == sorted(p.name for p in (seq / "all_in_focus").iterdir())
        for t, name in enumerate(names):
            img = Image.open(seq / "bokeh" / name)
            assert img.mode == "RGB"
            assert img.size == (SIZE, SIZE)
            # Each sequence gets its own row's output, frame by frame; the mp4 is lossy.
            assert abs(np.asarray(img).mean() - (40 + 100 * i + 8 * t)) < 4


@pytest.mark.usefixtures("fake_a2b")
def test_the_bokeh_stream_is_as_readable_as_the_others(dataset: Path) -> None:
    # Whoever can read a sequence's all_in_focus/ must be able to read its bokeh/ too.
    AnyToBokeh().render(_sequences(dataset), strength=16, focus_disparity=None)
    for seq in _sequences(dataset):
        assert (seq / "bokeh").stat().st_mode == (seq / "all_in_focus").stat().st_mode


def test_leaves_the_submodule_untouched(dataset: Path, fake_a2b: Path) -> None:
    before = sorted(p.relative_to(fake_a2b) for p in fake_a2b.rglob("*"))
    AnyToBokeh().render(_sequences(dataset), strength=16, focus_disparity=None)
    assert sorted(p.relative_to(fake_a2b) for p in fake_a2b.rglob("*")) == before


@pytest.mark.usefixtures("fake_a2b")
def test_the_demo_runs_with_the_encoder_chunked(dataset: Path, tmp_path: Path) -> None:
    AnyToBokeh().render(_sequences(dataset)[:1], strength=16, focus_disparity=None)
    log = json.loads((tmp_path / "fake_log.json").read_text())
    assert log["encoder"] == "chunked"


@pytest.mark.usefixtures("fake_a2b")
def test_passes_strength_and_a_fixed_focus(dataset: Path, tmp_path: Path) -> None:
    AnyToBokeh().render(_sequences(dataset)[:1], strength=24, focus_disparity=0.5)
    log = json.loads((tmp_path / "fake_log.json").read_text())
    assert log["rows"][0]["k"] == "24"
    assert all("_zf_0.500000" in name for name in log["disp"][0])


@pytest.mark.usefixtures("fake_a2b")
def test_a_frame_count_mismatch_writes_nothing(
    dataset: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Only the last sequence comes back short, so the first would already be written by
    # a renderer that checked and wrote one sequence at a time.
    monkeypatch.setenv("FAKE_DROP_LAST", "1")
    with pytest.raises(RuntimeError, match=f"{FRAMES - 1} frames for {FRAMES} in 0002"):
        AnyToBokeh().render(_sequences(dataset), strength=16, focus_disparity=None)
    for seq in _sequences(dataset):
        assert not (seq / "bokeh").exists()
        assert not list(seq.glob(".bokeh-*"))


@pytest.mark.usefixtures("fake_a2b")
def test_a_failed_inference_says_why(
    dataset: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_FAIL", "1")
    with pytest.raises(WorkerError, match="CUDA error"):
        AnyToBokeh().render(_sequences(dataset), strength=16, focus_disparity=None)


def test_missing_checkpoints_name_the_setup_script(
    dataset: Path,
    fake_a2b: Path,
) -> None:
    (fake_a2b / "checkpoints" / "vae").rmdir()
    with pytest.raises(RuntimeError, match="setup_third_party.sh"):
        AnyToBokeh().render(_sequences(dataset), strength=16, focus_disparity=None)


@pytest.mark.usefixtures("fake_a2b")
def test_the_command_renders_the_chosen_sequences(dataset: Path) -> None:
    assert cli.main(["--data-root", str(dataset), "--seqs", "0002"]) == 0
    assert (dataset / "sequences" / "0002" / "bokeh").is_dir()
    assert not (dataset / "sequences" / "0001" / "bokeh").exists()


def test_relative_paths_in_the_environment_still_work(
    dataset: Path,
    fake_a2b: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The demo runs from a temporary directory, so a relative root must not be read
    # from there.
    monkeypatch.chdir(fake_a2b.parent)
    monkeypatch.setenv("VIDEO_BOKEH_A2B_ROOT", fake_a2b.name)
    AnyToBokeh().render(_sequences(dataset)[:1], strength=16, focus_disparity=None)
    assert (_sequences(dataset)[0] / "bokeh").is_dir()


@pytest.mark.usefixtures("fake_a2b")
def test_a_sequence_too_short_to_group_is_refused_before_the_model_runs(
    dataset: Path,
    tmp_path: Path,
) -> None:
    """any-to-bokeh fails on twelve frames or fewer, after the model has loaded, and
    takes the whole batch down with it.
    """
    _write_sequence(dataset / "sequences" / "0003", frames=12)
    with pytest.raises(ValueError, match=r"at least 13 frames.*0003 has 12 frames"):
        AnyToBokeh().render(_sequences(dataset), strength=16, focus_disparity=None)
    assert not (tmp_path / "fake_log.json").exists(), "the demo must not have started"
    assert not any((seq / "bokeh").exists() for seq in _sequences(dataset))


def _rendered(tmp_path: Path) -> list[str]:
    """The sequences the fake demo was handed, by name."""
    log = json.loads((tmp_path / "fake_log.json").read_text())
    return [Path(row["aif_folder"]).name for row in log["rows"]]


@pytest.mark.usefixtures("fake_a2b")
def test_missing_renders_only_the_sequences_without_bokeh(
    dataset: Path,
    tmp_path: Path,
) -> None:
    cli.main(["--data-root", str(dataset), "--seqs", "0001"])
    assert cli.main(["--data-root", str(dataset), "--missing"]) == 0
    assert _rendered(tmp_path) == ["0002"]


@pytest.mark.usefixtures("fake_a2b")
def test_missing_skips_what_the_renderer_cannot_take(
    dataset: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The page can make a sequence too short for any-to-bokeh; that must not block the
    sequences beside it, as handing it over would.
    """
    _write_sequence(dataset / "sequences" / "0003", frames=12)
    assert cli.main(["--data-root", str(dataset), "--missing"]) == 0
    assert _rendered(tmp_path) == ["0001", "0002"]
    assert not (dataset / "sequences" / "0003" / "bokeh").exists()
    assert "0003" in capsys.readouterr().out


@pytest.mark.usefixtures("fake_a2b")
def test_missing_with_nothing_left_starts_nothing(
    dataset: Path,
    tmp_path: Path,
) -> None:
    cli.main(["--data-root", str(dataset)])
    (tmp_path / "fake_log.json").unlink()
    assert cli.main(["--data-root", str(dataset), "--missing"]) == 0
    assert not (tmp_path / "fake_log.json").exists()


@pytest.mark.usefixtures("fake_a2b")
def test_a_sequence_still_being_written_is_not_a_sequence(
    dataset: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The API generates into `.tmp-*` beside the finished ones and renames it."""
    _write_sequence(dataset / "sequences" / ".tmp-abc123")
    assert cli.main(["--data-root", str(dataset)]) == 0
    assert _rendered(tmp_path) == ["0001", "0002"]
    assert ".tmp-abc123: still being written" in capsys.readouterr().out


@pytest.mark.usefixtures("fake_a2b")
def test_missing_before_the_page_made_anything_renders_nothing(
    tmp_path: Path,
) -> None:
    assert cli.main(["--data-root", str(tmp_path / "empty"), "--missing"]) == 0


@pytest.mark.usefixtures("fake_a2b")
def test_missing_over_a_page_still_writing_its_first_renders_nothing(
    tmp_path: Path,
) -> None:
    """The API makes sequences/ before its first generation is renamed into place."""
    root = tmp_path / "api"
    _write_sequence(root / "sequences" / ".tmp-first")
    assert cli.main(["--data-root", str(root), "--missing"]) == 0


@pytest.mark.usefixtures("fake_a2b")
def test_runs_in_its_docker_image(
    dataset: Path,
    fake_docker: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_DOCKER_IMAGES", "video-bokeh-a2b")
    AnyToBokeh().render(_sequences(dataset), strength=16, focus_disparity=None)

    runs = [
        json.loads(line)
        for line in fake_docker.read_text().splitlines()
        if json.loads(line)[0] == "run"
    ]
    assert len(runs) == 1
    argv = runs[0]
    assert argv[argv.index("video-bokeh-a2b") + 1] == "python"
    assert any(arg.endswith("_a2b_launch.py") for arg in argv)
    for seq in _sequences(dataset):
        assert len(list((seq / "bokeh").iterdir())) == FRAMES


@pytest.mark.usefixtures("fake_a2b")
def test_a_missing_image_stops_before_converting(
    dataset: Path,
    fake_docker: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FAKE_DOCKER_IMAGES", "")

    def converted(*args: object, **kwargs: object) -> None:
        raise AssertionError("converted before the image was checked")

    monkeypatch.setattr(a2b_module, "write_inputs", converted)
    with pytest.raises(RuntimeError, match="video-bokeh-a2b.*make images"):
        AnyToBokeh().render(_sequences(dataset), strength=16, focus_disparity=None)
    assert not (tmp_path / "fake_log.json").exists()
