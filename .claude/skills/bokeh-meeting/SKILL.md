---
name: bokeh-meeting
description: >-
  Turn a recorded sync into the two vault notes this project runs on: the raw
  transcript under docs/meetings/transcripts/ and a digested meeting note under
  docs/meetings/, both following the repo's templates, naming and prose style.
  Takes a Fathom share link, a call id, or a local transcript file. Use when the
  user says "запиши митинг", "оформи встречу", pastes a fathom.video link, or
  invokes /bokeh-meeting.
disable-model-invocation: false
---

# Bokeh meeting

File a sync into the vault so that `bokeh-task` can work from it later. **Read
[`../shared/bokeh-conventions.md`](../shared/bokeh-conventions.md) first** for the language
policy and the vault map; this skill does not repeat them.

The digest is the artifact that survives. Months later nobody reopens the recording — they
read this note and act on it, so a decision recorded vaguely becomes a decision lost.

Make a TodoWrite list with one item per step below, then follow it.

## 1. Resolve the source

| Input | What to do |
|---|---|
| `https://fathom.video/share/<token>` or `/calls/<id>` | `get_recording_by_url` → keep `recording_id` and `url` |
| A bare number | `get_recording_by_call_id`; if that 404s, retry the same number as a `recording_id` |
| A local file (`meeting.txt`, a pasted dump) | Read it; skip the MCP entirely |
| Nothing | `list_meetings` and offer the recent ones — never guess |

With a recording id: `get_meeting_transcript` (pass the `url` so timestamps become deep
links) and `get_meeting_summary`. If the MCP fails, stop and surface the error rather than
writing a note from the summary alone.

## 2. Derive the metadata

Date, duration in minutes, attendees, recording URL, and a topic line. Attendees use the
short names the vault already uses — Slava, Pablo, Valery — not the full transcript labels.

Slug: `YYYY-MM-DD-<topic-slug>`, lowercase kebab-case, the main story of the meeting in two
to four words. **The transcript and the digest share the slug** and differ only by folder.
Check `docs/meetings/` for an existing file with that slug before writing anything.

Find the previous sync — the newest note in `docs/meetings/` before this date — so the
digest can link back to it.

## 3. Depth checkpoint

Ask once, in Russian, which topics deserve full depth. Default split, stated so the user can
override it in one word:

- **Full depth** — anything touching the pipeline, the dataset, formats, algorithms,
  measurements, or a decision someone will implement later.
- **Compressed** — logistics, hardware, travel, small talk, and side topics the project does
  not act on.

A long meeting is usually 20% decisions and 80% context. Getting this split wrong in either
direction is the main way this note fails.

## 4. Write the raw transcript

`docs/meetings/transcripts/<slug>.md`, frontmatter shaped like `docs/templates/transcript.md`
(read the template for the field list; it is a Templater scaffold, so copy the shape, do not
execute it):

```yaml
---
type: transcript
date: YYYY-MM-DD
attendees: [Slava, Pablo, Valery]
source: fathom
recording: <url>
duration_min: <n>
meeting_note: "[[meetings/<slug>]]"
tags: [transcript, fathom, <topic tags>]
---
```

Then the heading, a one-line pointer to the digest, and the transcript **verbatim**. Keep
Fathom's own `ACTION ITEM:` and `SCREEN SHARING:` markers where they fall. Do not clean up,
reorder or summarise here — this file exists precisely so the digest can be checked against
it.

## 5. Write the digest

`docs/meetings/<slug>.md`. Frontmatter per `docs/templates/meeting.md` plus `status:
processed`, `transcript:` and `recording:`. Then:

```markdown
# YYYY-MM-DD — <Topic>

> <Kind of sync>, <n> min. Raw transcript: [[meetings/transcripts/<slug>]].
> Previous sync: [[meetings/<previous-slug>]].
> Fathom recording: <url> (<n> min).
> Attendees: Slava, Pablo, Valery.

## 1) <first topic>
...

---

## Action items
### Slava
- [ ] …
### Pablo
### Valery

---

## Decisions
## Open questions
## Next sync
```

Rules that make the difference:

1. **Follow `docs/STYLE.md`.** Lead each section with its conclusion, one idea per sentence,
   plain verbs, concrete numbers, jargon unpacked on first use. Pablo and Valery read this
   vault too.
2. **A decision, an open question or a trade-off gets its own labelled bullet.** Never bury
   one inside prose — that is the single rule this note exists to serve.
3. **Deep sections carry the mechanism, not the vibe.** Formats, thresholds, file paths,
   who argued what and why the alternative was rejected. A table beats a paragraph for
   anything enumerable — streams and their formats, options and their trade-offs.
4. **Harvest Fathom's `ACTION ITEM:` markers, then re-attribute them.** Fathom credits
   whoever was speaking, which is often the person *asking*, not the owner. Assign from
   context and fold them into the per-person lists.
5. **Transcription is lossy — repair the obvious, flag the rest.** Known technical terms get
   normalised silently (`Twif` → TIFF, `VPB` → VPV, `Hug and Face` → Hugging Face,
   `any2bokeh` → any-to-bokeh). Genuinely garbled cross-talk is marked as unclear or left
   out, never smoothed into a confident claim. If two readings are possible, say so.
6. **Link, do not restate.** Wikilink to `docs/explanation/` for background and to the
   previous meeting note for history.

## 6. Diagrams, if the meeting drew one

If the call walked through an algorithm on a whiteboard or a shared screen, offer the gstack
`diagram` skill and put the result under `docs/attachments/<slug>/`, embedded with `![[…]]`.
Prior meeting notes do this and it is worth the effort for anything a reader must picture.

## 7. Hand off

Reply in Russian: both paths, which topics got full depth, how many action items landed on
whom, and anything you marked as unclear.

**Do not commit.** `docs/meetings/` is gitignored — say so once if the user expects a commit.

## Red flags — stop and ask

- The recording is one the user has not mentioned and may not want filed.
- Two meetings on the same date compete for the slug.
- The transcript contradicts a decision recorded in an earlier meeting note. Write both,
  flag the conflict in **Open questions**, and say it in chat — do not silently pick one.
- A decision in the transcript contradicts what the code does. That is a finding for
  `bokeh-task`'s investigate route, not something to quietly correct in the minutes.
