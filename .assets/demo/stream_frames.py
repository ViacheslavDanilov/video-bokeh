"""Writes the streams scene's frames: the preview's own coloring, Lanczos-scaled to 824 px.

824 px is a stream tile (412 CSS px) at the 4K render's 2x scale. Run from backend/:
    uv run python ../.assets/demo/stream_frames.py SEQ_DIR OUT_DIR
"""

import sys
from pathlib import Path

from PIL import Image

from video_bokeh.preview.pack import _flow_frames, list_stream_frames, load_frame

SIZE = 824
seq_dir, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
for stream in ("all_in_focus", "bokeh", "disparity", "flow"):
    paths = list_stream_frames(seq_dir, stream)
    frames = (
        _flow_frames(paths)
        if stream == "flow"
        else (load_frame(p, stream, "spectral_r") for p in paths)
    )
    (out_dir / stream).mkdir(parents=True, exist_ok=True)
    n = 0
    for n, frame in enumerate(frames, 1):
        image = Image.fromarray(frame).resize((SIZE, SIZE), Image.LANCZOS)
        image.save(out_dir / stream / f"{n:03d}.png", compress_level=1)
    print(stream, n)
