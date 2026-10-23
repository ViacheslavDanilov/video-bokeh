"""A renderer's output without a GPU: a sequence's frames copied into its ``bokeh/``.

Rendering it takes torch, which the API's own install leaves out, so the API tests and the
browser smoke test write the stream the way a renderer lands it, one RGB PNG per frame, and
check it is served.

Run as a script on a sequence directory:

    uv run python tests/api/fake_bokeh.py <sequence-dir>
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def render_fake_bokeh(sequence_dir: Path) -> None:
    bokeh = sequence_dir / "bokeh"
    bokeh.mkdir()
    for frame in sorted((sequence_dir / "all_in_focus").glob("*.png")):
        shutil.copy(frame, bokeh / frame.name)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: fake_bokeh.py <sequence-dir>")
    render_fake_bokeh(Path(sys.argv[1]))
