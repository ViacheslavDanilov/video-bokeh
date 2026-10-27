"""Writes the streams scene's frames: the preview's own coloring, Lanczos-scaled to 688 px.

688 px is a stream tile (344 CSS px) at the 4K render's 2x scale. The six streams are
colored the way their panes show them: disparity in Spectral, alpha by object, the flow
forward, the occlusion mask white on black. Run from backend/:
    uv run python ../.assets/demo/stream_frames.py SEQ_DIR OUT_DIR
"""

import sys
from pathlib import Path

from PIL import Image

from video_bokeh.preview.pack import (
    _flow_frames,
    _occlusion_frames,
    list_stream_frames,
    load_frame,
)

SIZE = 688
STREAMS = ("all_in_focus", "alpha", "disparity", "bokeh", "flow", "occlusion")
seq_dir, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
for stream in STREAMS:
    paths = list_stream_frames(seq_dir, stream)
    if stream == "flow":
        frames = _flow_frames(paths)
    elif stream == "occlusion":
        frames = _occlusion_frames(paths, None)
    else:
        frames = (load_frame(p, stream, "spectral_r") for p in paths)
    (out_dir / stream).mkdir(parents=True, exist_ok=True)
    n = 0
    for n, frame in enumerate(frames, 1):
        image = Image.fromarray(frame).resize((SIZE, SIZE), Image.LANCZOS)
        image.save(out_dir / stream / f"{n:03d}.png", compress_level=1)
    print(stream, n)
