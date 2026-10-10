---
type: reference
status: active
tags: [reference, dataset, formats, on-disk-contract]
related: [pipeline-explainer, generate-a-dataset]
---

# Dataset layout — the on-disk contract

This page is the single source of truth for what the pipeline writes to disk. Every format
below was checked by opening a generated file, not by reading a docstring.

If code and this page disagree, the code is right and this page is a bug. Fix it in the same
pull request.

---

## Stage A — the artifact library

Built once per asset pool by `video_bokeh.library.build`. Depth is estimated here and never again.

```
<library-root>/
├── foregrounds/<id>/
│   ├── rgb.png        RGBA  uint8   (1024, 1024, 4)   the cut-out object
│   ├── alpha.png      L     uint8   (1024, 1024)      its matte, 0–255
│   ├── depth.png      I;16  uint16  (1024, 1024)      propagated disparity
│   ├── depth_raw.png  I;16  uint16  (1024, 1024)      estimator output, diagnostic, optional
│   ├── depth_input.png RGB  uint8   (1024, 1024, 3)   what the estimator saw, diagnostic, optional
│   └── meta.json      JSON                            how the asset was produced, diagnostic
└── backgrounds/<id>/
    ├── rgb.png        RGB   uint8   (1536, 1536, 3)   larger than the frame, for pan headroom
    └── depth.png      I;16  uint16  (1536, 1536)      disparity
```

**Depth in the library is 16-bit, not 8-bit.** Each map is min/max-normalized to the full
`[0, 65535]` range on write and read back as float32 in `[0, 1]`
(`_library.py:_write_depth_png`). The absolute scale is dropped on purpose: the compositor
percentile-stretches every map into a band, so only relative structure survives, and 16 bits
carry it without visible banding.

`depth_raw.png` is optional. Libraries built before it existed load with `raw_depth=None`.

`meta.json` records the `--model` string Stage A ran with, the propagation parameters, and
raw-depth statistics such as `core_frac` — the fraction of the object the trusted core covered.
Stage B never reads it; it exists so a bad depth map can be diagnosed without re-running Stage A.

`depth_input.png` is the image the estimator was actually given: the cut-out composited onto
the neutral texture, because a depth model cannot read a transparent cut-out. Statistics alone
cannot tell a model failure from a compositing failure — with this you can look. It costs
about 38 % of a foreground's footprint, which is nothing against the dataset the library
produces.

---

## Stage B — a generated sequence

Written by `video_bokeh.scenes.generate`. This is the layout `bridge/any_to_bokeh.py` consumes.

```
<output>/
├── manifest.csv
└── sequences/<seq-id>/
    ├── all_in_focus/<frame>.png   RGB    uint8   the sharp composite
    ├── alpha/<frame>.tif          multi-page uint8, one page per object
    ├── disparity/<frame>.png      I;16   uint16  disparity, larger = closer
    ├── layers/                                   optional, written with --layers
    └── bokeh/<frame>.png          RGB    uint8   optional, by --bokeh or Stage C
```

- `<seq-id>` is 4 digits, 1-based: `0001`, `0002`.
- `<frame>` is zero-padded to `max(2, len(str(n_frames)))` digits and 1-based, so an 80-frame
  clip runs `01` … `80`. any-to-bokeh parses frame order from this numeric prefix.
- A sequence whose trajectories cannot be made collision-free is skipped, not written. The
  numbering keeps its gap, because sequence `i` is always seeded from `seed + i`.

### The three streams

| stream | format | dtype | what a pixel means |
|---|---|---|---|
| `all_in_focus` | PNG, RGB | uint8 | the composite with nothing blurred |
| `alpha` | TIFF, multi-page | uint8 | page `k` is object `k`'s matte, `0`–`255`, soft |
| `disparity` | PNG, `I;16` | uint16 | `[0, 1]` disparity scaled to `[0, 65535]`, larger = closer |

Both sides of these formats live in `src/video_bokeh/core/_streams.py`, so the writer and the reader
cannot drift apart.

**The alpha TIFF is multi-page, never multi-sample.** Pillow raises
`UnidentifiedImageError` on a TIFF with more than four samples per pixel; it reads a paged
file exactly. The writer pins `photometric="minisblack"` for a second reason: without it
`tifffile` infers meaning from the array shape, turning three masks into one RGB page and four
into one RGBA page — silently, and exactly at the commonest object counts.

