"""Depth estimator registry, and resolution of `--model` to a class."""

from __future__ import annotations

import importlib

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


def missing_methods(cls: type) -> list[str]:
    """The methods of the estimator interface that ``cls`` does not provide."""
    return [m for m in ("load", "infer") if not callable(getattr(cls, m, None))]


def resolve_estimator(spec: str) -> type[DepthEstimator]:
    """A registered name, or ``package.module:ClassName`` for a model outside this package.

    The import path is how someone plugs in their own model without editing this
    repository. Raises ValueError naming what is wrong, which argparse reports as a usage
    error rather than a traceback.
    """
    if spec in ESTIMATORS:
        return ESTIMATORS[spec]
    if ":" not in spec:
        known = ", ".join(sorted(ESTIMATORS))
        raise ValueError(
            f"unknown model {spec!r}: use one of {known}, or package.module:ClassName",
        )

    module_name, _, class_name = spec.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ValueError(f"cannot import module {module_name!r}: {exc}") from exc
    cls = getattr(module, class_name, None)
    if not isinstance(cls, type):
        raise ValueError(f"module {module_name!r} has no class {class_name!r}")
    # ``name`` is not asked for: only the registry reads it, and this class is not in it.
    missing = missing_methods(cls)
    if missing:
        raise ValueError(
            f"{spec} is not a depth estimator: it lacks {', '.join(missing)}",
        )
    return cls
