"""Depth Anything V2 estimators via Hugging Face transformers."""

from __future__ import annotations

from typing import Any, ClassVar

import numpy as np
import torch
from PIL import Image

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


class _DepthAnythingV2Base:
    """Shared logic for the published DA-V2 variants."""

    name: ClassVar[str] = ""
    hf_model_id: ClassVar[str] = ""

    def __init__(self) -> None:
        self._processor: Any = None
        self._model: Any = None
        self._device: torch.device | None = None

    def load(self, device: torch.device) -> None:
        _ensure_transformers_loaded()
        self._processor = AutoImageProcessor.from_pretrained(self.hf_model_id)
        self._model = AutoModelForDepthEstimation.from_pretrained(self.hf_model_id)
        self._model = self._model.to(device).eval()
        self._device = device

    def infer(self, images: list[Image.Image]) -> list[np.ndarray]:
        if self._model is None or self._processor is None or self._device is None:
            raise RuntimeError(f"{type(self).__name__}.load() not called")

        sizes = [(img.height, img.width) for img in images]
        inputs = self._processor(images=images, return_tensors="pt").to(self._device)
        with torch.no_grad():
            outputs = self._model(**inputs)

        disparity = outputs.predicted_depth
        out: list[np.ndarray] = []
        for j, (height, width) in enumerate(sizes):
            disp = torch.nn.functional.interpolate(
                disparity[j : j + 1].unsqueeze(1),
                size=(height, width),
                mode="bicubic",
                align_corners=False,
            ).squeeze()
            out.append(disp.detach().cpu().numpy().astype(np.float32))
        return out


class DepthAnythingV2Small(_DepthAnythingV2Base):
    name: ClassVar[str] = "da2-small"
    hf_model_id: ClassVar[str] = "depth-anything/Depth-Anything-V2-Small-hf"


class DepthAnythingV2Base(_DepthAnythingV2Base):
    name: ClassVar[str] = "da2-base"
    hf_model_id: ClassVar[str] = "depth-anything/Depth-Anything-V2-Base-hf"


class DepthAnythingV2Large(_DepthAnythingV2Base):
    name: ClassVar[str] = "da2-large"
    hf_model_id: ClassVar[str] = "depth-anything/Depth-Anything-V2-Large-hf"
