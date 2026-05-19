#!/usr/bin/env python3
"""Generate synthetic video sequences for matting-network training.

Each sequence composites 1–3 MAGICK foregrounds (RGBA) over one BG-20k
background, with smooth keyframed perspective motion per layer. Three
pixel-aligned streams are written per frame: all-in-focus RGB (input to
Depth Anything and what the matting net sees), union alpha (matting GT),
and per-object alpha layers packed into a single RGB PNG.

Layout:

    <out>/
    ├── manifest.csv                  # one row per sequence (seed-driven + post-render channel map)
    └── sequences/
        └── 0001/
            ├── all_in_focus/01.png … 80.png    # RGB composite (input to Depth Anything)
            ├── alpha/01.png … 80.png           # union alpha (matting GT)
            └── alpha_layers/01.png … 80.png    # per-object alpha; R=ch0 (bottommost), G=ch1, B=ch2

The channel index in `alpha_layers` encodes paint order (0 = drawn first
over the background, N-1 = drawn last on top). It is NOT depth order —
non-occluding objects have arbitrary channel ordering. The post-render
column `channel_refs` in `manifest.csv` is the source of truth for the
channel ↔ source-image mapping (pipe-separated, in channel order). Slots
beyond `len(channel_refs)` in the alpha_layers PNG are zero-filled.

Rendering is deterministic: same row in the manifest → byte-identical output.
Re-run with `--from-manifest` to re-render a (possibly edited) manifest.

Usage:
    uv run python -m data.generate_sequences \
        --fg-data-root backend/data/magick_dev \
        --bg-data-root backend/data/bg-20k_dev \
        --output  backend/data/synth_dev \
        --count   10 \
        --seed    0

    uv run python -m data.generate_sequences ... \
        --subjects person,animal,plant \
        --subject-thr 0.6
"""

from __future__ import annotations

import argparse
import csv
import random
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

from data._sequence_geometry import (
    EASING_FNS,
    EASING_NAMES_DEFAULT,
    SampleConfig,
    replay_scene,
)

# Max per-object alpha layers packed into the RGB channels of a single
# `alpha_layers/<frame>.png`. Capped at 3 because a single RGB PNG has 3
# channels; supporting more layers would require a multi-channel TIFF or a
# second sidecar PNG.
LAYER_CHANNELS = 3

# --------------------------------------------------------------------------- #
# Foreground filter defaults                                                  #
# --------------------------------------------------------------------------- #
DEFAULT_KEEP_SUBJECTS: tuple[str, ...] = ("person", "animal", "plant", "food", "object")
DEFAULT_KEEP_STYLES: tuple[str, ...] = ("photo", "render")
DEFAULT_SUBJECT_THR: float = 0.50
DEFAULT_STYLE_THR: float = 0.00


def _load_predictions(fg_root: Path) -> pd.DataFrame:
    """Load <fg_root>/predictions.csv as a DataFrame indexed by page_id."""
    path = fg_root / "predictions.csv"
    if not path.exists():
        raise SystemExit(
            f"foreground filtering requires {path}; "
            f"run `data.classify_clip` on {fg_root} first.",
        )
    return pd.read_csv(path, encoding="utf-8-sig").set_index("page_id")


def list_foreground_refs(
    fg_root: Path,
    subjects: tuple[str, ...] | list[str] | None = DEFAULT_KEEP_SUBJECTS,
    styles: tuple[str, ...] | list[str] | None = DEFAULT_KEEP_STYLES,
    subject_thr: float = DEFAULT_SUBJECT_THR,
    style_thr: float = DEFAULT_STYLE_THR,
) -> list[str]:
    """Return relative paths like ``0L/0LZCNUeBHK.png`` under ``<fg_root>/images``.

    A foreground is kept when ``top_subject`` ∈ ``subjects``, ``top_style`` ∈
    ``styles``, ``top_subject_score`` ≥ ``subject_thr``, and
    ``top_style_score`` ≥ ``style_thr``. Pass an empty / None list or 0.0 to
    skip the corresponding predicate.
    """
    root = fg_root / "images"
    if not root.exists():
        raise FileNotFoundError(f"foreground images dir missing: {root}")
    refs = sorted(str(p.relative_to(root)) for p in root.rglob("*.png") if p.is_file())

    needs_filter = (
        bool(subjects) or bool(styles) or subject_thr > 0.0 or style_thr > 0.0
    )
    if not needs_filter:
        return refs

    preds = _load_predictions(fg_root)
    mask = pd.Series(True, index=preds.index)
    if subjects:
        mask &= preds["top_subject"].isin(list(subjects))
    if styles:
        mask &= preds["top_style"].isin(list(styles))
    if subject_thr > 0.0:
        mask &= preds["top_subject_score"] >= subject_thr
    if style_thr > 0.0:
        mask &= preds["top_style_score"] >= style_thr

    kept_ids = set(preds.index[mask])
    return [r for r in refs if Path(r).stem in kept_ids]


