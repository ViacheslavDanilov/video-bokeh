---
type: how-to
status: active
tags: [how-to, any-to-bokeh, inference, bokeh, runbook]
related: [dataset-layout, generate-a-dataset, cli]
---

# Run any-to-bokeh inference

Converts a generated sequence tree into the layout the vendored `any-to-bokeh` code expects,
then runs its inference script.

Commands run from `backend/`. All of them have been executed as written, except the inference
step itself, which needs the model checkpoints.

---

## One command

On the machine with the NVIDIA card, after `scripts/setup_third_party.sh`, Stage C does the
conversion and the inference in one go and writes each sequence's `bokeh/` stream:

```bash
uv run --extra render python -m video_bokeh.render.run --data-root data/demo \
  --renderer any-to-bokeh
```

It keeps its inputs and the script's `output/` in a temporary directory, so the submodule stays
clean, and it checks that every sequence got back as many frames as it sent. Before the model
loads, it refuses a batch holding a sequence of twelve frames or fewer, because any-to-bokeh
fails on such a sequence. Flags are in [[cli]]. The stream is in [[dataset-layout]].

**It first ran to completion on 2026-10-07, on an RTX 5090 with 32 GiB**: one 80-frame sequence
at 512 px in 90 s, model load included. It starts the demo through `_a2b_launch.py`, which has
the VAE encode a few frames at a time, keeps the UNet off the card while the VAE decodes, and
loads the sequences without the demo's 64 data-loader workers, whose shared memory a run of
twelve outgrew in a container. The demo on its own runs out of memory on that card. On a machine
without the any-to-bokeh venv it stops before converting anything:

```
RuntimeError: no interpreter at .../third_party/any-to-bokeh/.venv/bin/python: run scripts/setup_third_party.sh, or set VIDEO_BOKEH_A2B_PYTHON
```

The sections below are what it does by hand, which is still the way to look at the inputs any-to-bokeh
receives.

---

## 1. Convert the sequences

```bash
uv run python -m video_bokeh.bridge.any_to_bokeh --data-root data/demo
```

```
  0001: wrote 80 frame(s)
  0002: wrote 80 frame(s)

Done. CSV: third_party/any-to-bokeh/csv_file/demo.csv
Inference working directory: third_party/any-to-bokeh
  python test/inference_demo.py --val_csv_path csv_file/demo.csv
```

The last line appears only when the inference script is actually present. Without the
submodule checked out, the command still writes its inputs and says so instead of printing a
path that does not exist.

What lands where is in [[dataset-layout]].

---

## 2. Choose the focus plane

The renderer needs one in-focus disparity per frame, and it reads it out of the disparity
filename — `01_zf_0.500000.png`.

| what you want | flag |
|---|---|
| Follow one object, drawn by area: its mean disparity in each frame | default, or `--focus object` |
| Focus on the mean disparity under all the objects' masks together | `--focus alpha` |
| Focus on the mean disparity of the whole frame | `--focus full` |
| Pin one focus plane for the entire clip | `--focus-disparity 0.5` |

**The default keeps one object sharp, the way a camera operator follows a subject.** Each
sequence draws one object, with odds in proportion to the mean area it holds alone. The draw
is keyed on the seed the sequence was generated from, which `manifest.csv` or `sequence.json`
records. A re-run therefore keeps the object, and the training loader draws the same one for
that seed. A sequence that records no seed is keyed on its name. The object's mean disparity
is the focus in every frame.
A frame where it is off screen or wholly covered keeps the last focus. A sequence with
no object focuses on the whole frame. Weighting by area rather than taking the largest keeps
the focus off the foreground, where the large objects usually are, without landing on a speck.

**Only the pixels an object holds alone count.** The alpha masks are whole, drawn before
occlusion, while the disparity shows the nearest object. Where two masks overlap, the
disparity may be either object's. Taken whole, a far object at 0.2 three quarters behind one
at 0.8 would focus at 0.65. So the focus and the area count only the pixels no other mask
covers. A small object wholly inside a larger one's mask reads as hidden in that frame, even
when it is in front, and the focus keeps its last value.

