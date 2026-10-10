"""Stage C through the layered renderer, over sequences written with their layers."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from video_bokeh.bridge.any_to_bokeh import write_inputs
from video_bokeh.render import RENDERERS
from video_bokeh.render import run as cli
from video_bokeh.render.layered import Layered
from video_bokeh.scenes.generate import generate_dataset

FRAMES, SIZE = 4, 64


@pytest.fixture
def dataset(library: Path, tmp_path: Path) -> Path:
    out = tmp_path / "data"
    generate_dataset(
        library,
        out,
        count=3,
        n_frames=FRAMES,
        size=SIZE,
        seed=0,
        n_objects_max=2,
        layers=True,
    )
    return out


def _sequences(root: Path) -> list[Path]:
    return sorted((root / "sequences").iterdir())


def _pixels(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im, dtype=np.float32)


def test_is_registered() -> None:
    assert RENDERERS["layered"] is Layered


def test_writes_every_frame_and_records_what_made_them(dataset: Path) -> None:
    assert cli.main(["--data-root", str(dataset), "--renderer", "layered"]) == 0
    for seq in _sequences(dataset):
        names = sorted(p.name for p in (seq / "all_in_focus").glob("*.png"))
        assert sorted(p.name for p in (seq / "bokeh").glob("*.png")) == names
        with Image.open(seq / "bokeh" / names[0]) as im:
            assert (im.mode, im.size) == ("RGB", (SIZE, SIZE))
        record = json.loads((seq / "bokeh" / "focus.json").read_text())
        assert record["renderer"] == "layered"
        assert record["strength"] == 16
        assert record["gamma"] == 2.2 and record["radius_step"] == 1.0
        assert len(record["zf"]) == FRAMES
        assert not list(seq.glob(".bokeh-*"))


def test_is_what_stage_c_runs_unless_told_otherwise(dataset: Path) -> None:
    assert cli.main(["--data-root", str(dataset)]) == 0
    for seq in _sequences(dataset):
        record = json.loads((seq / "bokeh" / "focus.json").read_text())
        assert record["renderer"] == "layered"


def test_zero_strength_gives_back_the_all_in_focus_frames(dataset: Path) -> None:
    cli.main(["--data-root", str(dataset), "--renderer", "layered", "--strength", "0"])
    for seq in _sequences(dataset):
        for frame in sorted((seq / "all_in_focus").glob("*.png")):
            bokeh = _pixels(seq / "bokeh" / frame.name)
            # The layers are stored to 8 bits on their own, as the frame is.
            assert np.abs(bokeh - _pixels(frame)).max() <= 2.0


def test_focuses_where_any_to_bokeh_would(dataset: Path, tmp_path: Path) -> None:
    cli.main(["--data-root", str(dataset), "--renderer", "layered"])
    seqs = _sequences(dataset)
    bridged = write_inputs(
        seqs,
        tmp_path / "v",
        tmp_path / "d",
        tmp_path / "a.csv",
        "16",
    )
    for seq, inputs in zip(seqs, bridged, strict=True):
        record = json.loads((seq / "bokeh" / "focus.json").read_text())
        assert record["object"] == inputs.focus_object
        # The bridge reads the disparity at 8 bits, the layered renderer at 16.
        assert record["zf"] == pytest.approx(inputs.zf, abs=1 / 255)


def test_a_pinned_focus_holds_in_every_frame(dataset: Path) -> None:
    cli.main(
        [
            "--data-root",
            str(dataset),
            "--renderer",
            "layered",
            "--focus-disparity",
            "0.5",
        ],
    )
    for seq in _sequences(dataset):
        record = json.loads((seq / "bokeh" / "focus.json").read_text())
        assert record["object"] is None
        assert record["zf"] == [0.5] * FRAMES


@pytest.mark.parametrize("damage", ["no layers", "interrupted"])
def test_a_sequence_without_complete_layers_is_refused_before_any_is_rendered(
    dataset: Path,
    damage: str,
) -> None:
    seqs = _sequences(dataset)
    layers = seqs[1] / "layers"
    if damage == "no layers":
        shutil.rmtree(layers)
    else:
        (layers / "paint_order.json").unlink()
    with pytest.raises(ValueError, match=f"{seqs[1].name}.*--layers"):
        Layered().render(seqs, 16.0, None)
    assert not any((seq / "bokeh").exists() for seq in seqs)


def test_missing_leaves_out_a_sequence_without_layers(
    dataset: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seqs = _sequences(dataset)
    shutil.rmtree(seqs[1] / "layers")
    args = ["--data-root", str(dataset), "--renderer", "layered", "--missing"]
    assert cli.main(args) == 0
    assert (seqs[0] / "bokeh").is_dir() and (seqs[2] / "bokeh").is_dir()
    assert not (seqs[1] / "bokeh").exists()
    assert f"skip {seqs[1].name}" in capsys.readouterr().out
