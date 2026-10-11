"""Layer-wise bokeh: each layer blurred by its distance from the focus, then composited.

A package of its own rather than part of ``render``, Stage C's renderers, because the
training loader renders with it too: it needs torch and nothing of Stage C's.
"""

from video_bokeh.layered._renderer import render_bokeh
from video_bokeh.layered._sequence import (
    RENDERER,
    LayeredFrame,
    bokeh_device,
    bokeh_record,
    layered_frame,
    render_sequence,
)

__all__ = [
    "RENDERER",
    "LayeredFrame",
    "bokeh_device",
    "bokeh_record",
    "layered_frame",
    "render_bokeh",
    "render_sequence",
]
