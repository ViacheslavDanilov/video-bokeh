"""The HTTP surface: which libraries are mounted, and sequences generated on demand.

Decision 7 of the 2026-09-18 design. Generation is synchronous because Stage B is
CPU work measured in seconds, and the sequence id is a hash of the request and the
library, so the cache is the directory on disk and there is no database.

Rendering bokeh is not here. That is minutes of GPU work in its own container, so it
gets a job id and polling when `render` exists.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Annotated, Self

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi import Path as PathParam
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator

from video_bokeh.api._library import (
    DuplicateLibraryError,
    LibrarySummary,
    summarize_all,
)
from video_bokeh.api._sequences import (
    VIDEO_STREAMS,
    SequenceRequest,
    SequenceUnsatisfiableError,
    ensure_sequence,
)
from video_bokeh.api._settings import (
    LibraryUnavailableError,
    Settings,
    find_libraries,
    load_settings,
)
from video_bokeh.preview._colormap import COLORMAPS
from video_bokeh.preview._masks import object_color_hex
from video_bokeh.preview.pack import encode_stream, list_stream_frames

#: Matches the defaults of `video_bokeh.preview.pack`, so a stream looks the same
#: whether it was packed on the command line or served from here.
_FPS = 24
_QUALITY = 10
DEFAULT_COLORMAP = "spectral_r"

#: The endpoint blocks while it generates, so the request has to be bounded. 240
#: frames is three times the 80 every measurement so far has used.
_MAX_FRAMES = 240

#: Total pixels a single request may ask for, frames times area.
#:
#: Each limit alone is harmless and the product is not: `render_scene` holds every
#: frame of the sequence in memory at once, so cost grows with the area and with the
#: count together. Measured on an Apple M3 Pro against `data/library_dev`:
#:
#:     80 frames at 512   =  21.0 Mpx    2.6 to 3.3 s     modest
#:     80 frames at 1024  =  83.9 Mpx   11.2 s            2.9 GB peak
#:    240 frames at 1024  = 251.7 Mpx   97 s              9.7 GB peak, machine swaps
#:
#: The last one takes the whole machine down with it, which a synchronous endpoint
#: must not let a caller do. The cap admits the second and refuses the third. Lifting
#: it means making generation stream to disk instead of accumulating frames, which is
#: a change to Stage B rather than to the API.
_MAX_PIXELS = 96_000_000

router = APIRouter()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the application.

    CORS is the one setting read here rather than per request, because middleware is
    installed when the app object is built. Taking `settings` as an argument is what
    makes that testable: patching `load_settings` after import cannot reach middleware
    that was already installed, so a test that tried would pass or fail on whatever
    happened to be in the environment at import time.
    """
    settings = settings or load_settings()
    application = FastAPI(
        title="Video Bokeh",
        description=(
            "Depth-aware synthetic bokeh pipeline for video, with a FastAPI backend "
            "and Next.js frontend."
        ),
        version="0.1.0",
    )
    # The page always runs on a different port from the API, so without a matching
    # origin here the browser refuses every request before it reaches a route.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["content-type"],
    )
    application.include_router(router)
    return application


class SequenceParams(BaseModel):
    #: The id of the library to generate from. Optional while only one is mounted.
    library: str | None = None
    seed: int = 0
    frames: int = Field(default=80, ge=1, le=_MAX_FRAMES)
    size: int = Field(default=512, ge=64, le=2048)
    n_objects_min: int = Field(default=1, ge=1, le=16)
    n_objects_max: int = Field(default=5, ge=1, le=16)

    @model_validator(mode="after")
    def _range_is_ordered(self) -> Self:
        if self.n_objects_min > self.n_objects_max:
            raise ValueError("n_objects_min must not exceed n_objects_max")
        return self

    @model_validator(mode="after")
    def _fits_in_memory(self) -> Self:
        pixels = self.frames * self.size * self.size
        if pixels > _MAX_PIXELS:
            affordable = _MAX_PIXELS // (self.size * self.size)
            raise ValueError(
                f"{self.frames} frames at {self.size} px is "
                f"{pixels / 1e6:.0f} megapixels, over the {_MAX_PIXELS / 1e6:.0f} "
                f"a single request may hold in memory. At {self.size} px, ask for "
                f"{affordable} frames or fewer, or drop the size.",
            )
        return self


class LibraryResponse(BaseModel):
    id: str
    name: str
    n_foregrounds: int
    n_backgrounds: int
    depth_estimator: str | None
    asset_size: int | None


class StreamInfo(BaseModel):
    """How one stream of a sequence can be displayed.

    The client renders whatever this manifest reports rather than knowing the stream
    names itself, so a stream added later -- `bokeh`, once the render container
    exists -- shows up in the interface without a frontend change.
    """

    url: str
    #: Colormaps this stream accepts, empty when it is already RGB and the parameter
    #: would do nothing.
    colormaps: list[str]
    #: Which of them the url above already renders. Named rather than left to the
    #: order of `colormaps`, so adding one whose name sorts last cannot silently
    #: change what a client shows.
    default: str | None


class SequenceResponse(BaseModel):
    id: str
    #: The library it was generated from, so a client can label what is on screen
    #: after the person has picked another one.
    library: str
    cached: bool
    seed: int
    frames: int
    size: int
    n_objects: int
    #: One hex colour per object, in the order the alpha pages carry them, so a legend
    #: cannot drift from what the alpha video actually paints.
    object_colors: list[str]
    streams: dict[str, StreamInfo]


