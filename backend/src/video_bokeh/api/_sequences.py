"""Generate a sequence, or recognize that it already exists.

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
from functools import partial
from pathlib import Path

from video_bokeh.core._focus import frame_focus
from video_bokeh.core._streams import BOKEH_STRENGTH
from video_bokeh.scenes._compositor import (
    CollisionRetriesExhausted,
    Scene,
    iter_frames,
)
from video_bokeh.scenes.generate import (
    MOTION_STREAMS,
    counted,
    motion_steps,
    sample_sequence,
    write_bokeh_stream,
    write_motion_streams,
    write_sequence,
)

_ID_CHARS = 16
_META = "sequence.json"

#: Servable as video, in the order a person reads them: the frame, who is in it, and
#: how far away they are. `alpha` is multi-page TIFF with one page per object, which
#: `preview` renders by coloring each object rather than flattening them into one
#: silhouette.
VIDEO_STREAMS = ("all_in_focus", "alpha", "disparity")

#: The bokeh stream. Generation renders it with the sequence when asked, with the layered
#: renderer; Stage C can also write it into a sequence this API generated, whole or not at
#: all. It is served once it is there.
BOKEH = "bokeh"

#: The motion streams: the optical flow, the backward flow and the occlusion mask, written
#: with every sequence, and added to one generated before they came with it. Each is listed
#: once it is there, as bokeh is.
FLOW, FLOW_BACK, OCCLUSION = MOTION_STREAMS

#: Served once a sequence has them, after `VIDEO_STREAMS`, in this order.
OPTIONAL_STREAMS = (BOKEH, FLOW, FLOW_BACK, OCCLUSION)


def video_streams(sequence_dir: Path) -> list[str]:
    """The streams of this sequence that can be served, the optional ones among them once
    they are written.
    """
    streams = list(VIDEO_STREAMS)
    for optional in OPTIONAL_STREAMS:
        if (sequence_dir / optional).is_dir():
            streams.append(optional)
    return streams


def rendered_strength(sequence_dir: Path) -> float | None:
    """The strength the sequence's bokeh record names, or None when it has none.

    The record is written with the frames, so it stays true when a renderer other than
    this API's renders the stream again at another strength.
    """
    record = sequence_dir / BOKEH / "focus.json"
    if not record.is_file():
        return None
    strength = json.loads(record.read_text(encoding="utf-8")).get("strength")
    return None if strength is None else float(strength)


class SequenceUnsatisfiableError(RuntimeError):
    """The request is valid but no collision-free scene could be sampled for it."""


@dataclass(frozen=True)
class SequenceRequest:
    seed: int
    frames: int
    size: int
    n_objects_min: int
    n_objects_max: int
    #: The bokeh's strength: the blur radius in pixels, at a 1024-pixel width, one unit of
    #: disparity from the focus.
    bokeh_strength: float = BOKEH_STRENGTH


@dataclass(frozen=True)
class SequenceResult:
    id: str
    path: Path
    cached: bool
    n_objects: int


def sequence_id(library_id: str, request: SequenceRequest) -> str:
    """A sequence is fully determined by the library, five numbers and its bokeh's strength.

    The strength is hashed only when it is not the default. Every sequence cached before a
    request could name it was rendered at the default, so each keeps the id it had.
    """
    parts: list[object] = [
        library_id,
        request.seed,
        request.frames,
        request.size,
        request.n_objects_min,
        request.n_objects_max,
    ]
    if request.bokeh_strength != BOKEH_STRENGTH:
        # As a float, so 24 and 24.0 name one sequence.
        parts.append(float(request.bokeh_strength))
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


#: Told how a generation is going: the step, how much of it is done, and out of how much.
#: The steps are ``sampling``, ``frames``, ``writing``, ``flow`` and ``bokeh``; "step"
#: rather than "stage", which names the pipeline's Stages A, B and C.
Progress = Callable[[str, int, int], None]
#: Told, before the first step, every step the generation will take, in order, each with
#: the total it will count to: what lets a client draw one bar for the whole of it.
Plan = Callable[[list[tuple[str, int]]], None]


def _generate_into(
    work_dir: Path,
    library_root: Path,
    library_id: str,
    request: SequenceRequest,
    bokeh: bool,
    progress: Progress,
    plan: Plan,
) -> int:
    n = request.frames
    plan(
        [("sampling", 1), ("frames", n), ("writing", n)]
        + ([("bokeh", n)] if bokeh else []),
    )
    scene = _scene(library_root, request, progress)
    rendered = iter_frames(scene, flow=True, flow_back=True, occlusion=True)
    frames = list(counted(rendered, n, partial(progress, "frames")))
    focus = [frame_focus(f.object_alphas, f.disparity) for f in frames] if bokeh else []
    write_sequence(work_dir, counted(frames, n, partial(progress, "writing")), n)
    # The bokeh pass renders the frames again with their layers, a few at a time; holding
    # these as well would add the whole clip to its peak.
    del frames
    placed = len(scene.objects)
    (work_dir / _META).write_text(
        json.dumps(
            {
                "library_id": library_id,
                "n_objects": placed,
                "streams": list(VIDEO_STREAMS),
                "created": datetime.now(UTC).isoformat(),
                **asdict(request),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if bokeh:
        write_bokeh_stream(
            work_dir,
            scene,
            request.seed,
            focus,
            request.bokeh_strength,
            report=partial(progress, "bokeh"),
        )
    return placed


def _scene(library_root: Path, request: SequenceRequest, progress: Progress) -> Scene:
    """The request's scene. Sampling it is one step, which retries make take a while."""
    progress("sampling", 0, 1)
    try:
        scene = sample_sequence(
            library_root,
            seed=request.seed,
            n_frames=request.frames,
            size=request.size,
            n_objects_min=request.n_objects_min,
            n_objects_max=request.n_objects_max,
        )
    except CollisionRetriesExhausted as exc:
        raise SequenceUnsatisfiableError(str(exc)) from exc
    progress("sampling", 1, 1)
    return scene


