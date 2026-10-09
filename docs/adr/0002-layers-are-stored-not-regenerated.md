# The layers are stored, not regenerated

A layer-wise bokeh renderer needs what each frame was composited from: the whole background
and each whole object, with its own disparity. Stage B writes these as an optional `layers/`
stream beside the sequence's other streams, when `scenes.generate --layers` asks for it.
Stage C reads them from there. It does not run Stage B again to get them. Decided on
2026-10-10, for the layer-wise renderer agreed after the 2026-10-08 sync.

## Considered options

- **Regenerate the layers in Stage C from the seed and the library.** No extra disk. But Stage
  C would read the library, which it never has, and the dataset's `manifest.csv` records the
  seed and the object count, not the library's id or the sampling configuration. A rebuilt
  library, or any change to the compositor since the dataset was written, would give bokeh that
  silently no longer matches the stored frames.
- **Render the bokeh inside Stage B and never store the layers.** The least code and no extra
  disk, but the renderer would bypass Stage C's `--renderer` interface, a new strength would
  mean regenerating every sequence, and nobody outside the process could get the layers.
- **Store them, only when asked.** The dataset grows, so it is opt-in. Stage C stays a reader of
  the sequence layout, as ADR 0001 has it.

## Consequences

- `docs/reference/dataset-layout.md` describes `layers/`. Nothing that reads a sequence
  without it changes, and no existing dataset has to be regenerated.
- A dataset written with `--layers` is about twice the size: 3.77 MiB per 1024-pixel frame
  against 1.75 MiB, measured on 5 sequences of 80 frames.
- The layers are a deliverable of their own. Anyone can render bokeh their way from exactly the
  frames the dataset holds, and a renderer of theirs plugs into Stage C by reading the same files.
- The training loader never writes anything, so it keeps the layers in memory and is not
  affected.
