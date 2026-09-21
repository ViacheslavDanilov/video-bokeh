"""Depth estimator registry."""

from __future__ import annotations

from video_bokeh.library.depth.base import DepthEstimator
from video_bokeh.library.depth.depth_anything_v2 import (
    DepthAnythingV2Base,
    DepthAnythingV2Large,
    DepthAnythingV2Small,
)

ESTIMATORS: dict[str, type[DepthEstimator]] = {
    DepthAnythingV2Small.name: DepthAnythingV2Small,
    DepthAnythingV2Base.name: DepthAnythingV2Base,
    DepthAnythingV2Large.name: DepthAnythingV2Large,
}
