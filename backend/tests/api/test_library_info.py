from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from video_bokeh.api._library import summarize
from video_bokeh.core._metadata import write_asset_metadata


def test_reports_what_is_mounted(library: Path, facts) -> None:
    summary = summarize(library)
    assert summary.n_foregrounds == 2
    assert summary.n_backgrounds == 2
    assert summary.depth_model == facts.estimator
    assert summary.asset_size == facts.fg_size


def test_id_is_stable_across_calls(library: Path) -> None:
    assert summarize(library).id == summarize(library).id


def test_id_moves_when_an_asset_is_added(make_library: Callable[..., Path]) -> None:
    """Decision 9: a library that changes must not keep the id every cached scene hashes."""
    small = make_library("small", ("fg_a",), ("bg_a",))
    large = make_library("large", ("fg_a", "fg_b"), ("bg_a",))
    assert summarize(small).id != summarize(large).id


def test_id_moves_when_the_depth_model_changes(
    make_library: Callable[..., Path],
) -> None:
    root = make_library("lib", ("fg_a",), ("bg_a",))
    before = summarize(root).id
    write_asset_metadata(
        root / "foregrounds" / "fg_a",
        {"estimator": "da2-large", "source_ref": "xx/fg_a.png"},
    )
    assert summarize(root).id != before


def test_id_ignores_where_the_library_sits(make_library: Callable[..., Path]) -> None:
    """The same assets under a different path are the same library, so scenes stay cached."""
    here = make_library("here", ("fg_a",), ("bg_a",))
    there = make_library("there", ("fg_a",), ("bg_a",))
    assert summarize(here).id == summarize(there).id


def test_id_is_short_enough_to_read(library: Path) -> None:
    summary = summarize(library)
    assert len(summary.id) == 12
    assert all(c in "0123456789abcdef" for c in summary.id)
