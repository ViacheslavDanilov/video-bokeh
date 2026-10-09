"""Read and write the per-frame streams of a generated sequence.

Both sides of each format live here so they cannot drift apart. The formats are fixed by
docs/reference/dataset-layout.md:

    alpha/<frame>.tif       multi-page uint8 TIFF, one page per object, deflate + predictor
    disparity/<frame>.png   uint16 PNG, [0, 1] mapped onto [0, 65535]

and the object layers, written only on request:

    layers/objects/<frame>.tif            multi-page RGB uint8 TIFF, one page per object
    layers/objects_disparity/<frame>.tif  multi-page uint16 TIFF, one page per object
    layers/paint_order.json               per frame, the object pages far to near

**Multi-page, not multi-sample.** Pillow cannot open a TIFF with more than four samples per
pixel at all -- it raises ``UnidentifiedImageError`` -- while it reads a multi-page file
exactly. Everything here and everyone who downloads the dataset uses Pillow, so the page
layout is the compatible one and the sample layout is a trap.

Alpha stays soft on the way through. The mattes carry anti-aliased rims and real
transparency, which is what the dataset exists to provide, so nothing binarizes.
"""

from __future__ import annotations

import json
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

    pages = np.stack([quantize_alpha(m) for m in masks])
    # photometric="minisblack" is load-bearing, not decoration. Without it tifffile
    # infers meaning from the shape: (3, H, W) becomes one RGB page and (4, H, W)
    # one RGBA page, so three or four masks -- the commonest counts -- would be
    # silently interleaved into a single colour image and read back as one mask.
    _write_pages(path, pages, "minisblack")


def quantize_alpha(mask: np.ndarray) -> np.ndarray:
    """A mask in ``[0, 1]`` as the uint8 its alpha page stores."""
    return (np.clip(mask, 0.0, 1.0) * _U8_MAX).round().astype(np.uint8)


def read_alpha_tiff(path: Path) -> list[np.ndarray]:
    """Read the pages back as float32 in [0, 1], preserving order."""
    return [page / _U8_MAX for page in _read_pages(path)]


def write_rgb_tiff(path: Path, images: list[np.ndarray]) -> None:
    """Write one RGB uint8 page per ``(H, W, 3)`` image in ``[0, 255]``, in order.

    Page ``k`` is object ``k``, as in the alpha stream. Values are truncated, as the
    all-in-focus stream's are, so an opaque pixel matches that stream's byte for byte.
    """
    pages = np.stack([np.clip(im, 0, _U8_MAX).astype(np.uint8) for im in images])
    _write_pages(path, pages, "rgb")


def read_rgb_tiff(path: Path) -> list[np.ndarray]:
    """Read the pages back as ``(H, W, 3)`` float32 in ``[0, 255]``, preserving order."""
    return _read_pages(path)


def write_disparity_tiff(path: Path, maps: list[np.ndarray]) -> None:
    """Write one uint16 page per disparity map in ``[0, 1]``, in order."""
    pages = np.stack([_quantize_disparity(m) for m in maps])
    _write_pages(path, pages, "minisblack")


def read_disparity_tiff(path: Path) -> list[np.ndarray]:
    """Read the pages back as float32 in ``[0, 1]``, preserving order."""
    return [page / _U16_MAX for page in _read_pages(path)]


def _write_pages(path: Path, pages: np.ndarray, photometric: str) -> None:
    """One page per entry of ``pages``. ``photometric`` stops tifffile guessing it."""
    tifffile.imwrite(
        path,
        pages,
        photometric=photometric,
        compression="deflate",
        predictor=True,
    )


def _read_pages(path: Path) -> list[np.ndarray]:
    """Every page as float32, in its stored scale, through Pillow."""
    with Image.open(path) as im:
        return [
            np.asarray(page, dtype=np.float32) for page in ImageSequence.Iterator(im)
        ]


def write_disparity_png(path: Path, disparity: np.ndarray) -> None:
    """Write float32 disparity in [0, 1] as a uint16 PNG. Larger means closer."""
    # Pillow infers mode 'I;16' from the uint16 dtype; passing mode= is deprecated.
    Image.fromarray(_quantize_disparity(disparity)).save(path, compress_level=6)


def _quantize_disparity(disparity: np.ndarray) -> np.ndarray:
    return (np.clip(disparity, 0.0, 1.0) * _U16_MAX).round().astype(np.uint16)


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


def write_paint_order(path: Path, orders: list[list[int]]) -> None:
    """Write each frame's paint order: its object pages, far to near."""
    path.write_text(json.dumps(orders) + "\n", encoding="utf-8")


def read_paint_order(path: Path) -> list[list[int]]:
    """Read each frame's paint order, refusing one that is not a permutation of pages."""
    orders = json.loads(path.read_text(encoding="utf-8"))
    for frame, order in enumerate(orders):
        if sorted(order) != list(range(len(order))):
            raise ValueError(
                f"{path}: frame {frame + 1}'s paint order {order} is not a permutation "
                f"of its {len(order)} object pages",
            )
    return orders