def _complete(
    dest: Path,
    library_root: Path,
    request: SequenceRequest,
    progress: Progress,
    plan: Plan,
    *,
    motion: list[str],
    bokeh: bool,
) -> None:
    """Add the motion streams named in ``motion``, the bokeh or both to a sequence already
    on disk, from its scene.

    For a sequence generated before they came with it. Each stream appears whole or not
    at all, so whoever is reading the others meanwhile is not disturbed. The scene is
    sampled once for all of them, and the motion streams are one step, ``flow``, written in
    one pass. The bokeh renders the frames twice, once for the focus and once for itself.
    """
    n = request.frames
    plan(
        [("sampling", 1)]
        + ([("flow", motion_steps(motion, n))] if motion else [])
        + ([("frames", n), ("bokeh", n)] if bokeh else []),
    )
    scene = _scene(library_root, request, progress)
    if motion:
        write_motion_streams(dest, scene, motion, report=partial(progress, "flow"))
    if bokeh:
        frames = iter_frames(scene)
        measured = counted(frames, scene.n_frames, partial(progress, "frames"))
        focus = [frame_focus(f.object_alphas, f.disparity) for f in measured]
        write_bokeh_stream(
            dest,
            scene,
            request.seed,
            focus,
            request.bokeh_strength,
            replace=False,
            report=partial(progress, "bokeh"),
        )


def ensure_sequence(
    library_root: Path,
    library_id: str,
    sequences_root: Path,
    request: SequenceRequest,
    *,
    bokeh: bool = False,
    progress: Progress = lambda step, done, total: None,
    plan: Plan = lambda steps: None,
) -> SequenceResult:
    """Return the sequence for this request, generating it if it is not on disk yet.

    The sequence comes with its motion streams, the optical flow, the backward flow and
    the occlusion mask, written with it, or added to a cached one that lacks any. With
    ``bokeh``, which needs torch, it comes with its bokeh stream the same way.
    ``progress`` hears of each step as it goes, frame by frame, and ``plan`` of them all
    before the first; a cached sequence that lacks nothing reports none.

    Generation writes to a temporary directory beside the destination and renames it
    into place, so a sequence is either absent or complete. That is what makes a crashed
    or concurrent generation harmless: there is no window in which a half-written
    directory looks like a cache hit.
    """
    sid = sequence_id(library_id, request)
    dest = sequences_root / sid
    cached = _read_cached(dest, sid)
    if cached is not None:
        # A single frame has no motion, so it is never missing any.
        missing_motion = [
            stream
            for stream in MOTION_STREAMS
            if request.frames > 1 and not (dest / stream).is_dir()
        ]
        missing_bokeh = bokeh and not (dest / BOKEH).is_dir()
        if missing_motion or missing_bokeh:
            _complete(
                dest,
                library_root,
                request,
                progress,
                plan,
                motion=missing_motion,
                bokeh=missing_bokeh,
            )
        return cached

    sequences_root.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix=".tmp-", dir=sequences_root))
    try:
        n_objects = _generate_into(
            work_dir,
            library_root,
            library_id,
            request,
            bokeh,
            progress,
            plan,
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
