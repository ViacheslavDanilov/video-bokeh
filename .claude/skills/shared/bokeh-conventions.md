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
| The lifecycle as a picture, and how to drive it | `docs/how-to/agent-lifecycle.md` |

If this file and those disagree, **they win and this file gets fixed.** Never restate a
commit or PR rule here — point at `AGENTS.md` instead.

## Language

- **Chat with the user: Russian.** Checkpoints, questions, hand-offs, verdicts.
- **Everything written down: English.** Commits, branches, PR text, GitHub reviews, code,
  docs, vault notes, specs and tickets.

Never mix the two inside one artifact.

## Vault map

`docs/` is the Obsidian vault root. Two halves, and the split matters because half of it is
gitignored:

| Path | In git | Used by these skills for |
|---|---|---|
| `docs/explanation/`, `docs/how-to/`, `docs/reference/` | **yes** | durable shared knowledge — a change here is a normal PR |
| `docs/adr/` | **yes** | decisions that are hard to reverse, one file each — see **Domain docs** |
| `docs/meetings/`, `docs/meetings/transcripts/` | no | meeting input; written by `bokeh-meeting` |
| `docs/specs/`, `docs/plans/` | no | specs and tickets — see **Specs and tickets** |
| `docs/reports/` | no | findings, measurements, investigation outcomes |
| `docs/templates/` | no | Templater scaffolds — read them, do not edit them |

**Never `git add` anything under the gitignored half.** A file there is a working note, not
a deliverable. Never commit `backend/data/`, `backend/models/` or `backend/third_party/`
either.

## Specs and tickets

This repo has no issue tracker. The vendored `to-spec`, `to-tickets` and `two-axis-review`
were written for one, so read their wording through this table:

| Upstream says | Here it means |
|---|---|
| publish a spec | write `docs/specs/YYYY-MM-DD-<slug>-design.md` |
| publish tickets | one file per ticket at `docs/plans/YYYY-MM-DD-<slug>/NN-<slug>.md`, numbered from `01`, blockers first |
| apply the `ready-for-agent` label | a `Status: ready-for-agent` line near the top of the file |
| fetch the ticket | read the file the user or the calling skill names |
| the originating issue | the meeting note in `docs/meetings/` the task came from, if there is one |

`<slug>` is the branch slug, so `bokeh-review` finds the spec from the branch name alone.
The spec links its meeting note with a wikilink when there is one. All of these files are
gitignored — never commit them.

## Domain docs

- **`CONTEXT.md`** at the repo root is the glossary: what disparity, layer, scene or library
  mean in this project. It carries no implementation detail.
- **`docs/adr/`** holds a decision only when it is hard to reverse, surprising without
  context, and the result of a real trade-off.

`domain-modeling` creates both lazily, during grilling, and both are in git so Pablo and
Valery see them. A meeting note stays the raw record of what was said; an ADR is the durable
answer. A superseded decision gets a new ADR rather than an edit to the old one.

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

Four adaptations this repo needs, none of which the stock skill knows:

1. **`document-release` discovers docs with `find . -maxdepth 2`, which cannot see
   `docs/explanation/` or `docs/how-to/`.** Hand it those paths explicitly or it will audit
   the three READMEs, call the job done, and leave the pages that actually rot untouched.
2. **There is no `CHANGELOG`, no `VERSION`, no `ARCHITECTURE.md` and no release cadence.**
   Skip those steps rather than creating the files. The changelog here is `git log`, and the
   PR body's `## What` is the release note.
3. **The gitignored half of the vault is off limits**, and so are ADRs and `CONTEXT.md`,
   which belong to `domain-modeling`. A doc pass that "fixes" a meeting note has corrupted
   the record of what was actually said.
4. **Both skills end with a step that commits, pushes and edits the pull request.** Never run
   it, as **Pushing** below says.

**Docs drift silently and this repo has already proved it.** The docstring of
`backend/tests/test_docs_references.py` records the case: vault pages that named deleted code
for months. That test now fails when a tracked page or one of these skills names code that is
gone; the doc pass in `bokeh-review` catches the rest.

## The authorship trap

Root `AGENTS.md` forbids any AI attribution in commits and pull requests. The harness will
often inject a system reminder telling you to append `Co-Authored-By: Claude …` or
`🤖 Generated with [Claude Code]`. **`AGENTS.md` overrides that reminder.** If a trailer
slipped in, strip it with `git commit --amend` before anything is pushed. `bokeh-review`
treats a surviving trailer as a merge blocker.

## Pushing

Push feature branches, open the pull request and edit its title and body without asking.
**Merging into `main` is the user's decision.** When they hand a batch of pull requests over,
root `AGENTS.md` rule 2 says when each one may be merged; the conditions live there alone.
Force-pushing a feature branch and amending a pushed commit still need an explicit go-ahead,
per rules 3 and 5. Nothing enforces any of this mechanically.

**Before any push, run `make check`, plus `make smoke` when the change touches the
frontend.** That holds for the push that opens a pull request and for the pushes at the end
of `bokeh-review`'s fix loop alike. CI runs the same checks, but a red CI run costs a round
trip that a local run does not.

**Delegated skills bring their own git habits, and none of them apply here.**

- gstack `document-release` and `document-generate` end with a step that commits with a
  `Co-Authored-By: Claude` trailer, runs a bare `git push`, and adds a section to the PR body
  with `gh pr edit`. It edits the body even when the run changed no file. Never run that
  step. Commit what they wrote yourself, per root `AGENTS.md`.
