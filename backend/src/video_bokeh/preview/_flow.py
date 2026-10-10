"""Optical flow in colour, the way optical-flow papers draw it.

The colour wheel of Baker et al., "A Database and Evaluation Methodology for Optical Flow"
(IJCV 2011), which the Middlebury benchmark introduced and RAFT's ``flow_viz`` draws: the
hue is the direction, the saturation the speed, and white is still. Researchers read it
without a legend; the demo draws one anyway, from the anchors below.
"""

from __future__ import annotations

import numpy as np

#: The wheel's six arcs, red to yellow, green, cyan, blue, magenta and back to red, each as
#: many steps long as Baker et al. make it, so that equal turns look about equally different.
_ARCS = (15, 6, 4, 11, 13, 6)


def _wheel() -> np.ndarray:
    """The 55 colours around the wheel, as floats in [0, 1]."""
    rising = [np.floor(255 * np.arange(n) / n) / 255 for n in _ARCS]
    falling = [1 - r for r in rising]
    full = [np.ones(n) for n in _ARCS]
    none = [np.zeros(n) for n in _ARCS]
    arcs = [
        (full[0], rising[0], none[0]),  # red to yellow
        (falling[1], full[1], none[1]),  # yellow to green
        (none[2], full[2], rising[2]),  # green to cyan
        (none[3], falling[3], full[3]),  # cyan to blue
        (rising[4], none[4], full[4]),  # blue to magenta
        (full[5], none[5], falling[5]),  # magenta to red
    ]
    return np.concatenate([np.stack(arc, axis=1) for arc in arcs])


_WHEEL = _wheel()


def flow_to_rgb(flow: np.ndarray, top_speed: float) -> np.ndarray:
    """Colour an ``(H, W, 2)`` flow in pixels per frame as uint8 RGB.

    ``top_speed`` is the speed drawn fully saturated. A video passes the fastest of the
    whole sequence, so that its frames share one scale and do not flicker.
    """
    u = flow[..., 0] / top_speed
    v = flow[..., 1] / top_speed
    # Rightward is the wheel's first colour, red, and it turns from there through down,
    # left and up, as image rows count downwards.
    position = (np.arctan2(-v, -u) / np.pi + 1) / 2 * (len(_WHEEL) - 1)
    k0 = np.floor(position).astype(int)
    k1 = (k0 + 1) % len(_WHEEL)
    f = (position - k0)[..., None]
    hue = (1 - f) * _WHEEL[k0] + f * _WHEEL[k1]
    speed = np.hypot(u, v)[..., None]
    # Towards white as the speed falls; past the top, darker, as the reference does.
    rgb = np.where(speed <= 1, 1 - speed * (1 - hue), hue * 0.75)
    return np.floor(255 * rgb).astype(np.uint8)
