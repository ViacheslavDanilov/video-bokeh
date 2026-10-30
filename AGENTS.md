# Video Bokeh: Agent Guide

Depth-aware synthetic bokeh pipeline for video. FastAPI backend (Python 3.13, `uv`), Next.js frontend (Node 24, `pnpm`). Two stacks, two toolchains: read the area-specific guide before touching code:

- `backend/AGENTS.md`: Python, uv, ruff, ty, pytest
- `frontend/AGENTS.md`: Next.js (non-standard), pnpm 11, eslint, prettier

## Language

**American English everywhere in the repository:** code, names, comments, UI text, docs, commit
messages and pull requests. Color, center, behavior, gray, normalize, labeled, judgment. Three
exceptions keep their spelling: quoted names and titles; strings that reach outside the
repository, such as the `grey` colormap id the API's URLs and cached files use, or the CLIP
prompts the stored predictions were made with; and vendored text, the skills
`.claude/skills/VENDORED.md` lists, which stays as upstream wrote it.

No emoji in code, comments or commit messages unless the user asks; the READMEs may use them.
No em dash (U+2014) in anything written for the repository: use a colon, a comma or
parentheses.

## Commit messages

Conventional Commits format:

```
type: short imperative description

Optional body explaining why the change was needed, wrapped at ~72 columns.
```

- Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `perf`, `ci`, `build`
- Scope is optional; omit the parentheses when there is no scope
- Subject: imperative mood ("add", not "added"), lower case after the colon, no trailing period, 72 characters or fewer
- One logical change per commit; don't bundle unrelated edits. Pull requests are squash-merged, and GitHub lists these subjects in the squash body, so they are what a reader sees when unpacking a merged pull request
- Body explains *why*, not *what*. The diff already shows what changed
- No trailers other than a genuine `Co-Authored-By` for a human collaborator
- Examples in `git log`

## Pull requests

Title: `Short imperative description`. No `type:` prefix, capitalized, no trailing period. It summarizes the whole pull request, so it need not repeat any single commit subject. Body: three sections, in this order, and nothing else.

```markdown
## What

- one bullet per change a reviewer needs to notice

## Why

The problem this solves, in one or two sentences. Not a restatement of What.

## Verified

- `uv run pre-commit run --all-files`: passes
- `cd backend && uv run pytest`: 92 passed
- measurements, screenshots, or manual checks, with actual numbers
```

- Merging squashes, and GitHub appends `(#NN)` to the title, so the title becomes the commit subject on `main` (see `git log`). Keep it to about 65 characters so the result still fits 72
- `What` lists changes, not files. The diff already shows the files
- `Why` explains the problem, not the solution
- `Verified` records what was actually run and what it printed. Numbers are measured, never estimated. If something was not verified, leave it out rather than implying it passed
- Pre-existing test failures belong in `Verified`, named as pre-existing, with the baseline they were compared against
- Drop a section only when it would be empty. A docs-only change may have nothing under `Verified` beyond the pre-commit run
- No screenshots of text, no checklists of process steps
- Assign every pull request to Viacheslav Danilov (`--assignee ViacheslavDanilov`) and label it by type: one label for each Conventional Commit type among its commits. `feat` is `enhancement`, `fix` is `bug`, `docs` is `documentation`, and `refactor`, `perf`, `test`, `ci`, `build` and `chore` carry their own names. `duplicate`, `invalid` and `wontfix` are for a pull request closed without merging

## Git workflow

1. **Never commit directly to `main`.** Branch, commit there, then open a pull request.
2. **Push feature branches, open pull requests and edit their title and body without asking. Merging into `main` is the user's decision.** They may hand a batch of pull requests over explicitly; the agent then merges each one only once CI is green on its current head and a review that covers every commit of its own says it is ready to merge. An update from `main` that adds nothing of its own needs no new review; one that resolves a conflict or carries any other edit does. Nothing enforces either rule mechanically.
3. **Never `--force-push` to `main`.** Force-push to feature branches only after the user authorizes it.
4. **Pre-commit runs on every commit.** Config is `.pre-commit-config.yaml`. If hooks fail, fix the underlying issue. Don't use `--no-verify`.
5. **Don't amend pushed commits** without the user's go-ahead (force-push territory).
6. Commit and pull request text follows the notation in "Commit messages" and "Pull requests" above.

## Model routing

Work goes to a model by its kind, the paths it touches and the review pass, never by a guess at how hard it is. The main session orchestrates: it talks to the user, writes `BRIEF.md` and `STATUS.md`, and commits. The agents are in `.claude/agents/`.

| Work | Worker | Model, effort |
|---|---|---|
| Dialog, criteria, small edits, commits | the main session | Sonnet, high |
| A plan for a structural change: the dataset contract, the API, build, CI, Docker, `.claude/` | `planner` | Opus, xhigh |
| Taste: the page under `frontend/src/`, prose under `docs/`, the READMEs, the demo video | `crafter` | Sonnet, xhigh |
| Code with a check that passes or fails: backend code and tests, scripts, `comparison/`, benchmarks | Codex, `workspace-write` | gpt-6.1-sol, xhigh |
| Review, first or delta pass; `xhigh` when it touches a high-risk path from `bokeh-review` step 2 | `reviewer` | Opus, high |
| Review, a trivial pass (≤ 15 delta lines, ≤ 2 files, no high-risk path) or comment-only; the fix loop; QA | general-purpose agent | Sonnet, high |
| Review lenses #2 (bugs) and #7 (second model) | Codex, `read-only` | gpt-6.1-sol, xhigh |
| Commands, searches, counts | `runner` | Haiku, high |

