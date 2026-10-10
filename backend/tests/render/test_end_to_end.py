"""Stage B writes a sequence's bokeh in the same run, from the layers it holds in memory."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from video_bokeh.render.layered import Layered
from video_bokeh.scenes.generate import generate_dataset, main

FRAMES, SIZE = 4, 64


def _sequences(root: Path) -> list[Path]:
    return sorted((root / "sequences").iterdir())


def _pixels(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im, dtype=np.float32)


def test_writes_the_bokeh_in_the_same_run(library: Path, tmp_path: Path) -> None:
    out = tmp_path / "data"
    generate_dataset(library, out, 2, FRAMES, SIZE, seed=0, n_objects_max=2, bokeh=True)
    for seq in _sequences(out):
        names = sorted(p.name for p in (seq / "all_in_focus").glob("*.png"))
        assert sorted(p.name for p in (seq / "bokeh").glob("*.png")) == names
        record = json.loads((seq / "bokeh" / "focus.json").read_text())
        assert record["renderer"] == "layered"
        assert record["strength"] == 16
        assert len(record["zf"]) == FRAMES
        assert not (seq / "layers").exists()  # the layers stay in memory


def test_matches_stage_c_over_the_written_layers(library: Path, tmp_path: Path) -> None:
    out = tmp_path / "data"
    generate_dataset(
        library,
        out,
        2,
        FRAMES,
        SIZE,
        seed=0,
        n_objects_max=2,
        layers=True,
        bokeh=True,
    )
    seqs = _sequences(out)
    for seq in seqs:
        shutil.move(seq / "bokeh", seq / "end_to_end")
    Layered().render(seqs, 16.0, None)
    for seq in seqs:
        mine = json.loads((seq / "end_to_end" / "focus.json").read_text())
        stage_c = json.loads((seq / "bokeh" / "focus.json").read_text())
        assert mine["object"] == stage_c["object"]
        # Stage C reads layers stored at 8 and 16 bits; this run held them as floats.
        assert mine["zf"] == pytest.approx(stage_c["zf"], abs=1e-3)
        for frame in sorted((seq / "bokeh").glob("*.png")):
            assert (
                np.abs(_pixels(seq / "end_to_end" / frame.name) - _pixels(frame)).max()
                <= 3.0
            )


def test_the_command_line_takes_the_bokeh_and_its_strength(
    library: Path,
    tmp_path: Path,
) -> None:
    out = tmp_path / "data"
    main(
        [
            "--library-root",
            str(library),
            "--output",
            str(out),
            "--count",
            "1",
            "--frames",
            str(FRAMES),
            "--size",
            str(SIZE),
            "--bokeh",
            "--bokeh-strength",
            "0",
        ],
    )
    (seq,) = _sequences(out)
    assert json.loads((seq / "bokeh" / "focus.json").read_text())["strength"] == 0
    for frame in sorted((seq / "all_in_focus").glob("*.png")):
        assert np.abs(_pixels(seq / "bokeh" / frame.name) - _pixels(frame)).max() <= 1.0


def test_focuses_where_the_loader_does_for_the_same_seed(
    library: Path,
    tmp_path: Path,
) -> None:
    from video_bokeh.loader import SequenceStream

    out = tmp_path / "data"
    generate_dataset(library, out, 1, FRAMES, SIZE, seed=1, n_objects_max=2, bokeh=True)
    (seq,) = _sequences(out)
    record = json.loads((seq / "bokeh" / "focus.json").read_text())
    stream = SequenceStream(
        library,
        n_frames=FRAMES,
        size=SIZE,
        n_objects_max=2,
        seed=1,
        streams=("focus",),
    )
    item = next(iter(stream))
    assert item["focus_object"] == (
        -1 if record["object"] is None else record["object"]
    )
    assert item["focus_disparity"].tolist() == pytest.approx(record["zf"], abs=1e-6)


def test_bokeh_without_torch_is_refused_before_anything_is_written(
    library: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib.util

    real = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a: None if name == "torch" else real(name, *a),
    )
    with pytest.raises(ValueError, match="torch"):
        generate_dataset(
            library,
            tmp_path / "data",
            1,
            FRAMES,
            SIZE,
            seed=0,
            bokeh=True,
        )
    assert not (tmp_path / "data").exists()
