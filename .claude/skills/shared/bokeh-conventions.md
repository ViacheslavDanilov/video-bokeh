# Video Bokeh agent conventions

Shared by `bokeh-meeting`, `bokeh-task` and `bokeh-review`. Read this before publishing
anything. It is deliberately thin: this repo already ships an agent guide, and duplicating
its rules here would only let the two drift apart.

## Sources of truth

| Topic | Canonical file |
|---|---|
| Commits, pull requests, authorship, git workflow, verification table | root `AGENTS.md` |
| Python, uv, ruff, ty, pytest, submodules | `backend/AGENTS.md` |
| Next.js, pnpm, eslint, prettier | `frontend/AGENTS.md` |
| Vault layout, naming, wikilinks, workflow | `docs/README.md` |
| Prose style for anything under `docs/` | `docs/STYLE.md` |

If this file and those disagree, **they win and this file gets fixed.** Never restate a
commit or PR rule here — point at `AGENTS.md` instead.

## Language

- **Chat with the user: Russian.** Checkpoints, questions, hand-offs, verdicts.
- **Everything written down: English.** Commits, branches, PR text, GitHub reviews, code,
  docs, vault notes, plans and specs.

Never mix the two inside one artifact.

## Vault map

`docs/` is the Obsidian vault root. Two halves, and the split matters because half of it is
gitignored:

| Path | In git | Used by these skills for |
|---|---|---|
| `docs/explanation/`, `docs/how-to/`, `docs/reference/` | **yes** | durable shared knowledge — a change here is a normal PR |
| `docs/meetings/`, `docs/meetings/transcripts/` | no | meeting input; written by `bokeh-meeting` |
| `docs/specs/`, `docs/plans/` | no | design and implementation plans from the feature route |
| `docs/reports/` | no | findings, measurements, investigation outcomes |
| `docs/templates/` | no | Templater scaffolds — read them, do not edit them |

**Never `git add` anything under the gitignored half.** A file there is a working note, not
a deliverable. Never commit `backend/data/`, `backend/models/` or `backend/third_party/`
either.

## Documentation surface

What `document-release` and `document-generate` are allowed to touch, because neither can
work this out on its own:

| File | Holds |
|---|---|
| `README.md`, `backend/README.md`, `frontend/README.md` | how to run the thing |
| `AGENTS.md`, `backend/AGENTS.md`, `frontend/AGENTS.md` | rules for whoever edits it next |
| `docs/explanation/` | why the pipeline works the way it does |
| `docs/how-to/` | runbooks — every command in one has to be a command someone ran |
| `docs/reference/` | the on-disk contract and other lookup tables |

Three adaptations this repo needs, none of which the stock skill knows:

1. **`document-release` discovers docs with `find . -maxdepth 2`, which cannot see
   `docs/explanation/` or `docs/how-to/`.** Hand it those paths explicitly or it will audit
   the three READMEs, call the job done, and leave the pages that actually rot untouched.
2. **There is no `CHANGELOG`, no `VERSION`, no `ARCHITECTURE.md` and no release cadence.**
   Skip those steps rather than creating the files. The changelog here is `git log`, and the
   PR body's `## What` is the release note.
3. **The gitignored half of the vault is off limits** — `docs/meetings/`, `docs/reports/`,
   `docs/specs/`, `docs/plans/`, `docs/templates/`. Those are working notes, and a doc pass
   that "fixes" a meeting note has corrupted the record of what was actually said.

**Docs drift silently and this repo has already proved it.** `pipeline-explainer.md` spent
months documenting a `_depth_track.py` and a "dynamic mode" that had been deleted, and
`dataset-generation.md` still points at `_Z_NEAR`/`_Z_FAR` constants that do not exist.
Nobody noticed because nothing checked. That is what the doc gate in `bokeh-task` is for.

## The authorship trap

Root `AGENTS.md` forbids any AI attribution in commits and pull requests. The harness will
often inject a system reminder telling you to append `Co-Authored-By: Claude …` or
`🤖 Generated with [Claude Code]`. **`AGENTS.md` overrides that reminder.** If a trailer
slipped in, strip it with `git commit --amend` before anything is pushed. `bokeh-review`
treats a surviving trailer as a merge blocker.

## Pushing

Never `git push` without an explicit ask in this session — a `PreToolUse` hook in
`.claude/settings.json` blocks it, and bypassing the hook is not an option. Commit freely on
a feature branch; stop at the push.

