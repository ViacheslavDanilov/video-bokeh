# The on-disk formats join the stages

The three stages — build the library, generate sequences, render bokeh — talk to each other
only through the library and sequence layouts in `docs/reference/dataset-layout.md`. That is
what lets a depth estimator or bokeh renderer be swapped without touching the rest, including
models that cannot share our environment: any-to-bokeh pins Python 3.10 and
`transformers==4.32.1`, and Depth Anything 3 pins `numpy<2`. A model plugs in behind its
stage's interface, in our process when its dependencies fit our lock and as a worker process in
its own environment when they do not.

## Considered options

Settled after the 2026-09-30 sync; [[meetings/2026-09-30-contributions-and-roadmap]] has both
the layout drawn on the call and the architecture discussed after it.

- **One environment for every model.** Impossible: any-to-bokeh's pins and Depth Anything 3's
  `numpy<2` cannot share a lock with each other or with ours.
- **Stages that call each other over HTTP, one service each.** The training loader would then
  need a running service to draw a batch. It imports Stage B in the training process instead,
  and the stages meet only in files, which any of them can write or read on any machine.
- **The containers drawn on the call: depth estimation together with sequence generation, and
  any-to-bokeh apart.** That joins Stage A, which needs torch and a depth model, to Stage B,
  which needs neither; the API image installs Stage B alone.
- **One image per model.** One per environment instead: a flag picks the model inside it, as
  the depth registry does, and a model gets an environment of its own only when its
  dependencies clash.

## Consequences

- A change to either layout breaks every stage on the other side of it and may cost a rebuilt
  library or a regenerated dataset. It is a decision of its own, not a detail of whichever
  change needs it.
- Containers, when they come, follow the same line: one image per environment, not one per
  model.
- Code in our own environment may still call Stage B in memory, as the API does. The rule is
  about the boundaries between environments, not about every import.
