---
type: how-to
status: active
tags: [how-to, lab-machine, runbook, depth-estimator, any-to-bokeh]
related: [cli, generate-a-dataset, run-any-to-bokeh-inference]
---

# Run everything on the lab machine

**One command runs the whole test, and one log comes back.** It measures every depth estimator
on the machine's GPU, builds a library with each from the dev pools, generates the same
sequences from every library, renders their bokeh and packs MP4s to look at.

Commands run from the repository root. Everything that can run without an NVIDIA card has run
on an Apple M3 Pro, as marked; the any-to-bokeh setup and Stage C have not run anywhere yet.

---

## Set up, once per machine

1. `make setup` installs every backend extra, the frontend and the smoke test's browser. Run
   here.
2. `scripts/setup_third_party.sh` checks out any-to-bokeh, builds its Python 3.10 venv and
   downloads its checkpoints and the Stable Video Diffusion base model, about 10 GB. It needs
   an NVIDIA card and has not run yet. [[run-any-to-bokeh-inference]] has the details.
3. `scripts/setup_depth_anything_3.sh` builds the venv the `da3-*` depth estimators run in.
   Run here. [[cli]], section "Depth Anything 3's own environment", says what it leaves out.
4. `uv run --directory backend --extra library python -m video_bokeh.library.check` says
   whether each depth estimator can run on the machine, without downloading anything. Run
   here.

---

## Run

```bash
scripts/lab_run.sh
```

It does five things, in order. Every step but the first stops the run when it fails:

1. **The device check with `--measure`**, every depth estimator in a process of its own. This
   downloads every checkpoint that is not cached: 5.97 GiB from scratch. A model that fails to
   measure does not stop the run.
2. **One library per depth estimator** from `backend/data/magick_dev` and
   `backend/data/bg-20k_dev`, with no class filter, so each holds all 30 foregrounds and all 30
   backgrounds. It goes through `make libraries`, so a library that exists is skipped.
3. **The same sequences from every library**: 4 of 80 frames at 512 px, seeds 0 to 3. Same
   seeds and same assets give the same scenes, so only the disparity differs between libraries.
4. **Bokeh, Stage C**, through any-to-bokeh, into each sequence's `bokeh/`.
5. **MP4s** of each sequence's frames, disparity and bokeh, next to the frames.

A re-run picks up where the last one stopped: libraries, sequences and bokeh that exist are not
made again.

**Send back the log** it names on its last line, `backend/data/measurements/lab-<time>.log`.
It carries the commands, the GPU, the versions and a timing for every step.

Measured on the Apple M3 Pro with one estimator and without Stage C, the part of the run that
can go there:

```bash
scripts/lab_run.sh --no-render da2-small
```

```
===== summary =====
device check                                      5 s
libraries                                        26 s
sequences, da2-small                             16 s
```

52 s in all. The library held 30 foregrounds and 30 backgrounds. A second run skipped the
library and the sequences.

| knob | default | meaning |
|---|---|---|
| estimators, as arguments | every registered one | e.g. `scripts/lab_run.sh da2-large depth-pro` |
| `--no-render` | off | stop before Stage C, for a machine with no NVIDIA card |
| `COUNT` | `4` | sequences per estimator |
| `FRAMES` | `80` | frames per sequence; Stage C refuses 12 or fewer |
| `SIZE` | `512` | frame side; any-to-bokeh renders at 1024×576 whatever it is given |

---

## Look at the result

The libraries land in `backend/data/lab/libraries/`, one per depth estimator, which is the
layout the page's picker reads:

```bash
make api LIBRARY=backend/data/lab/libraries
make web
```

The page does not show bokeh yet. The MP4s from step 5 do: each sequence under
`backend/data/lab/sequences/<estimator>/sequences/<id>/` holds `all_in_focus.mp4`,
`disparity.mp4` and `bokeh.mp4`.

---

## What has not run yet

- `scripts/setup_third_party.sh`, Stage C and therefore steps 4 and 5's bokeh: they need the
  NVIDIA card.
- `da3-metric-large`: not downloaded on the Apple machine, to spare its memory.
- The CUDA paths of the device check, its VRAM figures and its peak memory.