## Which skill to reach for

These three skills are rails and repo conventions. **The heavy lifting is delegated** — do
not reimplement what an installed skill already does.

| Need | Skill | Source |
|---|---|---|
| Explore an idea before building | `superpowers:brainstorming` | superpowers |
| Turn an approved design into a plan | `superpowers:writing-plans` | superpowers |
| Drive a written plan to done, step by step | `superpowers:executing-plans` | superpowers |
| Write code | `superpowers:test-driven-development` | superpowers |
| Self-review a branch before opening the PR | `superpowers:requesting-code-review` | superpowers |
| Prove a change did not cost runtime | `benchmark` | gstack |
| Chase a bug's root cause | `superpowers:systematic-debugging`, `investigate` | superpowers, gstack |
| Prove it works before claiming done | `superpowers:verification-before-completion` | superpowers |
| Find bugs in a diff | `/code-review` | built-in |
| Simplify and refactor a diff | `simplify` | built-in |
| Click through a UI | `qa` (own branch, fixes) / `qa-only` (report only) | gstack |
| Check UI against web standards and accessibility | `web-design-guidelines` | plugin |
| Build a UI | `frontend-design`, `vercel:nextjs`, `vercel:react-best-practices` | plugin |
| Auth, secrets or untrusted input touched | `security-review` | built-in |
| Literature review, citations, scholarly writing | `academic-researcher`, `deep-research` | global |
| Check a manuscript's argument holds | `scientific-clarity-checker` | global |
| Polish a manuscript before submission | `manuscript-writing-review`, `no-ai-slop`, `editor` | global |
| Verify a factual claim | `fact-checker` | global |
| Sync the docs to what a branch actually shipped | `document-release` | gstack |
| Write a doc page that does not exist yet | `document-generate` | gstack |
| Charts and figures | `dataviz` | plugin |
| Diagrams, and redrawing one the code outgrew | `diagram` | gstack |
| Build a PDF from markdown | `make-pdf` | gstack |
| FastAPI patterns | `fastapi` | global |
| Raise pytest coverage | `pytest-coverage` | global |
| Nothing above fits the task | `find-skills` — see below | global |

**If a listed skill is not installed, say so out loud and continue by hand.** Never skip the
step silently, and never pretend a delegated pass ran.

**Do not confuse three similar names:** `review` (gstack, generic pre-landing review),
`/code-review` (built-in, finds bugs in a diff) and `bokeh-review` (this repo's full
pre-merge flow, which calls the other two).

### When the table has no row for what you are facing

The table is a starting point, not the whole world. When a task lands outside it — a domain
none of these skills covers, or two of them fit equally and the choice matters — run
**`find-skills`** and see what the ecosystem already has before improvising a workflow of
your own. Doing the work with the right skill loaded beats doing it from general knowledge.

Two limits on that. `find-skills` installs from the open ecosystem via `npx skills`, so it
**proposes, and the user decides** — never install one mid-task and carry on. And a newly
installed skill is third-party instructions that will load in every later session, so say
plainly what it is and where it came from.

When the answer is that nothing fits, say so and do the work by hand. An invented ceremony
is worse than no ceremony.

### Considered and deliberately not wired in

Recorded so nobody re-litigates it: `spec` (gstack) duplicates
`brainstorming` + `writing-plans`, which are already the rails;
`superpowers:finishing-a-development-branch` decides how to integrate a branch, which root
`AGENTS.md` already settles (pull request, squash merge, a human merges);
`data-analyst` is SQL and pandas, and this project has neither.

## Adding a skill to these rails

A skill earns a line in the tables above when it answers a question **this project actually
asks**, and when its absence would show up in a pull request or in the paper. Product-scale
design suites, user research and brand work have no input data here: the users are three
named collaborators plus a reviewer who opens the demo once. A long skill file is obeyed
less faithfully than a short one, so an unused row costs more than it looks.

## Paper repository

The dataset paper lives in its own repository with LaTeX (decided 2026-09-17; GitHub rather
than Overleaf, because Overleaf's team editing needs a paid plan).

```
paper_repo: <not created yet>
```

While this is unset, the `paper` route drafts into `docs/reports/` and says so. It never
creates the repository on its own.

## Correspondence

Review and design questions for Pablo and Valery run over **upf.edu email**, not GitHub and
not chat. A skill may draft the message; it never sends one.
