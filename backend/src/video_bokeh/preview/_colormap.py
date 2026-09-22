"""Depth colormap lookup tables -- no runtime dependency on matplotlib.

`Spectral_r` is the ColorBrewer diverging palette the Depth Anything V2 repository
draws its qualitative figures with; matching it lets our disparity renders sit next
to the published ones without a reader re-learning the colour coding. Built here as
a 256-entry lookup table rather than through matplotlib -- see
tests/preview/test_colormap.py for the fidelity check against the real thing.
"""

from __future__ import annotations

import numpy as np

# ColorBrewer "Spectral", eleven classes, in its native (red-to-blue) order.
_SPECTRAL_ANCHORS = np.array(
    [
        [0x9E, 0x01, 0x42],
        [0xD5, 0x3E, 0x4F],
        [0xF4, 0x6D, 0x43],
        [0xFD, 0xAE, 0x61],
        [0xFE, 0xE0, 0x8B],
        [0xFF, 0xFF, 0xBF],
        [0xE6, 0xF5, 0x98],
        [0xAB, 0xDD, 0xA4],
        [0x66, 0xC2, 0xA5],
        [0x32, 0x88, 0xBD],
        [0x5E, 0x4F, 0xA2],
    ],
    dtype=np.float64,
)


def _interpolate(anchors: np.ndarray, n: int = 256) -> np.ndarray:
    """Linearly interpolate an (11, 3) anchor table to an (n, 3) uint8 table."""
    positions = np.linspace(0.0, 1.0, len(anchors))
    samples = np.linspace(0.0, 1.0, n)
    channels = [np.interp(samples, positions, anchors[:, c]) for c in range(3)]
    return np.stack(channels, axis=-1).round().astype(np.uint8)


def _grey_table(n: int = 256) -> np.ndarray:
    ramp = np.linspace(0.0, 255.0, n).round().astype(np.uint8)
    return np.stack([ramp, ramp, ramp], axis=-1)


# Reversed so disparity 0 (farthest) reads blue-violet and 1 (closest) reads
# dark red, matching how Depth Anything V2 renders its own figures.
COLORMAPS: dict[str, np.ndarray] = {
    "spectral_r": _interpolate(_SPECTRAL_ANCHORS)[::-1],
    "grey": _grey_table(),
}


def apply_colormap(disparity: np.ndarray, name: str = "spectral_r") -> np.ndarray:
    """Map float32 disparity in [0, 1] to a uint8 (H, W, 3) RGB image.

    Values outside [0, 1] are clipped before quantizing. Raises `KeyError` for an
    unknown `name`.
    """
    table = COLORMAPS[name]
    indices = (np.clip(disparity, 0.0, 1.0) * 255).round().astype(np.uint8)
    return table[indices]
