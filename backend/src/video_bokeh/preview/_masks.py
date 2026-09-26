"""Turn a frame's per-object alpha planes into one image a person can read.

A scene's alpha stream is a multi-page TIFF with **one page per object, in a fixed
order for the whole clip** — `scenes/_compositor.py` is explicit that the index is the
object's identity and not its draw order, because paint order is recomputed every frame
as objects move past each other in depth.

Two consequences shape this rendering:

**Colour means identity, not depth.** Object 2 keeps its colour from the first frame to
the last, so watching which colour covers which is watching the depth ordering change.
The depth itself is the pane next door.

**The masks are amodal.** `_compositor` stores each object's own warped alpha, not the
part left visible after nearer objects were painted over it, so silhouettes overlap.
They are composited here in page order, which means the overlap is resolved by object
number rather than by distance. That is a property of the data worth seeing rather than
a flaw to hide: amodal masks are the reason the alpha stream is stored per object at all.
"""

from __future__ import annotations

import numpy as np

#: ColorBrewer Set1, a qualitative scheme: neighbouring entries are as unlike each other
#: as the space allows, because these are labels rather than a measurement. Deliberately
#: nothing like `Spectral`, which is a ramp and carries an order — mixing the two up is
#: exactly the mistake this pane could invite.
OBJECT_COLORS: tuple[tuple[int, int, int], ...] = (
    (228, 26, 28),
    (55, 126, 184),
    (77, 175, 74),
    (152, 78, 163),
    (255, 127, 0),
    (255, 255, 51),
    (166, 86, 40),
    (247, 129, 191),
    (153, 153, 153),
)

#: Anything under this is a stray edge sample rather than the object, and painting it
#: leaves a halo of colour where the warp filtered against the background.
_COVERAGE_FLOOR = 0.5


def object_color(index: int) -> tuple[int, int, int]:
    """The colour for object `index`, wrapping once the scheme runs out."""
    return OBJECT_COLORS[index % len(OBJECT_COLORS)]


def object_color_hex(index: int) -> str:
    """The same colour as CSS hex, for a legend that must match the video."""
    red, green, blue = object_color(index)
    return f"#{red:02x}{green:02x}{blue:02x}"


def render_object_masks(alphas: list[np.ndarray]) -> np.ndarray:
    """Composite per-object alpha planes into one uint8 RGB image on black.

    Painted in page order, so a later object covers an earlier one where their
    silhouettes overlap. See the module docstring for why that is identity order rather
    than depth order.
    """
    if not alphas:
        raise ValueError("no alpha pages: a scene frame always has at least one object")

    height, width = alphas[0].shape
    out = np.zeros((height, width, 3), dtype=np.uint8)
    for index, alpha in enumerate(alphas):
        if alpha.shape != (height, width):
            raise ValueError(
                f"alpha page {index} is {alpha.shape}, expected {(height, width)}",
            )
        out[alpha >= _COVERAGE_FLOOR] = object_color(index)
    return out
