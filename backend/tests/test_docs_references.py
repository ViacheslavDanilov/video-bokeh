"""Fail when a tracked doc names code that does not exist.

The vault once documented `_depth_track.py` and a "dynamic mode" for months after both were
deleted, and cited `_Z_NEAR`/`_Z_FAR` constants that never existed in the file it named.
Nothing caught either, because nothing was looking. This is the thing that looks.

Only the tracked half of the vault is checked. `meetings/`, `reports/`, `specs/` and `plans/`
record a moment in time and are allowed to name code that has since changed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SRC = _REPO / "backend" / "src"
# Everything we are responsible for. `third_party/` is vendored and read-only, so a module
# living there is listed below by hand rather than scanned -- the submodule may not be
# checked out, and a test that changes its mind based on that is worse than useless.
_OURS = (_SRC, _REPO / "backend" / "tests", _REPO / "scripts")
_VENDORED = {"inference_demo.py"}  # third_party/any-to-bokeh/test/inference_demo.py
_DOC_ROOTS = ("docs/explanation", "docs/how-to", "docs/reference")
_DOC_FILES = ("AGENTS.md", "README.md", "docs/README.md", "docs/STYLE.md")

# Any Python module the docs name: `src/data/foo.py`, `backend/src/...`, or a bare `foo.py`.
_PATH_RE = re.compile(r"\b(?:backend/)?src/[\w/]+\.py\b")
_NAME_RE = re.compile(r"\b([a-z_][\w]*\.py)\b")
# Module constants named inside backticks, which is how the docs write them:
# `_ALPHA_CHANNELS`, `_ALPHA_CHANNELS = 3`, `_Z_NEAR`/`_Z_FAR`.
_CONST_RE = re.compile(r"\b(_[A-Z][A-Z0-9_]{2,})\b")
_TICKS_RE = re.compile(r"`([^`\n]+)`")


def _tracked_docs() -> list[Path]:
    docs = [p for root in _DOC_ROOTS for p in sorted((_REPO / root).rglob("*.md"))]
    docs += [_REPO / name for name in _DOC_FILES]
    return [p for p in docs if p.is_file()]


def _sources() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in _SRC.rglob("*.py"))


@pytest.mark.parametrize("doc", _tracked_docs(), ids=lambda p: str(p.name))
def test_doc_names_only_code_that_exists(doc: Path) -> None:
    text = doc.read_text(encoding="utf-8")
    rel = doc.relative_to(_REPO)

    known_names = {f.name for root in _OURS for f in root.rglob("*.py")} | _VENDORED

    missing_paths = sorted(
        {
            m
            for m in _PATH_RE.findall(text)
            if not (_REPO / "backend" / m.removeprefix("backend/")).is_file()
        }
        | {n for n in _NAME_RE.findall(text) if n not in known_names},
    )
    assert not missing_paths, (
        f"{rel} names source files that do not exist: {missing_paths}. "
        f"Either the file moved and the doc did not follow, or the doc is inventing a path."
    )

    sources = _sources()
    named = {c for span in _TICKS_RE.findall(text) for c in _CONST_RE.findall(span)}
    missing_consts = sorted({c for c in named if c not in sources})
    assert not missing_consts, (
        f"{rel} names constants that appear nowhere in backend/src: {missing_consts}. "
        f"A renamed or deleted constant leaves the doc quietly wrong."
    )


def test_the_check_has_something_to_check() -> None:
    """Guard against the regexes silently matching nothing and the suite going green."""
    joined = "\n".join(p.read_text(encoding="utf-8") for p in _tracked_docs())
    found = (
        len(_PATH_RE.findall(joined))
        + len(_NAME_RE.findall(joined))
        + len(
            [c for span in _TICKS_RE.findall(joined) for c in _CONST_RE.findall(span)],
        )
    )
    assert found >= 5, (
        f"only {found} code references found across the tracked docs; "
        f"the extraction patterns have probably stopped matching."
    )
