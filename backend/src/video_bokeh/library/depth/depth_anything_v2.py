"""Depth Anything V2 estimators via Hugging Face transformers.

The model predicts affine-invariant inverse depth, so its raw output is disparity as it
stands. Licences: Small is Apache-2.0; Base and Large are CC BY-NC 4.0.
"""

from __future__ import annotations

from typing import ClassVar

from video_bokeh.library.depth._transformers import TransformersDepthEstimator


class DepthAnythingV2Small(TransformersDepthEstimator):
    name: ClassVar[str] = "da2-small"
    hf_model_id: ClassVar[str] = "depth-anything/Depth-Anything-V2-Small-hf"


class DepthAnythingV2Base(TransformersDepthEstimator):
    name: ClassVar[str] = "da2-base"
    hf_model_id: ClassVar[str] = "depth-anything/Depth-Anything-V2-Base-hf"


class DepthAnythingV2Large(TransformersDepthEstimator):
    name: ClassVar[str] = "da2-large"
    hf_model_id: ClassVar[str] = "depth-anything/Depth-Anything-V2-Large-hf"
