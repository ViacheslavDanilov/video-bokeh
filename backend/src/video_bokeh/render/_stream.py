"""Writing a sequence's bokeh stream, whole or not at all, for any renderer."""

from __future__ import annotations

import json
import shutil
import stat
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from PIL import Image


def write_bokeh(
    seq: Path,
    frames: Iterable[tuple[str, Image.Image]],
    record: dict[str, Any],
) -> None:
    """Write ``seq/bokeh/``: each named frame as a PNG, and ``record`` as focus.json.

    The frames go to a hidden folder beside it, named per run so two runs over one data
    root cannot delete each other's, which is renamed to ``bokeh/`` only when every frame
    is in place. Anything that fails on the way leaves the old ``bokeh/`` untouched.
    """
    staging = Path(tempfile.mkdtemp(prefix=".bokeh-", dir=seq))
    # mkdtemp makes it private (0700); the stream gets the access its siblings have.
    staging.chmod(stat.S_IMODE((seq / "all_in_focus").stat().st_mode))
    try:
        for name, image in frames:
            image.save(staging / name, compress_level=6)
        (staging / "focus.json").write_text(json.dumps(record) + "\n", encoding="utf-8")
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    shutil.rmtree(seq / "bokeh", ignore_errors=True)
    staging.rename(seq / "bokeh")
