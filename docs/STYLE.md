---
type: style-guide
tags: [meta, writing-style, vault]
---

# Vault writing style

Plain, direct prose. The vault is read by Pablo and Valery as well as Slava — keep the technical density for code comments and design specs, not for the shared notes.

## Rules

1. **Lead with the takeaway.** First sentence of every section = the conclusion. Detail comes after.
2. **One idea per sentence.** If you'd join two clauses with `; `, split them.
3. **Active voice, plain verbs.** "We run X on Y" beats "X is run on Y" or "X performs Y-ification."
4. **Unpack jargon on first use.** "Percentile-clamped rescale" → "clip the top and bottom 1 % of pixels before rescaling so one outlier can't ruin the result."
5. **No stacked technical adjectives.** "Percentile-clamped scale-band normalization" → "rescale into a narrow band on the depth axis."
6. **Numbered recipes for processes.** Five short steps beat one long paragraph.
7. **Concrete numbers, not qualifiers.** "8,586 assets" not "a large subset"; "~30 min" not "a while."
8. **Each decision / open question / trade-off gets its own labelled bullet.** Never bury a decision inside prose.
9. **No shell commands in `explanation/`.** A page with a `$` or a ```bash fence is a how-to or a reference, whatever folder it sits in. This one is greppable, so it is the rule that actually holds.
10. **A command lives in exactly one file.** Everything else links to it. The same command in three places is three chances to rot, and when the copies disagree nobody can tell which is right.
11. **Avoid Latin and math notation in prose** (`i.e.`, `e.g.`, `≲`, `∈`) unless it's strictly more compact and the audience expects it. Prefer "about," "for example," "in."

## Where this applies

- `reports/*` — meeting prep, weekly summaries, deep dives.
- `meetings/*` — meeting notes, action items, decisions.
- `explanation/*` — long-running topic pages.
- `how-to/*` — runbooks.

## Where it doesn't apply

- Code comments and docstrings — terse and technical is correct.
- `specs/*` and `plans/*` — these sit next to the code; the audience is a developer with the file open.
- Source files in `backend/`, `frontend/`, etc.

## Reference

[[reports/2026-05-20-dataset-pipeline-update]] is the calibration sample. If a new doc reads less clearly than that one, revise.
