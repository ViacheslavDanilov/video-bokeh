from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import tifffile
from PIL import Image

from data import estimate_disparity as ed
from data.generate_sequences import (
    SampleConfig,
    SequenceSpec,
    render_sequence,
    write_manifest,
)


class _FakeEstimator:
    name = "fake"

    def load(self, _device) -> None:
        return None

    def infer(self, images: list[Image.Image]) -> list[np.ndarray]:
        out: list[np.ndarray] = []
        for image in images:
            gray = np.asarray(image.convert("L"), dtype=np.float32) / 255.0
            x_grad = np.linspace(0.0, 0.25, image.width, dtype=np.float32)
            out.append((gray + x_grad[None, :]).astype(np.float32))
        return out


def test_fuse_smoke_with_fake_estimator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fg_root = Path("data/magick_dev")
    bg_root = Path("data/bg-20k_dev")
    if not fg_root.exists() or not bg_root.exists():
        pytest.skip("fixture data missing; run from backend/")

    root = tmp_path / "synth"
    seq_dir = root / "sequences" / "0001"
    spec = SequenceSpec(
        seq_id=1,
        seed=42,
        n_frames=2,
        size=128,
        bg_ref="testval/h_5ea69f46.jpg",
        object_refs=["WL/WLjuUIyRNn.png", "1Q/1Q5iguFTYX.png"],
    )
    render_sequence(spec, fg_root, bg_root, seq_dir, SampleConfig())
    write_manifest(root / "manifest.csv", [spec])

    monkeypatch.setitem(ed.ESTIMATORS, "fake", _FakeEstimator)

    rc = ed.main(
        [
            "--data-root",
            str(root),
            "--fg-data-root",
            str(fg_root),
            "--bg-data-root",
            str(bg_root),
            "--model",
            "fake",
            "--device",
            "cpu",
            "--seqs",
            "0001",
        ],
    )

    assert rc == 0
    tifs = sorted((seq_dir / "disparity").glob("*.tif"))
    assert len(tifs) == spec.n_frames

    arr = tifffile.imread(tifs[0])
    assert arr.dtype == np.float32
    assert arr.shape == (spec.size, spec.size)
    assert arr.min() >= 0.0 - 1e-6
    assert arr.max() <= 1.0 + 1e-6
    assert arr.max() > 0.05
