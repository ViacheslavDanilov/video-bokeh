"""``render.run`` through the layered renderer, over sequences written with their layers."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from video_bokeh.core._streams import read_alpha_tiff, read_disparity_png
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


def _objects(seq: Path) -> list[np.ndarray]:
    return read_alpha_tiff(next((seq / "alpha").glob("*.tif")))


def _pixels(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im, dtype=np.float32)


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


def test_is_what_render_run_uses_unless_told_otherwise(dataset: Path) -> None:
    assert cli.main(["--data-root", str(dataset)]) == 0
    for seq in _sequences(dataset):
        record = json.loads((seq / "bokeh" / "focus.json").read_text())
        assert record["renderer"] == "layered"


def test_render_run_without_layers_says_what_to_do_instead_of_a_traceback(
    dataset: Path,
) -> None:
    seqs = _sequences(dataset)
    shutil.rmtree(seqs[1] / "layers")
    with pytest.raises(SystemExit) as exit_:
        cli.main(["--data-root", str(dataset)])
    message = str(exit_.value)
    assert seqs[1].name in message and seqs[0].name not in message
    assert "--layers" in message and "--bokeh" in message
    assert not any((seq / "bokeh").exists() for seq in seqs)


def test_zero_strength_gives_back_the_all_in_focus_frames(dataset: Path) -> None:
    cli.main(["--data-root", str(dataset), "--renderer", "layered", "--strength", "0"])
    for seq in _sequences(dataset):
        for frame in sorted((seq / "all_in_focus").glob("*.png")):
            bokeh = _pixels(seq / "bokeh" / frame.name)
            # The layers are stored to 8 bits on their own, as the frame is.
            assert np.abs(bokeh - _pixels(frame)).max() <= 2.0


def test_focuses_where_the_same_run_would(
    dataset: Path,
    library: Path,
    tmp_path: Path,
) -> None:
    """``render.run`` over written layers draws the object the same scene draws when its
    bokeh is rendered in the run that wrote it, so a dataset's bokeh can be rendered again.
    """
    cli.main(["--data-root", str(dataset), "--renderer", "layered"])
    same_run = tmp_path / "same_run"
    generate_dataset(
        library,
        same_run,
        count=3,
        n_frames=FRAMES,
        size=SIZE,
        seed=0,
        n_objects_max=2,
        bokeh=True,
    )
    for seq, other in zip(_sequences(dataset), _sequences(same_run), strict=True):
        record = json.loads((seq / "bokeh" / "focus.json").read_text())
        expected = json.loads((other / "bokeh" / "focus.json").read_text())
        assert record["object"] == expected["object"]
        # The same run reads the disparity in memory, ``render.run`` from 16-bit PNGs.
        assert record["zf"] == pytest.approx(expected["zf"], abs=1e-3)


@pytest.mark.parametrize("focus", ["-0.1", "1.1", "nan"])
def test_a_focus_outside_the_unit_range_is_refused_before_rendering(
    dataset: Path,
    focus: str,
) -> None:
    with pytest.raises(SystemExit):
        cli.main(["--data-root", str(dataset), "--focus-disparity", focus])
    assert not any((seq / "bokeh").exists() for seq in _sequences(dataset))


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


def _alone_mean_disparity(seq: Path, k: int) -> list[float]:
    """Each frame's mean disparity over the pixels object ``k`` holds alone."""
    means = []
    for frame in sorted((seq / "disparity").glob("*.png")):
        masks = [a > 0.5 for a in read_alpha_tiff(seq / "alpha" / f"{frame.stem}.tif")]
        alone = masks[k] & ~np.any([m for j, m in enumerate(masks) if j != k], axis=0)
        means.append(float(read_disparity_png(frame)[alone].mean()))
    return means


def test_a_chosen_object_is_followed_instead_of_drawn(dataset: Path) -> None:
    cli.main(["--data-root", str(dataset)])
    seq = next(s for s in _sequences(dataset) if len(_objects(s)) == 2)
    drawn = json.loads((seq / "bokeh" / "focus.json").read_text())["object"]
    other = 1 - drawn
    cli.main(
        ["--data-root", str(dataset), "--seqs", seq.name, "--focus-object", str(other)]
    )
    record = json.loads((seq / "bokeh" / "focus.json").read_text())
    assert record["object"] == other
    assert record["zf"] == pytest.approx(_alone_mean_disparity(seq, other), abs=1e-6)


def test_choosing_the_drawn_object_renders_what_the_draw_does(dataset: Path) -> None:
    cli.main(["--data-root", str(dataset)])
    seq = _sequences(dataset)[0]
    drawn = json.loads((seq / "bokeh" / "focus.json").read_text())["object"]
    shutil.move(seq / "bokeh", seq / "drawn")
    cli.main(
        ["--data-root", str(dataset), "--seqs", seq.name, "--focus-object", str(drawn)]
    )
    for frame in sorted((seq / "drawn").iterdir()):
        assert (seq / "bokeh" / frame.name).read_bytes() == frame.read_bytes()


@pytest.mark.parametrize(
    ("flags", "message"),
    [
        (["--focus-object", "-1"], "must be 0 or more"),
        (["--focus-object", "0", "--focus-disparity", "0.5"], "exclude each other"),
    ],
)
def test_a_bad_focus_object_is_refused_before_rendering(
    dataset: Path,
    capsys: pytest.CaptureFixture[str],
    flags: list[str],
    message: str,
) -> None:
    with pytest.raises(SystemExit):
        cli.main(["--data-root", str(dataset), *flags])
    assert message in capsys.readouterr().err
    assert not any((seq / "bokeh").exists() for seq in _sequences(dataset))


def test_an_object_a_sequence_lacks_is_refused_before_any_is_rendered(
    dataset: Path,
) -> None:
    seqs = _sequences(dataset)
    lacking = next(s for s in seqs if len(_objects(s)) == 1)
    # Last, so that a renderer writing as it goes would have written the others.
    batch = [*(s for s in seqs if s != lacking), lacking]
    with pytest.raises(ValueError, match=f"no object 1 in {lacking.name}"):
        Layered().render(batch, 16.0, None, focus_object=1)
    assert not any((seq / "bokeh").exists() for seq in seqs)


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
