"""Stage C: bokeh renderers, and resolution of ``--renderer`` to a class."""

from __future__ import annotations

from video_bokeh.core._plugins import resolve_class
from video_bokeh.render.any_to_bokeh import AnyToBokeh
from video_bokeh.render.base import BokehRenderer
from video_bokeh.render.layered import Layered

RENDERERS: dict[str, type[BokehRenderer]] = {
    AnyToBokeh.name: AnyToBokeh,
    Layered.name: Layered,
}


def resolve_renderer(spec: str) -> type[BokehRenderer]:
    """A registered name, or ``package.module:ClassName`` for a renderer of one's own.

    See ``video_bokeh.core._plugins.resolve_class`` for the errors it raises.
    """
    return resolve_class(spec, RENDERERS, ("render",), "bokeh renderer")
