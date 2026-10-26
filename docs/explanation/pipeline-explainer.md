---
type: topic
status: active
tags: [topic, pipeline, depth, disparity, trajectories]
related: [dataset-layout, generate-a-dataset, datasets, cli, loader]
---

# How the pipeline works

A plain-language walkthrough of the two stages that make the synthetic data and its bokeh:
what each stage computes and why it is built this way.

No commands here. To run it, see [generate-a-dataset](../how-to/generate-a-dataset.md). For what
it writes, see [dataset-layout](../reference/dataset-layout.md).

---

## The big picture

We want to train a model that adds realistic blur to a video based on depth. That needs
training data where the distance of every pixel is known exactly. Real video does not come
with that, so we build synthetic video instead: cut-out objects composited onto backgrounds,
each with a depth we assigned and therefore know.

Two stages, split by cost. Stage A computes depth once per asset. Stage B turns those assets
into as many videos as you want, and its bokeh renderer blurs each video by its depth.

```mermaid
flowchart LR
  pools["Source images<br/>MAGICK, BG-20K"] --> A["Stage A<br/>build the library"]
  A --> lib[("library/<br/>color, matte, disparity")]
  lib --> gen
  subgraph B["Stage B"]
    gen["generate sequences"] -->|layers| render["bokeh renderer"]
  end
  gen --> seq[("sequences/<br/>all_in_focus, alpha, disparity")]
  render -->|"bokeh/"| seq
  seq -.->|"layers/, to render again"| render
  B -.-> stream["Sequence stream<br/>inside a training loop"]
  B -.-> api["Demo API"]
```

- **Stage A takes its depth estimator from a flag, and `render.run` its bokeh renderer.**
  Either can be a class of your own. Stage B's own pass, the stream and the API always use the
  layered renderer. [cli](../reference/cli.md) lists both.
- **Files on disk join the stages.** Stage B reads the library Stage A wrote. The renderer,
  run again over written sequences, reads the files Stage B wrote. That is what lets a model
  that cannot share our Python environment run in one of its own.
  [0001-on-disk-formats-join-the-stages](../adr/0001-on-disk-formats-join-the-stages.md) records
  why.
- **Stage A is the expensive stage.** It runs a neural depth estimator, and Stage B never does.
  The bokeh comes from our layer-wise renderer, which runs on any machine, in Stage B's pass
  or again over written sequences.

---

## Stage A: build the library

Run the depth estimator once per asset, clean the result, and save it.

### 1. Composite on a neutral background

A foreground is a cut-out with transparency. The depth model needs a full image, so the
object is pasted onto a backdrop first. That backdrop is deliberately not blank: it is
low-frequency noise around mid-gray, clipped to a narrow band, because a flat background gives
the model nothing to separate the object from. The composite is saved as `depth_input.png`, so
a bad depth map later can be traced to the model or to the compositing rather than guessed at.

### 2. Estimate depth

The model returns a disparity map: brighter means closer. That map, before propagation, is
saved as `depth_raw.png` for diagnosis only, scaled to its own minimum and maximum in 16 bits.

Which model runs is a flag: Depth Anything V2 by default, Depth Pro, Depth Anything 3, or one
of your own. Every model hands back disparity, so nothing after this step knows which one ran.

### 3. Clean the trusted core

The estimator is not perfect. Around thin structures like hair it leaves black holes where it
had no confident estimate. Propagating depth outward from a hole spreads the black into a
large dark patch, so the holes are removed first.

The trusted core is built in three steps:

1. Erode the object's alpha mask inward, because borders are unreliable.
2. Drop any pixel in the eroded region whose depth falls below the 2nd percentile. Those are
   the holes.
3. What remains is the core.

`meta.json` records how large the core was and how many holes were dropped, so a bad depth map
later can be traced to the estimator or to propagation without re-running Stage A.

### 4. Propagate to the full frame

Reliable values exist only inside the core, but compositing needs a value at every pixel.
Every pixel outside the core takes the depth of its nearest trusted pixel, and the result is
lightly blurred to soften the seams. That becomes `depth.png`.

Backgrounds skip all of this: they are already full-frame, so the estimator's output is
saved directly.

---

## Stage B: generate sequences

Pick a background and some objects, one to five by default, give each a motion path and a
depth trajectory, check nothing collides, render every frame.

### The disparity axis

Think of disparity as a ruler from 0 to 1. Zero is infinitely far, one is against the lens.
**Larger means closer**, throughout the pipeline, since disparity is roughly proportional to
`1 / distance`.

The background takes the bottom sliver, `[0, 0.05]`. Everything above is divided between the
objects into disjoint **slots**, separated by small gaps:

```
Background:  [0.00 - 0.05]
Object 1:          [0.05 ------------- 0.515]
Gap:                                          0.02
Object 2:                                     [0.535 ------------- 1.00]
```

An object never fills its slot. It occupies a narrow **active band**, 0.08 wide by default,
and the rest is room to move.

### What the slot is for

**The slot constrains frame 1 and nothing after it.** That is the whole design.

An earlier version pinned each object inside its slot for the entire clip. Collisions were
then impossible by construction, which was safe and wrong: an object could never move past
another in depth, and a camera that sees something approach is exactly what we are modeling.
That version has been removed.

Letting objects leave their slots means two can end up at the same depth, so what used to be
guaranteed by construction is now checked instead.

### How a trajectory is built

1. Sample a start interval inside the object's slot.
2. Sample an end pose. Its on-screen scale implies the end interval, which is *derived*,
   never sampled: growing on screen by a factor `k` means getting `k` times closer, so the
   whole interval is multiplied by `k`.
