"""Where the API finds the library it serves and the scenes it writes.

Two environment variables, both optional:

``VIDEO_BOKEH_DATA_ROOT``
    The single directory everything generated lives under. Defaults to ``data``,
    which is where it already is when the API runs from ``backend/``. Compose sets
    it to ``/data`` and mounts the real root there.

``CORS_ORIGINS``
    Comma-separated origins allowed to call the API from a browser. Defaults to the dev
    frontend, ``http://localhost:3000``. The page and the API are always on different
    ports, so without this every request from the browser is refused.

``VIDEO_BOKEH_LIBRARY``
    The library directory itself, when it is not ``$VIDEO_BOKEH_DATA_ROOT/library``.
    Every library on disk today is flat -- ``data/library_dev`` holds ``foregrounds/``
    and ``backgrounds/`` directly -- so naming it outright is what makes an existing
    checkout usable without moving anything.

Resolution is lazy, per request, not at import. The container has to be able to start
before the library volume is populated, and ``/health`` must answer either way.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATA_ROOT = "data"
DEFAULT_CORS_ORIGINS = ("http://localhost:3000",)

# A library is a directory holding these two. Both must exist: a library with no
# backgrounds cannot produce a scene, and finding out at render time gives a 500
# where a named configuration error belongs.
_REQUIRED_SUBDIRS = ("foregrounds", "backgrounds")


class LibraryUnavailableError(RuntimeError):
    """No usable library at the configured path."""


@dataclass(frozen=True)
class Settings:
    data_root: Path
    library: Path
    scenes: Path
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Read the two variables. An empty value counts as unset, because that is what
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
        scenes=data_root / "scenes",
        cors_origins=origins or DEFAULT_CORS_ORIGINS,
    )


def require_library(settings: Settings) -> Path:
    """Return the library path, or raise with the path and the reason in the message."""
    library = settings.library
    if not library.is_dir():
        raise LibraryUnavailableError(
            f"no library at {library}. Build one with video_bokeh.library.build, "
            f"or point VIDEO_BOKEH_LIBRARY at an existing one.",
        )
    missing = [name for name in _REQUIRED_SUBDIRS if not (library / name).is_dir()]
    if missing:
        raise LibraryUnavailableError(
            f"{library} is not a library: missing {', '.join(missing)}",
        )
    return library