**Alpha masks are soft and they overlap.** Measured over 24 frames: every frame has partially
transparent pixels, a median 7.9 % of the frame, and 13 of 24 frames had two objects with
non-zero alpha at the same pixel. The masks are independent of each other, recorded before
occlusion is resolved — they are not a partition of the frame, so a single index or label map
cannot represent them.

**Disparity, not depth.** Larger means closer, throughout the pipeline. The background
occupies `[0, bg_band_top]` with `bg_band_top = 0.05`; foreground objects live above it.

### The layers stream — optional

`layers/` holds what each frame was composited from. `scenes.generate --layers` writes it;
without the flag no layers are written, and any left from an earlier run are removed.

```
layers/
├── background/<frame>.png            RGB   uint8    the whole background, nothing in front
├── background_disparity/<frame>.png  I;16  uint16   its disparity
├── objects/<frame>.tif               multi-page RGB uint8, page k = object k's colour
├── objects_disparity/<frame>.tif     multi-page uint16, page k = object k's disparity
└── paint_order.json                  one list per frame: the object pages, far to near
```

- **Every layer is whole.** The background includes what the objects cover, and each object
  includes what a nearer object covers. A layer-wise renderer can blur each one without
  inpainting anything first.
- **`paint_order.json` is written last.** A `layers/` without it was interrupted and is not
  complete. Writing a sequence again removes its old `layers/` first, with or without
  `--layers`.
- **Object `k`'s alpha is page `k` of `alpha/<frame>.tif`.** It is not written twice.
- **An object layer is zero wherever its alpha page reads 0**, colour and disparity both.
  That is where the stored alpha rounds to 0, so no colour hides under a transparent pixel.
- **Compositing the layers gives back the frame.** Start from the background, then paint each
  object over it in the frame's `paint_order`, `out = a · object + (1 − a) · out`. The result
  is `all_in_focus`, and the same with the disparities gives `disparity`, up to the rounding of
  each file. The order is recorded because it changes from frame to frame, and because soft
  edges of objects at similar disparity may overlap.
- **Quantized like the other streams.** Colour is truncated to 8 bits as `all_in_focus` is, so
  a pixel no object covers matches it exactly. Disparity is 16-bit as `disparity` is.
- **The TIFFs follow the alpha stream's rules**: multi-page, deflate, read with Pillow.
  `src/video_bokeh/core/_streams.py` holds both sides of both formats.

**The layers double the dataset and add two thirds to the write time.** Measured on the lab
machine on 2026-10-10, five 80-frame sequences at 1024 × 1024 with 1 to 5 objects:

| | MiB per frame | seconds per sequence |
|---|---|---|
| without `--layers` | 1.746 | 31.4 |
| with `--layers` | 3.773 | 52.6 |

Of the 2.03 MiB the layers add, the background's colour is 1.14 MiB: it is a second
all-in-focus frame. Its disparity is 0.22 MiB. The object pages are mostly empty and compress
to 0.44 MiB for colour and 0.23 MiB for disparity.

### The bokeh stream — Stage C

`bokeh/` holds the rendered bokeh. `scenes.generate --bokeh` writes it in the same run as the
frames, from the layers it holds in memory, and `video_bokeh.render.run` writes it over
sequences already written. Both write the same stream; writing a sequence again removes the
old one.

| stream | format | dtype | what a pixel means |
|---|---|---|---|
| `bokeh` | PNG, RGB | uint8 | the frame as the bokeh renderer blurred it |

- **One file per `all_in_focus` frame, named like it**, at the sequence's own size.
- **`focus.json` beside the frames says what was in focus**: `{"object": 2, "zf": [...]}`,
  the object by its alpha page, or `null` when none held the focus, and each frame's in-focus
  disparity in `[0, 1]`. It also names the `renderer` and the `strength` it ran at, and the
  layered renderer adds its `gamma` and `radius_step`. A sequence rendered before 2026-10-10
  has only `object` and `zf`. A reader that lists the stream takes `*.png`.
- **It appears complete or not at all.** The renderer writes into a hidden folder beside it,
  `.bokeh-` and a random suffix, a new one per run. It renames that folder to `bokeh/` only
  when every frame is in place. A run that was killed can leave one behind, and deleting it
  loses nothing.
