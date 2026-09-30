# The on-disk formats join the stages

The pipeline has three stages — build the library, generate sequences, render bokeh — and each
must take any model: the paper's claim is that Depth Anything or any-to-bokeh can be swapped
without touching the rest. Some models cannot share our environment at all: any-to-bokeh pins
Python 3.10 and `transformers==4.32.1`, and Depth Anything 3 pins `numpy<2`. So the stages
talk to each other only through the library and sequence layouts in
`docs/reference/dataset-layout.md`, never through shared objects in memory. A model plugs in
behind its stage's interface, in our process when its dependencies fit our lock and as a
worker process in its own environment when they do not.

## Consequences

- A change to either layout breaks every stage on the other side of it, and may cost a
  rebuilt library or a regenerated dataset. It is a decision of its own, not a detail of
  whichever change needs it.
- Containers follow the same line: one image per environment, not one per model.
- The on-the-fly loader is the one reader that imports Stage B in memory. It lives in our
  environment, so it needs no format between them.
