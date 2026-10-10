#!/usr/bin/env python3
"""Stage B offline writer: materialize sampled scenes to the sequence layout.

    <output>/
    ├── manifest.csv
    └── sequences/<id>/
        ├── all_in_focus/<frame>.png   RGB uint8
        ├── alpha/<frame>.tif          multi-page uint8, one page per object
        ├── disparity/<frame>.png      uint16
        ├── layers/                    with --layers: what each frame was composited from
        └── flow/<frame>.png           with --flow: forward optical flow, KITTI 16-bit

This layout matches what bridge/any_to_bokeh.py consumes. Replaces the old
generate_sequences.py + estimate_disparity.py pair: depth is now sampled and
transformed from the library, not estimated per frame.

Usage:
    uv run python -m video_bokeh.scenes.generate \\
        --library-root data/library_dev \\
        --output       data/synth_dev \\
        --count 10 --frames 80 --size 1024 --seed 0
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import math
import random
import shutil
from collections.abc import Iterable, Iterator
from pathlib import Path

import numpy as np
from PIL import Image

from video_bokeh.core._focus import FrameFocus, focus_seed, focus_track, frame_focus
from video_bokeh.core._sequence_geometry import SampleConfig
from video_bokeh.core._streams import (
    BOKEH_STRENGTH,
    quantize_alpha,
    write_alpha_tiff,
    write_bokeh,
    write_disparity_png,
    write_disparity_tiff,
    write_flow_png,
    write_paint_order,
    write_rgb_tiff,
)
from video_bokeh.scenes._compositor import (
    CollisionRetriesExhausted,
    FrameLayers,
    RenderedFrame,
    Scene,
    iter_frames,
    sample_scene,
)

_MANIFEST_FIELDS = (
    "seq_id",
    "seed",
    "n_frames",
    "size",
    "n_objects",
    "n_rejections",
    "n_range_fallbacks",
)


def _save_frame(
    frame: RenderedFrame,
    stem: str,
    aif: Path,
    alp: Path,
    disp: Path,
) -> None:
    _write_rgb_png(aif / f"{stem}.png", frame.rgb)
    write_alpha_tiff(alp / f"{stem}.tif", frame.object_alphas)
    write_disparity_png(disp / f"{stem}.png", frame.disparity)


def _write_rgb_png(path: Path, rgb: np.ndarray) -> None:
    Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB").save(
        path,
        compress_level=6,
    )


#: The layers stream's directories. Each object's alpha is its page in ``alpha/``.
_LAYER_DIRS = ("background", "background_disparity", "objects", "objects_disparity")


def _save_layers(
    layers: FrameLayers,
    object_alphas: list[np.ndarray],
    stem: str,
    root: Path,
) -> None:
    # Zero wherever the alpha page will read 0, not only where the float alpha is: an
    # alpha below half a level rounds to 0 on disk, and its colour would be left behind.
    shown = [quantize_alpha(a) > 0 for a in object_alphas]
    _write_rgb_png(root / "background" / f"{stem}.png", layers.background_rgb)
    write_disparity_png(
        root / "background_disparity" / f"{stem}.png",
        layers.background_disparity,
    )
    write_rgb_tiff(
        root / "objects" / f"{stem}.tif",
        [rgb * m[..., None] for rgb, m in zip(layers.object_rgbs, shown, strict=True)],
    )
    write_disparity_tiff(
        root / "objects_disparity" / f"{stem}.tif",
        [d * m for d, m in zip(layers.object_disparities, shown, strict=True)],
    )


def sample_n_objects(seed: int, n_objects_min: int, n_objects_max: int) -> int:
    """How many objects a seed asks for.

    Keyed on a prefixed string rather than the bare seed so this draw is independent
    of the stream the scene itself uses.
    """
    return random.Random(f"nobj:{seed}").randint(n_objects_min, n_objects_max)


def sample_sequence(
    library_root: Path,
    seed: int,
    n_frames: int,
    size: int,
    n_objects_min: int,
    n_objects_max: int,
    cfg: SampleConfig | None = None,
) -> Scene:
    """The scene a seed and these settings name.

    The dataset writer, the API and the training stream all sample through here, so
    the same seed and settings give the same scene wherever it is made. Raises
    ``CollisionRetriesExhausted`` when no collision-free trajectories are found.
    """
    return sample_scene(
        library_root,
        seed=seed,
        n_frames=n_frames,
        size=size,
        n_objects=sample_n_objects(seed, n_objects_min, n_objects_max),
        cfg=cfg,
    )


def _frame_stem(index: int, n_frames: int) -> str:
    """Frame ``index``'s file stem: 1-based, padded to the width of the frame count."""
    return f"{index + 1:0{max(2, len(str(n_frames)))}d}"


