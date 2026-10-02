"""The on-the-fly loader renders sequences in memory, through Stage B, forever."""

from __future__ import annotations

import shutil
from itertools import islice
from pathlib import Path

import numpy as np
import pytest
import torch
from PIL import Image
from torch.utils.data import DataLoader

from video_bokeh.core._streams import read_alpha_tiff, read_disparity_png
from video_bokeh.loader import SequenceStream
from video_bokeh.loader import _stream as mod
from video_bokeh.scenes._compositor import CollisionRetriesExhausted
from video_bokeh.scenes.generate import generate_dataset

FRAMES, SIZE = 3, 64


def _stream(library: Path, **kwargs) -> SequenceStream:
    return SequenceStream(
        library,
        n_frames=FRAMES,
        size=SIZE,
        n_objects_min=1,
        n_objects_max=2,
        **kwargs,
    )


def test_an_item_has_fixed_shapes_and_ranges(library: Path) -> None:
    item = next(iter(_stream(library)))

    assert item["rgb"].shape == (FRAMES, 3, SIZE, SIZE)
    assert item["disparity"].shape == (FRAMES, 1, SIZE, SIZE)
    assert item["alpha"].shape == (FRAMES, 1, SIZE, SIZE)
    assert item["object_alphas"].shape == (FRAMES, 2, SIZE, SIZE)
    for key in ("rgb", "disparity", "alpha", "object_alphas"):
        assert item[key].dtype == torch.float32
        assert 0.0 <= float(item[key].min()) and float(item[key].max()) <= 1.0


def test_object_alphas_past_the_count_are_zero(library: Path) -> None:
    items = list(islice(iter(_stream(library)), 8))
    one_object = [it for it in items if it["n_objects"] == 1]
    assert one_object, "no single-object item in 8; widen the sample"
    for item in one_object:
        assert float(item["object_alphas"][:, 1].abs().max()) == 0.0
        assert float(item["object_alphas"][:, 0].max()) > 0.0


def test_matches_what_the_dataset_writer_writes(library: Path, tmp_path: Path) -> None:
    # One worker yields seeds seed, seed+1, ... -- the scenes scenes.generate writes for
    # --seed, so the stream and a written dataset are one distribution. The writer runs
    # for real here, so a drift in either one fails this test. Seed 1 places both
    # foregrounds, so the page order of the mattes is compared too.
    generate_dataset(
        library,
        tmp_path / "out",
        1,
        FRAMES,
        SIZE,
        seed=1,
        n_objects_max=2,
    )
    seq = tmp_path / "out" / "sequences" / "0001"
    item = next(iter(_stream(library, seed=1)))
    assert item["seed"] == 1
    assert item["n_objects"] == 2

    written_rgb = np.stack(
        [np.asarray(Image.open(p)) for p in sorted((seq / "all_in_focus").iterdir())],
    )
    streamed_rgb = item["rgb"].permute(0, 2, 3, 1).numpy() * 255.0
    # The writer truncates to uint8; one level either way is float rounding.
    assert np.abs(written_rgb - streamed_rgb).max() <= 1.0

    written_disp = np.stack(
        [read_disparity_png(p) for p in sorted((seq / "disparity").iterdir())],
    )
    streamed_disp = item["disparity"][:, 0].numpy()
    assert np.abs(written_disp - streamed_disp).max() <= 1.0 / 65535 + 1e-7

    written_alphas = np.stack(
        [read_alpha_tiff(p) for p in sorted((seq / "alpha").iterdir())],
    )
    placed = item["n_objects"]
    streamed_alphas = item["object_alphas"][:, :placed].numpy()
    assert written_alphas.shape == streamed_alphas.shape
    assert np.abs(written_alphas - streamed_alphas).max() <= 1.0 / 255 + 1e-6


def test_fewer_objects_placed_than_asked_keeps_the_shape(library: Path) -> None:
    # The fixture library holds two foregrounds, so asking for four places two.
    stream = SequenceStream(
        library,
        n_frames=FRAMES,
        size=SIZE,
        n_objects_min=4,
        n_objects_max=4,
    )
    item = next(iter(stream))
    assert item["n_objects"] == 2
    assert item["object_alphas"].shape == (FRAMES, 4, SIZE, SIZE)
    assert float(item["object_alphas"][:, 2:].abs().max()) == 0.0


@pytest.mark.parametrize(("lo", "hi"), [(0, 2), (3, 2)])
def test_an_object_range_that_cannot_hold_is_refused(
    library: Path,
    lo: int,
    hi: int,
) -> None:
    with pytest.raises(ValueError, match="n_objects_min"):
        SequenceStream(
            library,
            n_frames=FRAMES,
            size=SIZE,
            n_objects_min=lo,
            n_objects_max=hi,
        )


def test_the_default_collate_batches_it(library: Path) -> None:
    batch = next(iter(DataLoader(_stream(library), batch_size=2)))
    assert batch["rgb"].shape == (2, FRAMES, 3, SIZE, SIZE)
    assert batch["object_alphas"].shape == (2, FRAMES, 2, SIZE, SIZE)
    assert batch["n_objects"].shape == (2,)


def test_workers_never_repeat_each_other(library: Path) -> None:
    loader = DataLoader(_stream(library, seed=100), batch_size=None, num_workers=2)
    seeds = [int(item["seed"]) for item in islice(iter(loader), 6)]
    assert len(set(seeds)) == 6
    # Worker w of W takes seed + w, seed + w + W, ... ; together, a run is reproducible.
    assert sorted(seeds) == list(range(100, 106))


def test_a_seed_that_cannot_be_placed_is_skipped(
    library: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = mod.sample_sequence

    def refuses_seed_0(root, seed, *args, **kwargs):
        if seed == 0:
            raise CollisionRetriesExhausted("seed 0: objects still collide")
        return real(root, seed, *args, **kwargs)

    monkeypatch.setattr(mod, "sample_sequence", refuses_seed_0)
    assert next(iter(_stream(library)))["seed"] == 1


def test_a_stream_that_can_place_nothing_fails_instead_of_spinning(
    library: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def never(*args, **kwargs):
        raise CollisionRetriesExhausted("objects still collide")

    monkeypatch.setattr(mod, "sample_sequence", never)
    with pytest.raises(RuntimeError, match="100 seeds in a row"):
        next(iter(_stream(library)))


def test_a_path_that_is_not_a_library_is_refused_up_front(tmp_path: Path) -> None:
    """At construction, in the training process, rather than as a SystemExit inside a
    DataLoader worker once iteration starts.
    """
    with pytest.raises(ValueError, match="nothing-here"):
        SequenceStream(tmp_path / "nothing-here", n_frames=4, size=32)


def test_a_library_without_backgrounds_is_refused_up_front(
    library: Path,
    tmp_path: Path,
) -> None:
    half = tmp_path / "half"
    shutil.copytree(library / "foregrounds", half / "foregrounds")
    with pytest.raises(ValueError, match="backgrounds"):
        SequenceStream(half, n_frames=4, size=32)
