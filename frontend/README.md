# Video Bokeh Frontend

The scene browser: set the parameters, generate a scene from the mounted asset library, and
compare its streams side by side.

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

- **Parameters** — seed, frames, size, and the range of objects a scene may contain. The seed
  picks a count in that range, so the same five numbers always name the same scene.
- **Generate** — one call, and it blocks while it works: about 7 seconds for 80 frames at 512
  px. Asking twice for the same scene returns it in milliseconds, because the scene id is a
  hash and the directory on disk is the cache.
- **Compare** — up to three panes, each showing any stream, all driven by one transport so
  the frames line up. Disparity can be shown in Spectral or grey.

Bokeh is not here. It runs on a GPU in its own container, which does not exist yet.

## Conventions

`src/components/ui/` is shadcn/ui, copied into the repository rather than installed. Anything
else under `src/components/` is ours. `src/lib/api.ts` is the only file that knows the API
exists.

Which streams a scene has comes from the server, not from constants in the components, so a
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