- **It is optional.** A sequence without it is still a complete Stage B sequence. Nothing in
  Stage B or the demo reads it yet.
- **With any-to-bokeh it is lossy.** The vendored script writes an mp4 at 1024 × 576, which is
  decoded and resized back to the sequence's size. A lossless path waits for a GPU run that
  can check it.
- **With the layered renderer it is lossless**, rendered from `layers/` at the sequence's own
  size.

### How many objects a scene can hold

There is no format ceiling any more. A multi-page TIFF takes as many masks as it is given, and
`--n-objects-max` defaults to **5**.

The limit is now the depth axis. Objects get disjoint slots above the background, so each
extra object makes every slot narrower and collisions harder to avoid. Measured over 12 sequences
of 40 frames:

| objects | slot width | skipped | mean rejections | sec/sequence |
|---|---|---|---|---|
| 3 | 0.303 | 0 | 0.42 | 0.31 |
| 4 | 0.222 | 0 | 0.83 | 0.45 |
| 5 | 0.174 | 0 | 5.17 | 1.12 |
| 6 | 0.142 | 2 | 8.75 | 2.18 |
| 8 | 0.101 | 11 | 1.42 | 3.48 |

Five places every scene. Six starts losing them, and eight loses 11 of 12 — its low rejection
count is an artifact of scenes hitting the retry cap and being skipped rather than counted.

Above five, give each object more room rather than expecting the writer to refuse: lower the
slot `gap`, `bg_band_top` or `_ACTIVE_WIDTH`. Raising any of them leaves less.

### `manifest.csv`

One row per written sequence.

| column | meaning |
|---|---|
| `seq_id` | the directory name under `sequences/` |
| `seed` | `seed + i`. The sequence is fully reproducible from this, the library and the run's settings |
| `n_frames` | frames written |
| `size` | square frame side in pixels |
| `n_objects` | objects actually placed |
| `n_rejections` | trajectory sets discarded by the collision validator |
| `n_range_fallbacks` | objects forced to hold their start scale because no end pose fit |

`seed` makes the dataset reproducible rather than merely archived: the library plus a manifest,
which records the frame count and size beside each seed, regenerates every sequence exactly when
the run's other settings, the object range and the sampling configuration, are the same.

---

## The any-to-bokeh bridge

`video_bokeh.bridge.any_to_bokeh` converts a sequence tree into what the vendored inference code
expects.

```
<a2b-root>/
├── demo_dataset/<dataset-name>/
│   ├── videos/<seq-id>/<frame>.png              RGB uint8
│   └── disp/<seq-id>/<frame>_zf_<focus>.png     L   uint8
└── csv_file/<dataset-name>.csv                  aif_folder, disp_folder, k
```

`<focus>` is the in-focus disparity, six decimals. By default it is the mean disparity of one
object, over the pixels no other mask covers, the object drawn by that area for the whole
sequence. `--focus alpha` takes the mean under all the objects' masks, and `--focus-disparity`
pins one value for the whole clip instead, which is what you want when comparing frames rather
than chasing the subject.

The bridge reads the 16-bit disparity PNGs and quantizes them to the 8 bits any-to-bokeh
reads, once.

---

## Measured sizes

Real sequences, 1024 × 1024, three objects.

| stream | KB per frame | GB at 80 000 frames |
|---|---|---|
| `all_in_focus` | 900–1360 | 68–104 |
| `disparity` (uint8, before the move to 16-bit) | 52 | 4.0 |
| `alpha` | 50 | 3.8 |

A 1000-sequence, 80-frame dataset is roughly **75–113 GB**, and `all_in_focus` is 92 % of it.
These sizes predate 16-bit disparity. Re-measured on 2026-10-10, with 16-bit disparity and 1
to 5 objects, a frame takes 1.30 MiB of `all_in_focus`, 0.39 MiB of `disparity` and 0.05 MiB
of `alpha`, 1.75 MiB in all. The same dataset is then about **136 GiB**, and about **295 GiB**
with `--layers`. Anything that shrinks the dataset meaningfully has to address
`all_in_focus`.

---

## Related

- [[pipeline-explainer]] — why the pipeline is built this way
- [[generate-a-dataset]] — how to produce this tree
- [[run-any-to-bokeh-inference]] — how to feed it to the renderer
- [[cli]] — every flag of every module
