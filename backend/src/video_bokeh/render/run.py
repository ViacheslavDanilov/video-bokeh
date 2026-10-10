#!/usr/bin/env python3
"""Render bokeh for written sequences (Stage C).

Reads each sequence's all_in_focus, alpha and disparity streams and writes its bokeh
stream beside them:

    <data-root>/sequences/<id>/bokeh/<frame>.png   RGB uint8, the sequence's size

Usage:
    uv run --extra render python -m video_bokeh.render.run --data-root data/synth_dev

With ``--missing`` it renders only the sequences that have no ``bokeh/`` yet, and leaves
out any the renderer cannot take, saying which: shorter than any-to-bokeh can group, or
without the layers ``--renderer layered`` needs. Pointed at the API's data root,
that renders whatever the page has generated since the last run: ``make bokeh``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from video_bokeh.bridge.any_to_bokeh import list_png_frames
from video_bokeh.core._seq_io import has_layers, list_sequences
from video_bokeh.render import RENDERERS, resolve_renderer


def _validated_renderer(spec: str) -> str:
    try:
        resolve_renderer(spec)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return spec


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument(
        "--seqs",
        type=lambda s: [p.strip() for p in s.split(",") if p.strip()],
        default=None,
        help="comma-separated sequence ids (e.g. '0001,0003'). Default: all.",
    )
    parser.add_argument(
        "--renderer",
        type=_validated_renderer,
        default="any-to-bokeh",
        help=f"one of {', '.join(sorted(RENDERERS))}, or package.module:ClassName "
        "for a renderer of your own (default: any-to-bokeh).",
    )
    parser.add_argument(
        "--strength",
        type=float,
        default=16.0,
        help="blur strength, as any-to-bokeh's k: the blur radius in pixels, at a "
        "1024-pixel width, one unit of disparity from the focus (default: 16).",
    )
    parser.add_argument(
        "--focus-disparity",
        type=float,
        default=None,
        help="fixed in-focus disparity in [0, 1] for every frame. Default: the "
        "focus follows one object, drawn by area.",
    )
    parser.add_argument(
        "--missing",
        action="store_true",
        help="render only the sequences without bokeh/, leaving out any shorter than "
        "the renderer can take",
    )
    return parser


def _still_missing(
    seq_dirs: list[Path],
    min_frames: int,
    needs_layers: bool,
) -> list[Path]:
    """The sequences with no bokeh yet that the renderer can take, saying what it skips."""
    todo: list[Path] = []
    for seq in seq_dirs:
        if (seq / "bokeh").is_dir():
            continue
        if needs_layers and not has_layers(seq):
            print(f"  skip {seq.name}: no complete layers/, which the renderer needs")
            continue
        frames = len(list_png_frames(seq / "all_in_focus"))
        if frames < min_frames:
            print(
                f"  skip {seq.name}: {frames} frames, the renderer needs {min_frames}",
            )
            continue
        todo.append(seq)
    return todo


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.focus_disparity is not None and not 0 <= args.focus_disparity <= 1:
        parser.error("--focus-disparity must be in [0, 1]")
    seq_root = args.data_root / "sequences"
    if args.missing and not seq_root.is_dir():
        # A page that has generated nothing yet, not a mistake.
        print(f"Nothing to render: no sequences under {seq_root} yet.")
        return 0
    seq_dirs = list_sequences(args.data_root, args.seqs)
    for unfinished in sorted(seq_root.glob(".*")):
        if unfinished.is_dir():
            print(f"  skip {unfinished.name}: still being written")
    if not seq_dirs:
        if args.missing:
            print(f"Nothing to render: no finished sequences under {seq_root} yet.")
            return 0
        raise SystemExit(f"no sequences to render under {seq_root}")

    renderer = resolve_renderer(args.renderer)()
    if args.missing:
        seq_dirs = _still_missing(
            seq_dirs,
            getattr(renderer, "min_frames", 0),
            getattr(renderer, "needs_layers", False),
        )
        if not seq_dirs:
            print(
                "Nothing to render: every sequence has bokeh or is one the renderer "
                "cannot take.",
            )
            return 0
    print(f"Rendering {len(seq_dirs)} sequence(s) with {args.renderer}")
    renderer.render(seq_dirs, args.strength, args.focus_disparity)
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
