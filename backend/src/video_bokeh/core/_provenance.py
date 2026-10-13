"""Provenance of the checkout running a dataset or throughput measurement."""

import subprocess
from pathlib import Path


def _git_commit() -> str | None:
    """The video-bokeh commit, or None for an installed copy or unavailable git.

    An installed copy can sit in another project's tree, whose commit says
    nothing about this code.
    """
    root = Path(__file__).resolve().parents[4]
    if not (root / "backend/src/video_bokeh/core/_provenance.py").is_file():
        return None
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
