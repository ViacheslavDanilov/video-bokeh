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

`meta.json` records the estimator name, the propagation parameters, and raw-depth statistics
such as `core_frac` — the fraction of the object the trusted core covered. Stage B never reads
it; it exists so a bad depth map can be diagnosed without re-running Stage A.

`depth_input.png` is the image the estimator was actually given: the cut-out composited onto
the neutral texture, because a depth model cannot read a transparent cut-out. Statistics alone
cannot tell a model failure from a compositing failure — with this you can look. It costs
about 38 % of a foreground's footprint, which is nothing against the dataset the library
produces.

---

## Stage B — a generated sequence

Written by `video_bokeh.scenes.generate`. This is the layout `prepare_any_to_bokeh.py` consumes.

```
<output>/
├── manifest.csv
└── sequences/<seq-id>/
    ├── all_in_focus/<frame>.png   RGB    uint8   the sharp composite
    ├── alpha/<frame>.tif          multi-page uint8, one page per object
    └── disparity/<frame>.png      I;16   uint16  disparity, larger = closer
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
non-zero alpha at the same pixel. The masks are independent layers recorded before occlusion
is resolved — they are not a partition of the frame, so a single index or label map cannot
represent them.

**Disparity, not depth.** Larger means closer, throughout the pipeline. The background
occupies `[0, bg_band_top]` with `bg_band_top = 0.05`; foreground objects live above it.

### How many objects a scene can hold

There is no format ceiling any more. A multi-page TIFF takes as many masks as it is given, and
`--n-objects-max` defaults to **5**.

The limit is now the depth axis. Objects get disjoint slots above the background, so each
extra object makes every slot narrower and collisions harder to avoid. Measured over 12 scenes
of 40 frames:

| objects | slot width | skipped | mean rejections | sec/scene |
|---|---|---|---|---|
| 3 | 0.303 | 0 | 0.42 | 0.31 |
| 4 | 0.222 | 0 | 0.83 | 0.45 |
| 5 | 0.174 | 0 | 5.17 | 1.12 |
| 6 | 0.142 | 2 | 8.75 | 2.18 |
| 8 | 0.101 | 11 | 1.42 | 3.48 |

Five places every scene. Six starts losing them, and eight loses 11 of 12 — its low rejection
count is an artifact of scenes hitting the retry cap and being skipped rather than counted.

Above five, raise `bg_band_top`, the slot `gap`, or `_ACTIVE_WIDTH` rather than expecting the
writer to refuse.

### `manifest.csv`

One row per written sequence.

| column | meaning |
|---|---|
| `seq_id` | the directory name under `sequences/` |
| `seed` | `seed + i`. The sequence is fully reproducible from this plus the library |
| `n_frames` | frames written |
| `size` | square frame side in pixels |
| `n_objects` | objects actually placed |
| `n_rejections` | trajectory sets discarded by the collision validator |
| `n_range_fallbacks` | objects forced to hold their start scale because no end pose fit |

`seed` makes the dataset reproducible rather than merely archived: the library plus a manifest
regenerates every sequence exactly.

---

## The any-to-bokeh bridge

`data.prepare_any_to_bokeh` converts a sequence tree into what the vendored inference code
expects.

```
<a2b-root>/
├── demo_dataset/<dataset-name>/
│   ├── videos/<seq-id>/<frame>.png              RGB uint8
│   └── disp/<seq-id>/<frame>_zf_<focus>.png     L   uint8
└── csv_file/<dataset-name>.csv                  aif_folder, disp_folder, k
```

`<focus>` is the in-focus disparity, six decimals. By default it is the mean disparity under
the frame's alpha mask; `--focus-disparity` pins one value for the whole clip instead, which
is what you want when comparing frames rather than chasing the subject.

The bridge also reads legacy float32 `.tif` disparity, preferring `.png` when both exist.

**Known defect: disparity is quantized twice.** Stage B writes uint8, and
`_to_uint8_disparities` quantizes again on the way in. Harmless while the input is already
8-bit. The moment disparity gains precision, this silently throws it away, and no test covers
it.

---

## Measured sizes

Real sequences, 1024 × 1024, three objects.

| stream | KB per frame | GB at 80 000 frames |
|---|---|---|
| `all_in_focus` | 900–1360 | 68–104 |
| `disparity` (uint8) | 52 | 4.0 |
| `alpha` | 50 | 3.8 |

A 1000-sequence, 80-frame dataset is roughly **75–113 GB**, and `all_in_focus` is 92 % of it.
Anything that shrinks the dataset meaningfully has to address that stream.

---

## Related

- [[pipeline-explainer]] — why the pipeline is built this way
- [[generate-a-dataset]] — how to produce this tree
- [[run-any-to-bokeh-inference]] — how to feed it to the renderer
- [[cli]] — every flag of every module
