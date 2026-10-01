"""Where the API finds the libraries it serves and the sequences it writes.

Three environment variables, all optional:

``VIDEO_BOKEH_DATA_ROOT``
    The single directory everything generated lives under. Defaults to ``data``,
    which is where it already is when the API runs from ``backend/``. Compose sets
    it to ``/data`` and mounts the real root there.

``CORS_ORIGINS``
    Comma-separated origins allowed to call the API from a browser. Defaults to the dev
    frontend, ``http://localhost:3000``. The page and the API are always on different
    ports, so without this every request from the browser is refused.

``VIDEO_BOKEH_LIBRARY``
    Where the libraries are, when it is not ``$VIDEO_BOKEH_DATA_ROOT/library``. Either one
    library -- ``data/library_dev`` holds ``foregrounds/`` and ``backgrounds/`` directly,
    so naming it outright makes an existing checkout usable without moving anything -- or
    a directory with one library per subdirectory, such as one per depth estimator.

Resolution is lazy, per request, not at import. The container has to be able to start
before the library volume is populated, and ``/health`` must answer either way.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATA_ROOT = "data"
# Both spellings of the dev frontend: a browser treats them as different origins, and
# opening the page by IP otherwise gets every request refused with no explanation.
DEFAULT_CORS_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000")

# A library is a directory holding these two. Both must exist: a library with no
# backgrounds cannot produce a sequence, and finding out at render time gives a 500
# where a named configuration error belongs.
_REQUIRED_SUBDIRS = ("foregrounds", "backgrounds")


class LibraryUnavailableError(RuntimeError):
    """No usable library at the configured path."""


@dataclass(frozen=True)
class Settings:
    data_root: Path
    library: Path
    sequences: Path
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Read the three variables. An empty value counts as unset, because that is what
    ``docker compose`` passes through for a ``.env`` key with nothing after the ``=``.
    """
    env = os.environ if env is None else env
    data_root = Path(env.get("VIDEO_BOKEH_DATA_ROOT") or DEFAULT_DATA_ROOT)
    library = Path(env.get("VIDEO_BOKEH_LIBRARY") or data_root / "library")
    origins = tuple(
        o.strip() for o in env.get("CORS_ORIGINS", "").split(",") if o.strip()
    )
    return Settings(
        data_root=data_root,
        library=library,
        sequences=data_root / "sequences",
        cors_origins=origins or DEFAULT_CORS_ORIGINS,
    )


def _missing_subdirs(path: Path) -> list[str]:
    return [name for name in _REQUIRED_SUBDIRS if not (path / name).is_dir()]


def find_libraries(settings: Settings) -> list[Path]:
    """Every library at the configured path, in name order, or raise naming the path.

    The path is a library when it holds both subdirectories, and a broken one when it
    holds only one of them. Otherwise each immediate subdirectory holding both is a
    library. A name starting with a dot is skipped, because that is how a build still in
    progress is kept out of view until it is renamed into place.
    """
    root = settings.library
    if not root.is_dir():
        raise LibraryUnavailableError(
            f"no library at {root}. Build one with video_bokeh.library.build, "
            f"or point VIDEO_BOKEH_LIBRARY at an existing one.",
        )
    missing = _missing_subdirs(root)
    if not missing:
        return [root]
    if len(missing) < len(_REQUIRED_SUBDIRS):
        raise LibraryUnavailableError(
            f"{root} is not a library: missing {', '.join(missing)}",
        )
    libraries = sorted(
        child
        for child in root.iterdir()
        if child.is_dir()
        and not child.name.startswith(".")
        and not _missing_subdirs(child)
    )
    if not libraries:
        raise LibraryUnavailableError(
            f"no library at {root}: it is neither a library nor a directory of them. "
            f"Build one with video_bokeh.library.build, or point VIDEO_BOKEH_LIBRARY "
            f"at one.",
        )
    return libraries
