# The on-disk formats join the stages

The three stages — build the library, generate sequences, render bokeh — talk to each other
only through the library and sequence layouts in `docs/reference/dataset-layout.md`. That is
what lets a depth or bokeh model be swapped without touching the rest, including models that
cannot share our environment: any-to-bokeh pins Python 3.10 and `transformers==4.32.1`, and
Depth Anything 3 pins `numpy<2`. A model plugs in behind its stage's interface, in our process
when its dependencies fit our lock and as a worker process in its own environment when they do
not.

## Consequences

- A change to either layout breaks every stage on the other side of it and may cost a rebuilt
  library or a regenerated dataset. It is a decision of its own, not a detail of whichever
  change needs it.
- Containers, when they come, follow the same line: one image per environment, not one per
  model.
- Code in our own environment may still call Stage B in memory, as the API does. The rule is
  about the boundaries between environments, not about every import.
