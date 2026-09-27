---
name: bokeh-task
description: >-
  Take a task to an open pull request: a decision or action item from a meeting
  note, or a feature the user describes in chat. Triage the route (feature / bug /
  investigate / docs / paper / literature), optionally push the scope with a CEO
  review, grill out acceptance criteria and get them confirmed, write the spec,
  implement test-first, self-review in fresh context, commit in the repo notation
  and open the PR. Review, QA and the documentation pass run afterwards in
  /bokeh-review, in its own session. Routes that write no code are first-class
  endings. Use when the user says "сделай то, что решили на митинге", names an
  action item or a feature, or invokes /bokeh-task.
disable-model-invocation: false
---

# Bokeh task

One entry point for work, whether it came out of a sync or out of the user's head. **Read
[`../shared/bokeh-conventions.md`](../shared/bokeh-conventions.md) first** — it fixes the
language policy, the vault map, where specs live, the skill table and the authorship trap,
and this skill does not repeat them.

**Checkpoints are mandatory.** Requirements here arrive as speech, transcribed imperfectly,
or as one line in chat, and the record has already been wrong about concrete numbers. A
question costs a minute; a wrong assumption costs a regenerated dataset.

**This session ends at the pull request.** Review, QA and the doc pass belong to
`/bokeh-review`, run in a fresh session. The session that wrote the code knows what it meant,
and so it is the worst-placed to see what it actually wrote.

**No worktrees.** Work on a normal branch in the checkout the user has open.

Make a todo list with one item per step you will run, then follow it in order.
`docs/how-to/agent-lifecycle.md` has the whole flow as a diagram.

## 1. Resolve the source

