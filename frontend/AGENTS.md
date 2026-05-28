<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.

<!-- END:nextjs-agent-rules -->

# Frontend — Agent Guide

Next.js 16, React 19, TypeScript 5, Tailwind 4. Node.js 24, pnpm. ESLint + Prettier. Root rules in `../AGENTS.md` still apply.

## pnpm gotchas

- **Local pnpm should match CI.** CI installs `pnpm@latest` via `pnpm/action-setup@v4`. As of 2026-05-28 that's pnpm 11.4.0. Local versions older than 11 may not surface CI errors. Bump local pnpm if behavior diverges.
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

## Conventions

- **Don't add files to `.next/`.** It's the build output, gitignored.
- **Prettier owns formatting.** Don't hand-format; run `pnpm format`.
- **ESLint config** is `eslint.config.mjs` (flat config, ESLint 9).
- **No emoji in code, comments, or commit messages** unless the user explicitly asks.

## Verification before claiming done

For any UI change, run `pnpm dev`, open the page in a browser, and exercise the feature path. Type-check and lint do not verify visual behavior. If you cannot test the UI in a browser, say so — don't claim success.
