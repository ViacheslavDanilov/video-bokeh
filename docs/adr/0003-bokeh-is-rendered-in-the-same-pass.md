# Bokeh is rendered in the same pass as the frames

A sequence's bokeh is rendered by the layered renderer in the same run that renders its frames,
from the layers held in memory: `scenes.generate --bokeh` for a written dataset, the API for the
demo, and the training loader for every item. Decided on 2026-10-10, when the pipeline was
asked to go end to end, from a scene to every stream it has, optical flow included later.

This takes up the option ADR 0002 set aside, "render the bokeh inside Stage B", without dropping
what 0002 chose: the layers can still be written with `--layers`, and Stage C still renders
over written sequences.

## Considered options

- **Stage C only, over written layers.** One renderer interface for every renderer, but every
  sequence takes two runs and writes layers it may not need, and the demo waits on a separate
  step.
- **One pass that holds the whole sequence.** Simple, but 80 frames at 1024 pixels with five
  objects hold about 11 GB of layers.
- **One pass, frames rendered twice.** The focused object is drawn from the area each object
  holds over the whole clip, so no frame's bokeh can be rendered before the last frame is seen.
  The first pass writes the streams and keeps each frame's focus statistics; the second renders
  the frames again with their layers, eight at a time, and their bokeh.

## Consequences

- The layered renderer is the default source of the dataset's bokeh, as agreed after the
  2026-10-08 sync. any-to-bokeh stays a Stage C renderer for comparison.
- Stage B's warps run twice when bokeh is asked for.
- Writing bokeh needs torch, which the base install and the API's own install leave out. The
  demo then shows no bokeh pane.
- A stream added later, such as optical flow, joins the same pass.
