# Video Bokeh Frontend

The sequence browser: pick a depth estimator, set the parameters, generate a sequence from that
estimator's library, and compare its streams side by side.

Next.js 16, React 19, Tailwind 4, shadcn/ui on Radix primitives. **pnpm only** — never npm or
yarn.

## Run it

The page is useless without the API, and the API is useless without a library, so start from
the back:

```bash
# 1. one terminal, from backend/
VIDEO_BOKEH_LIBRARY=data/library_dev uv run uvicorn video_bokeh.api.main:app --port 8000

# 2. another terminal, from frontend/
pnpm install --frozen-lockfile
pnpm dev
```

Then open <http://localhost:3000>.

If `backend/data/library_dev` does not exist yet, build it once — `backend/README.md` has the
recipe, and a fresh clone has everything it needs.

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
- **Generate** — one call, and it blocks while it works: on an Apple M3 Pro at the page's
  defaults, 80 frames at 512 px with four to five objects, 7 to 11 seconds, and 16 to 21 with
  the bokeh. Asking twice for the same sequence returns it in milliseconds, because the
  sequence id is a hash and the directory on disk is the cache.
- **Compare** — up to six panes, each showing any stream, all driven by one transport so
  the frames line up. Disparity can be shown in Spectral or grey. The transport plays every pane
  at 0.25×, 0.5×, 1× or 2×, and the speed stays across a stream switch and the next sequence.
  The panes fit the window together, at the largest size that allows, in rows of even length.
  Where that size would be under 200 px, as on a phone or in a low window, they are at least
  280 px wide instead, and the page scrolls with the transport held at the bottom.
  The button beside the title folds the parameters away to give the panes their width, and
  the page remembers it.

**Optical flow comes with each sequence**, coloured as optical-flow papers colour it: the hue
is the direction, rightward red, and white is still. The wheel under its pane is the legend.

**Bokeh comes with each sequence** when the API runs with torch, which `make setup` installs:
the API renders it in the same request with the layered renderer, and a pane opens for it.
Without torch, Stage C can still add any-to-bokeh's on a machine with an NVIDIA card: run
`make bokeh` from the repository root and generate the same sequence again. The frames slider
starts at 16, because any-to-bokeh needs 13 frames or more.

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
