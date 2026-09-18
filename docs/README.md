# video-bokeh docs

This directory is the Obsidian vault root and the project's documentation tree. Open Obsidian on `docs/`, not on the repo root.

Two kinds of document live here, and the split is what `.gitignore` encodes.

**Shared, and in git.** What someone else needs to understand or run the pipeline. If a collaborator clones the repo, this is what they get.

| folder | holds | test |
|---|---|---|
| `explanation/` | how things work and why: the pipeline, the datasets, the methods we evaluated | no shell commands |
| `how-to/` | runbooks, one task each. Every command in one has been run | starts from a goal |
| `reference/` | lookup material: the on-disk contract, CLI flags, schemas | you look things up, not read it through |

**One home per fact.** A command, a format, a default belongs to exactly one page; everything
else links to it. This is the rule the vault previously lacked, and its absence is why
`explanation/` once held three overlapping descriptions of the same pipeline, one of which
documented code that had been deleted months earlier.

**Personal, and local only.** A record of a moment rather than a durable answer. Useful to you, noise to everyone else, and in the case of `attachments/` about 100 MB of screenshots.

| folder | holds |
|---|---|
| `meetings/` | digested meeting notes, one per sync |
| `meetings/transcripts/` | raw transcripts, same filename as the meeting they feed |
| `reports/` | progress reports, the ones exported to Notion |
| `specs/` | design specs for a change, written before the code |
| `plans/` | implementation plans derived from a spec |
| `templates/` | Templater scaffolds for new notes |
| `attachments/` | all media |
| `deprecated/` | superseded pages, kept until reviewed and deleted by hand |
| `dashboard.md` | Dataview index; only renders inside Obsidian |

Adding a new personal folder means adding a line to `.gitignore`, otherwise it lands in git by default.

## Naming

- Lowercase kebab-case. Dated when chronological: `2026-06-26-unrestricted-pipeline-algorithm.md`.
- A transcript and its digested meeting note share a filename and differ only by folder.
- Reports are `YYYY-MM-DD-<slug>.md` where the date starts the period covered and the slug names the period's main story. The duration lives in frontmatter (`period: 1w | 2w | 1m | adhoc`) so the filename stays sortable.

## Links

Prefer Obsidian wikilinks over markdown links: they survive renames.

- A bare name resolves anywhere in the vault: `[[layer-diffuse]]`, `[[pipeline-explainer]]`.
- Prefix with a path only to disambiguate a transcript from its meeting note, which share a filename: `[[meetings/2026-06-26-unrestricted-pipeline-algorithm]]` versus `[[meetings/transcripts/2026-06-26-unrestricted-pipeline-algorithm]]`.
- Media embeds with `![[image.png]]`. Older notes rely on Obsidian resolving that by filename alone; newer ones spell the path out. Both work as long as the file stays inside this vault.

## Workflow

1. Drop a raw transcript into `meetings/transcripts/` using the `transcript.md` template.
2. Digest it into `meetings/` under the same filename, using the `meeting.md` template. Pull out decisions and action items, link to `explanation/` rather than restating research.
3. Roll a period's meetings and work into `reports/`.
4. When a change needs designing, write the spec in `specs/`, then the plan in `plans/`.
5. When something in `explanation/`, `how-to/` or `reference/` goes stale, fix it in the same pull request as the code that made it stale. The `bokeh-task` skill runs `document-release` before every pull request for exactly this, and `backend/tests/test_docs_references.py` fails when a page names code that no longer exists.
6. When a page is superseded rather than wrong, move it to `deprecated/` with a banner saying what replaced it. Nothing is deleted on your behalf.

## Writing style

`STYLE.md` holds the conventions: lead with the takeaway, one idea per sentence, unpack jargon on first use, numbered recipes for anything procedural.
