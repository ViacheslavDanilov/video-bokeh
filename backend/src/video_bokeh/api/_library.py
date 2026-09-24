"""What the mounted library is, and the id every scene hash is keyed on.

Decision 9 of the 2026-09-18 design makes a library immutable and names the reason:
the scene id is hashed over the parameters *and* the library, so a library that
changes under a fixed name silently invalidates every cached scene while every hash
still matches. A directory name therefore cannot be the id.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from video_bokeh.core._library import FOREGROUNDS, list_backgrounds, list_foregrounds
from video_bokeh.core._metadata import read_asset_metadata

_ID_CHARS = 12


@dataclass(frozen=True)
class LibrarySummary:
    id: str
    n_foregrounds: int
    n_backgrounds: int
    depth_model: str | None
    asset_size: int | None


def _depth_model(library_root: Path, foreground_ids: list[str]) -> str | None:
    """The estimator Stage A ran, read off the first foreground.

    Stage A writes it per asset and there is no library-level manifest, so one asset
    is the only place to read it from. A library built in one run has one estimator.
    """
    if not foreground_ids:
        return None
    meta = read_asset_metadata(library_root / FOREGROUNDS / foreground_ids[0])
    if meta is None:
        return None
    model = meta.get("estimator")
    return str(model) if model is not None else None


def _asset_size(library_root: Path, foreground_ids: list[str]) -> int | None:
    """The side Stage A stored foregrounds at. Backgrounds are deliberately larger --
    Stage A oversizes them by a margin so Stage B's warp never samples past the edge.
    """
    if not foreground_ids:
        return None
    rgb = library_root / FOREGROUNDS / foreground_ids[0] / "rgb.png"
    if not rgb.exists():
        return None
    with Image.open(rgb) as img:
        return int(img.size[0])


def summarize(library_root: Path) -> LibrarySummary:
    """Read the library's shape and derive its id.

    The id covers the asset ids and the estimator. It moves when assets are added or
    removed and when the depth model changes, and it does not move when the same
    library is mounted at a different path -- scenes cached against it stay valid.

    **It does not cover pixel content.** The same ids and the same estimator over
    different images produce the same id. Hashing a full library's pixels at every
    startup is not worth it for a failure nobody has hit; rebuild under a new
    directory name, as decision 9 requires, and the question does not arise.
    """
    foreground_ids = list_foregrounds(library_root)
    background_ids = list_backgrounds(library_root)
    model = _depth_model(library_root, foreground_ids)

    digest = hashlib.sha256()
    for asset_id in foreground_ids:
        digest.update(b"fg:")
        digest.update(asset_id.encode())
    for asset_id in background_ids:
        digest.update(b"bg:")
        digest.update(asset_id.encode())
    digest.update(b"model:")
    digest.update((model or "").encode())

    return LibrarySummary(
        id=digest.hexdigest()[:_ID_CHARS],
        n_foregrounds=len(foreground_ids),
        n_backgrounds=len(background_ids),
        depth_model=model,
        asset_size=_asset_size(library_root, foreground_ids),
    )