- **A small edit stays in the main session.** Every delegated prompt carries the limits in `.claude/skills/shared/bokeh-conventions.md`, section **Delegating**.
- **Codex never decides how something looks or reads, and never commits.** The orchestrator reads its diff, runs the checks and commits. If Codex is missing or refuses the model, its code goes to the orchestrator, lens #2 to `/code-review`, and lens #7 is recorded as not run.
- **One session, one task.** Task sessions start on Sonnet; `/bokeh-review` and process or architecture talks start on Opus.

```bash
codex exec -m gpt-6.1-sol -c model_reasoning_effort=xhigh -s read-only -C <worktree> -o <report.md> "<prompt>" < /dev/null
```

Use `-s workspace-write` when Codex implements. Keep the `< /dev/null`: without it, a run in the background reads stdin and waits for input that never comes.

**`BRIEF.md` and `STATUS.md`** are gitignored and belong to one task. The brief holds the goal, the acceptance criteria the user confirmed word for word, a link to the spec when there is one, what is out of scope, how to verify, and the limits; it is written once, when the user confirms the criteria, and no worker edits it. The status holds what is done with commit SHAs, the next step, check results with numbers and questions for the user; it is updated after every step, by the orchestrator for a read-only worker. Pass both by absolute path to a worker in another worktree. A new session reads both and continues; another task's unfinished brief is closed first. Delete both when the task ends.

## Secrets and data

- `.env` files are gitignored. Never commit them or paste their contents into chat logs. `backend/.env.example` lists the backend's variables and the root `.env.example` those of `docker compose`; nothing loads either automatically.
- **`backend/data/` is mostly gitignored, with deliberate exceptions:** the small development pools, MAGICK's metadata and CLIP predictions, and the empty folders the pool and library commands fill. Cloning is then enough to run the pipeline. The comments in `.gitignore` say what is tracked and why.
- Everything a run generates under `backend/data/` stays ignored. Adding a generated tree to git is wrong; adding a source asset the dev recipes depend on is not.

## Don't touch

- `backend/data/`: mostly gitignored, with the tracked exception described under "Secrets and data".
- `frontend/.next/`, `frontend/node_modules/`, `.venv/`, `.mypy_cache/`, `.ruff_cache/`, `.pytest_cache/`: generated.

## Verification before claiming done

Run the actual check, don't assume. Type-checking and tests verify correctness of code, not of features. For UI changes, also start the dev server and confirm the behavior in a browser.

| Layer | Command |
|---|---|
| Pre-commit (all hooks) | `uv run pre-commit run --all-files` |
| Backend tests | `cd backend && uv run pytest` |
| Backend types | `cd backend && uv run ty check src/` |
| Backend lint | `cd backend && uv run ruff check src/` |
| Frontend lint | `cd frontend && pnpm lint` |
| Frontend format check | `cd frontend && pnpm check` |
| Frontend build | `cd frontend && pnpm build` |
| Frontend browser smoke | `cd frontend && pnpm e2e` |
| Docker build | `docker build -t video-bokeh-api -f backend/Dockerfile .` / `docker build -t video-bokeh-web ./frontend` |
| Model image (NVIDIA only) | `make images` |

`make check` runs the pre-commit, backend test, frontend lint and format check rows in one go, and `make help` lists the other shortcuts in the root `Makefile`. CI mirrors these in `.github/workflows/ci.yaml`. If a step passes locally but fails in CI, suspect tool-version drift first (e.g., pnpm `latest` may be newer than your local).

## Where things live

- `backend/src/video_bokeh/`: FastAPI runtime and dataset pipeline (run scripts from `backend/`)
- `frontend/src/`: Next.js app
- `docs/`: documentation and the Obsidian vault root (see `docs/README.md`). `explanation/`, `how-to/`, `reference/` and `adr/` are tracked; `meetings/`, `reports/`, `specs/`, `plans/`, `templates/` and `attachments/` are local-only. `docs/STYLE.md` has the writing conventions.
- `scripts/`: repo-level setup, analysis and review scripts (`setup_depth_anything_3.sh`, `analyze_magick_distribution.py`, `check_prose.py`). `scripts/README.md` describes each
- `comparison/`: runs other published bokeh renderers on our sequences and scores them against ours. Their code is cloned into an ignored folder, never tracked. `comparison/README.md` has the recipe
- `.assets/demo/`: the README's demo video, `video-bokeh-demo.mp4`, its poster, and everything that makes it: the recording scripts, the HyperFrames project and its sound, with the sound's credits. The README plays a copy uploaded to GitHub. `.assets/demo/README.md` has the recipe
- `CONTEXT.md`: the project glossary. Grilling adds a term to it once the term is settled
- `.claude/skills/`: the agent lifecycle (`/bokeh-meeting`, `/bokeh-task`, `/bokeh-review`, and the skills they call). `docs/how-to/agent-lifecycle.md` shows how to drive it

## Working principles

Adapted from [Andrej Karpathy's observations on LLM coding pitfalls](https://github.com/multica-ai/andrej-karpathy-skills) (MIT licensed).

1. **Think before coding.** State your assumptions. When a request reads two ways, or something is unclear, ask rather than pick silently. Say so when a simpler approach exists.
2. **Simplicity first.** The minimum code that solves the problem: no features, abstractions, options or error handling nobody asked for.
3. **Surgical changes.** Every changed line traces to the request. Match the existing style, don't improve adjacent code, and mention unrelated dead code rather than delete it. Remove only what your own change made unused.
4. **Goal-driven execution.** Turn a task into a check that can fail ("fix the bug" becomes "a test reproduces it, then passes"), and report what you verified, not what you expect.
