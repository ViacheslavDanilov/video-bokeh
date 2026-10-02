---
type: reference
status: active
tags: [reference, api, http, sequences]
related: [cli, dataset-layout, generate-a-dataset]
---

# HTTP API reference

Four endpoints. They mount the libraries Stage A built and generate Stage B sequences on demand,
from whichever library a request names.

**The API serves bokeh but does not render it.** Rendering is minutes of GPU work per sequence.
Stage C renders it into the sequences this API wrote, on a machine with an NVIDIA card:

```bash
make bokeh
```

That renders every sequence under `$VIDEO_BOKEH_DATA_ROOT/sequences/` that has no bokeh yet,
and leaves out any shorter than any-to-bokeh can take, saying which. Asking for a sequence again
then lists its `bokeh` stream. Starting a render from the API would need a job id and polling,
and waits on where Stage C runs.

Interactive docs are at `/docs` when the server is running.

## Configuration

Three environment variables, all optional.

| Variable | Default | Names |
|---|---|---|
| `VIDEO_BOKEH_DATA_ROOT` | `data` | the directory everything generated lives under |
| `VIDEO_BOKEH_LIBRARY` | `$VIDEO_BOKEH_DATA_ROOT/library` | one library, or a directory of them |
| `CORS_ORIGINS` | `http://localhost:3000` | comma-separated origins a browser may call from |

**The second one names a library or a directory of libraries.** A directory holding
`foregrounds/` and `backgrounds/` is one library, which is what makes an existing checkout work
without moving anything:

```bash
VIDEO_BOKEH_LIBRARY=data/library_dev uv run uvicorn video_bokeh.api.main:app --port 8000
```

Any other directory is read one level down, and every subdirectory holding both is a library.
That is the layout `make libraries` writes, one library per depth estimator, into
`data/library/`, the default, so the API serves all of them with nothing set:

```
data/library/
├── da2-large/
├── da3-mono-large/
└── depth-pro/
```

A subdirectory whose name starts with a dot is skipped, which is how a build still in progress
stays out of view. A directory holding only one of `foregrounds/` and `backgrounds/` is a
broken library, and the API says which half is missing.

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

## `GET /libraries`

What is mounted, in directory-name order.

```json
[
  {
    "id": "747c2380d504",
    "name": "da2-large",
    "n_foregrounds": 12,
    "n_backgrounds": 20,
    "depth_estimator": "da2-large",
    "asset_size": 1024
  }
]
```

**`id` is a digest of the asset ids, the depth estimator and the asset size**, not the directory
name. It moves when assets are added or removed, when Stage A is re-run with a different
estimator and when the library is rebuilt at another size, and it does not move when the same
library is mounted somewhere else.

It does not cover pixel content. The same asset ids, estimator and size over different images
produce the same id, wherever the library sits. So a library rebuilt in place keeps its id, and
the sequences cached against the old one are served as its own: delete
`$VIDEO_BOKEH_DATA_ROOT/sequences/` after a rebuild, which is safe because every sequence
regenerates. A rebuild mounted next to the original is refused, as the next paragraph says.

**Two mounted libraries with one id are refused.** Both this endpoint and `POST /sequences`
answer 503 and name the two directories. A request names its library by id, and the cache is
keyed on that id, so either library would serve the other's sequences.

`name` is the directory's own name. Under compose a single library is always called `library`,
because that is where compose mounts it.

`asset_size` is the side Stage A stored foregrounds at. Backgrounds are deliberately larger —
Stage A oversizes them so the Stage B warp never samples past the edge.

Answers 503 when there is no library at the configured path. The message names the path.

## `POST /sequences`

Generates one sequence and answers with its id.

| Field | Default | Range |
|---|---|---|
| `library` | the only one mounted | a library `id` from `GET /libraries` |
| `seed` | `0` | any integer |
| `frames` | `80` | 1 to 240 |
| `size` | `512` | 64 to 2048 |
| `n_objects_min` | `1` | 1 to 16 |
| `n_objects_max` | `5` | 1 to 16, and not below `n_objects_min` |

```bash
curl -X POST http://localhost:8000/sequences \
  -H 'content-type: application/json' \
  -d '{"library": "747c2380d504", "seed": 42, "frames": 80, "size": 512,
       "n_objects_min": 4, "n_objects_max": 5}'
```

```json
{
  "id": "499a2ad706800460",
  "library": "747c2380d504",
  "cached": false,
  "seed": 42,
  "frames": 80,
  "size": 512,
  "n_objects": 4,
  "streams": {
    "all_in_focus": {
      "url": "/sequences/499a2ad706800460/all_in_focus.mp4",
      "colormaps": [],
      "default": null
    },
    "alpha": {
      "url": "/sequences/499a2ad706800460/alpha.mp4",
      "colormaps": [],
      "default": null
    },
    "disparity": {
      "url": "/sequences/499a2ad706800460/disparity.mp4",
      "colormaps": ["grey", "spectral_r"],
      "default": "spectral_r"
    }
  }
}
```

**`streams` is a manifest, not a list of URLs.** Each entry says how that stream can be
displayed, and `colormaps` is empty when the stream is already RGB. A client that renders what
the manifest reports needs no change when a stream is added. `bokeh` appears here once Stage C
has rendered the sequence, with no colormaps, after the three every sequence has.

