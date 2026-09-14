# video-bokeh docs

This directory is the Obsidian vault root and the project's documentation tree. Open Obsidian on `docs/`, not on the repo root.

Two kinds of document live here, and the split is what `.gitignore` encodes.

**Shared, and in git.** What someone else needs to understand or run the pipeline. If a collaborator clones the repo, this is what they get.

| folder | holds |
|---|---|
| `explanation/` | how things work and why: the pipeline, the datasets, the methods we evaluated |
| `how-to/` | runbooks. Commands you follow to produce or inspect something |
| `reference/` | lookup material: flags, file layouts, schemas. Create it when there is something to put there |

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
5. When something in `explanation/` or `how-to/` goes stale, fix it in the same pull request as the code that made it stale.

## Writing style

`STYLE.md` holds the conventions: lead with the takeaway, one idea per sentence, unpack jargon on first use, numbered recipes for anything procedural.
