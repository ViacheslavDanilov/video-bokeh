from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from video_bokeh.api._scenes import SceneRequest, ensure_scene, scene_id

BASE = SceneRequest(seed=0, frames=3, size=64, n_objects_min=1, n_objects_max=2)


def test_id_is_short_enough_to_put_in_a_path() -> None:
    sid = scene_id("libaaa", BASE)
    assert len(sid) == 16
    assert all(c in "0123456789abcdef" for c in sid)


def test_same_request_is_the_same_scene() -> None:
    assert scene_id("libaaa", BASE) == scene_id("libaaa", BASE)


@pytest.mark.parametrize(
    "field,value",
    [
        ("seed", 1),
        ("frames", 4),
        ("size", 128),
        ("n_objects_min", 2),
        ("n_objects_max", 3),
    ],
)
def test_every_parameter_changes_the_id(field: str, value: int) -> None:
    assert scene_id("libaaa", replace(BASE, **{field: value})) != scene_id(
        "libaaa",
        BASE,
    )


def test_a_different_library_is_a_different_scene() -> None:
    """The whole point of decision 9: the same seed against new assets is a new scene."""
    assert scene_id("libaaa", BASE) != scene_id("libbbb", BASE)


def test_writes_the_three_streams(library: Path, tmp_path: Path) -> None:
    scenes = tmp_path / "scenes"
    result = ensure_scene(library, "libaaa", scenes, BASE)

    assert result.cached is False
    assert result.path == scenes / result.id
    for stream in ("all_in_focus", "alpha", "disparity"):
        frames = sorted((result.path / stream).iterdir())
        assert len(frames) == BASE.frames, stream


def test_reports_how_many_objects_it_placed(library: Path, tmp_path: Path) -> None:
    result = ensure_scene(library, "libaaa", tmp_path / "scenes", BASE)
    assert BASE.n_objects_min <= result.n_objects <= BASE.n_objects_max


def test_second_request_is_served_from_disk(library: Path, tmp_path: Path) -> None:
    scenes = tmp_path / "scenes"
    first = ensure_scene(library, "libaaa", scenes, BASE)
    stamp = (first.path / "all_in_focus").stat().st_mtime_ns

    second = ensure_scene(library, "libaaa", scenes, BASE)

    assert second.cached is True
    assert second.id == first.id
    assert (second.path / "all_in_focus").stat().st_mtime_ns == stamp


def test_leaves_no_temporary_directories_behind(library: Path, tmp_path: Path) -> None:
    scenes = tmp_path / "scenes"
    ensure_scene(library, "libaaa", scenes, BASE)
    assert [p.name for p in scenes.iterdir() if p.name.startswith(".tmp-")] == []


def test_a_half_written_scene_is_never_visible(library: Path, tmp_path: Path) -> None:
    """A crash during generation must not leave a directory that later looks cached."""
    scenes = tmp_path / "scenes"
    with pytest.raises(RuntimeError, match="boom"):
        ensure_scene(library, "libaaa", scenes, BASE, _render=_explode)
    assert list(scenes.iterdir()) == []


def _explode(*args: object, **kwargs: object) -> None:
    raise RuntimeError("boom")


def test_matches_what_the_cli_writes_for_the_same_seed(
    library: Path,
    tmp_path: Path,
) -> None:
    """The API and video_bokeh.scenes.generate must not drift into different scenes.

    They share sample_n_objects for exactly this reason: a seed that means four
    objects on the command line has to mean four objects over HTTP.
    """
    from video_bokeh.scenes.generate import generate_dataset

    api = ensure_scene(library, "libaaa", tmp_path / "scenes", BASE)

    cli_root = tmp_path / "cli"
    generate_dataset(
        library_root=library,
        output=cli_root,
        count=1,
        n_frames=BASE.frames,
        size=BASE.size,
        seed=BASE.seed,
        n_objects_min=BASE.n_objects_min,
        n_objects_max=BASE.n_objects_max,
    )
    cli = cli_root / "sequences" / "0001"

    for stream in ("all_in_focus", "alpha", "disparity"):
        api_frames = sorted((api.path / stream).iterdir())
        cli_frames = sorted((cli / stream).iterdir())
        assert [p.name for p in api_frames] == [p.name for p in cli_frames], stream
        for a, c in zip(api_frames, cli_frames, strict=True):
            assert a.read_bytes() == c.read_bytes(), f"{stream}/{a.name}"
