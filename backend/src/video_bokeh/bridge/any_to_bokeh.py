#!/usr/bin/env python3
"""Prepare synthetic sequences for the vendored any-to-bokeh inference code.

Reads our sequence layout:

    <data-root>/sequences/<id>/all_in_focus/*.png
    <data-root>/sequences/<id>/alpha/*.tif           (multi-page uint8)
    <data-root>/sequences/<id>/disparity/*.png       (uint16)

and writes any-to-bokeh-compatible inputs:

    <a2b-root>/demo_dataset/<dataset-name>/videos/<id>/01.png
    <a2b-root>/demo_dataset/<dataset-name>/disp/<id>/01_zf_0.123456.png
    <a2b-root>/csv_file/<dataset-name>.csv

Frame names are intentionally 1-based and zero-padded like our sequence
frames, unlike the vendored demo assets that start at 0. any-to-bokeh parses
frame order from the numeric filename prefix.
"""

from __future__ import annotations

import argparse
import csv
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from video_bokeh.core._seq_io import list_sequences
from video_bokeh.core._streams import read_alpha_tiff, read_disparity_png


def _parse_seqs(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _numeric_stem(path: Path) -> int:
    return int(path.stem.split("_", maxsplit=1)[0])


def list_png_frames(path: Path) -> list[Path]:
    if not path.exists():
        raise FileNotFoundError(f"frame directory missing: {path}")
    return sorted(path.glob("*.png"), key=_numeric_stem)


def _list_tif_frames(path: Path) -> list[Path]:
    """List the alpha pages. An existing but empty listing is an error, not a default.

    Returning [] here short-circuits the frame-count guard in ``_write_sequence`` and
    hands ``_load_focus_mask`` a None, which falls back to whole-frame focus without
    a word -- the same silent failure the union fix removed. The old alpha/*.png
    layout lands exactly here.
    """
    if not path.exists():
        raise FileNotFoundError(f"frame directory missing: {path}")
    frames = sorted(path.glob("*.tif"), key=_numeric_stem)
    if not frames:
        raise ValueError(
            f"{path} exists but has no .tif frames. The alpha stream is multi-page "
            f"TIFF; a dataset written in the older alpha/*.png layout has to be "
            f"regenerated.",
        )
    return frames


def _to_uint8_disparities(arrs: list[np.ndarray]) -> list[np.ndarray]:
    """Quantize float disparity to the 8 bits any-to-bokeh reads. Exactly once.

    The stream on disk is 16-bit, so this is the single lossy step in the bridge.
    It used to run on an already-quantized uint8 array, which was harmless only
    while the source had no precision to lose.
    """
    stack = np.asarray(arrs, dtype=np.float32)
    lo = float(np.nanmin(stack))
    hi = float(np.nanmax(stack))
    if lo >= 0.0 and hi <= 1.0:
        return [(arr.clip(0.0, 1.0) * 255.0).round().astype(np.uint8) for arr in arrs]

    scale = max(hi - lo, 1e-6)
    return [
        ((arr - lo) / scale * 255.0).clip(0, 255).round().astype(np.uint8)
        for arr in arrs
    ]


def _load_focus_mask(alpha_path: Path | None, shape: tuple[int, int]) -> np.ndarray:
    """Union of the object masks, used to average the in-focus disparity.

    Taking the union matters. The previous reader collapsed the RGB alpha stream
    with ``convert("L")``, a luminance blend weighting the channels 0.299, 0.587
    and 0.114, then thresholded at 127. An object alone in the first channel
    scored 76 and one in the third scored 29, so neither passed and the focus
    silently fell back to the whole frame.
    """
    if alpha_path is None or not alpha_path.exists():
        return np.ones(shape, dtype=bool)
    pages = read_alpha_tiff(alpha_path)
    if pages and pages[0].shape != shape:
        raise ValueError(
            f"alpha shape {pages[0].shape} does not match disparity shape {shape}: "
            f"{alpha_path}",
        )
    mask = np.zeros(shape, dtype=bool)
    for page in pages:
        mask |= page > 0.5
    if not mask.any():
        return np.ones(shape, dtype=bool)
    return mask


def _relative_to_a2b(path: Path, a2b_root: Path) -> str:
    return path.resolve().relative_to(a2b_root.resolve()).as_posix()


#: How each frame's in-focus disparity is chosen, when no fixed one is given.
#: ``object``: one object, drawn by area, in every frame. ``alpha``: the mean under the
#: union of the objects' masks. ``full``: the mean over the whole frame.
FOCUS_MODES = ("object", "alpha", "full")


@dataclass(frozen=True)
class SequenceInputs:
    """What the bridge wrote for one sequence: its frame count and its focus."""

    frames: int
    #: The object the focus follows, by alpha page, or None when no object held it.
    focus_object: int | None
    #: The in-focus disparity of each frame, in [0, 1].
    zf: list[float]


def choose_focus_object(areas: Sequence[float], seed: int) -> int | None:
    """One object, drawn with probability proportional to its area; None without any.

    By area rather than the largest: large objects are usually the near ones, so the
    largest would put the focus on the foreground almost every time. A tiny object in
    focus leaves next to nothing sharp, which the weighting makes rare.
    """
    weights = np.asarray(areas, dtype=np.float64)
    if weights.size == 0 or weights.sum() <= 0:
        return None
    rng = np.random.default_rng(seed)
    return int(rng.choice(weights.size, p=weights / weights.sum()))


def visible_masks(masks: list[np.ndarray], disparity: np.ndarray) -> list[np.ndarray]:
    """Where each object shows, from its whole mask and the composited disparity.

    Stage B writes each mask before occlusion and paints far to near, each object in its
    own disparity band. So an object's depth is its disparity where no other mask covers
    it, and a pixel two masks cover shows the nearer one. An object with no such pixel of
    its own takes the disparity under its whole mask: on top, that is its own; fully
    covered, it is its cover's, a tie it loses.
    """
    covered = [m.any() for m in masks]
    depth: list[tuple[float, bool]] = []
    for i, mask in enumerate(masks):
        others = np.zeros_like(mask)
        for j, other in enumerate(masks):
            if j != i:
                others |= other
        own = mask & ~others
        source = own if own.any() else mask
        value = float(np.median(disparity[source])) if covered[i] else -np.inf
        depth.append((value, bool(own.any())))
    visible = []
    for i, mask in enumerate(masks):
        nearer = np.zeros_like(mask)
        for j, other in enumerate(masks):
            if depth[j] > depth[i]:
                nearer |= other
        visible.append(mask & ~nearer)
    return visible


def _object_focus(
    seq_dir: Path,
    alpha_paths: list[Path],
    disps: list[np.ndarray],
) -> tuple[int | None, list[float | None]]:
    """The object the focus follows and its mean disparity per frame, None where hidden.

    Both count only where the object shows, so a nearer object in front of it neither pulls
    the focus nor adds to its area. The draw is seeded by the sequence's name, so a
    sequence keeps its focus across runs.
    """
    areas: list[list[int]] = []
    means: list[list[float | None]] = []
    for path, disp in zip(alpha_paths, disps, strict=True):
        masks = [page > 0.5 for page in read_alpha_tiff(path)]
        visible = visible_masks(masks, disp)
        areas.append([int(v.sum()) for v in visible])
        means.append(
            [float(disp[v].mean()) / 255 if v.any() else None for v in visible]
        )
    n_objects = max((len(a) for a in areas), default=0)
    totals = [
        sum(frame[i] for frame in areas if i < len(frame)) / len(areas)
        for i in range(n_objects)
    ]
    chosen = choose_focus_object(totals, zlib.crc32(seq_dir.name.encode()))
    if chosen is None:
        return None, [None] * len(disps)
    return chosen, [frame[chosen] if chosen < len(frame) else None for frame in means]


def _held(zfs: list[float | None]) -> list[float | None]:
    """Each hidden frame keeps the last focus seen; frames before the first take it."""
    first = next((z for z in zfs if z is not None), None)
    held: list[float | None] = []
    last = first
    for z in zfs:
        last = z if z is not None else last
        held.append(last)
    return held


def _write_sequence(
    seq_dir: Path,
    out_video_dir: Path,
    out_disp_dir: Path,
    focus: str,
    focus_disparity: float | None = None,
) -> SequenceInputs:
    image_paths = list_png_frames(seq_dir / "all_in_focus")
    disparity_paths = list_png_frames(seq_dir / "disparity")
    alpha_paths = (
        _list_tif_frames(seq_dir / "alpha") if (seq_dir / "alpha").exists() else []
    )

    if len(image_paths) != len(disparity_paths):
        raise ValueError(
            f"{seq_dir.name}: {len(image_paths)} all_in_focus frames but "
            f"{len(disparity_paths)} disparity frames",
        )
    use_alpha = focus_disparity is None and focus in ("object", "alpha")
    if use_alpha and alpha_paths and len(alpha_paths) != len(image_paths):
        raise ValueError(
            f"{seq_dir.name}: {len(image_paths)} all_in_focus frames but "
            f"{len(alpha_paths)} alpha frames",
        )

    out_video_dir.mkdir(parents=True, exist_ok=True)
    out_disp_dir.mkdir(parents=True, exist_ok=True)

    raw_disps = [read_disparity_png(path) for path in disparity_paths]
    disp_pngs = _to_uint8_disparities(raw_disps)
    digits = max(2, len(str(len(image_paths))))

    focus_object: int | None = None
    object_zf: list[float | None] = [None] * len(image_paths)
    if focus_disparity is None and focus == "object" and alpha_paths:
        focus_object, object_zf = _object_focus(seq_dir, alpha_paths, disp_pngs)
        object_zf = _held(object_zf)
    zfs: list[float] = []

    for idx, (image_path, disp_u8) in enumerate(
        zip(image_paths, disp_pngs, strict=True),
        start=1,
    ):
        frame_stem = f"{idx:0{digits}d}"
        Image.open(image_path).convert("RGB").save(
            out_video_dir / f"{frame_stem}.png",
            compress_level=6,
        )

        held = object_zf[idx - 1]
        if focus_disparity is not None:
            zf = focus_disparity
        elif held is not None:
            zf = float(held)
        else:
            alpha_path = alpha_paths[idx - 1] if use_alpha and alpha_paths else None
            mask = _load_focus_mask(alpha_path, disp_u8.shape)
            zf = float(disp_u8[mask].mean() / 255.0)
        zfs.append(zf)
        Image.fromarray(disp_u8, mode="L").save(
            out_disp_dir / f"{frame_stem}_zf_{zf:.6f}.png",
            compress_level=6,
        )

    return SequenceInputs(frames=len(image_paths), focus_object=focus_object, zf=zfs)


def write_inputs(
    seq_dirs: list[Path],
    videos_root: Path,
    disp_root: Path,
    csv_path: Path,
    k: str,
    focus: str = "object",
    focus_disparity: float | None = None,
    relative_to: Path | None = None,
) -> list[SequenceInputs]:
    """Write any-to-bokeh's inputs for ``seq_dirs``, and the CSV that lists them.

    CSV paths are relative to ``relative_to`` when it is given, which is how the vendored
    demo lays them out, and absolute otherwise, so the inputs can live outside the
    submodule. ``focus`` is one of ``FOCUS_MODES``; ``focus_disparity`` overrides it.
    Returns what was written for each sequence, in order.
    """
    if focus not in FOCUS_MODES:
        raise ValueError(f"focus must be one of {FOCUS_MODES}, not {focus!r}")
    rows: list[list[str]] = []
    written: list[SequenceInputs] = []
    for seq_dir in seq_dirs:
        out_video_dir = videos_root / seq_dir.name
        out_disp_dir = disp_root / seq_dir.name
        written.append(
            _write_sequence(
                seq_dir=seq_dir,
                out_video_dir=out_video_dir,
                out_disp_dir=out_disp_dir,
                focus=focus,
                focus_disparity=focus_disparity,
            ),
        )
        rows.append(
            [
                _csv_entry(out_video_dir, relative_to),
                _csv_entry(out_disp_dir, relative_to),
                k,
            ],
        )

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["aif_folder", "disp_folder", "k"])
        writer.writerows(rows)
    return written


