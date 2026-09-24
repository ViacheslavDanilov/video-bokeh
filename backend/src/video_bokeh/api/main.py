"""The HTTP surface: what library is mounted, and scenes generated on demand.

Decision 7 of the 2026-09-18 design. Generation is synchronous because Stage B is
CPU work measured in seconds, and the scene id is a hash of the request and the
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

from video_bokeh.api._library import summarize
from video_bokeh.api._scenes import (
    VIDEO_STREAMS,
    SceneRequest,
    SceneUnsatisfiableError,
    ensure_scene,
)
from video_bokeh.api._settings import (
    LibraryUnavailableError,
    Settings,
    load_settings,
    require_library,
)
from video_bokeh.preview._colormap import COLORMAPS
from video_bokeh.preview.pack import encode_stream, list_stream_frames

#: Matches the defaults of `video_bokeh.preview.pack`, so a stream looks the same
#: whether it was packed on the command line or served from here.
_FPS = 24
_QUALITY = 10
DEFAULT_COLORMAP = "spectral_r"

#: The endpoint blocks while it generates, so the request has to be bounded. 240
#: frames is three times the 80 every measurement so far has used.
_MAX_FRAMES = 240

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


class SceneParams(BaseModel):
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


class LibraryResponse(BaseModel):
    id: str
    n_foregrounds: int
    n_backgrounds: int
    depth_model: str | None
    asset_size: int | None


class StreamInfo(BaseModel):
    """How one stream of a scene can be displayed.

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


class SceneResponse(BaseModel):
    id: str
    cached: bool
    seed: int
    frames: int
    size: int
    n_objects: int
    streams: dict[str, StreamInfo]


def _mounted_library(settings: Settings) -> Path:
    """The library, or a 503 naming the path. Unavailable is a deployment state, not
    a bad request: the volume may simply not be populated yet.
    """
    try:
        return require_library(settings)
    except LibraryUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


@router.get("/library")
def read_library() -> LibraryResponse:
    settings = load_settings()
    summary = summarize(_mounted_library(settings))
    return LibraryResponse(**vars(summary))


@router.post("/scenes")
def create_scene(params: SceneParams) -> SceneResponse:
    """Generate a scene, or hand back the one this request already produced.

    Plain `def`, not `async def`: generation is seconds of CPU work, and FastAPI runs
    a sync endpoint in a threadpool instead of blocking the event loop with it.
    """
    settings = load_settings()
    library = _mounted_library(settings)
    summary = summarize(library)

    try:
        result = ensure_scene(
            library,
            summary.id,
            settings.scenes,
            SceneRequest(
                seed=params.seed,
                frames=params.frames,
                size=params.size,
                n_objects_min=params.n_objects_min,
                n_objects_max=params.n_objects_max,
            ),
        )
    except SceneUnsatisfiableError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return SceneResponse(
        id=result.id,
        cached=result.cached,
        seed=params.seed,
        frames=params.frames,
        size=params.size,
        n_objects=result.n_objects,
        streams={
            stream: StreamInfo(
                url=f"/scenes/{result.id}/{stream}.mp4",
                colormaps=sorted(COLORMAPS) if stream == "disparity" else [],
                default=DEFAULT_COLORMAP if stream == "disparity" else None,
            )
            for stream in VIDEO_STREAMS
        },
    )


@router.get("/scenes/{scene_id}/{stream}.mp4")
def read_scene_video(
    scene_id: Annotated[str, PathParam(pattern=r"^[0-9a-f]{16}$")],
    stream: str,
    colormap: Annotated[str, Query(pattern=r"^[a-z_]+$")] = DEFAULT_COLORMAP,
) -> FileResponse:
    """Serve one stream as H.264.

    Encoded on the first request and kept next to the frames, so the second request
    is a file read. `scene_id` is constrained to the hash alphabet in the route
    itself, which is also what keeps it from naming a path outside `scenes/`.

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
    scene_dir = settings.scenes / scene_id
    if not (scene_dir / "scene.json").is_file():
        raise HTTPException(status_code=404, detail=f"no scene {scene_id}")

    suffix = "" if colormap == DEFAULT_COLORMAP else f".{colormap}"
    video = scene_dir / f"{stream}{suffix}.mp4"
    if not video.is_file():
        frames = list_stream_frames(scene_dir, stream)
        if not frames:
            raise HTTPException(
                status_code=404,
                detail=f"scene {scene_id} has no {stream}",
            )
        # Encode beside the destination and rename, so a second request arriving
        # mid-encode either waits for nothing or serves a complete file. Writing
        # straight to `video` leaves a path that exists but is half-written, and
        # `is_file()` cannot tell the difference. Two panes showing one stream, or a
        # reload during the first encode, both reach this.
        with tempfile.NamedTemporaryFile(
            dir=scene_dir,
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
