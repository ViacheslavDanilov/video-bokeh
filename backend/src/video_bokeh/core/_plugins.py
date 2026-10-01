"""Resolve a stage's ``--model``-style flag to a class: a registered name, or a class of
the user's own named by import path."""

from __future__ import annotations

import importlib
from collections.abc import Mapping


def missing_methods(cls: type, methods: tuple[str, ...]) -> list[str]:
    """The ``methods`` that ``cls`` does not provide."""
    return [m for m in methods if not callable(getattr(cls, m, None))]


def resolve_class(
    spec: str,
    registry: Mapping[str, type],
    methods: tuple[str, ...],
    kind: str,
) -> type:
    """``registry[spec]``, or the class ``package.module:ClassName`` names.

    The import path is how someone plugs in their own model without editing this
    repository. Raises ValueError naming what is wrong, which argparse reports as a usage
    error rather than a traceback. A custom class is asked only for ``methods``: its
    ``name`` is read by nothing but the registry, and it is not in it.
    """
    if spec in registry:
        return registry[spec]
    if ":" not in spec:
        known = ", ".join(sorted(registry))
        raise ValueError(
            f"unknown {kind} {spec!r}: use one of {known}, or package.module:ClassName",
        )

    module_name, _, class_name = spec.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ValueError(f"cannot import module {module_name!r}: {exc}") from exc
    cls = getattr(module, class_name, None)
    if not isinstance(cls, type):
        raise ValueError(f"module {module_name!r} has no class {class_name!r}")
    missing = missing_methods(cls, methods)
    if missing:
        raise ValueError(f"{spec} is not a {kind}: it lacks {', '.join(missing)}")
    return cls
