"""Shared base for depth models served through Hugging Face transformers."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import torch
from PIL import Image

from video_bokeh.core._worker import WorkerProcess, model_command, runner
from video_bokeh.library.depth.base import resize_map

_WORKER = Path(__file__).with_name("_transformers_worker.py")

AutoImageProcessor: Any = None
AutoModelForDepthEstimation: Any = None


def _ensure_transformers_loaded() -> None:
    global AutoImageProcessor, AutoModelForDepthEstimation
    if AutoImageProcessor is not None and AutoModelForDepthEstimation is not None:
        return
    from transformers import AutoImageProcessor as _AutoImageProcessor
    from transformers import AutoModelForDepthEstimation as _AutoModelForDepthEstimation

    AutoImageProcessor = _AutoImageProcessor
    AutoModelForDepthEstimation = _AutoModelForDepthEstimation


class TransformersDepthEstimator:
    """A transformers depth model whose raw ``predicted_depth`` is already disparity.

    A subclass names its checkpoint. The subclass, or the module defining it, says why the
    model's raw output is near-larger-than-far, because that is the one thing the contract
    cannot check. A model that predicts depth needs its own ``infer`` instead of this one.

    It runs in this process, or with ``VIDEO_BOKEH_RUNNER=docker`` in its family's image,
    ``docker_image``, through ``_transformers_worker.py``, which returns the same raw
    output for this class to resize.
    """

    name: ClassVar[str] = ""
    hf_model_id: ClassVar[str] = ""
    docker_image: ClassVar[str] = ""

    def __init__(self) -> None:
        self._processor: Any = None
        self._model: Any = None
        self._device: torch.device | None = None
        self._worker: WorkerProcess | None = None

    @classmethod
    def environment_problem(cls) -> str | None:
        """Why this estimator cannot run here, or None. In process it needs nothing."""
        if runner() == "local":
            return None
        try:
            cls._command()
        except RuntimeError as exc:
            return str(exc)
        return None

    @classmethod
    def _command(cls) -> list[str]:
        # The local arguments never apply: in process there is no interpreter to find.
        return model_command("", Path(), "", cls.docker_image)

    def load(self, device: torch.device) -> None:
        if runner() == "docker":
            if self._worker is None:
                self._worker = WorkerProcess(
                    [*self._command(), str(_WORKER), self.hf_model_id, str(device)],
                )
            return
        _ensure_transformers_loaded()
        self._processor = AutoImageProcessor.from_pretrained(self.hf_model_id)
        self._model = AutoModelForDepthEstimation.from_pretrained(self.hf_model_id)
        # transformers 5 keeps a checkpoint's own dtype, float16 for Depth Pro, which
        # leaves disparity far coarser than the uint16 the library stores.
        self._model = self._model.to(device=device, dtype=torch.float32).eval()
        self._device = device

    def infer(self, images: list[Image.Image]) -> list[np.ndarray]:
        if self._worker is not None:
            return self._infer_in_worker(images)
        if self._model is None or self._processor is None or self._device is None:
            raise RuntimeError(f"{type(self).__name__}.load() not called")

        sizes = [(img.height, img.width) for img in images]
        inputs = self._processor(images=images, return_tensors="pt").to(self._device)
        with torch.no_grad():
            outputs = self._model(**inputs)

        disparity = outputs.predicted_depth
        return [
            resize_map(disparity[j], height, width)
            for j, (height, width) in enumerate(sizes)
        ]

    def _infer_in_worker(self, images: list[Image.Image]) -> list[np.ndarray]:
        assert self._worker is not None
        out: list[np.ndarray] = []
        with tempfile.TemporaryDirectory() as tmp:
            # One image per request, as the processor would otherwise resize a batch to
            # one size; in process a batch of one is what Stage A sends anyway.
            for img in images:
                image_path = Path(tmp) / "image.png"
                depth_path = Path(tmp) / "depth.npy"
                img.convert("RGB").save(image_path)
                self._worker.request(
                    {"image": str(image_path), "output": str(depth_path)},
                )
                disparity = torch.from_numpy(np.load(depth_path))
                out.append(resize_map(disparity, img.height, img.width))
        return out

    def peak_memory(self) -> int | None:
        """Bytes the worker holding the weights has used, or None in process."""
        if self._worker is None:
            return None
        return int(self._worker.request({"memory": True})["memory"])

    def close(self) -> None:
        if self._worker is not None:
            self._worker.close()
            self._worker = None
