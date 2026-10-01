"""Depth Anything 3 runs in its own environment; CI runs its real worker on a fake package."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import torch
from PIL import Image

from video_bokeh.library.depth import ESTIMATORS
from video_bokeh.library.depth import depth_anything_v3 as mod

# Every Depth Anything 3 checkpoint the registry knows, each through the same worker.
_DA3 = [
    cls for cls in ESTIMATORS.values() if issubclass(cls, mod.DepthAnything3Estimator)
]
# Written out rather than read off the classes, so a class naming the wrong checkpoint
# fails here; the multi-view ones are absent on purpose, see the module docstring.
_CHECKPOINTS = {
    "da3-mono-large": "depth-anything/DA3MONO-LARGE",
    "da3-metric-large": "depth-anything/DA3METRIC-LARGE",
}

# Stands in for the depth_anything_3 package, so the real worker script runs in CI with
# no weights: depth, far larger, at a 504 px working size whatever the input was, far on
# the right. It also asserts one image per call, which the worker promises.
_FAKE_API = """
import os

import numpy as np


class _Prediction:
    def __init__(self, depth):
        self.depth = depth


class DepthAnything3:
    @classmethod
    def from_pretrained(cls, model_id):
        assert model_id == os.environ["FAKE_DA3_MODEL_ID"], model_id
        return cls()

    def to(self, device):
        return self

    def inference(self, images):
        assert len(images) == 1, images
        print("the model's own logging, on stdout")
        os.write(1, b"native code writing straight to fd 1\\n")
        depth = np.tile(np.linspace(1.0, 5.0, 504, dtype=np.float32), (504, 1))
        return _Prediction(depth[None])
"""


@pytest.fixture
def fake_worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "depth_anything_3"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "api.py").write_text(_FAKE_API, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    monkeypatch.setenv("VIDEO_BOKEH_DA3_PYTHON", sys.executable)
    monkeypatch.setenv("FAKE_DA3_MODEL_ID", mod.DepthAnything3MonoLarge.hf_model_id)


def test_registered() -> None:
    assert ESTIMATORS["da3-mono-large"] is mod.DepthAnything3MonoLarge


@pytest.mark.usefixtures("fake_worker")
def test_returns_disparity_at_each_input_size() -> None:
    est = mod.DepthAnything3MonoLarge()
    est.load(torch.device("cpu"))
    try:
        out = est.infer([Image.new("RGB", (64, 48)), Image.new("RGB", (32, 32))])
    finally:
        est.close()

    assert [d.shape for d in out] == [(48, 64), (32, 32)]
    assert all(d.dtype == np.float32 for d in out)
    # The fake put far on the right, so disparity must fall from left to right.
    assert out[0][:, 0].mean() > out[0][:, -1].mean()


def test_missing_environment_names_the_setup_script(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIDEO_BOKEH_DA3_PYTHON", str(tmp_path / "no" / "python"))
    with pytest.raises(RuntimeError, match="setup_depth_anything_3.sh"):
        mod.DepthAnything3MonoLarge().load(torch.device("cpu"))


def test_infer_before_load_is_refused() -> None:
    with pytest.raises(RuntimeError, match="load"):
        mod.DepthAnything3MonoLarge().infer([Image.new("RGB", (8, 8))])


@pytest.mark.usefixtures("fake_worker")
def test_reports_the_memory_of_the_process_holding_the_weights() -> None:
    est = mod.DepthAnything3MonoLarge()
    est.load(torch.device("cpu"))
    try:
        est.infer([Image.new("RGB", (16, 16))])
        memory = est.peak_memory()
    finally:
        est.close()
    assert memory is not None
    assert memory > 0


def test_environment_names_the_setup_script_when_the_venv_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIDEO_BOKEH_DA3_PYTHON", str(tmp_path / "no" / "python"))
    problem = mod.DepthAnything3MonoLarge.environment_problem()
    assert problem is not None
    assert "setup_depth_anything_3.sh" in problem


def test_environment_is_ready_once_the_interpreter_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIDEO_BOKEH_DA3_PYTHON", sys.executable)
    assert mod.DepthAnything3MonoLarge.environment_problem() is None


def test_each_name_loads_its_own_checkpoint() -> None:
    assert {cls.name: cls.hf_model_id for cls in _DA3} == _CHECKPOINTS


@pytest.mark.parametrize("estimator", _DA3, ids=lambda cls: cls.name)
@pytest.mark.usefixtures("fake_worker")
def test_each_checkpoint_loads_its_own_weights(
    estimator: type[mod.DepthAnything3Estimator],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fake refuses any id but the expected one, so a wrong id fails the test."""
    monkeypatch.setenv("FAKE_DA3_MODEL_ID", _CHECKPOINTS[estimator.name])
    est = estimator()
    est.load(torch.device("cpu"))
    try:
        [out] = est.infer([Image.new("RGB", (40, 30))])
    finally:
        est.close()
    assert out.shape == (30, 40)
