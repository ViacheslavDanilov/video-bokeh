"""scripts/check_prose.py finds the prose a change touches and flags the em dash offline."""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import urllib.error
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_prose.py"


@pytest.fixture(scope="module")
def check_prose():
    spec = importlib.util.spec_from_file_location("check_prose", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
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

> A quote that runs
> over two lines.
>
> A second quoted paragraph.

Last words.
"""
    assert check_prose.paragraphs(text) == [
        (7, 8, "First line of a paragraph and its second line."),
        (17, 17, "an item"),
        (18, 18, "another item"),
        (20, 21, "A quote that runs over two lines."),
        (23, 23, "A second quoted paragraph."),
        (25, 25, "Last words."),
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


def _repo(root: Path) -> None:
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "a@b.c")
    _git(root, "config", "user.name", "A")


def test_a_renamed_page_is_still_checked(
    check_prose, tmp_path: Path, monkeypatch, capsys
) -> None:
    _repo(tmp_path)
    (tmp_path / "old.md").write_text("Plain words.\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "first")
    _git(tmp_path, "checkout", "-q", "-b", "change")
    _git(tmp_path, "mv", "old.md", "caf\u00e9.md")
    (tmp_path / "caf\u00e9.md").write_text("Plain words \u2014 and a dash.\n")
    _git(tmp_path, "commit", "-q", "-am", "move")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    check_prose.main(["--base", "main"])

    assert "caf\u00e9.md:1: em dash" in capsys.readouterr().out


class _Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def test_jev_scores_flag_what_reads_as_machine_written(
    check_prose, tmp_path: Path, monkeypatch, capsys
) -> None:
    page = tmp_path / "page.md"
    page.write_text(
        "This robust and seamless pipeline truly empowers every researcher who"
        " uses it.\n\nThe loader reads one shard at a time and unpacks each item"
        " into the library folder.\n"
    )

    def urlopen(request, timeout):
        text = json.loads(request.data)["state"]["paragraph"]
        noul = 0.9 if "robust" in text else 0.1
        return _Answer(json.dumps({"answers": {"ai": {"noul": noul}}}).encode())

    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setattr(check_prose.urllib.request, "urlopen", urlopen)

    assert check_prose.main([str(page), "--strict"]) == 1
    out = capsys.readouterr().out.splitlines()
    assert out == [
        f"{page}:1: reads as machine-written (0.90): This robust and seamless"
        " pipeline truly empowers every researcher who uses it."
    ]


def test_a_refused_key_falls_back_to_the_dash_check(
    check_prose, tmp_path: Path, monkeypatch, capsys
) -> None:
    page = tmp_path / "page.md"
    page.write_text(
        "\n\n".join(
            f"Paragraph {n} reads one shard at a time and unpacks each item into"
            " the library folder, then deletes the shard."
            for n in range(40)
        )
        + "\n"
    )
    calls = []

    def urlopen(request, timeout):
        calls.append(1)
        raise urllib.error.HTTPError(check_prose.API, 401, "Unauthorized", {}, None)

    monkeypatch.setenv("TYPESAFE_API_KEY", "wrong")
    monkeypatch.setattr(check_prose.urllib.request, "urlopen", urlopen)

    assert check_prose.main([str(page), "--strict"]) == 0
    out = capsys.readouterr()
    assert "HTTP 401: checked the em dash only" in out.err
    assert len(calls) <= 8  # at most the requests already in flight
