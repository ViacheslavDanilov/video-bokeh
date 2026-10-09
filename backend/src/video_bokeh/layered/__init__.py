"""Layer-wise bokeh: each layer blurred by its distance from the focus, then composited.

A package of its own rather than part of ``render``, Stage C's renderers, because the
training loader renders with it too: it needs torch and nothing of Stage C's.
"""

from video_bokeh.layered._renderer import GAMMA, RADIUS_STEP, render_bokeh

__all__ = ["GAMMA", "RADIUS_STEP", "render_bokeh"]
