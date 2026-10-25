"""The test foregrounds are drawn per subject, in its share, the same way every time."""

from __future__ import annotations

from pathlib import Path

import pytest

from video_bokeh.library.split import draw, main, page_id

# Ten people and twenty objects, ids as Stage A names MAGICK images: folder, then page.
PEOPLE = [f"p{i}__P{i:03d}" for i in range(10)]
THINGS = [f"o{i}__O{i:03d}" for i in range(20)]
SUBJECTS = {page_id(i): "person" for i in PEOPLE} | {
    page_id(i): "object" for i in THINGS
}


def test_page_id_is_the_last_part_of_the_id() -> None:
    assert page_id("0L__0LZCNUeBHK") == "0LZCNUeBHK"


def test_each_subject_gives_its_share() -> None:
    test = draw(PEOPLE + THINGS, SUBJECTS, fraction=0.1)
    assert len(set(test) & set(PEOPLE)) == 1
    assert len(set(test) & set(THINGS)) == 2
    assert test == sorted(test)


def test_the_draw_depends_on_the_seed_alone() -> None:
    once = draw(PEOPLE + THINGS, SUBJECTS, fraction=0.2, seed=3)
    # The order the library lists its ids in does not move the draw.
    again = draw(list(reversed(PEOPLE + THINGS)), SUBJECTS, fraction=0.2, seed=3)
    assert once == again
    assert draw(PEOPLE + THINGS, SUBJECTS, fraction=0.2, seed=4) != once


def test_a_foreground_without_a_subject_is_refused() -> None:
    with pytest.raises(ValueError, match="1 foregrounds have no subject, x__X first"):
        draw([*PEOPLE, "x__X"], SUBJECTS)


def test_the_command_writes_the_list(tmp_path: Path) -> None:
    library = tmp_path / "library"
    for asset_id in PEOPLE + THINGS:
        (library / "foregrounds" / asset_id).mkdir(parents=True)
    predictions = tmp_path / "predictions.csv"
    predictions.write_text(
        "page_id,top_subject\n"
        + "".join(f"{page},{subject}\n" for page, subject in SUBJECTS.items()),
        encoding="utf-8",
    )
    out = tmp_path / "test_foregrounds.txt"
    main(
        [
            "--library-root",
            str(library),
            "--predictions",
            str(predictions),
            "--output",
            str(out),
        ],
    )
    assert out.read_text(encoding="utf-8").splitlines() == draw(
        PEOPLE + THINGS, SUBJECTS
    )
