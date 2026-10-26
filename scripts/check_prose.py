"""Flag prose in changed Markdown that reads as machine-written.

    python3 scripts/check_prose.py                  # Markdown changed since origin/main
    python3 scripts/check_prose.py --base main~3    # changed since another commit
    python3 scripts/check_prose.py docs/STYLE.md    # these files, every paragraph

Two checks run on each paragraph a change touches. The em dash is found locally, with no
network. The other asks Jev, TypeSafe's classifier, how likely the paragraph is to read
as machine-written, and reports those at ``--threshold`` or above. That needs
``TYPESAFE_API_KEY``; without it the script says so and runs the local check alone, so a
review never fails for want of a key. Paragraphs go to api.typesafe.ai, so run it on
public text only.

It prints one line per flagged paragraph and exits 0, or 1 with ``--strict`` when
anything was flagged. Only the standard library is used, so it runs with any Python 3.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

API = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
THRESHOLD = 0.6
#: Paragraphs shorter than this many words say too little to judge.
MIN_WORDS = 12
EM_DASH = "—"
QUESTION = (
    "Does `paragraph` read as machine-written (generic filler, inflated or vague claims, "
    "stock AI phrasing, needless dramatic structure) rather than plain technical prose a "
    "person wrote? Judge the writing, not the topic; terse or technical is not "
    "machine-like."
)
#: Lines that hold no prose: headings, tables, HTML, images, front-matter fences.
_NOT_PROSE = ("#", "|", "<", "![", "---")
_ITEM = re.compile(r"^([-*]|\d+\.) ")


def paragraphs(text: str) -> list[tuple[int, int, str]]:
    """The prose paragraphs of a Markdown text, as (first line, last line, text).

    A paragraph is a run of prose lines; each list item starts one. Fenced code, front
    matter, headings, tables, HTML and images are left out.
    """
    lines = text.splitlines()
    start_at = 0
    if lines and lines[0].strip() == "---":
        end = next((i for i, x in enumerate(lines[1:], 1) if x.strip() == "---"), 0)
        start_at = end + 1
    found: list[tuple[int, int, str]] = []
    cur: list[str] = []
    first = last = 0
    fence = False

    def close() -> None:
        if cur:
            found.append((first, last, " ".join(cur)))
            cur.clear()

    for n, line in enumerate(lines[start_at:], start_at + 1):
        s = line.strip()
        if s.startswith("```"):
            close()
            fence = not fence
            continue
        if fence or not s or s.startswith(_NOT_PROSE):
            close()
            continue
        if _ITEM.match(s) or s.startswith("> "):
            close()
            s = re.sub(r"^([-*]|\d+\.|>) ", "", s)
        if not cur:
            first = n
        cur.append(s)
        last = n
    close()
    return found


def changed_lines(path: str, base: str) -> set[int]:
    """The line numbers of ``path`` that differ from ``base``, as git's diff names them."""
    diff = subprocess.run(
        ["git", "diff", "--unified=0", f"{base}...HEAD", "--", path],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    lines: set[int] = set()
    for match in re.finditer(r"^@@ .* \+(\d+)(?:,(\d+))? @@", diff, re.M):
        start, count = int(match[1]), int(match[2] or 1)
        lines.update(range(start, start + count))
    return lines


def changed_markdown(base: str) -> list[str]:
    out = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--diff-filter=AM",
            f"{base}...HEAD",
            "--",
            "*.md",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [p for p in out.splitlines() if p]


def ask_jev(text: str, key: str) -> float | None:
    """Jev's probability that ``text`` reads as machine-written, or None if it failed."""
    body = {
        "model": MODEL,
        "state": {"paragraph": text},
        "questions": {"ai": {"type": "noul", "instructions": QUESTION}},
    }
    request = urllib.request.Request(
        API,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)["answers"]["ai"]["noul"]
        except (OSError, KeyError, ValueError):
            time.sleep(2**attempt)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("files", nargs="*", help="check every paragraph of these files")
    parser.add_argument(
        "--base", default="origin/main", help="compare with this commit"
    )
    parser.add_argument("--threshold", type=float, default=THRESHOLD)
    parser.add_argument(
        "--strict", action="store_true", help="exit 1 if anything is flagged"
    )
    args = parser.parse_args(argv)

    targets: list[tuple[str, int, str]] = []
    for path in args.files or changed_markdown(args.base):
        wanted = None if args.files else changed_lines(path, args.base)
        for first, last, text in paragraphs(Path(path).read_text(encoding="utf-8")):
            if wanted is None or wanted & set(range(first, last + 1)):
                targets.append((path, first, text))

    flagged = [
        f"{path}:{line}: em dash: {text[:100]}"
        for path, line, text in targets
        if EM_DASH in text
    ]
    key = os.environ.get("TYPESAFE_API_KEY")
    judged = [t for t in targets if len(t[2].split()) >= MIN_WORDS]
    if not key:
        print("TYPESAFE_API_KEY is not set: checked the em dash only", file=sys.stderr)
    elif judged:
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            scores = list(pool.map(lambda t: ask_jev(t[2], key), judged))
        failed = sum(s is None for s in scores)
        if failed:
            print(f"Jev did not answer for {failed} paragraphs", file=sys.stderr)
        flagged += [
            f"{path}:{line}: reads as machine-written ({score:.2f}): {text[:100]}"
            for (path, line, text), score in sorted(
                zip(judged, scores, strict=True), key=lambda pair: -(pair[1] or 0)
            )
            if score is not None and score >= args.threshold
        ]
    print("\n".join(flagged) if flagged else f"{len(targets)} paragraphs, none flagged")
    return 1 if flagged and args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
