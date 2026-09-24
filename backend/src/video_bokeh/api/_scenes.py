"""Generate a scene, or recognise that it already exists.

Decision 7: the scene id is a hash of the request parameters together with the id of
the mounted library. Stage B is deterministic, so the same request always produces the
same scene, the cache is the directory ``scenes/<id>/``, and there is no database.

A scene is one sequence, not a dataset, so the three streams sit directly under
``scenes/<id>/`` rather than under ``sequences/0001/``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from video_bokeh.scenes._compositor import (
    CollisionRetriesExhausted,
    RenderedFrame,
    Scene,
    render_scene,
    sample_scene,
)
from video_bokeh.scenes.generate import sample_n_objects, write_sequence

_ID_CHARS = 16
_META = "scene.json"

#: Streams a scene writes.
STREAMS = ("all_in_focus", "alpha", "disparity")

#: Servable as video, in the order a person reads them: the frame, who is in it, and
#: how far away they are. `alpha` is multi-page TIFF with one page per object, which
#: `preview` renders by colouring each object rather than flattening them into one
#: silhouette.
VIDEO_STREAMS = ("all_in_focus", "alpha", "disparity")


class SceneUnsatisfiableError(RuntimeError):
    """The request is valid but no collision-free scene could be sampled for it."""


@dataclass(frozen=True)
class SceneRequest:
    seed: int
    frames: int
    size: int
    n_objects_min: int
    n_objects_max: int


@dataclass(frozen=True)
class SceneResult:
    id: str
    path: Path
    cached: bool
    n_objects: int


def scene_id(library_id: str, request: SceneRequest) -> str:
    """A scene is fully determined by the library and these five numbers."""
    parts = (
        library_id,
        request.seed,
        request.frames,
        request.size,
        request.n_objects_min,
        request.n_objects_max,
    )
    payload = "|".join(str(part) for part in parts).encode()
    return hashlib.sha256(payload).hexdigest()[:_ID_CHARS]


def _read_cached(dest: Path, sid: str) -> SceneResult | None:
    """A scene counts as present only once its metadata is there.

    The directory appears atomically, so this is belt and braces rather than the
    mechanism -- but it also means a directory left behind by an older, interrupted
    layout is not mistaken for a finished scene.
    """
    meta_path = dest / _META
    if not meta_path.is_file():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return SceneResult(id=sid, path=dest, cached=True, n_objects=int(meta["n_objects"]))


def _generate_into(
    work_dir: Path,
    library_root: Path,
    library_id: str,
    request: SceneRequest,
    render: Callable[[Scene], list[RenderedFrame]],
) -> int:
    n_objects = sample_n_objects(
        request.seed,
        request.n_objects_min,
        request.n_objects_max,
    )
    try:
        scene = sample_scene(
            library_root,
            seed=request.seed,
            n_frames=request.frames,
            size=request.size,
            n_objects=n_objects,
        )
    except CollisionRetriesExhausted as exc:
        raise SceneUnsatisfiableError(str(exc)) from exc

    write_sequence(work_dir, render(scene))
    placed = len(scene.objects)
    (work_dir / _META).write_text(
        json.dumps(
            {
                "library_id": library_id,
                "n_objects": placed,
                "streams": list(STREAMS),
                "created": datetime.now(UTC).isoformat(),
                **asdict(request),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return placed


def ensure_scene(
    library_root: Path,
    library_id: str,
    scenes_root: Path,
    request: SceneRequest,
    *,
    _render: Callable[[Scene], list[RenderedFrame]] | None = None,
) -> SceneResult:
    """Return the scene for this request, generating it if it is not on disk yet.

    Generation writes to a temporary directory beside the destination and renames it
    into place, so a scene is either absent or complete. That is what makes a crashed
    or concurrent generation harmless: there is no window in which a half-written
    directory looks like a cache hit.
    """
    sid = scene_id(library_id, request)
    dest = scenes_root / sid
    cached = _read_cached(dest, sid)
    if cached is not None:
        return cached

    scenes_root.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix=".tmp-", dir=scenes_root))
    try:
        n_objects = _generate_into(
            work_dir,
            library_root,
            library_id,
            request,
            _render or render_scene,
        )
        try:
            os.replace(work_dir, dest)
        except OSError:
            # Another request finished the same id while this one worked. Its output
            # is equivalent -- the id is a hash of everything that determines the
            # scene -- so discard ours rather than overwrite a directory someone may
            # be reading.
            winner = _read_cached(dest, sid)
            if winner is None:
                raise
            return winner
        return SceneResult(id=sid, path=dest, cached=False, n_objects=n_objects)
    finally:
        # A no-op after a successful rename, since the directory has moved.
        shutil.rmtree(work_dir, ignore_errors=True)
