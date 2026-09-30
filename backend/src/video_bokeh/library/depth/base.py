"""Protocol every depth estimator implements."""

from __future__ import annotations

from typing import ClassVar, Protocol, runtime_checkable

import numpy as np
import torch
from PIL import Image


@runtime_checkable
class DepthEstimator(Protocol):
    """Stateful estimator: call load(device) once, then infer(...) repeatedly.

    Every model behind this interface returns the same thing, so Stage B never needs to
    know which one built the library. A model that predicts depth, far larger than near,
    converts inside ``infer``; nothing downstream does.
    """

    name: ClassVar[str]

    def load(self, device: torch.device) -> None:
        """Materialize weights on device. Idempotent."""

    def infer(self, images: list[Image.Image]) -> list[np.ndarray]:
        """Return one float32 disparity map per image, larger = closer.

        Each map has its image's own height and width. Scale and offset are free: the
        library min/max-normalizes every map when it writes it.
        """
