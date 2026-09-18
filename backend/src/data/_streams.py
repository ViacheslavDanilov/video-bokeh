"""Read and write the per-frame streams of a generated sequence.

Both sides of each format live here so they cannot drift apart. The formats are fixed by
docs/reference/dataset-layout.md:

    alpha/<frame>.tif       multi-page uint8 TIFF, one page per object, deflate + predictor
    disparity/<frame>.png   uint16 PNG, [0, 1] mapped onto [0, 65535]

**Multi-page, not multi-sample.** Pillow cannot open a TIFF with more than four samples per
pixel at all -- it raises ``UnidentifiedImageError`` -- while it reads a multi-page file
exactly. Everything here and everyone who downloads the dataset uses Pillow, so the page
layout is the compatible one and the sample layout is a trap.

Alpha stays soft on the way through. The mattes carry anti-aliased rims and real
transparency, which is what the dataset exists to provide, so nothing binarizes.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import tifffile
from PIL import Image, ImageSequence

_U8_MAX = 255
_U16_MAX = 65535


def write_alpha_tiff(path: Path, masks: list[np.ndarray]) -> None:
    """Write one uint8 page per mask, in the order given.

    Page ``k`` is object ``k`` for the whole clip, so the order is part of the contract, not
    an implementation detail.
    """
    if not masks:
        raise ValueError("alpha stream needs at least one mask")
    shape = masks[0].shape
    if any(m.shape != shape for m in masks):
        raise ValueError(
            f"all alpha masks must have the same shape; got {[m.shape for m in masks]}",
        )

    pages = np.stack(
        [(np.clip(m, 0.0, 1.0) * _U8_MAX).round().astype(np.uint8) for m in masks],
    )
    # photometric="minisblack" is load-bearing, not decoration. Without it tifffile
    # infers meaning from the shape: (3, H, W) becomes one RGB page and (4, H, W)
    # one RGBA page, so three or four masks -- the commonest counts -- would be
    # silently interleaved into a single colour image and read back as one mask.
    tifffile.imwrite(
        path,
        pages,
        photometric="minisblack",
        compression="deflate",
        predictor=True,
    )


def read_alpha_tiff(path: Path) -> list[np.ndarray]:
    """Read the pages back as float32 in [0, 1], preserving order."""
    with Image.open(path) as im:
        return [
            np.asarray(page, dtype=np.float32) / _U8_MAX
            for page in ImageSequence.Iterator(im)
        ]


def write_disparity_png(path: Path, disparity: np.ndarray) -> None:
    """Write float32 disparity in [0, 1] as a uint16 PNG. Larger means closer."""
    quantized = (np.clip(disparity, 0.0, 1.0) * _U16_MAX).round().astype(np.uint16)
    # Pillow infers mode 'I;16' from the uint16 dtype; passing mode= is deprecated.
    Image.fromarray(quantized).save(path, compress_level=6)


def read_disparity_png(path: Path) -> np.ndarray:
    """Read a uint16 disparity PNG back as float32 in [0, 1].

    Refuses anything that is not 16-bit. Datasets written before this format existed
    hold 8-bit disparity and nothing deletes them, so a permissive reader would scale
    one by 1/65535 instead of 1/255 -- a silent factor of 257 that produces a
    near-black stream, no exception, and a zero exit code.
    """
    with Image.open(path) as im:
        arr = np.asarray(im)
    if arr.dtype != np.uint16:
        raise ValueError(
            f"{path} is {arr.dtype}, not 16-bit. The disparity stream is uint16 PNG; "
            f"an older 8-bit dataset has to be regenerated, not reinterpreted.",
        )
    return arr.astype(np.float32) / _U16_MAX
