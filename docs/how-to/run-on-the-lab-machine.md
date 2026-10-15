---
type: how-to
status: active
tags: [how-to, lab-machine, runbook, depth-estimator]
related: [cli, generate-a-dataset]
---

# Run everything on the lab machine

**One command runs the whole test, and one log comes back.** It measures every depth estimator
on the machine's GPU, builds a library with each from the dev pools, generates the same
sequences from every library with their bokeh, and packs MP4s to look at.

Commands run from the repository root. The setup steps say whether they have run on an Apple
M3 Pro, and "What has not run yet" lists the rest.

---

## Set up, once per machine

1. `make setup` installs every backend extra, the frontend and the smoke test's browser. Run
   here.
2. `make images` builds the one model image, `video-bokeh-da3`, for Depth Anything 3, which
   cannot share our environment: 8 to 12 GB, with no weights in it. It needs Docker with the
   NVIDIA Container Toolkit, and ran on the RTX 5090. `da2-*` and `depth-pro` run in this
   process and need no image.
3. On a machine without Docker's NVIDIA runtime, such as the Mac,
   `scripts/setup_depth_anything_3.sh` builds the venv the `da3-*` depth estimators run in
   instead. Run here. [cli](../reference/cli.md), section "Depth Anything 3's own environment",
   says what it leaves out.
4. `uv run --directory backend --extra library python -m video_bokeh.library.check` says
   whether each depth estimator can run on the machine, without downloading anything. Run
   here.

---

## Run

```bash
scripts/lab_run.sh
```

It does four things, in order:

1. **The device check with `--measure`**, every depth estimator in a process of its own. This
   downloads every checkpoint that is not cached: 5.97 GiB from scratch.
2. **One library per depth estimator** from `backend/data/magick_dev` and
   `backend/data/bg-20k_dev`, with no class filter, so each holds all 30 foregrounds and all 30
   backgrounds. It goes through `make libraries`, so a library that exists is skipped.
3. **The same sequences from every library, with their bokeh**: 4 of 80 frames at 512 px,
   seeds 0 to 3, through `scenes.generate --bokeh`. Same seeds and same assets give the same
   scenes, so only the disparity differs between libraries.
4. **MP4s** of each sequence's frames, disparity and bokeh, next to the frames.

**On Linux with Docker's NVIDIA runtime, Depth Anything 3 runs in its own image.** The other
depth models run in this process. The runner is `docker` when this user can reach a daemon
that has that runtime, and `local` otherwise. A shell opened before joining the `docker`
group gets `local`. The log's header says which ran, and `VIDEO_BOKEH_RUNNER` picks one
outright. Under `docker` the run checks for the image before anything long starts, and names
`make images` when it is missing. On the RTX 5090 on 2026-10-07, with `COUNT=2 FRAMES=24`,
any-to-bokeh still rendering the bokeh in a step of its own and each depth model in an image
of its own, the whole run took 15 minutes under `docker`: 62 to 90 s per library, and the
device check's peak memory matched the venv run's for every estimator.

**One estimator failing does not stop the others.** A library that does not build is named in
the summary, its estimator gets no sequences, and the rest go on. The run then exits 1. The
same holds for a set of sequences.

**A re-run picks up where the last one stopped.** A library that exists is not made again.
Sequences are made again, with their bokeh, when `COUNT`, `FRAMES` or `SIZE` changed or the
last set did not finish. To redo an estimator from scratch, delete both
`backend/data/lab/libraries/<estimator>` and `backend/data/lab/sequences/<estimator>`.

**Send back the log** it names on its first and its last line,
`backend/data/measurements/lab-<time>.log`. It carries the commands, the GPU, the torch and
CUDA versions of each environment the run uses, the host's and each image's or venv's, and a
summary with a timing and an outcome for each step that ran: the device check, and each
library and set of sequences. A library that exists still gets a line, from the make target
that skips it. Skipped sequences get none. The summary is printed even when a step fails.

Run on the Apple M3 Pro with one estimator:

```bash
scripts/lab_run.sh da2-small
```

```
===== summary =====
device check                              7 s  ok
library, da2-small                        0 s  ok
sequences, da2-small                     16 s  ok
```

The library had been built by an earlier run, in 26 s, and held 30 foregrounds and 30
backgrounds. A second run skipped the library and the sequences. A run with a second estimator
whose load fails named that estimator's library as failed, went on with `da2-small`, and
exited 1.

| knob | default | meaning |
|---|---|---|
| estimators, as arguments | every registered one | such as `scripts/lab_run.sh da2-large depth-pro` |
| `COUNT` | `4` | sequences per estimator |
| `FRAMES` | `80` | frames per sequence |
| `SIZE` | `512` | frame side |

---

## Look at the result

The libraries land in `backend/data/lab/libraries/<estimator>`, which is the
layout the page's picker reads:

```bash
make api LIBRARY=backend/data/lab/libraries
make web
```

The script's own sequences are not the page's: the page generates its own and caches them under
`backend/data/sequences/`. Each comes with its bokeh, rendered by the layered renderer in the
same request, because `make setup` installs torch.

The script's own bokeh is in the MP4s from step 4: each sequence under
`backend/data/lab/sequences/<estimator>/sequences/<id>/` holds `all_in_focus.mp4`,
`disparity.mp4` and `bokeh.mp4`.

---

## What has not run yet

- The script with `--bokeh` in step 3. Its earlier shape, with any-to-bokeh rendering the
  bokeh in a step of its own, ran on an RTX 5090 on 2026-10-07.
- The script over every depth estimator. Only `da2-small` has gone through it. Every other
  checkpoint was already cached on the Apple machine but `da3-metric-large`, 1.2 GiB, which
  stays off it to spare its memory.
- `da3-metric-large` anywhere, for that reason.
- The CUDA paths of the device check, its VRAM figures and its peak memory.
