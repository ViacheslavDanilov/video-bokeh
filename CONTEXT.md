# Video Bokeh

Synthetic training data for depth-aware video bokeh: cut-out objects composited onto
backgrounds at disparities we assign and therefore know, rendered as sequences, plus a demo
that shows them.

## Assets and the library

**Asset pool**:
A source collection of images before Stage A — MAGICK foregrounds, BG-20K backgrounds, and
their small development subsets.
_Avoid_: dataset, source data

**Foreground**:
A cut-out image in the library, with its matte and disparity map — the reusable template
that objects are made from.
_Avoid_: object (for the library item), cut-out, sprite

**Background**:
A full-frame image in the library, larger than a frame so that it can pan.
_Avoid_: backdrop, plate

**Matte**:
A foreground's soft alpha channel, stored with it in the library.
_Avoid_: mask, alpha mask

**Library**:
Every asset with its disparity map, computed once by Stage A and read by every sequence.
_Avoid_: artifact library, asset store, cache

**Depth estimator**:
Any model behind Stage A's interface that turns an asset into one disparity map — Depth
Anything V2 by default, Depth Pro, or one of the user's own. The only term in this project
where the word "depth" survives.
_Avoid_: depth model

**Trusted core**:
The part of a foreground's disparity map kept as reliable: its eroded matte minus the holes
where the depth estimator had no confident answer.
_Avoid_: core mask, valid region

## Sequences

**Scene**:
The sampled setup a sequence is rendered from: its background, its objects with their
trajectories, the frame count and the size — everything the seed decides before a frame is
drawn.
_Avoid_: layout, plan

**Sequence**:
One generated clip: a scene rendered frame by frame into streams, fully determined by its
seed and the library.
_Avoid_: clip, video

**Frame**:
One time step of a sequence, across all of its streams.
_Avoid_: image

**Object**:
A foreground placed in a sequence, with its own trajectory and alpha mask.
_Avoid_: foreground (for the placed instance), layer, actor

**Stream**:
One per-frame output of a sequence: all-in-focus, alpha, disparity, and later bokeh.
_Avoid_: channel, modality

**All-in-focus**:
The stream holding the sharp composite, with nothing blurred.
_Avoid_: RGB, sharp frame

**Alpha mask**:
One object's soft matte in the alpha stream, recorded before occlusion is resolved, so it
holds the full silhouette including the hidden part. Alpha masks of different objects
overlap.
_Avoid_: mask, segmentation, label map, matte

**Disparity**:
Inverse distance scaled to [0, 1], where larger means closer — the one quantity every map in
the pipeline stores.
_Avoid_: depth, depth map

**Background band**:
The bottom sliver of disparity, reserved for the background.
_Avoid_: background depth

**Slot**:
A disparity interval above the background band, one per object and disjoint from the others,
that constrains where the object starts on the first frame and nothing after.
_Avoid_: lane, depth slot

**Active band**:
The narrow disparity interval an object occupies on a given frame; it moves as the object
approaches or recedes.
_Avoid_: depth range

**Trajectory**:
An object's path through a sequence: its on-screen motion and its active band on every
frame, sampled together.
_Avoid_: motion path, depth track

**Occlusion**:
A nearer object covering a farther one on screen while their active bands stay apart.
Expected and allowed.

**Collision**:
Two objects overlapping on screen and in active band on the same frame — a sample with no
defensible depth order, so its trajectories are thrown away and resampled.
_Avoid_: overlap, intersection

**Rejection**:
One set of trajectories thrown away because some frame of it collided.

**Paint order**:
The far-to-near order in which objects are composited, recomputed on every frame.
_Avoid_: z-order, layer order

**Seed**:
The integer that, together with the library, fully determines a sequence.

**Dataset**:
The sequences Stage B writes, with their manifest.
_Avoid_: asset pool, library

**Manifest**:
The dataset's table with one row per written sequence.
_Avoid_: using it for stream info

**Stage A**:
Building the library; the only stage that runs the depth estimator.
_Avoid_: preprocessing

**Stage B**:
Generating sequences from the library; it never runs the depth estimator.
_Avoid_: rendering

**Stage C**:
Rendering bokeh for each sequence with a bokeh renderer; it never reads the library.
_Avoid_: post-processing

## Rendering and the demo

**Bokeh**:
The disparity-dependent blur the trained model is meant to produce; a stream that does not
exist yet.
_Avoid_: blur, defocus

**Bokeh renderer**:
A model that writes a sequence's bokeh stream in Stage C — any-to-bokeh so far.
_Avoid_: bokeh model

**any-to-bokeh**:
The first bokeh renderer: external code that turns an all-in-focus stream and its disparity
into bokeh.

**Focus disparity**:
The disparity that stays sharp in a bokeh render.
_Avoid_: focal plane, focus depth

**Preview**:
A stream encoded as video for a person to watch; never part of the dataset.
_Avoid_: render

**Colormap**:
How a preview paints disparity for a person — Spectral or grey.

**Stream info**:
What the API reports for one stream of a generated sequence: where to fetch its preview and
which colormaps it takes.
_Avoid_: manifest

**Pane**:
One stream shown in the viewer.

**Transport**:
The single play, speed and position control that keeps every pane on the same frame.
_Avoid_: player, scrubber