3. If the derived interval leaves `[0.05, 1.0]`, throw the pose away and draw another. After
   100 tries, fall back to holding the start scale, which always fits. The manifest counts
   these fallbacks.
4. Every frame in between interpolates the interval from start to end.

**The law is `ratio = scale_end / scale_start`, not its reciprocal.** Apparent size and
disparity are both proportional to `1 / distance`, so they rise and fall together. The
approved research spec writes the reciprocal because it derives the rule for depth-as-distance
and then applies the formula to a disparity interval. Taken literally it makes an object that
grows on screen recede in the depth stream, exactly the inconsistency this design exists to
remove. The code is right and the spec's formula is not; `derive_end_range` in
`src/video_bokeh/core/_trajectory.py` carries the argument in full.

An object coming closer therefore occupies a *wider* disparity interval, because the whole
interval scales. That is physically correct: the nearer something is, the more depth it spans.

### Collision validation

Two objects can end up overlapping on screen while sharing a depth.
That sample has no defensible depth ordering and would teach the model something untrue.

Every frame is checked for pairs that overlap in alpha **and** in disparity interval. A
2D overlap alone is fine: that is just occlusion. If any frame collides, the whole trajectory
set is discarded and resampled, up to 50 times, after which the sequence is skipped rather
than written. The manifest records the rejection count.

### Rendering a frame

1. Warp the background's color and depth by its homography.
2. Sort objects by the center of their disparity interval **for this frame**, far to near.
3. For each, in that order: warp its color and depth, stretch its depth into its interval for
   this frame, alpha-composite it onto the canvas, and record its mask separately.
4. Write the three streams.

**Paint order is recomputed every frame.** Two objects that swap depth mid-clip swap which one
occludes the other, which is the whole point of letting them move.

**Each object keeps one alpha page for the whole clip**, even as paint order changes. The
masks are recorded before occlusion is resolved, so they are independent soft masks, not a
partition of the frame, so a renderer can blur each layer separately and then composite. That
independence is also why a single index or label map cannot stand in for them: two objects
can be partly transparent at the same pixel.

**The layers themselves can be written too.** With `--layers`, Stage B also writes what each
frame was composited from: the whole background, each whole object with its own disparity, and
the paint order. A layer-wise bokeh renderer needs exactly this, because the composite no longer
holds what a blurred object in front would let through.
[0002-layers-are-stored-not-regenerated](../adr/0002-layers-are-stored-not-regenerated.md)
records why they are stored rather than regenerated, and [layered-bokeh](layered-bokeh.md)
explains the renderer that reads them.

---

## The bokeh renderer, in Stage B

A bokeh renderer reads a sequence's layers and writes what a camera with a shallow focus would
have recorded: the `bokeh` stream, one frame for every `all_in_focus` frame. It is a component
of Stage B. It only reads the layers, which Stage B writes with `--layers` or hands out from
the sequence stream, and it never reads the library.

The layer-wise renderer is the one the dataset's bokeh comes from. It blurs each layer of a
frame on its own and stacks them again, so a blurred object in front thins out at its edges and
shows what is behind it. It runs in our own process, on a CPU or a GPU. By default the focus
follows one object per sequence, drawn with odds in proportion to its area, so one object is
sharp and the others blur by how far they are from it in depth.
[layered-bokeh](layered-bokeh.md) explains it.

any-to-bokeh, a diffusion model, was the first renderer. It has since left the pipeline,
because it ran offline only, on an NVIDIA card, in an environment of its own, and could not
join the same pass as the frames. Comparing our renderer with it and with other published ones
is a task of its own, outside the pipeline.

**Bokeh is rendered end to end.** Stage B renders a sequence's bokeh in the same pass as its
frames, in a second pass over the scene from the layers it holds in memory:
`scenes.generate --bokeh` for a dataset, the API for the demo, the loader for training, in its
workers or on the training GPU. The renderer can also run again over sequences already written
with their layers, for a new strength or focus. That is optional, and only a sequence that
holds its layers can take it.
[0003-bokeh-is-rendered-in-the-same-pass](../adr/0003-bokeh-is-rendered-in-the-same-pass.md)
records why.

---

## How the stages connect

Stage B never calls the depth model. It reads the library's precomputed maps and warps them
with the same homography as the color. Three things follow:

- **Depth stays aligned with the object** as it pans, rotates and scales, because both go
  through the same transform.
- **Thousands of videos come from a small library**, since sampling is cheap and estimation
  already happened.
- **Temporal consistency is free.** One depth map per asset, warped per frame, cannot flicker
  the way per-frame estimation would.

A sequence is also reproducible. Sampling is deterministic, so the library, the seed and the
run's settings (frame count, size, the object range and the sampling configuration)
regenerate it exactly. The manifest records the seed, the frame count and the size.

**Stage B also runs inside training.** The sequence stream, [loader](../reference/loader.md),
calls the same Stage B for every item a training loop asks for and writes nothing. A model can
then train on as many sequences as it likes, from the same distribution as the written dataset.

---

## Related

- [dataset-layout](../reference/dataset-layout.md): the on-disk contract, with formats and bit
  depths
- [generate-a-dataset](../how-to/generate-a-dataset.md): how to run Stages A and B
- [loader](../reference/loader.md): the sequence stream, for training on the fly
- [check-trajectories-by-eye](../how-to/check-trajectories-by-eye.md): how to judge the
  result by eye
- Local-only note `meetings/2026-06-26-unrestricted-pipeline-algorithm.md`: where the
  unrestricted design was agreed