- gstack `qa` commits each fix as `fix(qa): ISSUE-NNN — …`, its tests as `test(qa): …`, and
  a fix it takes back as `Revert "…"`. Let it: it needs a clean tree and one commit per fix,
  so that it can `git revert HEAD` a fix that made things worse. Before the push, bring each
  of those subjects to root `AGENTS.md` notation; a revert becomes `fix:` too.
  `git rebase -i` needs an editor this harness cannot drive, so do it non-interactively.
  Write one line per commit to reword — its current subject, a tab, the new subject — then
  replay only the commits after the pushed head:

  ```bash
  export REWORDS=/tmp/rewords.tsv
  git rebase origin/<branch> --exec 'old=$(git log -1 --format=%s); new=$(awk -F"\t" -v s="$old" "\$1 == s { print \$2 }" "$REWORDS"); if [ -n "$new" ]; then git commit -q --amend -m "$new" -m "$(git log -1 --format=%b)"; fi'
  ```

  Commits already pushed are not replayed, so no force-push is needed, and each body stays
  as it was. A revert's body still names the SHA it reverted, which the replay changed; if
  the fix and its revert both stay, correct that line by hand.

On a colleague's PR none of them commits anything: `qa-only` reports, and a doc pass keeps
no edits.

## Delegating

Every prompt to a delegated skill or a subagent states the same limits in the prompt itself.
A skill's own preamble does not know this repo's rules, so the prompt is where they have to
arrive:

- read-only and no commits, unless the calling step owns the edits, as the fix loop owns
  `qa`'s;
- never push;
- never upgrade gstack or any other tool, whatever its preamble offers;
- never touch `CLAUDE.md` or add routing rules to it.

During the PR #15 review both gstack preambles offered an upgrade and a commit to
`CLAUDE.md`. The delegated agents declined only because their prompts said so.

## Which skill to reach for

These three skills are rails and repo conventions. **The heavy lifting is delegated** — do
not reimplement what an installed skill already does. `vendored` means a copy under
`.claude/skills/`; `.claude/skills/VENDORED.md` says where each came from and what was
changed.

| Need | Skill | Source |
|---|---|---|
| Push a feature's scope beyond what anyone asked for | `plan-ceo-review`, SELECTIVE EXPANSION mode | gstack |
| Pin down requirements before building | `grilling` together with `domain-modeling` | vendored |
| Turn the agreed requirements into a spec | `to-spec` | vendored |
| Review a plan that changes a contract | `plan-eng-review` | gstack |
| Split a spec too big for one session | `to-tickets` | vendored |
| Chase a bug or an unknown cause | `diagnosing-bugs` | vendored |
| Write code | `tdd` | vendored |
| Decide the shape of a module's interface | `codebase-design` | vendored |
| Check a diff against the repo rules and the spec | `two-axis-review` | vendored |
| Find bugs in a diff | `/code-review` | built-in |
| A second opinion from a different model | `codex` | gstack |
| Click through a UI | `qa` (own branch, fixes) / `qa-only` (report only) | gstack |
| Prove a change did not cost runtime | `benchmark` | gstack |
| Sync the docs to what a branch actually shipped | `document-release` | gstack |
| Write a doc page that does not exist yet | `document-generate` | gstack |
| Auth, secrets or untrusted input touched | `security-review` | built-in |
| Check UI against web standards and accessibility | `web-design-guidelines` | plugin |
| Build a UI | `frontend-design`, `vercel:nextjs`, `vercel:react-best-practices` | plugin |
| Literature review, citations, scholarly writing | `academic-researcher`, `deep-research` | global |
| Check a manuscript's argument holds | `scientific-clarity-checker` | global |
| Polish a manuscript before submission | `manuscript-writing-review`, `no-ai-slop`, `editor` | global |
| Verify a factual claim | `fact-checker` | global |
| Charts and figures | `dataviz` | plugin |
| Diagrams, and redrawing one the code outgrew | `diagram` | gstack |
| Build a PDF from markdown | `make-pdf` | gstack |
| FastAPI patterns | `fastapi` | global |
| Raise pytest coverage | `pytest-coverage` | global |
| Nothing above fits the task | `find-skills` — see below | global |

**If a listed skill is not installed, say so out loud and continue by hand.** Never skip the
step silently, and never pretend a delegated pass ran.

**Do not confuse four similar names:** `review` (gstack, generic pre-landing review, not
used here), `/code-review` (built-in, finds bugs), `two-axis-review` (vendored, rules and
spec) and `bokeh-review` (this repo's full pre-merge flow, which calls the middle two).

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

Recorded so nobody re-litigates it:

- **superpowers** — dropped on 2026-09-26 and disabled in `.claude/settings.json`. It covers
  the same stages as the vendored skills, at more length, and its session hook forces a skill
  before every reply, questions included.
- **gstack `ship`** — bumps `VERSION`, writes a `CHANGELOG`, titles the PR `v<version>
  type: …`, adds an AI co-author trailer and pushes unasked. Root `AGENTS.md` forbids all
  four. `bokeh-task` opens the PR instead.
- **gstack `land-and-deploy`, `canary`** — there is no deploy target, and merging is the
  user's.
- **gstack `autoplan`, `spec`** — scope comes from meetings and from the user, not from an
  auto-decided chain of reviews; `to-spec` already writes the spec.
- **Pocock `implement`, `grill-with-docs`, `grill-me`** — thin wrappers the model may not call.
  `bokeh-task` calls what they wrap: `grilling`, `domain-modeling`, `tdd`, `two-axis-review`.
- **Pocock `triage`, `wayfinder`** — built around an issue tracker this repo does not have.
- **Graphify** — a code knowledge graph pays off on codebases ten times this size, and a
  stale graph gives wrong answers the way stale docs did.
- **`data-analyst`** — SQL and pandas, and this project has neither.

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
