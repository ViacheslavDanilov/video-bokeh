"""scripts/check_prose.py finds the prose a change touches and flags the em dash offline."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_prose.py"


@pytest.fixture(scope="module")
def check_prose():
    spec = importlib.util.spec_from_file_location("check_prose", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_prose"] = module
    spec.loader.exec_module(module)
    return module


def test_paragraphs_skip_what_is_not_prose(check_prose) -> None:
    text = """---
title: x
---

# A heading

First line of a paragraph
and its second line.

```bash
echo code
```

| a | b |
|---|---|

- an item
- another item

Last words.
"""
    assert check_prose.paragraphs(text) == [
        (7, 8, "First line of a paragraph and its second line."),
        (17, 17, "an item"),
        (18, 18, "another item"),
        (20, 20, "Last words."),
    ]


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def test_only_paragraphs_a_change_touches_are_checked(
    check_prose, tmp_path: Path, monkeypatch, capsys
) -> None:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "a@b.c")
    _git(tmp_path, "config", "user.name", "A")
    page = tmp_path / "page.md"
    page.write_text("An old paragraph — left alone.\n\nA second one.\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "first")
    _git(tmp_path, "checkout", "-q", "-b", "change")
    page.write_text("An old paragraph — left alone.\n\nA second one — edited.\n")
    _git(tmp_path, "commit", "-q", "-am", "second")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    status = check_prose.main(["--base", "main", "--strict"])

    out = capsys.readouterr()
    assert status == 1
    assert out.out.splitlines() == ["page.md:3: em dash: A second one — edited."]
    assert "TYPESAFE_API_KEY is not set" in out.err


def test_clean_text_passes_without_a_key(
    check_prose, tmp_path: Path, monkeypatch, capsys
) -> None:
    page = tmp_path / "page.md"
    page.write_text("Plain words, with a comma and a colon: nothing else.\n")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    assert check_prose.main([str(page), "--strict"]) == 0
    assert "1 paragraphs, none flagged" in capsys.readouterr().out