def write_bokeh_stream(
    seq_dir: Path,
    scene: Scene,
    scene_seed: int,
    focus: list[FrameFocus],
    strength: float = BOKEH_STRENGTH,
    replace: bool = True,
) -> None:
    """Render a written sequence's bokeh from its scene, in memory, into ``bokeh/``.

    ``focus`` is each frame's focus statistics, gathered while the frames were written;
    the focused object is drawn from the scene's seed, as the loader and Stage C draw
    it. The frames are rendered again with their layers, a few at a time, so the layers
    are never held whole. ``replace`` is ``write_bokeh``'s. Needs torch.
    """
    from video_bokeh.layered import (
        bokeh_device,
        bokeh_record,
        layered_frame,
        render_sequence,
    )

    focus_object, zf = focus_track(focus, focus_seed(scene_seed))
    images = render_sequence(
        (layered_frame(frame) for frame in iter_frames(scene, layers=True)),
        zf,
        strength,
        bokeh_device(),
    )
    names = [f"{_frame_stem(i, scene.n_frames)}.png" for i in range(scene.n_frames)]
    record = bokeh_record(focus_object, zf, strength)
    write_bokeh(seq_dir, zip(names, images, strict=True), record, replace=replace)


def _measured(
    frames: Iterable[RenderedFrame],
    focus: list[FrameFocus],
) -> Iterator[RenderedFrame]:
    """Pass the frames through, keeping each one's focus statistics in ``focus``."""
    for frame in frames:
        focus.append(frame_focus(frame.object_alphas, frame.disparity))
        yield frame


def write_sequence(
    seq_dir: Path,
    frames: Iterable[RenderedFrame],
    n_frames: int | None = None,
) -> None:
    """Write one sequence's three streams into ``seq_dir``, and its layers and flow if it
    has them.

    Frames rendered with ``layers`` also write ``layers/``: the background and each
    object per frame, then ``paint_order.json``, the objects far to near in each frame.
    It comes last, so a ``layers/`` without it was interrupted. Frames rendered with
    ``flow`` write ``flow/``, one file per frame but the last. Any ``layers/``, ``flow/``
    or ``bokeh/`` already in ``seq_dir`` is removed first: an earlier run's would
    otherwise pass for this one's.

    ``frames`` may be a generator, written as it yields, so that a long sequence is
    never held whole; ``n_frames`` then says how many it yields.

    The frame-number width comes from the frame count, so an 80-frame sequence is
    ``01``..``80`` and a 100-frame one is ``001``..``100``. The bridge and
    ``preview.pack`` both sort on the numeric prefix, so the width only has to be
    consistent inside a sequence.
    """
    aif = seq_dir / "all_in_focus"
    alp = seq_dir / "alpha"
    disp = seq_dir / "disparity"
    for d in (aif, alp, disp):
        d.mkdir(parents=True, exist_ok=True)
    layer_root = seq_dir / "layers"
    shutil.rmtree(layer_root, ignore_errors=True)
    shutil.rmtree(seq_dir / "bokeh", ignore_errors=True)
    flow_dir = seq_dir / "flow"
    shutil.rmtree(flow_dir, ignore_errors=True)
    if n_frames is None:
        frames = list(frames)
        n_frames = len(frames)
    paint_orders: list[list[int]] = []
    for fi, frame in enumerate(frames):
        stem = _frame_stem(fi, n_frames)
        _save_frame(frame, stem, aif, alp, disp)
        if frame.layers is not None:
            if not paint_orders:
                for name in _LAYER_DIRS:
                    (layer_root / name).mkdir(parents=True, exist_ok=True)
            _save_layers(frame.layers, frame.object_alphas, stem, layer_root)
            paint_orders.append(frame.layers.paint_order)
        if frame.flow is not None:
            flow_dir.mkdir(exist_ok=True)
            write_flow_png(flow_dir / f"{stem}.png", frame.flow)
    if paint_orders:
        write_paint_order(layer_root / "paint_order.json", paint_orders)