**`library` may be left out only while one library is mounted.** With several, leaving it out
answers 422 and lists the ids. An id that is not mounted answers the same way. The API never
picks a library for you. The response's `library` names the one the sequence came from.

The same parameters against two libraries built from the same assets give the same scene —
the objects, their paths and their masks — and differ only in disparity. That is what
comparing depth estimators means here.

**The sequence id is a hash of the five parameters and the library id.** Stage B is
deterministic, so the same request always names the same sequence. The cache is the directory
`$VIDEO_BOKEH_DATA_ROOT/sequences/<id>/`, and there is no database.

`cached` says whether this request generated the sequence or found it. On a cache hit the call
returns in milliseconds.

**The call blocks while it generates.** Measured against `data/library_dev` at size 512 with
four to five objects per sequence:

| Where | 24 frames | 80 frames | cache hit |
|---|---|---|---|
| Apple M3 Pro, native | 2.0 to 3.7 s | 6.6 to 8.0 s | 0.02 s |
| the same machine, in the container | 3.5 to 6.1 s | 10.1 to 11.0 s | 0.04 s |

Cost scales with frame count, roughly linearly. The spread inside each cell is seed to seed:
sampling collision-free trajectories takes a variable number of retries, which is worth up to
about a factor of two. The container is consistently slower than the host, which is what
running Linux in a virtual machine on macOS costs.

Anything driving this from a browser needs a spinner.

Answers 422 when the parameters are out of range, when the object range is inverted, when no
library is named while several are mounted, when the named one is unknown, or when no
collision-free scene could be sampled. Answers 503
when there is no library, or when two cannot be told apart.

## `GET /sequences/{id}/{stream}.mp4`

Serves one stream as H.264. `stream` is `all_in_focus`, `alpha`, `disparity`, or `bokeh` once
Stage C has rendered the sequence.

**`alpha` is one colour per object, not one silhouette.** The stream is a multi-page TIFF
with one page per object, and the page index is that object's identity for the whole clip —
`scenes/_compositor.py` fixes it deliberately, because paint order is recomputed every frame
as objects move past each other. So an object keeps its colour from the first frame to the
last, and watching which colour covers which is watching the depth ordering change.

The masks are **amodal**: each page holds the object's full silhouette, including the part a
nearer object hides. They are painted in page order, so where two overlap the higher object
number wins — that is identity order, not distance. The disparity pane beside it is where
distance is read.

`object_colors` in the sequence response names the colour of each object, so a legend cannot
drift from what the video paints.

Encoded on the first request at 24 fps and kept next to the frames, so the second request is a
file read. A stream whose frames changed after its video was encoded is encoded again: Stage C
run a second time replaces `bokeh/`, and the page plays the new render once reloaded.

**`?colormap=` applies to `disparity` only.** It is 16-bit greyscale on disk and gets its
colour when served, so `spectral_r` (the default, matching what `video_bokeh.preview.pack`
writes) and `grey` are two renderings of one stream. Each is cached as its own file,
`disparity.mp4` and `disparity.grey.mp4`. Every other stream is already RGB, so the parameter
is dropped rather than forking that stream's cache into identical copies. An unknown name
answers 422 and lists the ones that exist.

Answers 404 for an unknown sequence, an unknown stream, or an id that is not a 16-character hex
hash.

## What a sequence looks like on disk

```
$VIDEO_BOKEH_DATA_ROOT/sequences/<id>/
├── sequence.json           the request, the library id and the object count
├── all_in_focus/           RGB uint8 PNG
├── alpha/                  multi-page uint8 TIFF, one page per object
├── disparity/              uint16 PNG
├── bokeh/                  RGB uint8 PNG, once Stage C has rendered it
├── all_in_focus.mp4        written on first request
├── disparity.mp4           written on first request, Spectral
└── disparity.grey.mp4      written if grey is ever asked for
```

The three stream directories are the layout in [[dataset-layout]], without the dataset's
`sequences/<seq-id>/` level around them: the API serves one sequence, not a dataset.

A sequence appears atomically. Generation writes to a temporary directory beside the destination
and renames it into place, so a sequence on disk is either absent or complete, and a crashed or
concurrent generation leaves nothing half-written behind.

## Limits

Deliberate, and worth knowing before the library or the audience grows.

**Nothing evicts `sequences/`.** It grows until someone deletes it. A sequence of 80 frames at 512
is about 44 MB, so a thousand of them is about 43 GB. Deleting the directory is safe: every
sequence is reproducible from its library and its seed, which is the same reason
[[dataset-layout]] treats frames as disposable and the library as the thing to keep.

**The libraries are re-read on every request.** Per library, two directory listings, one small
JSON and one image header, so that `/libraries` and `/sequences` always reflect what is mounted
rather than what was mounted at startup. Cheap against a few libraries of tens. Against
libraries of thousands it is worth caching on the directories' modification times.

**Two identical requests arriving together both generate.** There is no lock. The rename
decides which one lands and the loser discards its work, so the result is correct and no
directory is ever overwritten while someone reads it — it just costs the duplicated CPU. For
an audience of a handful of people that is cheaper than the coordination would be.

**The library id does not cover pixel content.** Covered above under `GET /libraries`.
