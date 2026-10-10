"""Read and write the per-frame streams of a generated sequence.

Both sides of each format live here so they cannot drift apart. The formats are fixed by
docs/reference/dataset-layout.md:

    alpha/<frame>.tif       multi-page uint8 TIFF, one page per object, deflate + predictor
    disparity/<frame>.png   uint16 PNG, [0, 1] mapped onto [0, 65535]

and the object layers, written only on request:

    layers/objects/<frame>.tif            multi-page RGB uint8 TIFF, one page per object
    layers/objects_disparity/<frame>.tif  multi-page uint16 TIFF, one page per object
    layers/paint_order.json               per frame, the object pages far to near

and the forward optical flow, written only on request, one file per frame but the last:

    flow/<frame>.png                      KITTI 16-bit RGB PNG: u, v, valid

and the bokeh stream, written whole or not at all by whatever renders it:

    bokeh/<frame>.png                     RGB uint8, beside focus.json

**Multi-page, not multi-sample.** Pillow cannot open a TIFF with more than four samples per
pixel at all -- it raises ``UnidentifiedImageError`` -- while it reads a multi-page file
exactly. Everything here and everyone who downloads the dataset uses Pillow, so the page
layout is the compatible one and the sample layout is a trap.

Alpha stays soft on the way through. The mattes carry anti-aliased rims and real
transparency, which is what the dataset exists to provide, so nothing binarizes.
"""

from __future__ import annotations

import json
import shutil
import stat
import tempfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import imagecodecs
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


#: KITTI's flow encoding: 1/64 px steps around 2**15, so about +-512 px fit.
_FLOW_SCALE = 64.0
_FLOW_ZERO = 2**15


def write_flow_png(path: Path, flow: np.ndarray) -> None:
    """Write ``(H, W, 2)`` float flow in pixels as KITTI's 16-bit RGB PNG.

    Red is ``u * 64 + 2**15``, green ``v * 64 + 2**15``, blue 1 where the vector is valid.
    A vector beyond the range the encoding holds is written invalid rather than clipped.
    Pillow cannot write 16-bit colour, so imagecodecs does.
    """
    coded = np.round(flow.astype(np.float64) * _FLOW_SCALE) + _FLOW_ZERO
    valid = ((coded >= 0) & (coded <= _U16_MAX)).all(axis=-1)
    coded = np.where(valid[..., None], coded, _FLOW_ZERO)
    pixels = np.dstack([coded, valid]).astype(np.uint16)
    path.write_bytes(imagecodecs.png_encode(pixels))


def read_flow_png(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Read a KITTI flow PNG back: float32 ``(H, W, 2)`` pixels, and where it is valid."""
    pixels = imagecodecs.png_decode(path.read_bytes())
    if pixels.dtype != np.uint16 or pixels.ndim != 3 or pixels.shape[2] != 3:
        raise ValueError(f"{path} is not a 16-bit RGB flow PNG")
    flow = (pixels[..., :2].astype(np.float32) - _FLOW_ZERO) / _FLOW_SCALE
    return flow, pixels[..., 2] > 0


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


#: The strength the bokeh stream is rendered at unless told otherwise: any-to-bokeh's
#: default ``k``, the blur radius in pixels at a 1024-pixel width one unit of disparity
#: from the focus.
BOKEH_STRENGTH = 16.0


@contextmanager
def staged_stream(seq: Path, stream: str, replace: bool = True) -> Iterator[Path]:
    """Write ``seq/<stream>/`` whole or not at all, through the folder this yields.

    The folder is hidden beside the stream, named per run so two runs over one data root
    cannot delete each other's, and renamed to ``<stream>/`` only when the block finishes.
    Anything that fails on the way leaves the old ``<stream>/`` untouched.

    ``replace`` replaces a ``<stream>/`` already there, as a new render does. Without it,
    one that appeared meanwhile, from another request writing the same sequence, is kept
    and this one dropped: nothing a reader may be reading is deleted.
    """
    staging = Path(tempfile.mkdtemp(prefix=f".{stream}-", dir=seq))
    # mkdtemp makes it private (0700); the stream gets the access its siblings have.
    staging.chmod(stat.S_IMODE((seq / "all_in_focus").stat().st_mode))
    try:
        yield staging
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    if replace:
        shutil.rmtree(seq / stream, ignore_errors=True)
    try:
        staging.rename(seq / stream)
    except OSError:
        if replace or not (seq / stream).is_dir():
            raise
        shutil.rmtree(staging, ignore_errors=True)


def write_bokeh(
    seq: Path,
    frames: Iterable[tuple[str, Image.Image]],
    record: dict[str, Any],
    replace: bool = True,
) -> None:
    """Write ``seq/bokeh/``: each named frame as a PNG, and ``record`` as focus.json.

    Whole or not at all, through ``staged_stream``, whose ``replace`` this is.
    """
    with staged_stream(seq, "bokeh", replace) as staging:
        for name, image in frames:
            image.save(staging / name, compress_level=6)
        (staging / "focus.json").write_text(json.dumps(record) + "\n", encoding="utf-8")
