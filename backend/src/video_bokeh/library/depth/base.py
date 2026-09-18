"""Protocol every depth estimator implements."""

from __future__ import annotations

from typing import ClassVar, Protocol, runtime_checkable

import numpy as np
import torch
from PIL import Image


@runtime_checkable
class DepthEstimator(Protocol):
    """Stateful estimator: call load(device) once, then infer(...) repeatedly."""

    name: ClassVar[str]

    def load(self, device: torch.device) -> None:
        """Materialize weights on device. Idempotent."""

    def infer(self, images: list[Image.Image]) -> list[np.ndarray]:
        """Return one float32 HxW disparity map per image, larger = closer."""
