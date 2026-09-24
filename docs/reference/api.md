---
type: reference
status: active
tags: [reference, api, http, scenes]
related: [cli, dataset-layout, generate-a-dataset]
---

# HTTP API reference

Four endpoints. They mount a library built by Stage A and generate Stage B scenes on demand.

Bokeh rendering is not here. That runs on a GPU for minutes per sequence, so it gets its own
container and its own asynchronous endpoints once that container exists.

Interactive docs are at `/docs` when the server is running.

## Configuration

Three environment variables, all optional.

| Variable | Default | Names |
|---|---|---|
| `VIDEO_BOKEH_DATA_ROOT` | `data` | the directory everything generated lives under |
| `VIDEO_BOKEH_LIBRARY` | `$VIDEO_BOKEH_DATA_ROOT/library` | the library directory itself |
| `CORS_ORIGINS` | `http://localhost:3000` | comma-separated origins a browser may call from |

Set the second one when the library is not called `library`. Every library on disk today is
flat — `data/library_dev` holds `foregrounds/` and `backgrounds/` directly — so pointing at it
is what makes an existing checkout work without moving anything:

```bash
VIDEO_BOKEH_LIBRARY=data/library_dev uv run uvicorn video_bokeh.api.main:app --port 8000
```

The two paths are read per request, not at startup: the container starts before the library
volume is populated, and `/health` answers either way.

`CORS_ORIGINS` is the exception — it is read once when the app is built, because middleware is
installed then. **The page and the API always sit on different ports**, so without a matching
origin here the browser refuses every request before it reaches a route.

## `GET /health`

Always 200. Does not touch the library.

```json
{"status": "healthy"}
```

## `GET /library`

What is mounted.

```json
{
  "id": "6016e7d35807",
  "n_foregrounds": 12,
  "n_backgrounds": 20,
  "depth_model": "da2-large",
  "asset_size": 1024
}
```

**`id` is a digest of the asset ids and the depth model**, not the directory name. It moves
when assets are added or removed and when Stage A is re-run with a different estimator, and it
does not move when the same library is mounted somewhere else.

It does not cover pixel content. The same asset ids and the same estimator over different
images produce the same id, so rebuild a changed library under a new directory name rather
than editing one in place.

`asset_size` is the side Stage A stored foregrounds at. Backgrounds are deliberately larger —
Stage A oversizes them so the Stage B warp never samples past the edge.

Answers 503 when there is no library at the configured path. The message names the path.

## `POST /scenes`

Generates one scene and answers with its id.

| Field | Default | Range |
|---|---|---|
| `seed` | `0` | any integer |
| `frames` | `80` | 1 to 240 |
| `size` | `512` | 64 to 2048 |
| `n_objects_min` | `1` | 1 to 16 |
| `n_objects_max` | `5` | 1 to 16, and not below `n_objects_min` |

```bash
curl -X POST http://localhost:8000/scenes \
  -H 'content-type: application/json' \
  -d '{"seed": 42, "frames": 80, "size": 512, "n_objects_min": 4, "n_objects_max": 5}'
```

```json
{
  "id": "f68bd7a7b87c8404",
  "cached": false,
  "seed": 42,
  "frames": 80,
  "size": 512,
  "n_objects": 4,
  "streams": {
    "all_in_focus": {
      "url": "/scenes/f68bd7a7b87c8404/all_in_focus.mp4",
      "colormaps": [],
      "default": null
    },
    "alpha": {
      "url": "/scenes/f68bd7a7b87c8404/alpha.mp4",
      "colormaps": [],
      "default": null
    },
    "disparity": {
      "url": "/scenes/f68bd7a7b87c8404/disparity.mp4",
      "colormaps": ["grey", "spectral_r"],
      "default": "spectral_r"
    }
  }
}
```

**`streams` is a manifest, not a list of URLs.** Each entry says how that stream can be
displayed, and `colormaps` is empty when the stream is already RGB. A client that renders what
the manifest reports needs no change when a stream is added — `bokeh` will appear here once
the render container exists.

**The scene id is a hash of the five parameters and the library id.** Stage B is
deterministic, so the same request always names the same scene. The cache is the directory
`$VIDEO_BOKEH_DATA_ROOT/scenes/<id>/`, and there is no database.

