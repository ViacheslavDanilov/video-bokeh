---
name: bokeh-task
description: >-
  Take a decision or action item from a meeting note and carry it to its end:
  triage the route (feature / bug / investigate / docs / paper / literature),
  derive and confirm acceptance criteria the transcript never spelled out,
  implement via TDD, verify, sync the documentation to what actually shipped,
  commit in the repo notation, open the PR, and tick the item back in the note.
  Routes that write no code are first-class endings.
  Use when the user says "сделай то, что решили на митинге", names an action
  item, or invokes /bokeh-task.
disable-model-invocation: false
---

# Bokeh task

One entry point for work that came out of a sync. **Read
[`../shared/bokeh-conventions.md`](../shared/bokeh-conventions.md) first** — it fixes the
language policy, the vault map, the delegation table and the authorship trap, and this skill
does not repeat them.

**Checkpoints are mandatory.** This project's requirements arrive as speech, transcribed
imperfectly, and the record has already been wrong about concrete numbers. A question costs
a minute; a wrong assumption costs a regenerated dataset.

**No worktrees.** Work on a normal branch in the checkout the user has open.

Make a TodoWrite list with one item per step you will run, then follow it in order.

## 1. Resolve the source

Accept a meeting note path or slug, a quoted action item, or a free-form ask ("сделай то,
что решили про TIFF").

Read the note in `docs/meetings/` — **Action items**, **Decisions**, **Open questions** — and
search `docs/specs/` and `docs/plans/` for an existing design on the topic. If several
meetings touch it, read the newest and the one that first decided it.

If nothing matches, ask once. Never infer scope from a slug.

## 2. Triage — two levels

**Where the result lands**, which decides whether there is a PR at all:

| Destination | Ends with |
|---|---|
| Code in this repo | a pull request |
| `docs/explanation/`, `docs/how-to/`, `docs/reference/` | a pull request — these are in git |
| `docs/reports/`, `docs/specs/`, `docs/plans/`, `docs/meetings/` | a file, no commit |
| Outside this repo — the paper, an email, an IT ticket | a draft, or an honest "not this repo" |

**Which route**, stated in one line for the user to override:

| Route | When | Ends with |
|---|---|---|
| **feature** | new behaviour someone can observe | PR |
| **bug** | behaviour that already worked is wrong | repro test → PR |
| **investigate** | a question, an unknown cause, or "does the code match what we recorded" | a written finding, no code |
| **docs** | a runbook, an explanation page, a reference, a README | PR |
| **paper** | manuscript text, section structure, revisions | a draft in the paper repo, or `docs/reports/` while it does not exist |
| **literature** | a survey, a search for prior datasets, a comparison table | a note with verified citations |
| **out of scope** | install software, chase IT, write to a person | name it, stop, draft the message if there is one |

Signals for **investigate** even when the ask sounds like a change: no reproduction, "надо
проверить", a claim in the note that no one has checked against the code, or a request for
an estimate. When feature and bug both fit, take **bug** — repro-first is stricter.

## 3. Restate scope — checkpoint

A meeting note has no acceptance criteria. **You derive them and get them confirmed.** Reply
in Russian with:

- Источник: заметка и конкретный пункт или решение
- Маршрут и куда ляжет результат
- Цель одним предложением, своими словами
- Критерии приёмки чеклистом — выведенные вами, а не процитированные
- Что вне скоупа
- Открытые вопросы

**Wait for an explicit yes.**

## 4. Reality check — before any code

Verify the note's factual claims against the repo. The record has been wrong before: a
formula was written as its own reciprocal, and asset counts were stated inverted. Read the
code path, the config, the actual files.

If the note and the code disagree, **stop and say so.** That finding may be the whole task,
and implementing against a wrong premise is the most expensive mistake available here.

## 5a. Route: feature

1. `superpowers:brainstorming` — files to touch, data or format changes, CLI or API surface,
   test strategy. No code yet.
2. `superpowers:writing-plans` — plan to `docs/plans/YYYY-MM-DD-<slug>.md`, design to
   `docs/specs/YYYY-MM-DD-<slug>-design.md`. **Both folders are gitignored — never commit
   them.** (Older plans reference `docs/superpowers/specs/`; that path is stale.)
3. If the plan changes the on-disk dataset contract or anything Pablo and Valery consume,
   put it through `plan-eng-review` before writing code. A contract migration is the one
   mistake here that costs a regenerated dataset.
4. Branch, then step 6, driving the plan with `superpowers:executing-plans` rather than
   working from memory of what you wrote.

Reach further when the surface calls for it: `frontend-design` with `vercel:nextjs` and
`vercel:react-best-practices` for UI, `fastapi` for API work, `dataviz` for figures,
`diagram` for a schematic.

## 5b. Route: bug

**Reproduce before you fix.** A fix with no failing test in front of it is a guess.

1. Reproduce it — a failing test, or a command whose output you paste.
2. If the cause is not obvious, invoke `superpowers:systematic-debugging`, or gstack
   `investigate` for a genuine hunt.
3. If you cannot reproduce it, stop, report in Russian what you tried, and offer the
   investigate route. Do not fix a bug you have not seen.
4. Branch, write the failing test, then step 6.

## 5c. Route: investigate

Read-only. **No branch, no code, no PR.** The deliverable is understanding.

Gather evidence — code paths, `git log` and `git blame`, the generated artifacts, the
documented behaviour in `docs/explanation/` and `docs/reference/`. Use gstack `investigate`
for debugging hunts and `fact-checker` when a claim about the outside world is in dispute.

Land on exactly one outcome:

| Outcome | What you do |
|---|---|
| **Confirmed divergence or defect** | Name the cause and the fix you would make. Ask whether to switch to 5a/5b now or record a follow-up. Do not start fixing unasked. |
| **No divergence** | Say what the system actually does, cite the file and line that settles it. "The note was mis-transcribed" is a legitimate, publishable answer. |
| **Needs a decision from Pablo or Valery** | State both readings and what each costs. Draft the email; do not send it. |

Write the finding to `docs/reports/YYYY-MM-DD-<slug>.md`, or append a clearly labelled
section to the meeting note saying it was added later and checked against code. Then go to
step 10. **A task that ends here with no code is a successful run.**

## 5d. Route: docs

Tracked docs are a PR like any other. Match `docs/STYLE.md`, keep the runbooks executable —
every command in `docs/how-to/` must be one you actually ran.

`document-generate` (gstack) for a page from scratch; `editor` or `no-ai-slop` for a pass
over prose that reads stiffly. Then step 6, with commit type `docs`.

## 5e. Route: paper

Check `paper_repo` in the conventions file. While it is unset, draft into
`docs/reports/YYYY-MM-DD-<slug>.md` and say so — never create the repository unasked.

`academic-researcher` leads. Before anything is called finished:
`scientific-clarity-checker` for whether each claim is carried by its evidence,
`manuscript-writing-review` for submission readiness, `no-ai-slop` so the prose reads as a
person wrote it. `make-pdf` to build a readable draft, `pptx` if the output is slides.

Numbers in the manuscript are measured and traceable to a command or a file. Never carry a
figure from a meeting note into the paper without re-deriving it.

## 5f. Route: literature

`academic-researcher` plus `deep-research`. The recurring question here is whether a prior
synthetic dataset already covers this contribution — answer it with a comparison table:
datasets in rows, desirable properties in columns.

**Every citation is opened and verified.** Never cite from memory, never invent a DOI, never
report a paper's claim you have not read in the paper. `fact-checker` for anything
contested. An unverifiable source is reported as unverifiable.

Durable results belong in `docs/explanation/` — it is in git, so Pablo and Valery see it. A
dated snapshot belongs in `docs/reports/`.

## 5g. Route: out of scope

Say plainly that it is not work for this repo, and stop. Draft an email for anything that
needs Pablo or Valery, and leave sending to the user. Do not invent repo work to look busy.

## 6. Branch and implement

```
git checkout main
git pull                 # only if the user wants latest
git checkout -b <type>/<short-kebab-slug>
```

`<type>` matches the Conventional Commit type — `feat`, `fix`, `docs`. Slug ≤ 5 words.
**Never commit to `main`.**

Invoke `superpowers:test-driven-development`. Per plan step: failing test → smallest change
that passes → refactor only if it improves clarity.

Stay surgical. Every changed line traces to the task. Do not improve adjacent code, do not
delete pre-existing dead code — mention it instead.

Module notes:

- **`backend/`** — uv-managed. Run from `backend/`; `uv run pytest`, `uv run ruff check
  src/`, `uv run ty check src/`. Data scripts live in `backend/src/data/`.
- **`frontend/`** — **pnpm only**, never npm or yarn. Next.js 16 diverges from training
  data: read `node_modules/next/dist/docs/` before writing code, as `frontend/AGENTS.md`
  demands.
- **`backend/third_party/`** — vendored submodules, read-only.
- **`backend/data/`, `backend/models/`** — gitignored artifacts, never staged.

If a folder's semantics changed, update the `AGENTS.md` in every folder you touched.

## 7. Verify

Invoke `superpowers:verification-before-completion`, then run what the root `AGENTS.md`
verification table lists for the layers you touched. For a UI change, start the dev server
and use the feature in a browser — `qa` (gstack) drives it, `web-design-guidelines` checks
it. For a pipeline change, the script is `docs/how-to/demo-unrestricted-trajectories.md`.

Generation throughput is a published number here — `docs/how-to/` quotes seconds per scene —
so when a change touches the render or I/O path, use `benchmark` and put the measured
before/after in the PR. A format migration that quietly triples write time is a regression
even though every test passes.

Report what the commands printed. Never claim done without output.

## 8. Documentation sync — before the PR, not after

**The pipeline changes and the docs do not follow on their own.** This repo has already
proved it: `docs/explanation/pipeline-explainer.md` documented a `_depth_track.py` and a
"dynamic mode" for months after both were deleted. Nobody noticed, because nothing checked.
This step is the check.

Invoke **`document-release`**. It diffs the branch against the base, builds a coverage map of
what shipped against what is documented, and flags diagram drift. Three things it cannot work
out by itself, all of them in the conventions file's **Documentation surface** section — read
it before starting:

- it discovers docs with `find . -maxdepth 2`, which **cannot see `docs/explanation/` or
  `docs/how-to/`**. Hand it those paths or it will audit three READMEs and declare victory;
- there is no `CHANGELOG`, no `VERSION` and no release cadence here — skip those steps rather
  than creating the files;
- **the gitignored half of the vault is off limits.** A pass that "fixes" a meeting note has
  falsified the record of what was said.

Scale it to the change. A PR that adds a CLI flag, changes the on-disk dataset contract, or
renames anything Pablo and Valery consume gets the full pass. A one-line fix gets a look at
whether any page names the thing you touched. A docs-only PR has already done this.

Two follow-ons, when the pass turns them up:

- a genuine coverage gap — a new capability no page describes — is `document-generate`, and
  it writes into `docs/explanation/` or `docs/how-to/` per `docs/STYLE.md`;
- a diagram the code has outgrown is `diagram`, with the result under
  `docs/attachments/<slug>/` and embedded with `![[…]]`. `document-release` flags drift but
  deliberately does not redraw, so this is yours to decide.

Anything you choose not to fix is named in the PR body as known documentation debt, not left
silent. Tracked docs changed here are part of this PR, so they follow the same commit rules —
type `docs`, one logical change per commit.

## 9. Commit and open the PR

Commit per root `AGENTS.md`: Conventional Commits, one logical change per commit, no AI
trailer anywhere. Run a plain `git commit` and read its exit code — pre-commit reformats and
aborts, and piping the command through `tail` or `&&` hides that.

`git log main..HEAD --oneline` — do the commits read as one coherent change?

Then `superpowers:requesting-code-review` over your own branch before anyone else sees it.
Finding your own mistake costs a commit; finding it in `/bokeh-review` costs a round trip
through a second session.

**Stop before pushing.** Ask; a hook blocks it anyway. After approval, `gh pr create` with a
title that is a short imperative phrase, no `type:` prefix, ≈65 characters, and the
`## What` / `## Why` / `## Verified` body from `AGENTS.md`. `Verified` carries measured
numbers only, and names pre-existing failures as pre-existing. Documentation debt from step 8
goes in the body too — under `## What` if you fixed it, as a named gap if you did not.

## 10. Record the outcome

This replaces the tracker this project does not have. In the source meeting note:

- tick the action item and append the PR link or the report path under it;
- if the work answered an entry under **Open questions**, move the answer into
  **Decisions** with the date it was settled.

Measurements worth keeping go to `docs/reports/`. None of this is committed.

## 11. Hand off

Reply in Russian: the route taken, the PR URL or the file written, branch and head SHA, how
many files changed, what you verified, and anything you could not. **Do not merge** — that
is a human decision, and review runs in its own session via `/bokeh-review`.

## Red flags — stop and ask

- The note's acceptance criteria are yours to invent and the user has not confirmed them.
- The note contradicts the code, or contradicts an earlier meeting's decision.
- The change alters the on-disk dataset contract — stream layout, bit depth, channel
  count. Downstream readers like `prepare_any_to_bokeh.py` break silently.
- The work needs a decision from Pablo or Valery that nobody has made.
- The task would touch `backend/third_party/`.
- A number in the note that nobody measured is about to become a constant in the code.
