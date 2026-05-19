from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import tifffile
from PIL import Image

from data.prepare_any_to_bokeh import main


def _write_rgb(path: Path, value: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.full((4, 4, 3), value, dtype=np.uint8)
    Image.fromarray(arr, mode="RGB").save(path)


def _write_alpha(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.array(
        [
            [255, 255, 0, 0],
            [255, 255, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
        ],
        dtype=np.uint8,
    )
    Image.fromarray(arr, mode="L").save(path)


def test_prepare_any_to_bokeh_writes_one_based_frames_and_csv(tmp_path: Path) -> None:
    data_root = tmp_path / "synth"
    seq_dir = data_root / "sequences" / "0001"
    _write_rgb(seq_dir / "all_in_focus" / "01.png", 10)
    _write_rgb(seq_dir / "all_in_focus" / "02.png", 20)
    _write_alpha(seq_dir / "alpha" / "01.png")
    _write_alpha(seq_dir / "alpha" / "02.png")
    (seq_dir / "disparity").mkdir(parents=True)
    tifffile.imwrite(
        seq_dir / "disparity" / "01.tif",
        np.array(
            [
                [0.25, 0.25, 0.75, 0.75],
                [0.25, 0.25, 0.75, 0.75],
                [0.75, 0.75, 0.75, 0.75],
                [0.75, 0.75, 0.75, 0.75],
            ],
            dtype=np.float32,
        ),
    )
    tifffile.imwrite(
        seq_dir / "disparity" / "02.tif",
        np.full((4, 4), 0.5, dtype=np.float32),
    )

    a2b_root = tmp_path / "any-to-bokeh"
    rc = main(
        [
            "--data-root",
            str(data_root),
            "--a2b-root",
            str(a2b_root),
            "--dataset-name",
            "fixture",
            "--seqs",
            "0001",
        ],
    )

    assert rc == 0
    video_dir = a2b_root / "demo_dataset" / "fixture" / "videos" / "0001"
    disp_dir = a2b_root / "demo_dataset" / "fixture" / "disp" / "0001"
    assert sorted(path.name for path in video_dir.glob("*.png")) == ["01.png", "02.png"]
    disp_names = sorted(path.name for path in disp_dir.glob("*.png"))
    assert len(disp_names) == 2
    assert disp_names[0].startswith("01_zf_")
    assert disp_names[1].startswith("02_zf_")
    assert not any(name.startswith("00_zf_") for name in disp_names)

    disp_img = Image.open(disp_dir / disp_names[0])
    assert disp_img.mode == "L"
    assert disp_names[0] == "01_zf_0.250980.png"

    with (a2b_root / "csv_file" / "fixture.csv").open(
        newline="",
        encoding="utf-8",
    ) as f:
        rows = list(csv.DictReader(f))
    assert rows == [
        {
            "aif_folder": "demo_dataset/fixture/videos/0001",
            "disp_folder": "demo_dataset/fixture/disp/0001",
            "k": "16",
        },
    ]
