"""Depth estimator registry."""

from __future__ import annotations

from data.depth.base import DepthEstimator
from data.depth.depth_anything_v2 import (
    DepthAnythingV2Base,
    DepthAnythingV2Large,
    DepthAnythingV2Small,
)

ESTIMATORS: dict[str, type[DepthEstimator]] = {
    DepthAnythingV2Small.name: DepthAnythingV2Small,
    DepthAnythingV2Base.name: DepthAnythingV2Base,
    DepthAnythingV2Large.name: DepthAnythingV2Large,
}