def list_background_refs(bg_root: Path) -> list[str]:
    """Return list of relative paths like 'train/h_abc.jpg' under images/."""
    root = bg_root / "images"
    if not root.exists():
        raise FileNotFoundError(f"background images dir missing: {root}")
    refs: list[str] = []
    for ext in ("*.jpg", "*.jpeg", "*.png"):
        refs.extend(str(p.relative_to(root)) for p in root.rglob(ext) if p.is_file())
    return sorted(refs)


# --------------------------------------------------------------------------- #
# Sequence specs & manifest                                                   #
# --------------------------------------------------------------------------- #


@dataclass
class SequenceSpec:
    seq_id: int
    seed: int
    n_frames: int
    size: int
    bg_ref: str  # e.g. 'train/h_abc.jpg'
    object_refs: list[str]  # input order; e.g. ['0L/0LZCNUeBHK.png', ...]
    # Post-render: source ref per alpha_layers channel, in paint order.
    # Empty until render_sequence has run.
    channel_refs: list[str] = field(default_factory=list)
    # Per-layer easing names; paint-order aligned with channel_refs.
    # When loaded from manifest these guard render_sequence's sampling so
    # `--from-manifest` reproduces the recorded scene.
    bg_easing: str = ""
    object_easings: list[str] = field(default_factory=list)
    # Paint-order aligned with channel_refs; larger means farther from camera.
    object_depths: list[float] = field(default_factory=list)


MANIFEST_FIELDS = (
    "seq_id",
    "seed",
    "n_frames",
    "size",
    "bg_ref",
    "object_refs",
    "channel_refs",
    "bg_easing",
    "object_easings",
    "object_depths",
)


def _bg_split(bg_ref: str) -> str:
    head, _, _ = bg_ref.partition("/")
    return head


def build_manifest(args: argparse.Namespace) -> list[SequenceSpec]:
    fg_refs = list_foreground_refs(
        args.fg_data_root,
        subjects=args.subjects,
        styles=args.styles,
        subject_thr=args.subject_thr,
        style_thr=args.style_thr,
    )
    bg_refs = list_background_refs(args.bg_data_root)
    if not fg_refs:
        raise SystemExit(
            f"no foregrounds under {args.fg_data_root}/images match the filter "
            f"(subjects={args.subjects}, styles={args.styles}, "
            f"subject_thr={args.subject_thr}, style_thr={args.style_thr})",
        )
    if not bg_refs:
        raise SystemExit(f"no backgrounds found under {args.bg_data_root}/images")

    specs: list[SequenceSpec] = []
    for i in range(args.count):
        seq_seed = args.seed + i
        rng = random.Random(seq_seed)
        n_obj = rng.randint(args.n_objects_min, args.n_objects_max)
        n_obj = min(n_obj, len(fg_refs))
        objs = rng.sample(fg_refs, n_obj)
        bg = rng.choice(bg_refs)
        specs.append(
            SequenceSpec(
                seq_id=i + 1,
                seed=seq_seed,
                n_frames=args.frames,
                size=args.size,
                bg_ref=bg,
                object_refs=objs,
            ),
        )
    return specs


