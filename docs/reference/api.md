---
type: reference
status: active
tags: [reference, api, http, sequences]
related: [cli, dataset-layout, generate-a-dataset]
---

# HTTP API reference

Four endpoints. They mount the libraries Stage A built and generate Stage B sequences on demand,
from whichever library a request names.

**A generated sequence comes with its bokeh, when torch is installed.** The API renders it in
the same request with the layered renderer, so `POST /sequences` takes longer: on an Apple M3
Pro, 80 frames at 512 pixels with four to five objects took 8 to 14 s without bokeh and 16 to
25 s with it, optical flow included in both. A sequence cached without bokeh gets it when it is
asked for again. Without torch, as in the API's own install, sequences come without bokeh.

Interactive docs are at `/docs` when the server is running.

## Configuration

Four environment variables configure the API, all optional. A fifth picks the device the
bokeh renders on.

| Variable | Default | Names |
|---|---|---|
| `VIDEO_BOKEH_DATA_ROOT` | `data` | the directory everything generated lives under |
| `VIDEO_BOKEH_LIBRARY` | `$VIDEO_BOKEH_DATA_ROOT/library` | one library, or a directory of them |
| `CORS_ORIGINS` | `http://localhost:3000` | comma-separated origins a browser may call from |
| `VIDEO_BOKEH_RENDER_BOKEH` | `1` | whether a sequence comes with its bokeh; `0` turns it off, and without torch it is off anyway |
| `VIDEO_BOKEH_LAYERED_DEVICE` | `cpu` | the torch device the bokeh renders on: `cpu`, `mps` or `cuda` |

**The second one names a library or a directory of libraries.** A directory holding
`foregrounds/` and `backgrounds/` is one library:

```bash
VIDEO_BOKEH_LIBRARY=data/library_dev/da2-large uv run uvicorn video_bokeh.api.main:app --port 8000
```

Any other directory is read one level down, and every subdirectory holding both is a library.
That is the layout `make libraries` writes, one dev-pool library per depth estimator, into
`data/library_dev/`. `make api` sets `VIDEO_BOKEH_LIBRARY` to serve that root:

```
data/library_dev/
├── da2-large/
├── da3-mono-large/
└── depth-pro/
```

