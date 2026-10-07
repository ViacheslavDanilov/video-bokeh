"""Depth Anything 3 checkpoints, run in their own environment.

Depth Anything 3 cannot share ours; ``docs/reference/cli.md`` says why and how to build
its venv. These classes drive that venv through a worker process, ``_da3_worker.py``, or the
``video-bokeh-da3`` image with ``VIDEO_BOKEH_RUNNER=docker``.

Both checkpoints predict depth, far larger than near, at a 504 px working size, so
``infer`` takes the reciprocal and resizes back to each image's own size. Both are
Apache-2.0.

The multi-view checkpoints, Small, Base and Large, are left out on purpose. Their head has
no sky output, so the package never sets a sky to the far end, and where a sky lands is up
to the image. On one dev background with sky, Small and Base fell to almost no agreement
with Depth Anything V2 Large on 2026-10-01.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import ClassVar

import numpy as np
import torch
from PIL import Image

from video_bokeh.core._worker import WorkerProcess, model_command
from video_bokeh.library.depth.base import resize_map

_WORKER = Path(__file__).with_name("_da3_worker.py")
# backend/envs/..., where the setup script puts it. parents[4] is backend/.
_DEFAULT_PYTHON = (
    Path(__file__).resolve().parents[4]
    / "envs"
    / "depth-anything-3"
    / ".venv"
    / "bin"
    / "python"
)


#: The image ``make images`` builds, for ``VIDEO_BOKEH_RUNNER=docker``.
_IMAGE = "video-bokeh-da3"

#: What the worker imports before it loads a model, pycolmap stub included.
_IMPORT_CHECK = (
    "import sys, types; "
    "sys.modules.setdefault('pycolmap', types.ModuleType('pycolmap')); "
    "import depth_anything_3.api"
)


def _python() -> list[str]:
    """The venv's interpreter, or ``python`` in the image with ``VIDEO_BOKEH_RUNNER=docker``."""
    return model_command(
        "VIDEO_BOKEH_DA3_PYTHON",
        _DEFAULT_PYTHON,
        "scripts/setup_depth_anything_3.sh",
        _IMAGE,
    )


class DepthAnything3Estimator:
    """One Depth Anything 3 checkpoint; a subclass names it."""

    name: ClassVar[str] = ""
    hf_model_id: ClassVar[str] = ""
    docker_image: ClassVar[str] = _IMAGE

    def __init__(self) -> None:
        self._worker: WorkerProcess | None = None

    @classmethod
    def environment_problem(cls) -> str | None:
        """Why this estimator cannot run here, or None: its venv, or image, is all it needs.

        The package is imported, not just the interpreter found, so a venv whose install
        stopped half way reads as missing before a build finds out. The worker's pycolmap
        stub comes first, as in the worker.
        """
        try:
            python = _python()
        except (RuntimeError, ValueError, OSError) as exc:
            return str(exc)
        result = subprocess.run(
            # -P keeps the working directory off sys.path, where a folder named like the
            # package would stand in for it, as the worker's own `del sys.path[0]` does.
            [*python, "-P", "-c", _IMPORT_CHECK],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            last = (result.stderr.strip().splitlines() or ["no output"])[-1]
            if len(python) == 1:
                return (
                    f"{python[0]} cannot import depth_anything_3 ({last}): run "
                    "scripts/setup_depth_anything_3.sh again"
                )
            return (
                f"the {_IMAGE} image cannot import depth_anything_3 ({last}): run "
                "make images again"
            )
        return None

    def load(self, device: torch.device) -> None:
        if self._worker is not None:
            return
        self._worker = WorkerProcess(
            [*_python(), str(_WORKER), self.hf_model_id, str(device)],
        )

    def infer(self, images: list[Image.Image]) -> list[np.ndarray]:
        if self._worker is None:
            raise RuntimeError(f"{type(self).__name__}.load() not called")
        out: list[np.ndarray] = []
        with tempfile.TemporaryDirectory() as tmp:
            # One image per request: a batch of different sizes is centre-cropped to the
            # smallest before inference, and every map here must match its own image.
            for img in images:
                image_path = Path(tmp) / "image.png"
                depth_path = Path(tmp) / "depth.npy"
                img.convert("RGB").save(image_path)
                self._worker.request(
                    {"image": str(image_path), "output": str(depth_path)},
                )
                depth = torch.from_numpy(np.load(depth_path))
                out.append(resize_map(1.0 / depth, img.height, img.width))
        return out

    def peak_memory(self) -> int | None:
        """Bytes the worker, which holds the weights, has used on its device."""
        if self._worker is None:
            return None
        return int(self._worker.request({"memory": True})["memory"])

    def close(self) -> None:
        if self._worker is not None:
            self._worker.close()
            self._worker = None


class DepthAnything3MonoLarge(DepthAnything3Estimator):
    """Trained for single images, which is all Stage A gives it."""

    name: ClassVar[str] = "da3-mono-large"
    hf_model_id: ClassVar[str] = "depth-anything/DA3MONO-LARGE"


class DepthAnything3MetricLarge(DepthAnything3Estimator):
    """Predicts depth divided by the focal length, a factor per image that the library's
    min/max normalisation removes, so the reciprocal is disparity all the same.
    """

    name: ClassVar[str] = "da3-metric-large"
    hf_model_id: ClassVar[str] = "depth-anything/DA3METRIC-LARGE"
