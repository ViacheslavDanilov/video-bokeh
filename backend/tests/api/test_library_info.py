from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image

from video_bokeh.api._library import DuplicateLibraryError, summarize, summarize_all
from video_bokeh.core._metadata import write_asset_metadata


def test_reports_what_is_mounted(library: Path, facts) -> None:
    summary = summarize(library)
    assert summary.n_foregrounds == 2
    assert summary.n_backgrounds == 2
    assert summary.depth_estimator == facts.estimator
    assert summary.asset_size == facts.fg_size
    assert summary.name == library.name
    assert summary.root == library


def test_names_a_library_mounted_as_the_working_directory(
    library: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`VIDEO_BOKEH_LIBRARY=.` must not produce a library with an empty name."""
    monkeypatch.chdir(library)
    assert summarize(Path()).name == library.name


def test_id_is_stable_across_calls(library: Path) -> None:
    assert summarize(library).id == summarize(library).id


def test_id_moves_when_an_asset_is_added(make_library: Callable[..., Path]) -> None:
    """Decision 9: a library that changes must not keep the id every cached sequence hashes."""
    small = make_library("small", ("fg_a",), ("bg_a",))
    large = make_library("large", ("fg_a", "fg_b"), ("bg_a",))
    assert summarize(small).id != summarize(large).id


def test_id_moves_when_the_depth_estimator_changes(
    make_library: Callable[..., Path],
) -> None:
    root = make_library("lib", ("fg_a",), ("bg_a",))
    before = summarize(root).id
    write_asset_metadata(
        root / "foregrounds" / "fg_a",
        {"estimator": "da2-large", "source_ref": "xx/fg_a.png"},
    )
    assert summarize(root).id != before


def test_id_moves_when_the_asset_size_changes(
    make_library: Callable[..., Path],
) -> None:
    """A 512 px and a 1024 px build of one pool are different libraries."""
    root = make_library("lib", ("fg_a",), ("bg_a",))
    before = summarize(root).id
    rgb = root / "foregrounds" / "fg_a" / "rgb.png"
    with Image.open(rgb) as img:
        larger = img.resize((img.width * 2, img.height * 2))
    larger.save(rgb)
    assert summarize(root).id != before


def test_two_libraries_that_share_an_id_are_refused_by_name(
    make_library: Callable[..., Path],
) -> None:
    here = make_library("here", ("fg_a",), ("bg_a",))
    there = make_library("there", ("fg_a",), ("bg_a",))
    with pytest.raises(DuplicateLibraryError) as excinfo:
        summarize_all([here, there])
    assert str(here) in str(excinfo.value)
    assert str(there) in str(excinfo.value)


def test_libraries_that_differ_are_summarized_in_the_order_given(
    make_library: Callable[..., Path],
) -> None:
    a = make_library("a", ("fg_a",), ("bg_a",))
    b = make_library("b", ("fg_a",), ("bg_a",), estimator="depth-pro")
    assert [s.root for s in summarize_all([a, b])] == [a, b]


def test_id_ignores_where_the_library_sits(make_library: Callable[..., Path]) -> None:
    """The same assets under a different path are the same library, so sequences stay cached."""
    here = make_library("here", ("fg_a",), ("bg_a",))
    there = make_library("there", ("fg_a",), ("bg_a",))
    assert summarize(here).id == summarize(there).id


def test_id_is_short_enough_to_read(library: Path) -> None:
    summary = summarize(library)
    assert len(summary.id) == 12
    assert all(c in "0123456789abcdef" for c in summary.id)
