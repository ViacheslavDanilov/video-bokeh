#!/usr/bin/env python3
"""Render sequences' bokeh with Any-to-Bokeh, from the all-in-focus frames and their disparity.

Runs in ``comparison/envs/render`` and starts Any-to-Bokeh's own demo in its environment,
``comparison/envs/any-to-bokeh``, through ``a2b_launch.py`` (see ``comparison/README.md``).
It skips every sequence under ``--data-root`` that was not written with ``--layers`` or holds
no ``bokeh/focus.json``, so that the focus and the strength are the ones our renderer
recorded, and every sequence of fewer than 13 frames, which the demo cannot group. For the
others it writes

    <sequence>/bokeh_any_to_bokeh/<frame>.png   RGB uint8, the sequence's size
    <sequence>/bokeh_any_to_bokeh/run.json      the settings

Any-to-Bokeh (https://github.com/vivoCameraResearch/any-to-bokeh, ICLR 2026; code and weights
CC BY-NC 4.0) is a video diffusion model, the learned baseline of the comparison and not a
reference. It takes a clip of frames and one 8-bit disparity map per frame whose file name
carries that frame's focus, ``<frame>_zf_<focus>.png``, and a blur strength ``k``. The demo
works at 1024 x 576 whatever it is given, so our square frames are stretched to that size, and
its blur is 1.78 times taller than wide. It writes an H.264 video, whose frames are resized
back to the sequence's size here and are lossy. Our disparity is quantized to 8 bits once.

Usage:
    comparison/envs/render/bin/python comparison/run_any_to_bokeh.py --data-root data/synth_dev
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import tempfile
from pathlib import Path

import imageio.v2 as imageio
import numpy as np
from common import (
    composite_frame,
    focus_record,
    frame_names,
    renderable_sequences,
    write_settings,
)
from PIL import Image

HERE = Path(__file__).resolve().parent
A2B_ROOT = HERE / "third_party" / "any-to-bokeh"
A2B_PYTHON = HERE / "envs" / "any-to-bokeh" / "bin" / "python"

#: The demo groups frames eight at a time, four overlapping. It cannot group a sequence of
#: eight frames or fewer, and nine to twelve fail after the model has loaded.
MIN_FRAMES = 13


def write_inputs(seqs: list[Path], work: Path) -> Path:
    """Write the demo's inputs for ``seqs`` under ``work`` and return its CSV.

    Per sequence, a folder of frames and a folder of 8-bit disparity maps named for each
    frame's focus. The CSV names them by absolute path, in the order of ``seqs``, with the
    strength ``k`` that our renderer recorded.
    """
    rows = []
    for seq in seqs:
        record = focus_record(seq)
        videos, disp = work / "videos" / seq.name, work / "disp" / seq.name
        videos.mkdir(parents=True)
        disp.mkdir(parents=True)
        for name, zf in zip(frame_names(seq), record["zf"], strict=True):
            rgb, disparity = composite_frame(seq, name)
            stem = Path(name).stem
            Image.fromarray(np.round(rgb * 255.0).astype(np.uint8)).save(
                videos / f"{stem}.png"
            )
            quantized = np.round(disparity * 255.0).astype(np.uint8)
            Image.fromarray(quantized).save(disp / f"{stem}_zf_{zf:.6f}.png")
        rows.append([str(videos), str(disp), f"{float(record['strength']):g}"])
    path = work / "inputs.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["aif_folder", "disp_folder", "k"])
        writer.writerows(rows)
    return path


def run_demo(csv_path: Path, work: Path) -> None:
    """Run the demo on ``csv_path``; it writes ``output/<row>.mp4`` under ``work``."""
    for sub in ("unet", "vae"):
        if not (A2B_ROOT / "checkpoints" / sub).is_dir():
            raise SystemExit(
                f"no Any-to-Bokeh checkpoint at {A2B_ROOT / 'checkpoints' / sub}: "
                "run comparison/setup.sh a2b"
            )
    if not A2B_PYTHON.exists():
        raise SystemExit(f"no environment at {A2B_PYTHON}: run comparison/setup.sh a2b")
    command = [
        str(A2B_PYTHON),
        str(HERE / "a2b_launch.py"),
        str(A2B_ROOT / "test" / "inference_demo.py"),
        "--val_csv_path",
        str(csv_path),
        "--unet_path",
        str(A2B_ROOT / "checkpoints" / "unet"),
        "--vae_path",
        str(A2B_ROOT / "checkpoints" / "vae"),
    ]
    # The demo writes output/ relative to its working directory.
    subprocess.run(command, cwd=work, check=True)


def decode(video: Path, seq: Path) -> list[Image.Image]:
    """The frames of ``video``, checked against the sequence's own frame count."""
    reader = imageio.get_reader(video)
    try:
        frames = [Image.fromarray(frame) for frame in reader.iter_data()]
    finally:
        reader.close()
    expected = len(frame_names(seq))
    if len(frames) != expected:
        raise RuntimeError(
            f"Any-to-Bokeh returned {len(frames)} frames for {expected} in {seq.name}"
        )
    return frames


def write_frames(frames: list[Image.Image], seq: Path) -> None:
    """Write one sequence's decoded frames to ``bokeh_any_to_bokeh/``, at its own size."""
    names = frame_names(seq)
    with Image.open(seq / "all_in_focus" / names[0]) as first:
        size = first.size
    out = seq / "bokeh_any_to_bokeh"
    out.mkdir(parents=True, exist_ok=True)
    for name, frame in zip(names, frames, strict=True):
        frame.convert("RGB").resize(size, Image.Resampling.BICUBIC).save(out / name)
    write_settings(
        out, "Any-to-Bokeh", seq, resized_from=list(frames[0].size), lossy="H.264"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--seqs", default=None, help="comma-separated sequence ids")
    args = parser.parse_args(argv)
    names = args.seqs.split(",") if args.seqs else None
    seqs = []
    for seq in renderable_sequences(args.data_root, names):
        count = len(frame_names(seq))
        if count < MIN_FRAMES:
            print(f"  skip {seq.name}: {count} frames, the demo needs {MIN_FRAMES}")
            continue
        seqs.append(seq)
    if not seqs:
        print("nothing to render")
        return 0
    with tempfile.TemporaryDirectory(prefix="any-to-bokeh-") as tmp:
        work = Path(tmp)
        csv_path = write_inputs(seqs, work)
        run_demo(csv_path, work)
        # Every count is checked before any frame is written, so a short output leaves no
        # sequence rendered while its neighbors are not.
        decoded = [
            decode(work / "output" / f"{index}.mp4", seq)
            for index, seq in enumerate(seqs)
        ]
        for seq, frames in zip(seqs, decoded, strict=True):
            write_frames(frames, seq)
            print(f"  {seq.name}: bokeh_any_to_bokeh written", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
