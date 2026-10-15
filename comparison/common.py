"""What the adapters in this folder share: reading our sequences and writing a method's bokeh.

Every adapter renders a sequence's frames from our layers, at the focus disparity and the
strength that our own renderer recorded in ``bokeh/focus.json``, so that its output compares
with ours like for like. They run in ``comparison/envs/render``, which has torch and none of the
backend's other dependencies, so the backend's source is put on the path here.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend" / "src"))

from video_bokeh.core._seq_io import (  # noqa: E402
    frame_names,
    has_layers,
    list_sequences,
)
from video_bokeh.layered import LayeredFrame  # noqa: E402
from video_bokeh.render.layered import _read_frames  # noqa: E402

#: The power the renderers raise colors to, around the blur, as an approximation of linear light.
GAMMA = 2.2
#: The frame width at which a strength is a radius in pixels.
REFERENCE_WIDTH = 1024


def renderable_sequences(data_root: Path, names: list[str] | None) -> Iterator[Path]:
    """The sequences under ``data_root`` that hold layers and a focus record.

    The others are named and skipped, as they cannot be rendered from layers or compared.
    """
    for seq in list_sequences(data_root, names):
        if not has_layers(seq) or not (seq / "bokeh" / "focus.json").is_file():
            print(f"  skip {seq.name}: needs layers/ and bokeh/focus.json", flush=True)
            continue
        yield seq


def focus_record(seq: Path) -> dict:
    """The focus our renderer recorded: its ``zf`` per frame, ``strength`` and ``object``."""
    return json.loads((seq / "bokeh" / "focus.json").read_text(encoding="utf-8"))


def frames_with_focus(seq: Path) -> Iterator[tuple[str, float, LayeredFrame]]:
    """Each frame's name, its in-focus disparity and its layers."""
    names = frame_names(seq)
    zfs = focus_record(seq)["zf"]
    yield from zip(names, zfs, _read_frames(seq, names), strict=True)


def save_rgb(directory: Path, name: str, rgb: np.ndarray) -> None:
    """Write an ``(H, W, 3)`` image in ``[0, 1]`` as an 8-bit PNG."""
    directory.mkdir(parents=True, exist_ok=True)
    pixels = np.round(np.clip(rgb, 0.0, 1.0) * 255.0).astype(np.uint8)
    Image.fromarray(pixels).save(directory / name)


def write_settings(directory: Path, method: str, seq: Path, **extra: object) -> None:
    """Record what made a method's frames, beside them."""
    record = focus_record(seq)
    settings = {
        "method": method,
        "strength": record["strength"],
        "zf": record["zf"],
        "focus_object": record.get("object"),
        "source": "our layers and our focus record",
        **extra,
    }
    (directory / "run.json").write_text(json.dumps(settings) + "\n", encoding="utf-8")
