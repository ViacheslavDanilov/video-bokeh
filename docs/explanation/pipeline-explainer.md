# How the pipeline works

A plain-language walkthrough of the two-stage synthetic data pipeline, what each stage computes, and why it is designed this way.

---

## The big picture

We want to train a model that can add realistic blur (bokeh) to a video based on depth. To do that we need training data: videos where we know exactly how far each pixel is from the camera.

Real video does not give us that for free. So we build synthetic videos by compositing cut-out foreground objects onto backgrounds, assigning each one a depth, and recording everything.

The pipeline has two stages. Stage A is slow and runs once. Stage B is fast and can be run many times from the same Stage A output.

```
Stage A  →  library/          (one depth map per asset, reusable)
Stage B  →  sequences/        (many videos sampled from the library)
```

---

## Stage A — build the library

**What it does:** take each foreground cut-out, run the depth estimator on it once, clean the result, and save it.

### Step 1 — composite on a neutral background

The foreground is a cut-out (RGBA image). The depth model needs a full image, not a transparent cut-out, so we paste the object onto a plain textured background before running the estimator.

### Step 2 — run the depth estimator

The depth model looks at the composited image and produces a disparity map: a greyscale image where brighter = closer to the camera. This is called `depth_raw.png` and is saved as-is for diagnostic use.

### Step 3 — clean the trusted core

The depth model is not perfect. Around thin structures like hair it sometimes leaves black holes — pixels where the model has no confident estimate. If we leave those holes in and propagate the depth outward, the black spreads to surrounding pixels and we get large dark patches in the final depth map.

To fix this, we build a "trusted core": the set of pixels we actually believe. We:

1. Take the object's alpha mask and erode it inward (remove a border of a few pixels, since borders are unreliable).
2. Drop any pixel in the eroded region whose depth value is suspiciously low — below the 2nd percentile of the region. These are the holes.
3. What is left is the trusted core.

A `meta.json` sidecar records how large the trusted core was and how many holes were dropped. If you see a bad depth map later, you can open this file and see whether the problem came from the depth model or from propagation.

### Step 4 — propagate the depth

We only have reliable depth values inside the trusted core (the interior of the object). But for compositing we need a depth value at every pixel in the frame, including outside the object.

Valery's propagation method does this: every pixel outside the trusted core inherits the depth value of its nearest trusted pixel, then the result is lightly blurred to smooth out the hard edges. This gives a full-frame depth map.

This is saved as `depth.png`.

### What the library contains per foreground

```
foregrounds/<id>/
├── rgb.png         RGBA cut-out
├── alpha.png       Alpha mask
├── depth.png       Propagated depth (used by Stage B)
├── depth_raw.png   Raw model output (diagnostic only)
└── meta.json       Core size, hole count, estimator name, parameters
```

Backgrounds are simpler: just `rgb.png` and `depth.png` (no propagation needed).

---

## Stage B — generate sequences

**What it does:** pick a background and one to three foreground objects from the library, give each one a motion path and a depth trajectory, check that nothing collides, render all the frames.

### Step 1 — assign depth envelopes

Each object gets a reserved slice of the disparity axis, called its **envelope**. Envelopes are disjoint, so two objects can never be assigned the same depth range. This is the collision-proof foundation.

Inside each envelope, the object does not fill the whole range. It occupies a narrow **active band** — about 8% of the full [0, 1] disparity range. The rest of the envelope is buffer space.

### Step 2 — sample a depth trajectory (dynamic mode only)

In fixed mode, the active band stays at the centre of the envelope. Simple but unrealistic.

In dynamic mode, each object gets a **depth trajectory**: a start depth `z_start` and end depth `z_end` in camera space. At each frame, the current depth `z(t)` is interpolated between the two.

From `z(t)`, two things are derived:

- **On-screen scale:** `scale(t) = scale_ref × z_ref / z(t)` — the object looks bigger when it is closer.
- **Disparity centre:** `disp(t) = disp_ref × z_ref / z(t)` — higher disparity when closer.

Both come from the same `z(t)`, so they are always consistent. An object that grows on screen also moves closer in the depth map. This was not true in the old pipeline.

### Step 3 — validate for collisions

After sampling all trajectories, the pipeline checks every frame for **3D collisions**: two objects that overlap in image space AND at the same depth at the same time.

A 2D overlap is fine on its own — one object is simply in front of the other. The collision only occurs if their depth ranges also overlap at the overlapping pixels.

If a collision is found in any frame, the whole trajectory set is thrown away and resampled. This repeats until a clean set is found (or a retry limit is hit). The number of rejections is recorded in `manifest.csv`.

### Step 4 — render each frame

For each frame:

1. Warp the background RGB and depth with its homography.
2. For each object (sorted far-to-near by depth centre for this frame):
   - Warp its RGBA and depth with the object's homography.
   - Map the object's warped depth into its active band for this frame.
   - Alpha-composite it on top of the current canvas (painter's algorithm).
   - Record the object's alpha mask separately.
3. Save the three output streams.

Paint order is recalculated per frame in dynamic mode, so if one object moves in front of another mid-clip, the correct one appears on top.

### Step 5 — save the outputs

Three image streams are written per frame:

**all_in_focus/** — the composited RGB frame with no blur. All objects sharp.

**disparity/** — a greyscale depth map. Brighter = closer. This is what a bokeh renderer will read to decide how much to blur each pixel.

**alpha/** — a 3-channel RGB image where each channel holds one object's alpha mask, in painter order (far-to-near):
- Red channel = farthest object
- Green channel = middle object
- Blue channel = nearest object

Separating the object masks into channels rather than merging them into a single grey image is essential for layer-wise bokeh rendering. The renderer needs to know which pixels belong to which object so it can blur each layer independently before compositing.

---

## Envelopes and active bands

Think of the full disparity axis as a ruler from 0 to 1, where 0 is infinitely far and 1 is right in front of the camera.

The background occupies the leftmost sliver (roughly 0–0.05). Everything above that is divided between the foreground objects.

An **envelope** is a reserved segment of that ruler for one object. No two objects share overlapping envelopes, so a collision is structurally impossible at the depth-assignment level.

### How envelopes are assigned

`assign_depth_slots` in `src/data/_fusion.py` takes the usable range above the background, subtracts small gaps between objects, and divides the rest equally:

```
Background:  [0.00 — 0.05]
Gap:                       0.02
Object 1:    [0.07 ————————————— 0.49]   ← envelope
Gap:                                   0.02
Object 2:    [0.51 ————————————— 0.93]   ← envelope
```

### Envelope vs active band

An object does not fill its entire envelope. Inside the envelope it occupies a narrow **active band** of fixed width (0.08). The rest of the envelope is buffer space.

```
Envelope:    [0.07 ————————————————————— 0.49]
Active band:          [0.27 ——— 0.35]
```

The centre of the active band moves inside the envelope as `z(t)` changes. When the object gets closer, the centre shifts right (higher disparity). When it moves away, the centre shifts left. It can never cross the envelope boundary — that is where the next object lives.

In **fixed mode** this movement is driven by the on-screen scale via `scaled_band` in `_fusion.py`. In **dynamic mode** it is driven directly by `z(t)` via `active_interval` in `_depth_track.py`.

### Disparity layout for 1, 2, and 3 objects

The numbers below use the default parameters: `bg_band_top = 0.05`, `gap = 0.02`, `active_width = 0.08`.

**1 object**

| Layer | Range | Width |
|---|---|---|
| Background | 0.00 – 0.05 | 0.05 |
| Object 1 envelope | 0.07 – 0.95 | 0.88 |
| Object 1 active band (at ref scale) | 0.47 – 0.55 | 0.08 |

**2 objects**

| Layer | Range | Width |
|---|---|---|
| Background | 0.00 – 0.05 | 0.05 |
| Object 1 envelope (far) | 0.07 – 0.49 | 0.42 |
| Object 1 active band | 0.24 – 0.32 | 0.08 |
| Object 2 envelope (near) | 0.51 – 0.93 | 0.42 |
| Object 2 active band | 0.68 – 0.76 | 0.08 |

**3 objects**

| Layer | Range | Width |
|---|---|---|
| Background | 0.00 – 0.05 | 0.05 |
| Object 1 envelope (farthest) | 0.07 – 0.35 | 0.28 |
| Object 1 active band | 0.17 – 0.25 | 0.08 |
| Object 2 envelope (middle) | 0.37 – 0.65 | 0.28 |
| Object 2 active band | 0.47 – 0.55 | 0.08 |
| Object 3 envelope (nearest) | 0.67 – 0.95 | 0.28 |
| Object 3 active band | 0.77 – 0.85 | 0.08 |

The active band can slide anywhere within its envelope depending on `z(t)`, so the ranges above show the position at reference scale. With three objects the envelopes are narrower (0.28 each), which leaves less room for the active band to travel — this is why scenes with three objects produce more collision rejections in dynamic mode.

---

## How disparity is encoded

Throughout the pipeline, **higher disparity value = closer to the camera**. Disparity is roughly proportional to 1/distance: things that are far away have very small disparity (near zero); things that are close have disparity near 1.

The background always occupies the lowest disparity range (near 0). Foreground objects sit above the background in separate non-overlapping bands. The nearest foreground object has the highest disparity values.

All depth maps are saved as uint16 PNG files, min-max normalised to the full 16-bit range. The compositor only needs relative structure (not absolute distances), so the normalisation does not lose information that matters.

---

## How the two stages connect

Stage A runs the depth model, which is the expensive part. Its output (the library) is a fixed set of pre-computed assets.

Stage B never calls the depth model. It reads the precomputed depth maps from the library, warps them with the same homography as the RGB, and maps the values into the assigned disparity band. This means:

- The depth map moves with the object as it pans, rotates, or tilts — they stay perfectly aligned.
- You can generate thousands of different videos from the same small library without re-running the depth model.
- Temporal consistency is guaranteed: the same depth map is used for every frame of a clip, just warped differently.

---

## Connection to the June 10 meeting

| Meeting discussion | What was implemented |
|---|---|
| Fixed lanes forbid realistic crossings | Dynamic mode: `z(t)` tracks with per-frame depth order |
| Zoom should change disparity (broken) | `scaled_band` rewritten with explicit active width; `z(t)` makes scale and disparity coherent |
| Black artifacts from propagation | Trusted-core cleanup drops low-percentile holes before propagation |
| Save raw vs propagated depth to diagnose artifacts | `depth_raw.png` saved alongside `depth.png`; `meta.json` records statistics |
| Dynamic 3D occupancy boxes for collision detection | `pair_collides` checks alpha overlap + depth interval overlap per frame; rejection sampling |
| Render bokeh per layer, then composite | Per-object alpha masks saved in R/G/B channels of the alpha image |
