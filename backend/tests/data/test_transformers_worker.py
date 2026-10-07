"""Depth Anything V2 and Depth Pro in their Docker images, through a worker process.

In-process is the default, and test_depth_registry covers it. With
VIDEO_BOKEH_RUNNER=docker the real worker script runs, behind a fake docker, on a fake
transformers package, so CI needs neither weights nor images.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import torch
from PIL import Image

from video_bokeh.library.depth import ESTIMATORS

# Disparity rising to the right at a 8 x 12 working size, whatever the input was; it
# records the checkpoint each model was loaded from and the dtype it was cast to.
_FAKE_TRANSFORMERS = """
import os
import torch


class _Inputs(dict):
    def to(self, device):
        return self


class AutoImageProcessor:
    @classmethod
    def from_pretrained(cls, model_id):
        return cls()

    def __call__(self, images, return_tensors):
        assert len(images) == 1, images
        assert return_tensors == "pt"
        return _Inputs()


class _Outputs:
    predicted_depth = torch.linspace(0.0, 1.0, 12).repeat(1, 8, 1)


class AutoModelForDepthEstimation:
    @classmethod
    def from_pretrained(cls, model_id):
        with open(os.environ["FAKE_TRANSFORMERS_LOG"], "a") as log:
            log.write(model_id + "\\n")
        return cls()

    def to(self, device=None, dtype=None):
        assert dtype == torch.float32, dtype
        return self

    def eval(self):
        return self

    def __call__(self, **inputs):
        print("the model's own logging, on stdout")
        os.write(1, b"native code writing straight to fd 1\\n")
        return _Outputs()
"""

_IMAGES = {
    "da2-small": "video-bokeh-da2",
    "da2-base": "video-bokeh-da2",
    "da2-large": "video-bokeh-da2",
    "depth-pro": "video-bokeh-depth-pro",
}


@pytest.fixture
def fake_transformers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_docker: Path,
) -> Path:
    package = tmp_path / "site" / "transformers"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(_FAKE_TRANSFORMERS, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "site"))
    monkeypatch.setenv("FAKE_TRANSFORMERS_LOG", str(tmp_path / "models.log"))
    monkeypatch.setenv("FAKE_DOCKER_IMAGES", " ".join(set(_IMAGES.values())))
    return tmp_path / "models.log"


def _runs(log: Path) -> list[list[str]]:
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    return [argv for argv in calls if argv[0] == "run"]


@pytest.mark.parametrize(("key", "image"), sorted(_IMAGES.items()))
def test_runs_in_its_family_s_image(
    key: str,
    image: str,
    fake_transformers: Path,
    fake_docker: Path,
) -> None:
    est = ESTIMATORS[key]()
    est.load(torch.device("cpu"))
    try:
        wide, square = est.infer(
            [Image.new("RGB", (64, 48)), Image.new("RGB", (32, 32))],
        )
    finally:
        est.close()
    assert wide.shape == (48, 64) and square.shape == (32, 32)
    assert wide.dtype == np.float32
    # Disparity as the model gave it, resized: rising to the right.
    assert wide[:, -1].mean() > wide[:, 0].mean()
    (argv,) = _runs(fake_docker)
    at = argv.index(image)
    assert argv[at + 1] == "python"
    assert argv[at + 2].endswith("_transformers_worker.py")
    assert argv[at + 3] == ESTIMATORS[key].hf_model_id
    assert fake_transformers.read_text().split() == [ESTIMATORS[key].hf_model_id]


@pytest.mark.usefixtures("fake_transformers")
def test_reports_the_memory_of_the_worker() -> None:
    est = ESTIMATORS["da2-small"]()
    est.load(torch.device("cpu"))
    try:
        memory = est.peak_memory()
    finally:
        est.close()
    assert isinstance(memory, int) and memory > 0


def test_environment_in_docker_names_the_missing_image(
    fake_docker: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_DOCKER_IMAGES", "")
    problem = ESTIMATORS["depth-pro"].environment_problem()
    assert problem is not None
    assert "video-bokeh-depth-pro" in problem and "make images" in problem


def test_in_process_has_no_environment_to_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VIDEO_BOKEH_RUNNER", raising=False)
    assert ESTIMATORS["da2-small"].environment_problem() is None


def test_an_estimator_without_an_image_says_so(
    fake_docker: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from video_bokeh.library.depth._transformers import TransformersDepthEstimator

    class Mine(TransformersDepthEstimator):
        name = "mine"
        hf_model_id = "me/mine"

    problem = Mine.environment_problem()
    assert problem is not None and "names no Docker image" in problem


@pytest.mark.parametrize("key", ["da2-small", "depth-pro", "da3-mono-large"])
def test_a_misspelt_runner_is_a_reason_not_a_crash(
    key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIDEO_BOKEH_RUNNER", "dokcer")
    problem = ESTIMATORS[key].environment_problem()
    assert problem is not None and "VIDEO_BOKEH_RUNNER" in problem
