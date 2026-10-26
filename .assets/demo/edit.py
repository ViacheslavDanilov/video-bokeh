"""Turns record.cjs's screencast frames into project/assets/ui-edit.mp4.

Setup plays at 1x and the generation wait is sped up to last GEN_EDIT seconds (about 4x),
whatever the generation took. The rest plays at 1x. Usage:
    python3 edit.py FRAMES_DIR   # then, from this folder, the ffmpeg command it prints
"""

import json
import sys
from pathlib import Path

GEN_EDIT = 4.2  # seconds the generation wait takes in the edit

frames_dir = Path(sys.argv[1])
d = json.loads((frames_dir / "frames.json").read_text())
frames, marks = d["frames"], d["marks"]
t0 = marks["start"]
a_end = marks["generate"] - t0 + 0.42  # just after the click
b_end = marks["panes"] - t0  # every pane decoded
speed = (b_end - a_end) / GEN_EDIT


def edit_time(t: float) -> float:
    if t < a_end:
        return t
    if t < b_end:
        return a_end + (t - a_end) / speed
    return a_end + GEN_EDIT + (t - b_end)


ts = [f["t"] - t0 for f in frames]
total = edit_time(marks["end"] - t0)
edit_frames = int(total * 30)
lines = ["ffconcat version 1.0"]
for i, f in enumerate(frames):
    start = 0 if i == 0 else edit_time(ts[i])
    nxt = edit_time(ts[i + 1]) if i + 1 < len(frames) else total
    lines += [f"file '{f['name']}'", f"duration {nxt - start:.6f}"]
lines.append(f"file '{frames[-1]['name']}'")
(frames_dir / "list.ffconcat").write_text("\n".join(lines) + "\n")
print(f"generation wait at {speed:.2f}x")
for name in marks:
    print(f"{name:9} {edit_time(marks[name] - t0):6.2f} s in the edit")
print(
    f"ffmpeg -f concat -safe 0 -i {frames_dir / 'list.ffconcat'}"
    f" -vf 'fps=30,crop=3600:1672:0:0,format=yuv420p' -frames:v {edit_frames}"
    " -c:v libx264 -preset slow -crf 12 -movflags +faststart project/assets/ui-edit.mp4"
)
