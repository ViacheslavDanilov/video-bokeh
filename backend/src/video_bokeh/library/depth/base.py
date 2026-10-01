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

    ``video_bokeh.library.check`` reads three optional parts when a class has them, and
    reports what it cannot know as unknown when it does not: ``hf_model_id``, the
    checkpoint whose weights it counts; ``environment_problem()``, a class method saying
    why the estimator cannot run here, or None; and ``peak_memory()``, the bytes used on
    its device by the process holding the weights, for an estimator that keeps them in
    another.
    """

    name: ClassVar[str]

    def load(self, device: torch.device) -> None:
        """Materialize weights on device. Idempotent."""

    def infer(self, images: list[Image.Image]) -> list[np.ndarray]:
        """Return one float32 disparity map per image, larger = closer.

        Each map has its image's own height and width. Scale and offset are free: the
        library min/max-normalizes every map when it writes it.
        """


def resize_map(disparity: torch.Tensor, height: int, width: int) -> np.ndarray:
    """A model's (H, W) map at its working size, resized bicubically to the image's."""
    resized = torch.nn.functional.interpolate(
        disparity[None, None],
        size=(height, width),
        mode="bicubic",
        align_corners=False,
    ).squeeze()
    return resized.detach().cpu().numpy().astype(np.float32)