Full-pool libraries use `data/library/<estimator>`. Neither root adds a suffix to estimator
names. See [Library names](../how-to/generate-a-dataset.md#library-names).

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

**`id` is a digest of the train assets' ids, the depth estimator and the asset size**, not the
directory name. A request's scene is drawn from the train split
([dataset-layout](dataset-layout.md#the-train-and-test-splits)), so a test asset added or
removed leaves the id, and every scene, as they were. The id moves when train assets are added
or removed, when Stage A is re-run with a different estimator and when the library is rebuilt
at another size, and it does not move when the same library is mounted somewhere else.
`n_foregrounds` and `n_backgrounds` count the train assets too, the ones a scene can show.

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
| `bokeh_strength` | `16` | 0 to 64 |

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
  "bokeh_strength": 16.0,
  "n_objects": 4,
  "streams": {
    "all_in_focus": {
      "url": "/sequences/499a2ad706800460/all_in_focus.mp4",
      "colormaps": [],
      "default": null,
      "opens_pane": true,
      "overlay": null,
      "backward": null
    },
    "alpha": {
      "url": "/sequences/499a2ad706800460/alpha.mp4",
      "colormaps": [],
      "default": null,
      "opens_pane": true,
      "overlay": null,
      "backward": null
    },
    "disparity": {
      "url": "/sequences/499a2ad706800460/disparity.mp4",
      "colormaps": ["grey", "spectral_r"],
      "default": "spectral_r",
      "opens_pane": true,
      "overlay": null,
      "backward": null
    },
    "flow": {
      "url": "/sequences/499a2ad706800460/flow.mp4",
      "colormaps": [],
      "default": null,
      "opens_pane": true,
      "overlay": null,
      "backward": "/sequences/499a2ad706800460/flow_back.mp4"
    },
    "occlusion": {
      "url": "/sequences/499a2ad706800460/occlusion.mp4",
      "colormaps": [],
      "default": null,
      "opens_pane": false,
      "overlay": "/sequences/499a2ad706800460/occlusion.mp4?overlay=true",
      "backward": null
    }
  }
}
```

**Each entry of `streams` is stream info: how the stream can be displayed, not only where it
is.** `colormaps` is empty when the stream has one rendering, as every stream but
`disparity` has. A client that renders
what `streams` lists needs no change when a stream is added. `bokeh`, `flow` and `occlusion`
appear here once the sequence has them, in that order, with no colormaps, after the three
every sequence has. The backward flow is not listed apart: it is the flow's other direction,
under `backward`.

- **`opens_pane` says whether the demo opens a pane for the stream on its own.** It is false
  for `occlusion`, which waits in the demo's stream picker, so a sequence opens with the panes
  it did before the mask was served.
- **`overlay` is the stream drawn over the frames it describes**, for `occlusion`, and null
  for every other stream. See `?overlay=` below.
- **`backward` is the same motion the other way**, for `flow`: the backward flow's video,
  where each pixel came from in the previous frame. Null for every other stream, and for a
  sequence without `flow_back/`. The demo picks between the two directions under the flow's
  pane.

**Every sequence of two frames or more comes with its motion streams:** the optical flow, the
backward flow and the occlusion mask. Generation writes `flow/`, `flow_back/` and
`occlusion/` in the same pass as the frames. A cached sequence generated before that gets the
ones it lacks on its next request, in one pass, each whole or not at all.

Writing the flow costs about 40% more time. Measured on an Apple M3 Pro, 80 frames, four
objects, without bokeh, each pair back to back:

| Size | Without flow | With flow |
|---|---|---|
| 512 px | 5.9 s, 0.90 GiB peak | 8.5 s, 1.04 GiB peak |
| 1024 px | 21.8 s, 3.18 GiB peak | 30.4 s, 3.85 GiB peak |

With bokeh, 80 frames at 1024 px took 61.1 s without flow and 67.9 s with it. The peak went
from 4.67 to 4.68 GiB, set by the bokeh pass after the frames are freed.

The backward flow and the occlusion mask cost about another third. Measured on the same
machine, 80 frames, four objects, without bokeh, each pair back to back:

| Size | Seeds | Forward flow only | All three motion streams |
|---|---|---|---|
| 512 px | 0 to 2 | 7.6 to 10.9 s, 1.06 GiB peak | 10.0 to 13.7 s, 1.25 GiB peak |
| 1024 px | 0 and 1 | 39.9 to 40.9 s, 3.90 GiB peak | 53.4 to 55.5 s, 4.51 to 4.61 GiB peak |

**`library` may be left out only while one library is mounted.** With several, leaving it out
answers 422 and lists the ids. An id that is not mounted answers the same way. The API never
picks a library for you. The response's `library` names the one the sequence came from.

The same parameters against two libraries built from the same assets give the same scene —
the objects, their paths and their masks — and differ only in disparity. That is what
comparing depth estimators means here.

**The sequence id is a hash of the five numbers, the library id and the bokeh strength.**
Stage B is deterministic, so the same request always names the same sequence. The cache is the
directory `$VIDEO_BOKEH_DATA_ROOT/sequences/<id>/`, and there is no database. The strength
joins the hash only when it is not 16. Every sequence cached before a request could name it
was rendered at 16, so each keeps the id it had.

**`bokeh_strength` is k, the blur radius in pixels at a 1024-pixel width, one unit of
disparity from the focus.** It is the strength `scenes.generate --bokeh-strength` takes. It
names the sequence as the seed does, so another k is another sequence, with its own copy of
every stream, cached apart. It does so whether or not the API renders bokeh, so the id never
depends on how the server is configured. A sequence cached without bokeh gets it at its own k
when it is asked for again. `-0` reads as `0`.

**The response's `bokeh_strength` is the one the sequence's bokeh was rendered at.** It comes
from `bokeh/focus.json`, which the renderer writes with the frames, so a renderer of one's own
that renders the stream again at another strength shows through. A sequence with no record
yet, because the API rendered no bokeh, names the strength the request asked for.

`render.run`'s layered renderer cannot render an API sequence's bokeh again, at any
`--strength`. It reads the `layers/` stream, which the API does not write, so it refuses the sequence
and leaves its bokeh as it was. Only a renderer of one's own that needs no layers could.

The cap of 64 is four times the default, because a wider blur takes longer to render and the
call blocks while it renders. Measured on an Apple M3 Pro, with the bokeh on the CPU:

| Shape | Seeds | At 16 | At 64 |
|---|---|---|---|
| 80 frames at 512 px, two to three objects, over HTTP | 0 to 2 | 15.8 to 18.6 s | 18.7 to 22.9 s |
| 80 frames at 1024 px, four objects, one process each | 0 | 93.2 s, 4.91 GiB peak | 129.4 s, 5.49 GiB peak |

Each pair ran back to back. The 1024 px row ran the generation the endpoint runs, in a fresh
process for each strength, so the peak is that generation's own.

`cached` says whether this request generated the sequence or found it. A cache hit answers at
once, 0.02 s over HTTP in the table below, unless it adds what a cached sequence lacks. For 80
frames at 512 px with four to five objects on an Apple M3 Pro, adding the bokeh took 16 to
19 s, and adding the flow 6 to 12 s.

**Without NDJSON, the call blocks while it generates.** Measured before the API rendered
bokeh, at size 512 with four to five objects per sequence:

| Where | 24 frames | 80 frames | cache hit |
|---|---|---|---|
| Apple M3 Pro, native | 2.0 to 3.7 s | 6.6 to 8.0 s | 0.02 s |
| the same machine, in the container | 3.5 to 6.1 s | 10.1 to 11.0 s | 0.04 s |

Cost scales with frame count, roughly linearly. The spread inside each cell is seed to seed:
sampling collision-free trajectories takes a variable number of retries, which is worth up to
about a factor of two. The container is consistently slower than the host, which is what
running Linux in a virtual machine on macOS costs.

**A client can hear the generation as it goes.** Sent with `Accept: application/x-ndjson`,
the request answers one JSON object a line instead: the steps it will take, a progress line
for each step, then the sequence, or an error.

```bash
curl -N -X POST http://localhost:8000/sequences \
  -H 'accept: application/x-ndjson' -H 'content-type: application/json' \
  -d '{"library": "747c2380d504", "seed": 42, "frames": 24, "size": 256}'
```

```
{"steps": [{"step": "sampling", "total": 1}, {"step": "frames", "total": 24}, {"step": "writing", "total": 24}, {"step": "bokeh", "total": 24}]}
{"step": "sampling", "done": 0, "total": 1}
{"step": "sampling", "done": 1, "total": 1}
{"step": "frames", "done": 0, "total": 24}
...
{"step": "writing", "done": 24, "total": 24}
{"step": "bokeh", "done": 0, "total": 24}
...
{"step": "bokeh", "done": 24, "total": 24}
{"sequence": {"id": "bfc884ca50c1f8fd", "library": "747c2380d504", "cached": false, ...}}
```

- **The steps come in order, each counted from 0 to its total:** `sampling` (choosing
  collision-free trajectories, one step that retries can make the longest), `frames`
  (rendering them, the motion streams included), `writing`, and `bokeh` when the API renders
  it. A cached sequence missing any motion stream or its bokeh reports `sampling` once, then
  `flow`, or `frames` and `bokeh`, or all three; one missing nothing reports no step, only
  itself. `flow` adds every motion stream the sequence lacks, in one pass. It counts the
  frames that give one of them a file. That is one fewer than the frames, or all of them
  when backward flow is added with either of the others, because backward flow starts a
  frame later. "Step", because
  "stage" names the pipeline's Stages A and B.
- **`steps` comes first and names every step, in order, with the total it will count to.**
  The counts done over the counts named are how far the whole generation has got, which
  the demo draws as one bar. A cached sequence missing nothing sends no `steps` either.
- **`sequence` is the body the JSON answer would have had.**
- **A failure after the first line ends the answer with `{"error": {"status", "detail"}}`:**
  422 for a scene with no collision-free trajectories, 500 for anything else. A request that
  is invalid, or names no mounted library, is refused before the first line, as without
  NDJSON. An `Accept` that rules NDJSON out with `q=0` gets JSON.
- **A client that goes away does not stop the generation.** The sequence is cached for the
  next ask.

The demo asks for NDJSON and fills one bar for the whole generation.

Answers 422 when the parameters are out of range, when the object range is inverted, when no
library is named while several are mounted, when the named one is unknown, or when no
collision-free scene could be sampled. Answers 503
when there is no library, or when two cannot be told apart.

## `GET /sequences/{id}/{stream}.mp4`

Serves one stream as H.264. `stream` is `all_in_focus`, `alpha`, `disparity`, or `bokeh`,
`flow`, `flow_back` and `occlusion` when the sequence has them.

**`alpha` is one color per object, not one silhouette.** The stream is a multi-page TIFF
with one page per object, and the page index is that object's identity for the whole clip —
`scenes/_compositor.py` fixes it deliberately, because paint order is recomputed every frame
as objects move past each other. So an object keeps its color from the first frame to the
last, and watching which color covers which is watching the depth ordering change.

The masks are **amodal**: each page holds the object's full silhouette, including the part a
nearer object hides. They are painted in page order, so where two overlap the higher object
number wins — that is identity order, not distance. The disparity pane beside it is where
distance is read.

`object_colors` in the sequence response names the color of each object, so a legend cannot
drift from what the video paints.

**`flow` is colored the way optical-flow papers color it:** the wheel of Baker et al., as
the Middlebury benchmark and RAFT's `flow_viz` draw it. The hue is the direction, rightward
red, and the saturation the speed, white where nothing moves. One scale serves the whole
sequence, the fastest valid motion in it, so the colors do not flicker from frame to frame.
The last frame has no flow, since there is no next frame to move to, so the video shows it
still. That keeps the video as long as the other streams and in step with them.

**`flow_back` is colored the same way**, at its own sequence's scale. Its first frame has no
previous one to come from, so that is the frame the video shows still. Its vectors point to
where each pixel came from, so a pixel moving right is drawn in the color of left. The
sequence response names this URL as the flow's `backward` rather than as a stream.

**`occlusion` is the mask as stored**: white where the pixel's surface is hidden in the next
frame, black elsewhere. The last frame has no next one, so its video frame is black.
**`?overlay=true` draws it over the all-in-focus frames instead.** The frames turn gray at 90%
of their brightness. The occluded pixels are drawn over them in cyan, `#00E5FF`, at 85%
opacity. The last frame is gray with nothing drawn on it. The overlay is cached as its own
file, `occlusion.overlay-cyan.mp4`. Earlier versions drew it in red, cached as
`occlusion.overlay.mp4`, and in orange, cached as `occlusion.overlay-orange.mp4`. Both are
left on disk and never served. The value is a yes or no, as `true`, `1` or `yes` and their
opposites, and anything else answers 422. Every other stream drops the parameter, whatever
its value, as it drops `?colormap=`.

Encoded on the first request at 24 fps and kept next to the frames, so the second request is a
file read. A stream whose frames changed after its video was encoded is encoded again: a renderer of
one's own, run over the sequence with `render.run`, replaces `bokeh/`, and the page plays the
new render once reloaded. The layered renderer cannot, because the API writes no `layers/`.

New encodes use H.264 High, `yuv420p` and CRF 17, and `ffprobe` confirms the High
profile. The old default meant lossless H.264 at CRF 0, which uses the High 4:4:4
Predictive profile. Firefox's decoders refuse that profile on Windows and macOS, as
Mozilla's
[`dom/media/platforms/PDMFactory.cpp`](https://raw.githubusercontent.com/mozilla-firefox/firefox/main/dom/media/platforms/PDMFactory.cpp)
specifies. Firefox playback was not tested here.

Existing cached MP4s keep their original encoding. The API re-encodes only when a video
is missing or its stream directory's modification or change time is newer than the video. Changing the
encoder settings alone does not invalidate cached files. The
[CLI reference](cli.md#video_bokehpreviewpack--png-streams-to-mp4) measures file sizes,
encoding times and fidelity for all five streams.

**`?colormap=` applies to `disparity` only.** It is 16-bit grayscale on disk and gets its
color when served, so `spectral_r` (the default, matching what `video_bokeh.preview.pack`
writes) and `grey` are two renderings of one stream. Each is cached as its own file,
`disparity.mp4` and `disparity.grey.mp4`. Every other stream has one rendering, so the
parameter is dropped rather than forking that stream's cache into identical copies. An unknown name
answers 422 and lists the ones that exist.

Answers 404 for an unknown sequence, an unknown stream, or an id that is not a 16-character hex
hash.

## What a sequence looks like on disk

```
$VIDEO_BOKEH_DATA_ROOT/sequences/<id>/
├── sequence.json                 the request, the library id and the object count
├── all_in_focus/                 RGB uint8 PNG
├── alpha/                        multi-page uint8 TIFF, one page per object
├── disparity/                    uint16 PNG
├── bokeh/                        RGB uint8 PNG and focus.json, with torch, or by a renderer of one's own
├── flow/                         KITTI 16-bit PNG, every frame but the last
├── flow_back/                    KITTI 16-bit PNG, every frame but the first
├── occlusion/                    8-bit PNG, every frame but the last
├── all_in_focus.mp4              written on first request
├── disparity.mp4                 written on first request, Spectral
├── disparity.grey.mp4            written if `grey` is ever asked for
└── occlusion.overlay-cyan.mp4    written if the overlay is ever asked for
```

The three stream directories are the layout in [dataset-layout](dataset-layout.md), without the
dataset's `sequences/<seq-id>/` level around them: the API serves one sequence, not a dataset.

A sequence appears atomically. Generation writes to a temporary directory beside the destination
and renames it into place, so a sequence on disk is either absent or complete, and a crashed or
concurrent generation leaves nothing half-written behind.

## Limits

Deliberate, and worth knowing before the library or the audience grows.

**Nothing evicts `sequences/`.** It grows until someone deletes it. Storage depends on the
scene and optional streams. A one-object, 80-frame, 512 px sequence used about 26 MiB for
`all_in_focus`, `alpha` and `disparity` frames, plus about 0.7 MiB for their CRF 17 MP4s.
Bokeh, flow and layers add to that. Deleting the directory is safe: every sequence is
reproducible from its library, its seed and the settings its request named, which
`sequence.json` records. That is the same reason [dataset-layout](dataset-layout.md) treats
frames as disposable and the library as the thing to keep.

**Each bokeh strength asked for stores a whole sequence.** k names the sequence, so a second k
writes every stream again, not only `bokeh/`. Measured from the `da2-large` dev library, a
fresh sequence with its bokeh and all three motion streams, before any MP4:

| Shape | Seeds | Bytes on disk |
|---|---|---|
| 80 frames at 512 px, one object | 0 | 90,760,849 |
| 80 frames at 512 px, two to three objects | 0 to 2 | 56,922,641 to 69,262,665 |
| 80 frames at 1024 px, four objects, at 16 and at 64 | 0 | 216,990,329 and 203,348,052 |

In every one of them the all-in-focus frames are the largest stream, and the bokeh the second.

**The libraries are re-read on every request.** Per library, two directory listings, one small
JSON and one image header, so that `/libraries` and `/sequences` always reflect what is mounted
rather than what was mounted at startup. Cheap against a few libraries of tens. Against
libraries of thousands it is worth caching on the directories' modification times.

**Two identical requests arriving together both generate.** There is no lock. The rename
decides which one lands and the loser discards its work, so the result is correct and no
directory is ever overwritten while someone reads it — it just costs the duplicated CPU. For
an audience of a handful of people that is cheaper than the coordination would be.

**The library id does not cover pixel content.** Covered above under `GET /libraries`.