`cached` says whether this request generated the scene or found it. On a cache hit the call
returns in milliseconds.

**The call blocks while it generates.** Measured against `data/library_dev` at size 512 with
four to five objects per scene:

| Where | 24 frames | 80 frames | cache hit |
|---|---|---|---|
| Apple M3 Pro, native | 2.0 to 3.7 s | 6.6 to 8.0 s | 0.02 s |
| the same machine, in the container | 3.5 to 6.1 s | 10.1 to 11.0 s | 0.04 s |

Cost scales with frame count, roughly linearly. The spread inside each cell is seed to seed:
sampling collision-free trajectories takes a variable number of retries, which is worth up to
about a factor of two. The container is consistently slower than the host, which is what
running Linux in a virtual machine on macOS costs.

Anything driving this from a browser needs a spinner.

Answers 422 when the parameters are out of range, when the object range is inverted, or when
no collision-free scene could be sampled. Answers 503 when there is no library.

## `GET /scenes/{id}/{stream}.mp4`

Serves one stream as H.264. `stream` is `all_in_focus`, `alpha` or `disparity`.

**`alpha` is one colour per object, not one silhouette.** The stream is a multi-page TIFF
with one page per object, and the page index is that object's identity for the whole clip —
`scenes/_compositor.py` fixes it deliberately, because paint order is recomputed every frame
as objects move past each other. So an object keeps its colour from the first frame to the
last, and watching which colour covers which is watching the depth ordering change.

The masks are **amodal**: each page holds the object's full silhouette, including the part a
nearer object hides. They are painted in page order, so where two overlap the higher object
number wins — that is identity order, not distance. The disparity pane beside it is where
distance is read.

`object_colors` in the scene response names the colour of each object, so a legend cannot
drift from what the video paints.

Encoded on the first request at 24 fps and kept next to the frames, so the second request is a
file read.

**`?colormap=` applies to `disparity` only.** It is 16-bit greyscale on disk and gets its
colour when served, so `spectral_r` (the default, matching what `video_bokeh.preview.pack`
writes) and `grey` are two renderings of one stream. Each is cached as its own file,
`disparity.mp4` and `disparity.grey.mp4`. Every other stream is already RGB, so the parameter
is dropped rather than forking that stream's cache into identical copies. An unknown name
answers 422 and lists the ones that exist.

Answers 404 for an unknown scene, an unknown stream, or an id that is not a 16-character hex
hash.

## What a scene looks like on disk

```
$VIDEO_BOKEH_DATA_ROOT/scenes/<id>/
├── scene.json              the request, the library id and the object count
├── all_in_focus/           RGB uint8 PNG
├── alpha/                  multi-page uint8 TIFF, one page per object
├── disparity/              uint16 PNG
├── all_in_focus.mp4        written on first request
├── disparity.mp4           written on first request, Spectral
└── disparity.grey.mp4      written if grey is ever asked for
```

The three stream directories are the layout in [[dataset-layout]], without the
`sequences/<id>/` level around them — a scene is one sequence, not a dataset.

A scene appears atomically. Generation writes to a temporary directory beside the destination
and renames it into place, so a scene on disk is either absent or complete, and a crashed or
concurrent generation leaves nothing half-written behind.

## Limits

Deliberate, and worth knowing before the library or the audience grows.

**Nothing evicts `scenes/`.** It grows until someone deletes it. A scene of 80 frames at 512
is about 44 MB, so a thousand of them is about 43 GB. Deleting the directory is safe: every
scene is reproducible from its library and its seed, which is the same reason
[[dataset-layout]] treats frames as disposable and the library as the thing to keep.

**The library is re-read on every request.** Two directory listings, one small JSON and one
image header, so that `/library` and `/scenes` always reflect what is mounted rather than what
was mounted at startup. Cheap against a library of tens. Against a library of thousands it is
worth caching on the directory's modification time.

**Two identical requests arriving together both generate.** There is no lock. The rename
decides which one lands and the loser discards its work, so the result is correct and no
directory is ever overwritten while someone reads it — it just costs the duplicated CPU. For
an audience of a handful of people that is cheaper than the coordination would be.

**The library id does not cover pixel content.** Covered above under `GET /library`.
