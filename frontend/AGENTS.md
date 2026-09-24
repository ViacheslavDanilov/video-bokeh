<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.

<!-- END:nextjs-agent-rules -->

# Frontend — Agent Guide

Next.js 16, React 19, TypeScript 5, Tailwind 4. Node.js 24, pnpm. ESLint + Prettier. Root rules in `../AGENTS.md` still apply.

## pnpm gotchas

- **pnpm is pinned through `packageManager` in `package.json`** (currently 11.5.0), and `pnpm/action-setup@v4` in CI reads it from there with `package_json_file: frontend/package.json`. CI and a laptop therefore run the same pnpm. Bump the field rather than the local install.
- **Build-script allowlist lives in `pnpm-workspace.yaml`** under the `allowBuilds:` key (pnpm 11 schema). The old `onlyBuiltDependencies: [...]` array and the `pnpm.*` field in `package.json` are **silently ignored** by pnpm 11. Currently allowed:

  ```yaml
  allowBuilds:
    sharp: true
    unrs-resolver: true
  ```

  Both are native modules required for normal operation (sharp = Next.js image optimization; unrs-resolver = eslint-config-next resolver). New native deps with postinstall scripts will fail `pnpm install --frozen-lockfile` until added here.

- **Always use `--frozen-lockfile`** in CI-equivalent installs. If `pnpm install` wants to update the lockfile and you didn't change `package.json`, something is wrong — investigate before committing.

## Commands

| Task             | Command                          |
| ---------------- | -------------------------------- |
| Install          | `pnpm install --frozen-lockfile` |
| Dev server       | `pnpm dev`                       |
| Lint             | `pnpm lint`                      |
| Format check     | `pnpm check`                     |
| Format write     | `pnpm format`                    |
| Production build | `pnpm build`                     |
| Add dep          | `pnpm add <pkg>`                 |
| Add dev dep      | `pnpm add -D <pkg>`              |

Run from `frontend/`.

## UI components

`src/components/ui/` is shadcn/ui, built on the `radix-ui` package. The files are **copied
into the repository, not a dependency** — edit them directly, and `pnpm dlx shadcn@latest add
<name>` brings in new ones (`dlx`, never `npx`: this repo is pnpm only).

One local change so far: `slider.tsx` forwards the accessible name to the thumb, because
that is the element carrying `role="slider"`. A label left on the root names a group and the
control stays anonymous. Re-adding the component from the registry would lose that.

Everything else under `src/components/` is this project's own.

## Turbopack serves stale CSS after a theme edit

**Editing `@theme` or `:root` in `globals.css` can leave the dev server serving the previous
compiled stylesheet.** The symptom is not an error: every custom property resolves to nothing,
so popovers are transparent, slider tracks vanish, and the page looks broken in ways that
point at the components. It cost an hour once.

Check it by reading a variable rather than guessing — `getComputedStyle(document.documentElement).getPropertyValue('--popover')` empty means stale. The fix is `rm -rf .next` and restart.

## Talking to the API

`src/lib/api.ts` is the only place that knows the API exists. The base URL comes from
`NEXT_PUBLIC_API_URL` and falls back to `http://localhost:8000`; being a `NEXT_PUBLIC_`
variable it is read at build time, so a container built for one address cannot be pointed at
another without rebuilding.

**Which streams a scene has, and which of them take a colormap, come from the server's
manifest.** Do not hardcode stream names in components — a stream added to the API appears in
the interface on its own, and that is the point.

## Conventions

- **Don't add files to `.next/`.** It's the build output, gitignored.
- **Prettier owns formatting.** Don't hand-format; run `pnpm format`.
- **ESLint config** is `eslint.config.mjs` (flat config, ESLint 9).
- **No emoji in code, comments, or commit messages** unless the user explicitly asks.

## Verification before claiming done

For any UI change, run `pnpm dev`, open the page in a browser, and exercise the feature path. Type-check and lint do not verify visual behavior. If you cannot test the UI in a browser, say so — don't claim success.