def write_manifest(path: Path, specs: list[SequenceSpec]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(MANIFEST_FIELDS)
        for s in specs:
            writer.writerow(
                [
                    s.seq_id,
                    s.seed,
                    s.n_frames,
                    s.size,
                    s.bg_ref,
                    "|".join(s.object_refs),
                    "|".join(s.channel_refs),
                    s.bg_easing,
                    "|".join(s.object_easings),
                    "|".join(f"{d:.17g}" for d in s.object_depths),
                ],
            )


def read_manifest(path: Path) -> list[SequenceSpec]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        specs: list[SequenceSpec] = []
        for row in reader:
            object_refs = [r for r in row["object_refs"].split("|") if r]
            object_easings = [
                e for e in (row.get("object_easings") or "").split("|") if e
            ]
            # Legacy fallback: an old manifest with no easing columns must
            # re-render bit-identically. Fill with the cosine ease-in-out
            # under its new name so render_sequence's sampling guard skips.
            bg_easing = row.get("bg_easing") or "easeInOutSine"
            if not object_easings:
                object_easings = ["easeInOutSine"] * len(object_refs)
            object_depths = [
                float(d) for d in (row.get("object_depths") or "").split("|") if d
            ]
            specs.append(
                SequenceSpec(
                    seq_id=int(row["seq_id"]),
                    seed=int(row["seed"]),
                    n_frames=int(row["n_frames"]),
                    size=int(row["size"]),
                    bg_ref=row["bg_ref"],
                    object_refs=object_refs,
                    channel_refs=[
                        r for r in (row.get("channel_refs") or "").split("|") if r
                    ],
                    bg_easing=bg_easing,
                    object_easings=object_easings,
                    object_depths=object_depths,
                ),
            )
    return specs


# --------------------------------------------------------------------------- #
# Rendering                                                                   #
# --------------------------------------------------------------------------- #


def _save_frame(
    rgb: np.ndarray,
    alpha: np.ndarray,
    layers: np.ndarray,
    aif_path: Path,
    alpha_path: Path,
    layers_path: Path,
) -> None:
    """Persist the three pixel-aligned streams for one frame."""
    Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), mode="RGB").save(
        aif_path,
        compress_level=6,
    )
    Image.fromarray(np.clip(alpha * 255.0, 0, 255).astype(np.uint8), mode="L").save(
        alpha_path,
        compress_level=6,
    )
    # (F, F, 3) RGB PNG: R=ch0 alpha, G=ch1, B=ch2. Empty channels = 0.
    layers_rgb = np.transpose(
        np.clip(layers * 255.0, 0, 255).astype(np.uint8),
        (1, 2, 0),
    )
    Image.fromarray(layers_rgb, mode="RGB").save(layers_path, compress_level=6)


