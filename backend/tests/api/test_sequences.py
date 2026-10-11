from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from video_bokeh.api._sequences import SequenceRequest, ensure_sequence, sequence_id

BASE = SequenceRequest(seed=0, frames=3, size=64, n_objects_min=1, n_objects_max=2)


def test_id_is_short_enough_to_put_in_a_path() -> None:
    sid = sequence_id("libaaa", BASE)
    assert len(sid) == 16
    assert all(c in "0123456789abcdef" for c in sid)


def test_same_request_is_the_same_sequence() -> None:
    assert sequence_id("libaaa", BASE) == sequence_id("libaaa", BASE)


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
    assert sequence_id("libaaa", replace(BASE, **{field: value})) != sequence_id(
        "libaaa",
        BASE,
    )


def test_a_different_library_is_a_different_sequence() -> None:
    """The whole point of decision 9: the same seed against new assets is a new sequence."""
    assert sequence_id("libaaa", BASE) != sequence_id("libbbb", BASE)


def test_writes_the_three_streams(library: Path, tmp_path: Path) -> None:
    sequences = tmp_path / "sequences"
    result = ensure_sequence(library, "libaaa", sequences, BASE)

    assert result.cached is False
    assert result.path == sequences / result.id
    for stream in ("all_in_focus", "alpha", "disparity"):
        frames = sorted((result.path / stream).iterdir())
        assert len(frames) == BASE.frames, stream


def test_writes_the_flow_of_every_frame_but_the_last(
    library: Path,
    tmp_path: Path,
) -> None:
    result = ensure_sequence(library, "libaaa", tmp_path / "sequences", BASE)
    frames = sorted(p.name for p in (result.path / "all_in_focus").iterdir())
    flows = sorted(p.name for p in (result.path / "flow").iterdir())
    assert flows == frames[:-1]


def test_reports_how_many_objects_it_placed(library: Path, tmp_path: Path) -> None:
    result = ensure_sequence(library, "libaaa", tmp_path / "sequences", BASE)
    assert BASE.n_objects_min <= result.n_objects <= BASE.n_objects_max


def test_second_request_is_served_from_disk(library: Path, tmp_path: Path) -> None:
    sequences = tmp_path / "sequences"
    first = ensure_sequence(library, "libaaa", sequences, BASE)
    stamp = (first.path / "all_in_focus").stat().st_mtime_ns

    second = ensure_sequence(library, "libaaa", sequences, BASE)

    assert second.cached is True
    assert second.id == first.id
    assert (second.path / "all_in_focus").stat().st_mtime_ns == stamp


def test_leaves_no_temporary_directories_behind(library: Path, tmp_path: Path) -> None:
    sequences = tmp_path / "sequences"
    ensure_sequence(library, "libaaa", sequences, BASE)
    assert [p.name for p in sequences.iterdir() if p.name.startswith(".tmp-")] == []


def test_a_half_written_sequence_is_never_visible(
    library: Path,
    tmp_path: Path,
) -> None:
    """A crash during generation must not leave a directory that later looks cached."""
    sequences = tmp_path / "sequences"
    with pytest.raises(RuntimeError, match="boom"):
        ensure_sequence(library, "libaaa", sequences, BASE, _render=_explode)
    assert list(sequences.iterdir()) == []


def _explode(*args: object, **kwargs: object) -> None:
    raise RuntimeError("boom")


def test_matches_what_the_cli_writes_for_the_same_seed(
    library: Path,
    tmp_path: Path,
) -> None:
    """The API and video_bokeh.scenes.generate must not drift into different sequences.

    They share sample_sequence for exactly this reason: a seed that means four
    objects on the command line has to mean four objects over HTTP.
    """
    from video_bokeh.scenes.generate import generate_dataset

    api = ensure_sequence(library, "libaaa", tmp_path / "sequences", BASE)

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


# --- progress -------------------------------------------------------------- #


def _recorder() -> tuple[list[tuple[str, int, int]], Callable[[str, int, int], None]]:
    events: list[tuple[str, int, int]] = []
    return events, lambda step, done, total: events.append((step, done, total))


def _last(events: list[tuple[str, int, int]], step: str) -> tuple[str, int, int]:
    return [e for e in events if e[0] == step][-1]


