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
| Follow the subject: focus on the mean disparity under the alpha mask | default, or `--focus alpha` |
| Focus on the mean disparity of the whole frame | `--focus full` |
| Pin one focus plane for the entire clip | `--focus-disparity 0.5` |

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
needs its own environment and checkpoints; see `scripts/setup_third_party.sh`.

**`--k` sets blur strength**, written into the CSV as a column, `16` by default. It is a
property of the conversion, not of the dataset, so re-running the bridge with a different
`--k` and a different `--dataset-name` is how you compare blur strengths.

---

## 4. Measure what inference costs

Nobody has measured it. The submodule has never been run, so every figure quoted so far —
"about a minute for 80 frames" — is a recollection. That matters beyond curiosity: anything
past a few seconds cannot be a synchronous HTTP request, so the shape of the render API hangs
off the answer.

`scripts/measure_a2b.sh` produces the number. It takes no arguments.

```bash
scripts/measure_a2b.sh
```

Prerequisite: `scripts/setup_third_party.sh` has been run once on the machine. Without the
submodule's venv the script stops immediately and says so, before generating anything.

It records the GPU and the torch build, generates one 80-frame sequence at 512 px with four
to five objects, converts it exactly as section 1 does, and wall-clocks the inference.
Everything is teed into `backend/data/measurements/a2b-<timestamp>.log`. **That file is what
to send back** — it carries the commands, the card and the timing in one place.

**Steps 2 and 3 have been executed as written. The environment capture and the inference have
not** — they need an NVIDIA card, and `test/inference_demo.py` is pinned to `cuda:0` in six
places.

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

The focus plane is the mean disparity under the **union** of the object masks. Until
2026-09-18 the bridge blended the mask channels by luminance instead, which dropped objects
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
