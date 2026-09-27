#!/usr/bin/env bash
# PreToolUse hook: block `git push` for anyone who wants every push to stay manual.
# Opt-in: root AGENTS.md lets agents push feature branches, and this hook is wired up only
# from a personal .claude/settings.local.json. Exits 2 (blocking) when a push is detected.

set -euo pipefail

cmd=$(python3 -c 'import json, sys; print(json.load(sys.stdin).get("tool_input", {}).get("command", ""))')

# Match `git push` at the start of the command, after whitespace, or after a shell separator.
# Catches: `git push`, `cd x && git push`, `foo; git push --force`, multi-line scripts.
# Does not catch: `git push` inside quoted strings, but that's edge-case enough to ignore.
if printf '%s\n' "$cmd" | grep -Eq '(^|[[:space:]]|;|&&|\|\|)git[[:space:]]+push([[:space:]]|$)'; then
  cat >&2 <<'MSG'
BLOCKED: the no-push hook is enabled in .claude/settings.local.json, so `git push` cannot
run from this shell, with or without approval.

What to do:
  1. Stop. Do not retry the push: the hook blocks every attempt.
  2. Tell the user what you want to push and why.
  3. The user runs the push themselves, or removes the hook.

Root AGENTS.md "Git workflow" rule 2 explains the hook.
MSG
  exit 2
fi

exit 0
