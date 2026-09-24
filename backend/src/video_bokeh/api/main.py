"""The HTTP surface: what library is mounted, and scenes generated on demand.

Decision 7 of the 2026-09-18 design. Generation is synchronous because Stage B is
CPU work measured in seconds, and the scene id is a hash of the request and the
library, so the cache is the directory on disk and there is no database.

Rendering bokeh is not here. That is minutes of GPU work in its own container, so it
gets a job id and polling when `render` exists.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Self

from fastapi import FastAPI, HTTPException
from fastapi import Path as PathParam
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
from video_bokeh.preview.pack import encode_stream, list_stream_frames

#: Matches the defaults of `video_bokeh.preview.pack`, so a stream looks the same
#: whether it was packed on the command line or served from here.
_FPS = 24
_QUALITY = 10
_COLORMAP = "spectral_r"

#: The endpoint blocks while it generates, so the request has to be bounded. 240
#: frames is three times the 80 every measurement so far has used.
_MAX_FRAMES = 240

app = FastAPI(
    title="Video Bokeh",
    description="Depth-aware synthetic bokeh pipeline for video, with a FastAPI backend and Next.js frontend.",
    version="0.1.0",
)


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


class SceneResponse(BaseModel):
    id: str
    cached: bool
    seed: int
    frames: int
    size: int
    n_objects: int
    streams: dict[str, str]


def _mounted_library(settings: Settings) -> Path:
    """The library, or a 503 naming the path. Unavailable is a deployment state, not
    a bad request: the volume may simply not be populated yet.
    """
    try:
        return require_library(settings)
    except LibraryUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/library")
def read_library() -> LibraryResponse:
    settings = load_settings()
    summary = summarize(_mounted_library(settings))
    return LibraryResponse(**vars(summary))


@app.post("/scenes")
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
            stream: f"/scenes/{result.id}/{stream}.mp4" for stream in VIDEO_STREAMS
        },
    )


@app.get("/scenes/{scene_id}/{stream}.mp4")
def read_scene_video(
    scene_id: Annotated[str, PathParam(pattern=r"^[0-9a-f]{16}$")],
    stream: str,
) -> FileResponse:
    """Serve one stream as H.264.

    Encoded on the first request and kept next to the frames, so the second request
    is a file read. `scene_id` is constrained to the hash alphabet in the route
    itself, which is also what keeps it from naming a path outside `scenes/`.
    """
    if stream not in VIDEO_STREAMS:
        raise HTTPException(status_code=404, detail=f"no video for stream {stream!r}")

    settings = load_settings()
    scene_dir = settings.scenes / scene_id
    if not (scene_dir / "scene.json").is_file():
        raise HTTPException(status_code=404, detail=f"no scene {scene_id}")

    video = scene_dir / f"{stream}.mp4"
    if not video.is_file():
        frames = list_stream_frames(scene_dir, stream)
        if not frames:
            raise HTTPException(
                status_code=404,
                detail=f"scene {scene_id} has no {stream}",
            )
        encode_stream(frames, video, _FPS, _QUALITY, stream, _COLORMAP)

    return FileResponse(video, media_type="video/mp4")
