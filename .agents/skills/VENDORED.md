# Vendored skills

Eight skills here are copies of [mattpocock/skills](https://github.com/mattpocock/skills) at
commit `c55ee46` (2026-09-18), copied rather than installed so they can be adapted to this
repo and so every session loads the same version.

| Here | Upstream |
|---|---|
| `grilling/` | `skills/productivity/grilling/` |
| `domain-modeling/` | `skills/engineering/domain-modeling/` |
| `codebase-design/` | `skills/engineering/codebase-design/` |
| `tdd/` | `skills/engineering/tdd/` |
| `diagnosing-bugs/` | `skills/engineering/diagnosing-bugs/` |
| `to-spec/` | `skills/engineering/to-spec/` |
| `to-tickets/` | `skills/engineering/to-tickets/` |
| `two-axis-review/` | `skills/engineering/code-review/` |

## Local edits

Kept to the minimum, so a later upstream copy can be diffed against these files:

- `to-spec` and `to-tickets` lose `disable-model-invocation: true`, so `bokeh-task` can call
  them. Upstream reserves them for the user's own slash command.
- `code-review` is renamed `two-axis-review`, because Claude Code ships a built-in
  `code-review` and the two would share a name. `tdd` points at the new name.
- Every pointer to `/setup-matt-pocock-skills`, `docs/agents/` or `.scratch/` now points at
  the **Specs and tickets** section of `shared/bokeh-conventions.md`. This repo has no issue
  tracker; specs and tickets are local files.
- Upstream's `agents/openai.yaml` files are not copied: a skill here needs only its `SKILL.md`
  and the files it references.

## Impeccable

`impeccable/` is a copy of [pbakaus/impeccable](https://github.com/pbakaus/impeccable)
`.claude/skills/impeccable/` at `3930843` (2026-10-30), skill 4.8.0, the Claude Code build. It
is taken from the author's site repository, which vendors the same copy, rather than with
`npx impeccable install`, so both repositories hold identical files.

- Its four agents, `impeccable-*`, are copied unchanged to `.claude/agents/`.
- Its three hooks (`SessionStart`, `PostToolUse` on `Edit|Write`, `Stop`) are in
  `.claude/settings.json` as upstream's own settings have them. The hooks skip themselves when
  the folder is missing.
- `.impeccable/config.json` turns on the hook's quiet mode. The `.gitignore` block between the
  `impeccable-ignore` markers is upstream's, and the root `.gitattributes` checks
  `impeccable.cmd` out with CRLF line endings, as upstream's does.
- The launcher in `impeccable/scripts/` downloads its engine once into `~/.impeccable/bin/` and
  checks it against `engine-checksums.txt`.
- `.pre-commit-config.yaml` excludes the folder and `.impeccable/`, so the hooks do not
  reformat upstream files and the copy stays diffable.
- Upstream `LICENSE` and `NOTICE.md` are in the folder, as Apache 2.0 requires.
- Nothing else is changed. `bokeh-task`, `bokeh-review` and `crafter` reach it through **UI
  work** in `shared/bokeh-conventions.md`.

To update it, copy `.claude/skills/impeccable/` from upstream's repository root over the
folder and refresh the `.gitignore` block from its README.

## Updating

Clone upstream, copy the eight folders over these, then re-apply the edits above. `git diff`
shows exactly what upstream changed.

## License

The eight skills above are under the MIT License. `impeccable/` is under the Apache License
2.0, whose text is in `impeccable/LICENSE`.

MIT License

Copyright (c) 2026 Matt Pocock

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