def render_sequence(
    spec: SequenceSpec,
    fg_root: Path,
    bg_root: Path,
    out_dir: Path,
    cfg: SampleConfig,
) -> None:
    """Render one sequence and populate spec.channel_refs / spec.bg_easing /
    spec.object_easings / spec.object_depths (all paint-order aligned)."""
    replay = replay_scene(spec, fg_root, bg_root, cfg)
    if len(replay.channel_refs) > LAYER_CHANNELS:
        raise ValueError(
            f"sequence {spec.seq_id}: {len(replay.channel_refs)} objects > LAYER_CHANNELS="
            f"{LAYER_CHANNELS}; alpha_layers PNG can pack at most 3 layers.",
        )

    aif_dir = out_dir / "all_in_focus"
    alpha_dir = out_dir / "alpha"
    layers_dir = out_dir / "alpha_layers"
    for d in (aif_dir, alpha_dir, layers_dir):
        d.mkdir(parents=True, exist_ok=True)

    digits = max(2, len(str(spec.n_frames)))
    frame_size = spec.size

    for i, frame in enumerate(replay.frames):
        rgb = np.asarray(frame.bg_rgb, dtype=np.float32)
        alpha = np.zeros((frame_size, frame_size), dtype=np.float32)
        layers = np.zeros((LAYER_CHANNELS, frame_size, frame_size), dtype=np.float32)

        for ch, fg_warp in enumerate(frame.object_rgbas):
            fg_arr = np.asarray(fg_warp, dtype=np.float32)
            fg_a = fg_arr[..., 3] / 255.0
            a = fg_a[..., None]
            rgb = a * fg_arr[..., :3] + (1.0 - a) * rgb
            alpha = np.maximum(alpha, fg_a)
            layers[ch] = fg_a

        name = f"{i + 1:0{digits}d}.png"
        _save_frame(
            rgb,
            alpha,
            layers,
            aif_dir / name,
            alpha_dir / name,
            layers_dir / name,
        )

    spec.channel_refs = list(replay.channel_refs)
    spec.bg_easing = replay.bg_easing
    spec.object_easings = list(replay.object_easings)
    spec.object_depths = list(replay.object_depths)


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fg-data-root", type=Path, default=Path("data/magick_dev"))
    parser.add_argument("--bg-data-root", type=Path, default=Path("data/bg-20k_dev"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--frames", type=int, default=80)
    parser.add_argument("--size", type=int, default=1024)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--n-objects-min", type=int, default=1)
    parser.add_argument("--n-objects-max", type=int, default=3)
    parser.add_argument("--scale-min", type=float, default=0.20)
    parser.add_argument("--scale-max", type=float, default=0.80)
    parser.add_argument("--max-exit", type=float, default=0.20)
    parser.add_argument("--max-rot", type=float, default=25.0)
    parser.add_argument("--max-tilt", type=float, default=15.0)
    parser.add_argument("--bg-pan", type=float, default=0.10)
    parser.add_argument("--bg-zoom", type=float, default=0.10)
    parser.add_argument(
        "--easings",
        type=lambda s: tuple(c.strip() for c in s.split(",") if c.strip()),
        default=EASING_NAMES_DEFAULT,
        help=(
            "Comma-separated subset of easing names to sample from per layer "
            "(background and each foreground). Default: all 9. Pass a single "
            "name to use one easing for every layer."
        ),
    )
    parser.add_argument(
        "--subjects",
        type=lambda s: [c.strip() for c in s.split(",") if c.strip()],
        default=list(DEFAULT_KEEP_SUBJECTS),
        help=(
            "Comma-separated subject labels to keep "
            f"(default: {','.join(DEFAULT_KEEP_SUBJECTS)}). "
            "Pass an empty string to disable subject-axis filtering. "
            "Requires <fg-data-root>/predictions.csv from `data.classify_clip`."
        ),
    )
    parser.add_argument(
        "--styles",
        type=lambda s: [c.strip() for c in s.split(",") if c.strip()],
        default=list(DEFAULT_KEEP_STYLES),
        help=(
            "Comma-separated style labels to keep "
            f"(default: {','.join(DEFAULT_KEEP_STYLES)}). "
            "Pass an empty string to disable style-axis filtering."
        ),
    )
    parser.add_argument(
        "--subject-thr",
        type=float,
        default=DEFAULT_SUBJECT_THR,
        help=(
            "Minimum top_subject_score to keep a foreground "
            f"(default: {DEFAULT_SUBJECT_THR}). Set to 0 to disable."
        ),
    )
    parser.add_argument(
        "--style-thr",
        type=float,
        default=DEFAULT_STYLE_THR,
        help=(
            "Minimum top_style_score to keep a foreground "
            f"(default: {DEFAULT_STYLE_THR}; 0 disables)."
        ),
    )
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="Write the manifest and exit; skip rendering.",
    )
    parser.add_argument(
        "--from-manifest",
        type=Path,
        default=None,
        help="Render a (possibly hand-edited) manifest.csv instead of building one.",
    )
    return parser


def _validate_easings(names: tuple[str, ...]) -> None:
    if not names:
        raise SystemExit("--easings cannot be empty")
    unknown = [n for n in names if n not in EASING_FNS]
    if unknown:
        raise SystemExit(
            f"unknown easing(s): {unknown}; valid: {sorted(EASING_FNS)}",
        )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _validate_easings(tuple(args.easings))

    cfg = SampleConfig(
        scale_min=args.scale_min,
        scale_max=args.scale_max,
        max_exit=args.max_exit,
        max_rot=args.max_rot,
        max_tilt=args.max_tilt,
        bg_pan=args.bg_pan,
        bg_zoom=args.bg_zoom,
        easings=tuple(args.easings),
    )

    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output / "manifest.csv"

    if args.from_manifest is not None:
        specs = read_manifest(args.from_manifest)
        print(f"Loaded {len(specs)} sequence(s) from {args.from_manifest}")
    else:
        specs = build_manifest(args)
        write_manifest(manifest_path, specs)
        print(f"Wrote manifest: {manifest_path} ({len(specs)} sequence(s))")
        if args.manifest_only:
            return 0

    for spec in specs:
        seq_name = f"{spec.seq_id:04d}"
        out_dir = args.output / "sequences" / seq_name
        print(
            f"  {seq_name}  seed={spec.seed}  "
            f"bg={_bg_split(spec.bg_ref)}  n_obj={len(spec.object_refs)}  "
            f"frames={spec.n_frames}",
        )
        render_sequence(
            spec,
            args.fg_data_root,
            args.bg_data_root,
            out_dir,
            cfg,
        )
        # Rewrite manifest after each sequence so channel_refs are durable
        # against Ctrl-C mid-batch.
        write_manifest(manifest_path, specs)

    print(f"\nDone. Sequences in {args.output / 'sequences'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