def test_reports_each_step_as_it_goes(library: Path, tmp_path: Path) -> None:
    events, progress = _recorder()
    ensure_sequence(library, "libaaa", tmp_path / "sequences", BASE, progress=progress)

    steps = [step for step, _, _ in events]
    assert steps[0] == "sampling"
    assert _last(events, "sampling") == ("sampling", 1, 1)
    frames = [done for step, done, _ in events if step == "frames"]
    assert frames == list(range(BASE.frames + 1))
    assert _last(events, "writing") == ("writing", BASE.frames, BASE.frames)
    # In that order: every frame rendered before the first is written.
    assert steps.index("writing") > len(steps) - 1 - steps[::-1].index("frames")


def test_reports_the_bokeh_frame_by_frame(library: Path, tmp_path: Path) -> None:
    events, progress = _recorder()
    ensure_sequence(
        library,
        "libaaa",
        tmp_path / "sequences",
        BASE,
        bokeh=True,
        progress=progress,
    )
    assert _last(events, "bokeh") == ("bokeh", BASE.frames, BASE.frames)
    assert [step for step, _, _ in events][-1] == "bokeh"


def test_a_cached_sequence_reports_nothing(library: Path, tmp_path: Path) -> None:
    sequences = tmp_path / "sequences"
    ensure_sequence(library, "libaaa", sequences, BASE)
    events, progress = _recorder()
    ensure_sequence(library, "libaaa", sequences, BASE, progress=progress)
    assert events == []


def test_a_cached_sequence_reports_adding_its_flow(
    library: Path,
    tmp_path: Path,
) -> None:
    sequences = tmp_path / "sequences"
    first = ensure_sequence(library, "libaaa", sequences, BASE)
    shutil.rmtree(first.path / "flow")
    events, progress = _recorder()
    ensure_sequence(library, "libaaa", sequences, BASE, progress=progress)
    assert _last(events, "flow") == ("flow", BASE.frames - 1, BASE.frames - 1)


def test_a_cached_sequence_samples_once_to_add_flow_and_bokeh(
    library: Path,
    tmp_path: Path,
) -> None:
    sequences = tmp_path / "sequences"
    first = ensure_sequence(library, "libaaa", sequences, BASE)
    shutil.rmtree(first.path / "flow")
    events, progress = _recorder()
    ensure_sequence(library, "libaaa", sequences, BASE, bokeh=True, progress=progress)
    steps = [step for step, _, _ in events]
    assert steps.count("sampling") == 2, "one scene: started and finished, once"
    assert _last(events, "flow") == ("flow", BASE.frames - 1, BASE.frames - 1)
    assert _last(events, "bokeh") == ("bokeh", BASE.frames, BASE.frames)


# --- plan ------------------------------------------------------------------ #


def _reported(events: list[tuple[str, int, int]]) -> list[tuple[str, int]]:
    """Each step reported, in the order it began, with the total it counted to."""
    totals: dict[str, int] = {}
    for step, _, total in events:
        totals[step] = total
    return list(totals.items())


@pytest.mark.parametrize("bokeh", [False, True])
def test_announces_the_steps_it_reports_before_the_first(
    library: Path,
    tmp_path: Path,
    bokeh: bool,
) -> None:
    """What lets a client draw one bar for the whole generation."""
    events, progress = _recorder()
    plans: list[list[tuple[str, int]]] = []

    def plan(steps: list[tuple[str, int]]) -> None:
        assert events == [], "announced before the first step"
        plans.append(steps)

    ensure_sequence(
        library,
        "libaaa",
        tmp_path / "sequences",
        BASE,
        bokeh=bokeh,
        progress=progress,
        plan=plan,
    )
    assert plans == [_reported(events)]


@pytest.mark.parametrize(
    "missing_flow,bokeh",
    [(True, False), (False, True), (True, True)],
)
def test_a_cached_sequence_announces_what_it_adds(
    library: Path,
    tmp_path: Path,
    missing_flow: bool,
    bokeh: bool,
) -> None:
    sequences = tmp_path / "sequences"
    first = ensure_sequence(library, "libaaa", sequences, BASE)
    if missing_flow:
        shutil.rmtree(first.path / "flow")
    events, progress = _recorder()
    plans: list[list[tuple[str, int]]] = []
    ensure_sequence(
        library,
        "libaaa",
        sequences,
        BASE,
        bokeh=bokeh,
        progress=progress,
        plan=plans.append,
    )
    assert plans == [_reported(events)]


def test_a_cached_sequence_announces_nothing(library: Path, tmp_path: Path) -> None:
    sequences = tmp_path / "sequences"
    ensure_sequence(library, "libaaa", sequences, BASE)
    plans: list[list[tuple[str, int]]] = []
    ensure_sequence(library, "libaaa", sequences, BASE, plan=plans.append)
    assert plans == []
