#!/usr/bin/env python3
"""Render bokeh for written sequences (Stage C).

Reads each sequence's all_in_focus, alpha and disparity streams and writes its bokeh
stream beside them:

    <data-root>/sequences/<id>/bokeh/<frame>.png   RGB uint8, the sequence's size

Usage:
    uv run --extra render python -m video_bokeh.render.run --data-root data/synth_dev
"""

from __future__ import annotations

import argparse
from pathlib import Path

from video_bokeh.core._seq_io import list_sequences
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
        help="blur strength; any-to-bokeh takes it as its k (default: 16).",
    )
    parser.add_argument(
        "--focus-disparity",
        type=float,
        default=None,
        help="fixed in-focus disparity in [0, 1] for every frame. Default: the "
        "renderer chooses; any-to-bokeh focuses on the objects.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.focus_disparity is not None and not 0 <= args.focus_disparity <= 1:
        parser.error("--focus-disparity must be in [0, 1]")
    seq_dirs = list_sequences(args.data_root, args.seqs)
    if not seq_dirs:
        raise SystemExit(f"no sequences to render under {args.data_root / 'sequences'}")

    renderer = resolve_renderer(args.renderer)()
    print(f"Rendering {len(seq_dirs)} sequence(s) with {args.renderer}")
    renderer.render(seq_dirs, args.strength, args.focus_disparity)
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