Accept a meeting note path or slug, a quoted action item, or a free-form ask ("добавь экспорт
в EXR"). A task no meeting produced is normal: the user's own product decision is a
legitimate source.

Either way, search `docs/specs/` and `docs/plans/` for an existing design on the topic, and
`docs/meetings/` for any sync that touched it. For a meeting-sourced task, read the note's
**Action items**, **Decisions** and **Open questions**; if several meetings touch it, read the
newest and the one that first decided it.

If the ask is ambiguous, ask once. Never infer scope from a slug.

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

## 3. Product check — optional

Offer `plan-ceo-review` on the **feature** route when the task did not come from a meeting
decision, or when it opens a new direction: a new property of the dataset, a new view in the
demo, something headed for the paper. Skip it for bugs, refactors, docs, and anything a
meeting already scoped.

Run it in **SELECTIVE EXPANSION** mode, which holds the stated scope and lists expansions
separately. Tell it up front what the product is, because it assumes a startup:

- the product is the dataset, the paper and the demo;
- the users are researchers who train on the dataset, Pablo and Valery, and the paper's
  reviewers;
- there is no market, no growth and no revenue.

The user picks the expansions worth taking. One that changes the research direction — what
the dataset contains, how it is measured, what the paper claims — needs Pablo and Valery
first: draft the email, and do not build it until they agree.

## 4. Pin down the requirements — checkpoint

A request has no acceptance criteria. **You derive them and get them confirmed.**

Invoke `grilling` together with `domain-modeling`. `grilling` asks in rounds, every question
numbered with a recommended answer, and looks facts up itself instead of asking for them.
`domain-modeling` records settled terms in `CONTEXT.md` as they land, and offers an ADR only
for a decision that is hard to reverse. On the investigate route it writes nothing: that
route ends without a branch, so a glossary edit or an ADR would have nowhere to land.
Proposed terms and decisions go into the written finding instead.

Scale it. When the meeting note already settles every question, skip the grilling and say
so. A one-line bug gets none.

Then reply in Russian with:

- Источник: заметка и пункт, или «запрос в чате»
- Маршрут и куда ляжет результат
- Цель одним предложением, своими словами
- Критерии приёмки чеклистом — выведенные вами, а не процитированные
- Что вне скоупа
- Открытые вопросы

**Wait for an explicit yes.**

## 5. Reality check — before any code

Verify the source's factual claims against the repo. The record has been wrong before: a
formula was written as its own reciprocal, and asset counts were stated inverted. Read the
code path, the config, the actual files.

If the source and the code disagree, **stop and say so.** That finding may be the whole
task, and implementing against a wrong premise is the most expensive mistake available here.

## 6a. Route: feature

1. `to-spec` writes the spec to `docs/specs/YYYY-MM-DD-<slug>-design.md`, `<slug>` being the
   branch slug. It confirms the test seams with the user, and that confirmation is the seam
   agreement `tdd` needs later.
2. `plan-eng-review` on the spec when it changes the on-disk dataset contract, the API the
   frontend consumes, or render throughput. A contract migration is the one mistake here
   that costs a regenerated dataset.
3. `to-tickets` when the spec will not fit one session. Tickets land under
   `docs/plans/YYYY-MM-DD-<slug>/`; work the frontier, one ticket per session if need be.
4. Branch, then step 7.

Reach further when the surface calls for it: `frontend-design` with `vercel:nextjs` and
`vercel:react-best-practices` for UI, `fastapi` for API work, `dataviz` for figures.

## 6b. Route: bug

Invoke `diagnosing-bugs`. Its first phase is the rule this repo already had: **no command
that goes red on this bug, no fix.** A fix with no failing test in front of it is a guess.

If you cannot build that loop, stop, report in Russian what you tried, and offer the
investigate route. Branch before the fix; the regression test lands with it. The PR names
the hypothesis that turned out right, so the next person debugging learns from it.

## 6c. Route: investigate

Read-only. **No branch, no code, no PR.** The deliverable is understanding.

Gather evidence — code paths, `git log` and `git blame`, the generated artifacts, the
documented behaviour in `docs/explanation/` and `docs/reference/`. For an unknown cause, run
the first three phases of `diagnosing-bugs` and stop before the fix. `fact-checker` when a
claim about the outside world is in dispute.

Land on exactly one outcome:

| Outcome | What you do |
|---|---|
| **Confirmed divergence or defect** | Name the cause and the fix you would make. Ask whether to switch to 6a/6b now or record a follow-up. Do not start fixing unasked. |
| **No divergence** | Say what the system actually does, cite the file and line that settles it. "The note was mis-transcribed" is a legitimate, publishable answer. |
| **Needs a decision from Pablo or Valery** | State both readings and what each costs. Draft the email; do not send it. |

Write the finding to `docs/reports/YYYY-MM-DD-<slug>.md`, or append a clearly labelled
section to the meeting note saying it was added later and checked against code. Then go to
step 11. **A task that ends here with no code is a successful run.**

## 6d. Route: docs

Tracked docs are a PR like any other. Match `docs/STYLE.md`, keep the runbooks executable —
every command in `docs/how-to/` must be one you actually ran.

`document-generate` (gstack) for a page from scratch; `editor` or `no-ai-slop` for a pass
over prose that reads stiffly. Then step 7, with commit type `docs`.

## 6e. Route: paper

Check `paper_repo` in the conventions file. While it is unset, draft into
`docs/reports/YYYY-MM-DD-<slug>.md` and say so — never create the repository unasked.

`academic-researcher` leads. Before anything is called finished:
`scientific-clarity-checker` for whether each claim is carried by its evidence,
`manuscript-writing-review` for submission readiness, `no-ai-slop` so the prose reads as a
person wrote it. `make-pdf` to build a readable draft, `pptx` if the output is slides.

Numbers in the manuscript are measured and traceable to a command or a file. Never carry a
figure from a meeting note into the paper without re-deriving it.

## 6f. Route: literature

`academic-researcher` plus `deep-research`. The recurring question here is whether a prior
synthetic dataset already covers this contribution — answer it with a comparison table:
datasets in rows, desirable properties in columns.

**Every citation is opened and verified.** Never cite from memory, never invent a DOI, never
report a paper's claim you have not read in the paper. `fact-checker` for anything
contested. An unverifiable source is reported as unverifiable.

Durable results belong in `docs/explanation/` — it is in git, so Pablo and Valery see it. A
dated snapshot belongs in `docs/reports/`.

## 6g. Route: out of scope

Say plainly that it is not work for this repo, and stop. Draft an email for anything that
needs Pablo or Valery, and leave sending to the user. Do not invent repo work to look busy.

## 7. Branch and implement

```
git checkout main
git pull                 # only if the user wants latest
git checkout -b <type>/<short-kebab-slug>
```

`<type>` matches the Conventional Commit type — `feat`, `fix`, `docs`. Slug ≤ 5 words, and
the same slug names the spec. **Never commit to `main`.**

Invoke `tdd` at the seams the spec agreed: one failing test, the smallest change that passes
it, next test. `codebase-design` when the shape of an interface is the open question.

Stay surgical. Every changed line traces to the task. Do not improve adjacent code, do not
delete pre-existing dead code — mention it instead.

Module notes:

- **`backend/`** — uv-managed. Run from `backend/`; `uv run pytest`, `uv run ruff check
  src/`, `uv run ty check src/`. Code lives under `backend/src/video_bokeh/`: `acquire`,
  `library`, `scenes`, `core`, `preview`, `bridge`, `api`.
- **`frontend/`** — **pnpm only**, never npm or yarn. Next.js 16 diverges from training
  data: read `node_modules/next/dist/docs/` before writing code, as `frontend/AGENTS.md`
  demands.
- **`backend/third_party/`** — vendored submodules, read-only.
- **`backend/data/`, `backend/models/`** — gitignored artifacts, never staged.

If a folder's semantics changed, update the `AGENTS.md` in every folder you touched.

## 8. Verify

Run what the root `AGENTS.md` verification table lists for the layers you touched, and
report what the commands printed. Never claim done without output.

Generation throughput is a published number here — `docs/how-to/` quotes seconds per scene —
so when a change touches the render or I/O path, use `benchmark` and put the measured
before/after in the PR. A format migration that quietly triples write time is a regression
even though every test passes.

The browser pass and the doc pass happen in `/bokeh-review`. The PR's `## Verified` lists
only what this session actually ran.

## 9. Self-review in fresh context

Commit first, by step 10's rules, and do not push. `two-axis-review` diffs committed history,
`origin/main...HEAD`, so it cannot see uncommitted work and stops on an empty diff.

Run `git fetch origin`, then invoke `two-axis-review` with `origin/main` as the fixed point
and the spec's path, or, on a route
that wrote no spec, the acceptance criteria confirmed in step 4. Its two subagents see the
diff and the spec, not this conversation, and that is the point: they read what you wrote
rather than what you meant.

Fix every hard standards violation and every spec gap, each fix a further commit. Fix a
judgement-call smell when it is cheap, otherwise name it in the PR body. One round only —
the full review is `/bokeh-review`'s job.

## 10. Commit and open the PR

Commit per root `AGENTS.md`: Conventional Commits, one logical change per commit, no AI
trailer anywhere. Run a plain `git commit` and read its exit code — pre-commit reformats and
aborts, and piping the command through `tail` or `&&` hides that.

`git log origin/main..HEAD --oneline` — do the commits read as one coherent change?

Run `make check`, plus `make smoke` when the change touches the frontend. Then push and open
the pull request without asking, per root `AGENTS.md` rule 2:
`gh pr create` with a title that is a short imperative phrase, no `type:` prefix, ≈65
characters, and the `## What` / `## Why` / `## Verified` body from `AGENTS.md`.
`Verified` carries measured numbers only, and names pre-existing failures as pre-existing.
A judgement call left from step 9 goes in the body as a named follow-up.

## 11. Record the outcome

This replaces the tracker this project does not have. When the task came from a meeting
note:

- tick the action item and append the PR link or the report path under it;
- if the work answered an entry under **Open questions**, move the answer into
  **Decisions** with the date it was settled.

Measurements worth keeping go to `docs/reports/`. None of this is committed.

## 12. Hand off

Reply in Russian: the route taken, the PR URL or the file written, branch and head SHA, how
many files changed, what you verified, and anything you could not. When there is a PR, end
with the next step: **new session, `/bokeh-review <n>`.** **Do not merge** unless the user has
handed this pull request over: merging is theirs by default, per root `AGENTS.md` rule 2.

## Red flags — stop and ask

- The acceptance criteria are yours to invent and the user has not confirmed them.
- The source contradicts the code, or contradicts an earlier meeting's decision.
- The change alters the on-disk dataset contract — stream layout, bit depth, channel
  count. Downstream readers like `backend/src/video_bokeh/bridge/any_to_bokeh.py` break
  silently.
- An expansion from the CEO review changes the research direction, and Pablo and Valery
  have not agreed to it.
- The work needs a decision from Pablo or Valery that nobody has made.
- The task would touch `backend/third_party/`.
- A number in the note that nobody measured is about to become a constant in the code.