`--focus alpha` was the default until 2026-10-07. With several objects at different depths, the
mean under all their masks falls between them, so none was sharp: on one sequence with objects
at disparity 0.11, 0.49 and 0.90 the focus came to 0.515.

**Pin the focus when you are comparing frames rather than following a subject.** With the
default the focus chases the object, so a clip where the object moves through depth never
shows it going out of focus — which is usually the thing you wanted to see.

```bash
uv run python -m video_bokeh.bridge.any_to_bokeh \
  --data-root data/demo --dataset-name pinned --focus-disparity 0.5
```

```
third_party/any-to-bokeh/demo_dataset/pinned/disp/0001/01_zf_0.500000.png
```

`--focus-disparity` overrides `--focus` and is rejected outside `[0, 1]`.

---

## 3. Run inference

```bash
cd third_party/any-to-bokeh
python test/inference_demo.py --val_csv_path csv_file/demo.csv
```

`third_party/any-to-bokeh` is a submodule and read-only — do not edit anything inside it. It
needs its own environment and checkpoints; see `scripts/setup_third_party.sh`. Run this way it
needs more than 32 GiB of GPU memory: it ran out on an RTX 5090, where Stage C's launcher fits.

**`--k` sets blur strength**, written into the CSV as a column, `16` by default. It is a
property of the conversion, not of the dataset, so re-running the bridge with a different
`--k` and a different `--dataset-name` is how you compare blur strengths.

---

## 4. Measure what inference costs

Stage C's first run gives one figure: 90 s for one 80-frame sequence at 512 px on an RTX 5090,
model load included. Nothing has been measured beyond that one run. That matters beyond curiosity: anything
past a few seconds cannot be a synchronous HTTP request, so the shape of the render API hangs
off the answer.

`../scripts/measure_a2b.sh` produces the number. It takes no arguments.

```bash
../scripts/measure_a2b.sh
```

Prerequisite: `scripts/setup_third_party.sh` has been run once on the machine. Without the
submodule's venv the script stops immediately and says so, before generating anything.

It records the GPU and the torch build, generates one 80-frame sequence at 512 px with four
to five objects, converts it exactly as section 1 does, and wall-clocks the inference.
Everything is teed into `backend/data/measurements/a2b-<timestamp>.log`. **That file is what
to send back** — it carries the commands, the card and the timing in one place.

**Steps 2 and 3 have been executed as written. The script's inference has not run to the end**:
it calls the demo directly, which runs out of memory on a 32 GiB card, and
`test/inference_demo.py` is pinned to `cuda:0` in six places.

Two things the script is careful about. It writes to `data/library_a2b_measure` and
`data/a2b_measure`, so an existing `data/demo` survives. And it removes the converted inputs
from the read-only submodule on the way out through an `EXIT` trap — including after a failed
inference, which is otherwise how that checkout ends up permanently dirty.

**a2b renders at 576×1024 regardless of what you generated.** `inference_demo.py` fixes the
sample size, so square frames come back stretched. That is its behaviour, not the bridge's.

---

## What the bridge loses

any-to-bokeh reads 8-bit disparity, so the bridge quantizes the 16-bit stream down. That is
the single lossy step, and it happens once — it used to happen twice, which was harmless only
while the source had no precision to lose.

With `--focus alpha`, the focus plane is the mean disparity under the **union** of the object
masks. Until 2026-09-18 the bridge blended the mask channels by luminance instead, which dropped objects
that were not in the middle channel and often fell back to whole-frame focus without saying
so. Any comparison against output generated before that fix is invalid.

---

## Clean up

The bridge writes into the submodule's working tree. To leave it clean:

```bash
rm -rf third_party/any-to-bokeh/demo_dataset/demo \
       third_party/any-to-bokeh/demo_dataset/pinned \
       third_party/any-to-bokeh/csv_file/demo.csv \
       third_party/any-to-bokeh/csv_file/pinned.csv
```
