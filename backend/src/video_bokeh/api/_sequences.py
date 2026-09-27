"""Generate a sequence, or recognise that it already exists.

Decision 7: the sequence id is a hash of the request parameters together with the id of
the mounted library. Stage B is deterministic, so the same request always produces the
same sequence, the cache is the directory ``sequences/<id>/``, and there is no database.

The API serves one sequence at a time, not a dataset, so the three streams sit directly
under ``sequences/<id>/`` rather than under a dataset's ``sequences/0001/``.
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
_META = "sequence.json"

#: Streams a sequence writes.
STREAMS = ("all_in_focus", "alpha", "disparity")

#: Servable as video, in the order a person reads them: the frame, who is in it, and
#: how far away they are. `alpha` is multi-page TIFF with one page per object, which
#: `preview` renders by colouring each object rather than flattening them into one
#: silhouette.
VIDEO_STREAMS = ("all_in_focus", "alpha", "disparity")


class SequenceUnsatisfiableError(RuntimeError):
    """The request is valid but no collision-free scene could be sampled for it."""


@dataclass(frozen=True)
class SequenceRequest:
    seed: int
    frames: int
    size: int
    n_objects_min: int
    n_objects_max: int


@dataclass(frozen=True)
class SequenceResult:
    id: str
    path: Path
    cached: bool
    n_objects: int


def sequence_id(library_id: str, request: SequenceRequest) -> str:
    """A sequence is fully determined by the library and these five numbers."""
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


def _read_cached(dest: Path, sid: str) -> SequenceResult | None:
    """A sequence counts as present only once its metadata is there.

    The directory appears atomically, so this is belt and braces rather than the
    mechanism -- but it also means a directory left behind by an older, interrupted
    layout is not mistaken for a finished sequence.
    """
    meta_path = dest / _META
    if not meta_path.is_file():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    return SequenceResult(
        id=sid,
        path=dest,
        cached=True,
        n_objects=int(meta["n_objects"]),
    )


def _generate_into(
    work_dir: Path,
    library_root: Path,
    library_id: str,
    request: SequenceRequest,
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
        raise SequenceUnsatisfiableError(str(exc)) from exc

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


def ensure_sequence(
    library_root: Path,
    library_id: str,
    sequences_root: Path,
    request: SequenceRequest,
    *,
    _render: Callable[[Scene], list[RenderedFrame]] | None = None,
) -> SequenceResult:
    """Return the sequence for this request, generating it if it is not on disk yet.

    Generation writes to a temporary directory beside the destination and renames it
    into place, so a sequence is either absent or complete. That is what makes a crashed
    or concurrent generation harmless: there is no window in which a half-written
    directory looks like a cache hit.
    """
    sid = sequence_id(library_id, request)
    dest = sequences_root / sid
    cached = _read_cached(dest, sid)
    if cached is not None:
        return cached

    sequences_root.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix=".tmp-", dir=sequences_root))
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
            # sequence -- so discard ours rather than overwrite a directory someone may
            # be reading.
            winner = _read_cached(dest, sid)
            if winner is None:
                raise
            return winner
        return SequenceResult(id=sid, path=dest, cached=False, n_objects=n_objects)
    finally:
        # A no-op after a successful rename, since the directory has moved.
        shutil.rmtree(work_dir, ignore_errors=True)
