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

Commands run from the repository root. The setup steps say whether they have run on an Apple
M3 Pro, and "What has not run yet" lists the rest. The any-to-bokeh setup and Stage C have not
run anywhere yet.

---

## Set up, once per machine

1. `make setup` installs every backend extra, the frontend and the smoke test's browser. Run
   here.
2. `scripts/setup_third_party.sh` checks out any-to-bokeh, builds its Python 3.10 venv and
   downloads its checkpoints and the Stable Video Diffusion base model, 4.2 GiB of fp16
   weights by the Hub's metadata on 2026-10-02. It needs an NVIDIA card and has not run yet.
   [[run-any-to-bokeh-inference]] has the details.
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

It does five things, in order:

1. **The device check with `--measure`**, every depth estimator in a process of its own. This
   downloads every checkpoint that is not cached: 5.97 GiB from scratch.
2. **One library per depth estimator** from `backend/data/magick_dev` and
   `backend/data/bg-20k_dev`, with no class filter, so each holds all 30 foregrounds and all 30
   backgrounds. It goes through `make libraries`, so a library that exists is skipped.
3. **The same sequences from every library**: 4 of 80 frames at 512 px, seeds 0 to 3. Same
   seeds and same assets give the same scenes, so only the disparity differs between libraries.
4. **Bokeh, Stage C**, through any-to-bokeh, into each sequence's `bokeh/`.
5. **MP4s** of each sequence's frames, disparity and bokeh, next to the frames.

**One estimator failing does not stop the others.** A library that does not build is named in
the summary, its estimator gets no sequences, and the rest go on. The run then exits 1. The
same holds for a set of sequences and for Stage C.

**A re-run picks up where the last one stopped.** A library or a bokeh stream that exists is
not made again. Sequences are made again, with their bokeh, when `COUNT`, `FRAMES` or `SIZE`
changed or the last set did not finish. To redo an estimator from scratch, delete both
`backend/data/lab/libraries/<estimator>` and `backend/data/lab/sequences/<estimator>`.

**Send back the log** it names on its first and its last line,
`backend/data/measurements/lab-<time>.log`. It carries the commands, the GPU, the torch and CUDA
versions of all three environments, and a summary with a timing and an outcome for each step that
ran: the device check, and each library, set of sequences and bokeh render. A library that
exists still gets a line, from the make target that skips it. Skipped sequences and bokeh get
none. The summary is printed even when a step fails.

Run on the Apple M3 Pro with one estimator and without Stage C, the part of the run that can go
there:

```bash
scripts/lab_run.sh --no-render da2-small
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
| `--no-render` | off | stop before Stage C, for a machine with no NVIDIA card |
| `COUNT` | `4` | sequences per estimator |
| `FRAMES` | `80` | frames per sequence. Stage C refuses 12 or fewer |
| `SIZE` | `512` | frame side. any-to-bokeh renders at 1024×576 whatever it is given |

---

## Look at the result

The libraries land in `backend/data/lab/libraries/`, one per depth estimator, which is the
layout the page's picker reads:

```bash
make api LIBRARY=backend/data/lab/libraries
make web
```

The script's own sequences are not the page's: the page generates its own and caches them under
`backend/data/sequences/`. To see bokeh in the page:

1. Pick a depth estimator and press Generate.
2. In another terminal, `make bokeh` renders every sequence the page has made that has no bokeh
   yet. It leaves out any of 12 frames or fewer, and says so.
3. Press Generate again with the same settings. The cached sequence now lists its bokeh, and a
   pane opens for it.

The script's own bokeh is in the MP4s from step 5: each sequence under
`backend/data/lab/sequences/<estimator>/sequences/<id>/` holds `all_in_focus.mp4`,
`disparity.mp4` and `bokeh.mp4`.

---

## What has not run yet

- `scripts/setup_third_party.sh`, Stage C and therefore steps 4 and 5's bokeh, and `make bokeh`
  with the real any-to-bokeh: they need the NVIDIA card. `make bokeh` has run here against a
  stand-in for any-to-bokeh, and the API served the stream it wrote.
- The script over every depth estimator. Only `da2-small` has gone through it. Every other
  checkpoint was already cached on the Apple machine but `da3-metric-large`, 1.2 GiB, which
  stays off it to spare its memory.
- `da3-metric-large` anywhere, for that reason.
- The CUDA paths of the device check, its VRAM figures and its peak memory.
