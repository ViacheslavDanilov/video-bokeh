# Video Bokeh Frontend

The sequence browser: pick a depth estimator, set the parameters, generate a sequence from that
estimator's library, and compare its streams side by side.

Next.js 16, React 19, Tailwind 4, shadcn/ui on Radix primitives. **pnpm only** — never npm or
yarn.

## Run it

The page is useless without the API, and the API is useless without a library, so start from
the back:

```bash
# 1. one terminal, from the repository root
make api

# 2. another terminal, from frontend/
pnpm install --frozen-lockfile
pnpm dev
```

Then open <http://localhost:3000>.

It serves every dev-pool library under `backend/data/library_dev/<estimator>`. Full-pool
libraries live in `backend/data/library/<estimator>`. If there is none yet, build the dev
libraries once with `make libraries` from the repository root. The root `README.md` has
the details, and a fresh clone has everything it needs.

The API address comes from `NEXT_PUBLIC_API_URL` and defaults to `http://localhost:8000`. It
is baked in at build time, so a container built for one address cannot be pointed at another
without rebuilding.

## What the page does

- **Depth estimator** — which library the sequence comes from, one library per depth
  estimator. The same seed through two estimators gives the same objects on the same paths;
  only the disparity differs. The list is read again whenever the page regains focus, so a
  library built while it is open shows without a reload.
- **Parameters** — seed, frames, size, and the range of objects a sequence may contain. The seed
  picks a count in that range, so the same five numbers from the same library always name the
  same sequence.
- **Generate** — one call, with one bar for the whole of it. The API names its steps first:
  choosing the trajectories, rendering the frames, writing them, and rendering the bokeh. The
  bar fills by their counts, beside the step under way, and stays full where it filled for
  half a second before the sequence is shown. On an Apple M3 Pro at the page's defaults, 80
  frames at 512 px with two to four objects, it took 6.1 to 7.3 seconds on 2026-10-11, seeds
  0 to 2, and 12.0 to 15.4 with the bokeh. Asking twice for the same sequence returns it in
  milliseconds, because the sequence id is a hash and the directory on disk is the cache. Each
  pane says it is preparing its video until the API starts sending it, since the API encodes a
  stream the first time it is asked for, and says so if the video fails to load.
- **What is on screen** — a line above the panes names the sequence's library, seed, object
  count, frame count and size, says when it came from the cache, and gives its id with a copy
  button. The header names the library picked; its `id` is a hash of the asset list, the depth
  estimator and the asset size, which every cached sequence is keyed on.
- **Compare** — up to six panes, each showing any stream, all driven by one transport so
  the frames line up. The disparity pane picks its colormap under the video, among those the
  API lists: Spectral, near red to far violet, by default, or gray, near white to far black.
  The legend beside the picker follows the map on screen. The transport
  plays every pane at 0.25×, 0.5×, 1× or 2×, and the speed stays across a stream switch and
  the next sequence.
  Dragging the position slider moves its thumb smoothly. Every pane shows the frame nearest
  to the thumb at once, drawn from frames decoded when its video loaded. The arrow keys step
  one frame. Page Up, Page Down and Shift with an arrow step ten.
  The panes fit the window together, at the largest size that allows, in rows of even length.
  Where that size would be under 200 px, as on a phone or in a low window, they are at least
  280 px wide instead, and the page scrolls with the transport held at the bottom.
  The button beside the title folds the parameters away to give the panes their width, and
  the page remembers it.
  "Add pane" adds a stream not on screen yet; once every stream is, it is disabled and reads
  "All streams shown". A repeat comes from switching an open pane's stream. The occlusion
  mask opens no pane of its own, so a sequence opens with the panes it always did; "Add
  pane" or a pane's stream picker shows it.
- **Arrange** — drag a pane by the grip in its header to a place between panes, where a
  line shows where it will go, or focus the grip and press the left or right arrow;
  playback goes on in step.

**Optical flow comes with each sequence**, colored as optical-flow papers color it: the hue
is the direction, rightward red, and white is still. The wheel under its pane is the legend.
The Direction dropdown under its pane switches it to the backward flow, colored the same
way, where each pixel came from in the previous frame, so a pixel moving right shows the
opposite color. The caption beside the wheel is one short line, and hovering or focusing it
shows how to read the direction on screen. The choice stays on the pane for the next
sequence.

**So does the occlusion mask**, white where a pixel's surface is hidden in the next frame,
on black, as it is stored. The Overlay button under its pane draws it instead as cyan on the
all-in-focus frames, shown in gray so the cyan stands out.

**Bokeh comes with each sequence** when the API runs with torch, which `make setup` installs:
the API renders it in the same request with the layered renderer, and a pane opens for it.
Without torch, the page shows no bokeh pane.

## Conventions

`src/components/ui/` is shadcn/ui, copied into the repository rather than installed. Anything
else under `src/components/` is ours. `src/lib/api.ts` is the only file that knows the API
exists.

Which streams a sequence has comes from the server, not from constants in the components, so a
stream added to the API shows up here on its own.

`AGENTS.md` in this directory has the rest: pnpm pinning, the build-script allowlist, and why
the Next.js docs in `node_modules` beat the ones you remember.

## Commands

| Task             | Command                          |
| ---------------- | -------------------------------- |
| Install          | `pnpm install --frozen-lockfile` |
| Dev server       | `pnpm dev`                       |
| Lint             | `pnpm lint`                      |
| Format check     | `pnpm check`                     |
| Format write     | `pnpm format`                    |
| Production build | `pnpm build`                     |
