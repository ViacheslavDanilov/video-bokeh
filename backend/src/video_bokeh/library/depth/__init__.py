"""Depth estimator registry, and resolution of `--model` to a class."""

from __future__ import annotations

from video_bokeh.core._plugins import resolve_class
from video_bokeh.library.depth.base import DepthEstimator
from video_bokeh.library.depth.depth_anything_v2 import (
    DepthAnythingV2Base,
    DepthAnythingV2Large,
    DepthAnythingV2Small,
)
from video_bokeh.library.depth.depth_anything_v3 import DepthAnything3MonoLarge
from video_bokeh.library.depth.depth_pro import DepthPro

ESTIMATORS: dict[str, type[DepthEstimator]] = {
    DepthAnythingV2Small.name: DepthAnythingV2Small,
    DepthAnythingV2Base.name: DepthAnythingV2Base,
    DepthAnythingV2Large.name: DepthAnythingV2Large,
    DepthPro.name: DepthPro,
    DepthAnything3MonoLarge.name: DepthAnything3MonoLarge,
}


#: What a depth estimator must provide; ``name`` matters only to this registry.
ESTIMATOR_METHODS = ("load", "infer")


def resolve_estimator(spec: str) -> type[DepthEstimator]:
    """A registered name, or ``package.module:ClassName`` for a model outside this package.

    See ``video_bokeh.core._plugins.resolve_class`` for the errors it raises.
    """
    return resolve_class(spec, ESTIMATORS, ESTIMATOR_METHODS, "depth estimator")
