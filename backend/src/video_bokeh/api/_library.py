"""What each mounted library is, and the id every sequence hash is keyed on.

Decision 9 of the 2026-09-18 design makes a library immutable and names the reason:
the sequence id is hashed over the parameters *and* the library, so a library that
changes under a fixed name silently invalidates every cached sequence while every hash
still matches. A directory name therefore cannot be the id.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from video_bokeh.core._library import FOREGROUNDS, list_backgrounds, list_foregrounds
from video_bokeh.core._metadata import read_asset_metadata

_ID_CHARS = 12


class DuplicateLibraryError(RuntimeError):
    """Two mounted libraries share an id, so neither can be told from the other."""


@dataclass(frozen=True)
class LibrarySummary:
    id: str
    #: The directory's own name, which is what a person picks a library by.
    name: str
    root: Path
    n_foregrounds: int
    n_backgrounds: int
    depth_estimator: str | None
    asset_size: int | None


def _depth_estimator(library_root: Path, foreground_ids: list[str]) -> str | None:
    """The estimator Stage A ran, read off the first foreground.

    Stage A writes it per asset and there is no library-level manifest, so one asset
    is the only place to read it from. A library built in one run has one estimator.
    """
    if not foreground_ids:
        return None
    meta = read_asset_metadata(library_root / FOREGROUNDS / foreground_ids[0])
    if meta is None:
        return None
    estimator = meta.get("estimator")
    return str(estimator) if estimator is not None else None


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

    The id covers the asset ids, the depth estimator and the asset size. It moves when
    assets are added or removed, when the depth estimator changes and when the library
    is rebuilt at another size, and it does not move when the same library is mounted at
    a different path -- sequences cached against it stay valid.

    **It does not cover pixel content.** The same ids, estimator and size over
    different images produce the same id, wherever the library sits, so a new directory
    name does not help. Hashing a full library's pixels at every startup is not worth it
    for a failure nobody has hit: never rebuild a library in place, which
    ``make libraries`` refuses to do, or clear the cached sequences after one.
    """
    foreground_ids = list_foregrounds(library_root)
    background_ids = list_backgrounds(library_root)
    estimator = _depth_estimator(library_root, foreground_ids)
    asset_size = _asset_size(library_root, foreground_ids)

    digest = hashlib.sha256()
    for asset_id in foreground_ids:
        digest.update(b"fg:")
        digest.update(asset_id.encode())
    for asset_id in background_ids:
        digest.update(b"bg:")
        digest.update(asset_id.encode())
    digest.update(b"model:")
    digest.update((estimator or "").encode())
    digest.update(b"size:")
    digest.update(str(asset_size or "").encode())

    return LibrarySummary(
        id=digest.hexdigest()[:_ID_CHARS],
        # Made absolute, so a library mounted as `.` is not named "". Not resolved: a
        # symlinked library keeps the name it is listed and sorted under.
        name=Path(os.path.abspath(library_root)).name,
        root=library_root,
        n_foregrounds=len(foreground_ids),
        n_backgrounds=len(background_ids),
        depth_estimator=estimator,
        asset_size=asset_size,
    )


def summarize_all(library_roots: list[Path]) -> list[LibrarySummary]:
    """Summarize each library, refusing two that share an id.

    A request names its library by id, and the id is what every cached sequence is
    keyed on, so two libraries with one id would serve each other's sequences. Built
    from the same assets by the same estimator at the same size, they differ only in
    pixel content the id does not cover. That is a deployment mistake, so it is named
    rather than resolved by picking one.
    """
    summaries = [summarize(root) for root in library_roots]
    seen: dict[str, Path] = {}
    for summary in summaries:
        if summary.id in seen:
            raise DuplicateLibraryError(
                f"{seen[summary.id]} and {summary.root} are the same library to the "
                f"API: both have id {summary.id}. Mount one of them.",
            )
        seen[summary.id] = summary.root
    return summaries