def _csv_entry(path: Path, relative_to: Path | None) -> str:
    if relative_to is None:
        return str(path.resolve())
    return _relative_to_a2b(path, relative_to)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        type=Path,
        required=True,
        help="dataset root containing sequences/ (e.g. data/synth_dev_new)",
    )
    parser.add_argument(
        "--a2b-root",
        type=Path,
        default=Path("third_party/any-to-bokeh"),
        help="vendored any-to-bokeh root, relative to backend/ by default",
    )
    parser.add_argument(
        "--dataset-name",
        default=None,
        help="name under demo_dataset/ and csv_file/. Default: data-root basename.",
    )
    parser.add_argument("--k", default="16", help="blur strength column for CSV")
    parser.add_argument(
        "--seqs",
        type=_parse_seqs,
        default=None,
        help="Comma-separated sequence ids (e.g. '0001,0003'). Default: all.",
    )
    parser.add_argument(
        "--focus-disparity",
        type=float,
        default=None,
        help="Fixed focus in [0, 1] for every frame; overrides --focus.",
    )
    parser.add_argument(
        "--focus",
        choices=FOCUS_MODES,
        default="object",
        help="how to compute zf in disparity filenames: one object drawn by area "
        "(default), the mean under all the objects' masks, or the whole frame's mean.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.focus_disparity is not None and not 0 <= args.focus_disparity <= 1:
        parser.error("--focus-disparity must be in [0, 1]")

    dataset_name = args.dataset_name or args.data_root.name
    a2b_root = args.a2b_root
    out_root = a2b_root / "demo_dataset" / dataset_name
    csv_path = a2b_root / "csv_file" / f"{dataset_name}.csv"

    seq_dirs = list_sequences(args.data_root, args.seqs)
    if not seq_dirs:
        raise SystemExit(
            f"no sequences to process under {args.data_root / 'sequences'}",
        )

    written = write_inputs(
        seq_dirs,
        videos_root=out_root / "videos",
        disp_root=out_root / "disp",
        csv_path=csv_path,
        k=str(args.k),
        focus=args.focus,
        focus_disparity=args.focus_disparity,
        relative_to=a2b_root,
    )
    for seq_dir, inputs in zip(seq_dirs, written, strict=True):
        print(f"  {seq_dir.name}: wrote {inputs.frames} frame(s)")

    print(f"\nDone. CSV: {csv_path}")
    print(f"Inference working directory: {a2b_root}")
    if (a2b_root / "test/inference_demo.py").is_file():
        print(
            f"  python test/inference_demo.py --val_csv_path csv_file/{dataset_name}.csv",
        )
    else:
        print(
            "Inputs only: use absolute paths to the inference script and checkpoints.",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
