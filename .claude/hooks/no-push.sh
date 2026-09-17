#!/usr/bin/env bash
# PreToolUse hook: block `git push` so the human stays in control of what hits the remote.
# Exits 2 (blocking) when a push is detected. Bypass: ask the user to run the push themselves.

set -euo pipefail

cmd=$(python3 -c 'import json, sys; print(json.load(sys.stdin).get("tool_input", {}).get("command", ""))')

# Match `git push` at the start of the command, after whitespace, or after a shell separator.
# Catches: `git push`, `cd x && git push`, `foo; git push --force`, multi-line scripts.
# Does not catch: `git push` inside quoted strings, but that's edge-case enough to ignore.
if printf '%s\n' "$cmd" | grep -Eq '(^|[[:space:]]|;|&&|\|\|)git[[:space:]]+push([[:space:]]|$)'; then
  cat >&2 <<'MSG'
BLOCKED: this project requires explicit user approval before `git push`.

What to do:
  1. Stop. Do not retry the push.
  2. Tell the user what you want to push and why.
  3. Wait for their explicit go-ahead, then re-run the push.

See AGENTS.md "Git workflow" for the full rule.
MSG
  exit 2
fi

exit 0
