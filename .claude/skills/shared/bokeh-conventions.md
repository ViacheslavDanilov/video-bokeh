# Video Bokeh agent conventions

Shared by `bokeh-meeting`, `bokeh-task` and `bokeh-review`. Root `AGENTS.md` holds the
rules; this file does not repeat them.

## Sources of truth

| Topic | Canonical file |
|---|---|
| Commits, pull requests, git workflow, verification table | root `AGENTS.md` |
| Python, uv, ruff, ty, pytest | `backend/AGENTS.md` |
| Next.js, pnpm, eslint, prettier | `frontend/AGENTS.md` |
| Vault layout, naming, links, workflow | `docs/README.md` |
| Prose style for anything under `docs/` | `docs/STYLE.md` |
| The lifecycle as a picture, and how to drive it | `docs/how-to/agent-lifecycle.md` |

If this file and those disagree, they win and this file gets fixed.

## Working rules

- Talk with the user in the user's language: checkpoints, questions, hand-offs, verdicts.
  Everything written down follows root `AGENTS.md`, section **Language**.

## Vault map

`docs/` is the Obsidian vault root. Two halves, and the split matters because half of it is
gitignored:

| Path | In git | Used by these skills for |
|---|---|---|
| `docs/explanation/`, `docs/how-to/`, `docs/reference/` | **yes** | durable shared knowledge: a change here is a normal PR |
| `docs/adr/` | **yes** | decisions that are hard to reverse, one file each, see **Domain docs** |
| `docs/meetings/`, `docs/meetings/transcripts/` | no | meeting input; written by `bokeh-meeting` |
| `docs/specs/`, `docs/plans/` | no | specs and tickets, see **Specs and tickets** |
| `docs/reports/` | no | findings, measurements, investigation outcomes |
| `docs/templates/` | no | Templater scaffolds: read them, do not edit them |

**Never `git add` anything under the gitignored half.** A file there is a working note, not
a deliverable. Never commit `backend/data/` either.

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
gitignored, so never commit them.

## Domain docs

- **`CONTEXT.md`** at the repo root is the glossary: what disparity, layer, scene or library
  mean in this project. It carries no implementation detail.
- **`docs/adr/`** holds a decision only when it is hard to reverse, surprising without
  context, and the result of a real trade-off.

`domain-modeling` creates both lazily, during grilling. A meeting note stays the raw record of what was said; an ADR is the durable
answer. A superseded decision gets a new ADR rather than an edit to the old one.

## Documentation surface

What `document-release` and `document-generate` are allowed to touch, because neither can
work this out on its own:

| File | Holds |
|---|---|
| `README.md`, `backend/README.md`, `frontend/README.md` | how to run the thing |
| `AGENTS.md`, `backend/AGENTS.md`, `frontend/AGENTS.md` | rules for whoever edits it next |
| `docs/explanation/` | why the pipeline works the way it does |
| `docs/how-to/` | runbooks: every command in one has to be a command someone ran |
| `docs/reference/` | the on-disk contract and other lookup tables |

Both passes must follow `docs/README.md`, section **Links**: tracked pages use relative
Markdown links, with existing target files and GitHub heading anchors. Preserve aliases as
link text. Gitignored meeting notes and specs may keep wikilinks.

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

`backend/tests/test_docs_references.py` fails when a tracked page or one of these skills
names code that is gone; the doc pass in `bokeh-review` catches the rest.

## Pushing

Pushing, merging, force-pushing and amending follow root `AGENTS.md`, "Git workflow"
rules 2, 3 and 5.

**Before any push, run `make check`, plus `make smoke` when the change touches the
frontend.** That holds for the push that opens a pull request and for the pushes at the end
of `bokeh-review`'s fix loop alike.

**Delegated skills bring their own git habits, and none of them apply here.**

- gstack `document-release` and `document-generate` end with a step that commits in their
  own notation, runs a bare `git push`, and adds a section to the PR body with `gh pr edit`,
  even when the run changed no file. Never run that step. Commit what they wrote yourself,
  per root `AGENTS.md`.
- gstack `qa` commits each fix as `fix(qa): ISSUE-NNN` plus a short description, its tests
  as `test(qa): …`, and a fix it takes back as `Revert "…"`. Let it: it needs a clean tree
  and one commit per fix, so that it can `git revert HEAD` a fix that made things worse.
  Before the push, bring each of those subjects to root `AGENTS.md` notation; a revert
  becomes `fix:` too.
  `git rebase -i` needs an editor this harness cannot drive, so do it non-interactively.
  Write one line per commit to reword (its current subject, a tab, the new subject), then
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

Every prompt to a delegated skill or a subagent states these limits in the prompt itself,
because a skill's own preamble does not know this repo's rules:

- read-only and no commits, unless the calling step owns the edits, as the fix loop owns
  `qa`'s;
- never push;
- never upgrade gstack or any other tool, whatever its preamble offers;
- never edit root `AGENTS.md`, `.claude/agents/` or `.claude/skills/` unless that change is
  the task; routing rules live only in root `AGENTS.md`, section **Model routing**.

## Which skill to reach for

These three skills are rails and repo conventions. **The heavy lifting is delegated**: do
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
| Find bugs in a diff | `codex exec`, read-only; `/code-review` when codex is missing or refuses the model | CLI, built-in |
| A second opinion from a different model | `codex` | gstack |
| Click through a UI | `qa` (own branch, fixes) / `qa-only` (report only) | gstack |
| Prove a change did not cost runtime | `benchmark` | gstack |
| Sync the docs to what a branch actually shipped | `document-release` | gstack |
| Write a doc page that does not exist yet | `document-generate` | gstack |
| Auth, secrets or untrusted input touched | `security-review` | built-in |
| Check UI against web standards and accessibility | `web-design-guidelines` | plugin |
| Build a UI | `frontend-design` | plugin |
| Literature review, citations, scholarly writing | `academic-researcher`, `deep-research` | global |
| Check a manuscript's argument holds | `scientific-clarity-checker` | global |
| Verify a factual claim | `fact-checker` | global |
| Charts and figures | `dataviz` | plugin |
| Diagrams, and redrawing one the code outgrew | `diagram` | gstack |
| Build a PDF from markdown | `make-pdf` | gstack |
| FastAPI patterns | `fastapi` | global |
| Raise pytest coverage | `pytest-coverage` | global |
| Nothing above fits the task | `find-skills`, see below | global |

**If a listed skill is not installed, say so out loud and continue by hand.** Never skip the
step silently, and never pretend a delegated pass ran.

**Do not confuse four similar names:** `review` (gstack, generic pre-landing review, not
used here), `/code-review` (built-in, finds bugs), `two-axis-review` (vendored, rules and
spec) and `bokeh-review` (this repo's full pre-merge flow, which calls `two-axis-review`, and
`/code-review` only when codex is missing or refuses the model).

When the table has no row for the task, `find-skills` may propose one; installing it is the
user's decision. When nothing fits, do the work by hand.

## Paper repository

```
paper_repo: ViacheslavDanilov/video-bokeh-paper
```

The paper is private, in LaTeX, checked out beside this repository at `../video-bokeh-paper`.
Paper work runs there, under its own `AGENTS.md` and its own `bokeh-task` and
`bokeh-review`. It reads this repository and never edits it.
