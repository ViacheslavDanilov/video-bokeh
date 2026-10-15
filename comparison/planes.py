"""Fit the plane that MPIB's ray tracer takes for each layer, from a disparity map.

MPIB's ray tracer (``bokeh_generator.py``) takes, per layer, an alpha mask and the three
numbers ``(A, B, C)`` of the plane ``Z = C + A X + B Y`` in depth ``Z = 1 / disparity``. A
pixel at ``(x, y)`` of that plane has disparity ``d = (1 - A x - B y) / C``, so a layer whose
disparity is ``p0 + p1 x + p2 y`` has ``C = 1 / p0``, ``A = -p1 C`` and ``B = -p2 C``. Pure
numpy, so it runs without the ray tracer's CUDA stack.
"""

from __future__ import annotations

import numpy as np

#: The least disparity a plane may have anywhere in the frame; below it the depth is not finite.
MIN_DISPARITY = 1e-3


def _flat(disparity: np.ndarray, weight: np.ndarray) -> tuple[float, float, float]:
    """A plane facing the camera at the weighted mean of the disparities given."""
    mean = float(np.average(disparity, weights=weight))
    return 0.0, 0.0, 1.0 / max(mean, MIN_DISPARITY)


def fit_plane(disparity: np.ndarray, weight: np.ndarray) -> tuple[float, float, float]:
    """The ``(A, B, C)`` of the plane ``Z = C + A X + B Y`` that best holds a layer's disparity.

    ``disparity`` and ``weight`` are ``(H, W)``; pixels with no weight do not count. The fit is
    ``d = p0 + p1 x + p2 y`` in pixel coordinates, by weighted least squares. A layer with
    fewer than three pixels to fit, whose pixels lie on one line, or whose fitted plane would
    fall below ``MIN_DISPARITY`` at a corner of the frame, is flat at its weighted mean
    disparity. A layer with no pixel at all is flat at the mean of the whole map.
    """
    ys, xs = np.nonzero(weight > 0)
    if len(xs) == 0:
        return 0.0, 0.0, 1.0 / max(float(disparity.mean()), MIN_DISPARITY)
    w = weight[ys, xs].astype(np.float64)
    if len(xs) < 3:
        return _flat(disparity[ys, xs], w)
    columns = [np.ones(len(xs)), xs.astype(np.float64), ys.astype(np.float64)]
    design = np.stack(columns, axis=1) * np.sqrt(w)[:, None]
    target = disparity[ys, xs].astype(np.float64) * np.sqrt(w)
    (p0, p1, p2), _, rank, _ = np.linalg.lstsq(design, target, rcond=None)
    if rank < 3:
        # The pixels lie on a line, so the plane is not determined across it.
        return _flat(disparity[ys, xs], w)
    height, width = disparity.shape
    corners = [p0 + p1 * x + p2 * y for x in (0, width - 1) for y in (0, height - 1)]
    if min(corners) < MIN_DISPARITY:
        return _flat(disparity[ys, xs], w)
    c = 1.0 / p0
    return float(-p1 * c), float(-p2 * c), float(c)