def generate_dataset(
    library_root: Path,
    output: Path,
    count: int,
    n_frames: int,
    size: int,
    seed: int,
    n_objects_min: int = 1,
    n_objects_max: int = 5,
    cfg: SampleConfig | None = None,
    layers: bool = False,
    bokeh: bool = False,
    bokeh_strength: float = BOKEH_STRENGTH,
    flow: bool = False,
) -> int:
    """Write ``count`` sequences and return how many were actually written.

    With ``bokeh``, each sequence's bokeh is rendered in the same run, from the layers
    held in memory; ``layers`` decides separately whether they are written too. With
    ``flow``, each sequence's forward optical flow is written in the same pass.

    A sequence whose trajectories cannot be made collision-free is skipped, not
    written. Sequence names stay tied to the seed, so a skip leaves a gap in the
    numbering rather than shifting every later sequence onto a different seed.
    """
    cfg = cfg or SampleConfig()
    if bokeh and importlib.util.find_spec("torch") is None:
        raise ValueError(
            "bokeh needs torch: install the render or the loader extra",
        )
    if bokeh and not (math.isfinite(bokeh_strength) and bokeh_strength >= 0):
        raise ValueError(f"bokeh strength must be 0 or more, got {bokeh_strength}")
    output.mkdir(parents=True, exist_ok=True)
    rows: list[list[str]] = []
    skipped: list[int] = []

    for i in range(count):
        seq_seed = seed + i
        try:
            scene = sample_sequence(
                library_root,
                seed=seq_seed,
                n_frames=n_frames,
                size=size,
                n_objects_min=n_objects_min,
                n_objects_max=n_objects_max,
                cfg=cfg,
            )
        except CollisionRetriesExhausted as exc:
            skipped.append(seq_seed)
            print(f"  skip  seed={seq_seed}  {exc}")
            continue
        seq_name = f"{i + 1:04d}"
        seq_dir = output / "sequences" / seq_name
        focus: list[FrameFocus] = []
        frames = iter_frames(scene, layers=layers, flow=flow)
        write_sequence(seq_dir, _measured(frames, focus) if bokeh else frames, n_frames)
        if bokeh:
            write_bokeh_stream(seq_dir, scene, seq_seed, focus, bokeh_strength)
        rows.append(
            [
                seq_name,
                str(seq_seed),
                str(n_frames),
                str(size),
                str(len(scene.objects)),
                str(scene.n_rejections),
                str(scene.n_range_fallbacks),
            ],
        )
        print(
            f"  {seq_name}  seed={seq_seed}  "
            f"n_obj={len(scene.objects)}  frames={n_frames}",
        )

    with (output / "manifest.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(_MANIFEST_FIELDS)
        writer.writerows(rows)

    if skipped:
        print(f"\nSkipped {len(skipped)} of {count} sequences; seeds: {skipped}")
    return len(rows)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--frames", type=int, default=80)
    parser.add_argument("--size", type=int, default=1024)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--n-objects-min", type=int, default=1)
    parser.add_argument("--n-objects-max", type=int, default=5)
    parser.add_argument(
        "--bokeh",
        action="store_true",
        help="also render each sequence's bokeh in the same run, with the layered "
        "renderer, from the layers in memory; needs torch",
    )
    parser.add_argument(
        "--bokeh-strength",
        type=float,
        default=BOKEH_STRENGTH,
        help=f"the bokeh's strength, as any-to-bokeh's k (default: {BOKEH_STRENGTH:g})",
    )
    parser.add_argument(
        "--layers",
        action="store_true",
        help="also write layers/: the background and each object per frame, before "
        "compositing, for a layer-wise bokeh renderer",
    )
    parser.add_argument(
        "--flow",
        action="store_true",
        help="also write flow/: each frame's exact forward optical flow to the next, as "
        "KITTI's 16-bit PNG",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        written = generate_dataset(
            library_root=args.library_root,
            output=args.output,
            count=args.count,
            n_frames=args.frames,
            size=args.size,
            seed=args.seed,
            n_objects_min=args.n_objects_min,
            n_objects_max=args.n_objects_max,
            layers=args.layers,
            bokeh=args.bokeh,
            bokeh_strength=args.bokeh_strength,
            flow=args.flow,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(f"\nDone. {written} sequences in {args.output / 'sequences'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