def _mounted_libraries(settings: Settings) -> list[LibrarySummary]:
    """The libraries, or a 503 naming the path. Unavailable is a deployment state, not
    a bad request: the volume may simply not be populated yet, or two libraries that
    cannot be told apart were mounted together.
    """
    try:
        return summarize_all(find_libraries(settings))
    except (LibraryUnavailableError, DuplicateLibraryError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _pick_library(
    libraries: list[LibrarySummary],
    wanted: str | None,
) -> LibrarySummary:
    """The library a request names, or the only one when it names none."""
    if wanted is None and len(libraries) == 1:
        return libraries[0]
    for library in libraries:
        if library.id == wanted:
            return library
    known = ", ".join(f"{lib.id} ({lib.name})" for lib in libraries)
    reason = (
        f"no library {wanted!r}"
        if wanted is not None
        else f"{len(libraries)} libraries are mounted, so name one"
    )
    raise HTTPException(status_code=422, detail=f"{reason}. Mounted: {known}")


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


@router.get("/libraries")
def read_libraries() -> list[LibraryResponse]:
    return [
        LibraryResponse.model_validate(lib, from_attributes=True)
        for lib in _mounted_libraries(load_settings())
    ]


@router.post("/sequences")
def create_sequence(params: SequenceParams) -> SequenceResponse:
    """Generate a sequence, or hand back the one this request already produced.

    Plain `def`, not `async def`: generation is seconds of CPU work, and FastAPI runs
    a sync endpoint in a threadpool instead of blocking the event loop with it.
    """
    settings = load_settings()
    library = _pick_library(_mounted_libraries(settings), params.library)

    try:
        result = ensure_sequence(
            library.root,
            library.id,
            settings.sequences,
            SequenceRequest(
                seed=params.seed,
                frames=params.frames,
                size=params.size,
                n_objects_min=params.n_objects_min,
                n_objects_max=params.n_objects_max,
            ),
        )
    except SequenceUnsatisfiableError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return SequenceResponse(
        id=result.id,
        library=library.id,
        cached=result.cached,
        seed=params.seed,
        frames=params.frames,
        size=params.size,
        n_objects=result.n_objects,
        object_colors=[object_color_hex(i) for i in range(result.n_objects)],
        streams={
            stream: StreamInfo(
                url=f"/sequences/{result.id}/{stream}.mp4",
                colormaps=sorted(COLORMAPS) if stream == "disparity" else [],
                default=DEFAULT_COLORMAP if stream == "disparity" else None,
            )
            for stream in VIDEO_STREAMS
        },
    )


@router.get("/sequences/{sequence_id}/{stream}.mp4")
def read_sequence_video(
    sequence_id: Annotated[str, PathParam(pattern=r"^[0-9a-f]{16}$")],
    stream: str,
    colormap: Annotated[str, Query(pattern=r"^[a-z_]+$")] = DEFAULT_COLORMAP,
) -> FileResponse:
    """Serve one stream as H.264.

    Encoded on the first request and kept next to the frames, so the second request
    is a file read. `sequence_id` is constrained to the hash alphabet in the route
    itself, which is also what keeps it from naming a path outside `sequences/`.

    `colormap` applies to `disparity` only -- it is 16-bit grey on disk and gets its
    colour here. Every other stream is already RGB, so the parameter is dropped
    rather than forking that stream's cache into identical copies.
    """
    if stream not in VIDEO_STREAMS:
        raise HTTPException(status_code=404, detail=f"no video for stream {stream!r}")
    if colormap not in COLORMAPS:
        raise HTTPException(
            status_code=422,
            detail=f"unknown colormap {colormap!r}. Known: {', '.join(sorted(COLORMAPS))}",
        )
    if stream != "disparity":
        colormap = DEFAULT_COLORMAP

    settings = load_settings()
    sequence_dir = settings.sequences / sequence_id
    if not (sequence_dir / "sequence.json").is_file():
        raise HTTPException(status_code=404, detail=f"no sequence {sequence_id}")

    suffix = "" if colormap == DEFAULT_COLORMAP else f".{colormap}"
    video = sequence_dir / f"{stream}{suffix}.mp4"
    if not video.is_file():
        frames = list_stream_frames(sequence_dir, stream)
        if not frames:
            raise HTTPException(
                status_code=404,
                detail=f"sequence {sequence_id} has no {stream}",
            )
        # Encode beside the destination and rename, so a second request arriving
        # mid-encode either waits for nothing or serves a complete file. Writing
        # straight to `video` leaves a path that exists but is half-written, and
        # `is_file()` cannot tell the difference. Two panes showing one stream, or a
        # reload during the first encode, both reach this.
        with tempfile.NamedTemporaryFile(
            dir=sequence_dir,
            prefix=f".{stream}-",
            suffix=".mp4",
            delete=False,
        ) as handle:
            partial = Path(handle.name)
        try:
            encode_stream(frames, partial, _FPS, _QUALITY, stream, colormap)
            os.replace(partial, video)
        finally:
            partial.unlink(missing_ok=True)

    return FileResponse(video, media_type="video/mp4")


app = create_app()
