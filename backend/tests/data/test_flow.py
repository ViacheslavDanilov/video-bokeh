"""Optical flow out of Stage B: written on request, and exact.

Every layer moves by a known homography per frame, so the flow is computed rather than
estimated. The test that holds it samples the next frame where the flow points and gets
the frame back, on a textured scene where a wrong flow could not hide.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageFilter

from video_bokeh.core._library import write_background, write_foreground
from video_bokeh.core._streams import read_alpha_tiff, read_flow_png, read_paint_order
from video_bokeh.scenes.generate import generate_dataset, main

FRAMES, SIZE = 6, 96


def _texture(rng: np.random.Generator, n: int) -> np.ndarray:
    """Smooth random colour, so a misplaced sample shows and bilinear sampling holds."""
    noise = rng.integers(0, 256, size=(n, n, 3), dtype=np.uint8)
    return np.asarray(Image.fromarray(noise).filter(ImageFilter.GaussianBlur(2)))


@pytest.fixture
def textured_library(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    rng = np.random.default_rng(0)
    for i in range(2):
        rgba = np.zeros((64, 64, 4), dtype=np.uint8)
        rgba[8:56, 8:56, :3] = _texture(rng, 48)
        rgba[8:56, 8:56, 3] = 255
        write_foreground(
            root,
            f"fg_{i}",
            Image.fromarray(rgba, "RGBA"),
            (rgba[..., 3] / 255.0).astype(np.float32),
            np.full((64, 64), 0.6 + 0.3 * i, dtype=np.float32),
        )
    write_background(
        root,
        "bg",
        Image.fromarray(_texture(rng, 128)),
        np.full((128, 128), 0.1, dtype=np.float32),
    )
    return root


def _generate(library: Path, out: Path, seed: int = 3, **kwargs: bool) -> Path:
    generate_dataset(
        library,
        out,
        count=1,
        n_frames=FRAMES,
        size=SIZE,
        seed=seed,
        n_objects_min=2,
        n_objects_max=2,
        **kwargs,
    )
    return out / "sequences" / "0001"


def _names(seq: Path) -> list[str]:
    return sorted(p.name for p in (seq / "all_in_focus").glob("*.png"))


def _rgb(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB"), dtype=np.float32)


def _front(seq: Path, name: str, order: list[int]) -> tuple[np.ndarray, np.ndarray]:
    """Which surface is in front at each pixel, an object page or -1 for background, and
    how many objects cover it.
    """
    alphas = read_alpha_tiff(seq / "alpha" / name.replace(".png", ".tif"))
    front = np.full(alphas[0].shape, -1)
    for idx in order:
        front[alphas[idx] >= 0.5] = idx
    return front, sum((a >= 0.5).astype(int) for a in alphas)


def _interior(front: np.ndarray, r: int = 2) -> np.ndarray:
    """Pixels whose whole ``(2r + 1)`` square shows the same surface."""
    padded = np.pad(front, r, mode="edge")
    same = np.ones(front.shape, dtype=bool)
    h, w = front.shape
    for dy in range(2 * r + 1):
        for dx in range(2 * r + 1):
            same &= padded[dy : dy + h, dx : dx + w] == front
    return same


def _bilinear(img: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    x0 = np.floor(x).astype(int)
    y0 = np.floor(y).astype(int)
    fx = (x - x0)[..., None]
    fy = (y - y0)[..., None]
    return (
        img[y0, x0] * (1 - fx) * (1 - fy)
        + img[y0, x0 + 1] * fx * (1 - fy)
        + img[y0 + 1, x0] * (1 - fx) * fy
        + img[y0 + 1, x0 + 1] * fx * fy
    )


def test_flow_is_written_for_every_frame_but_the_last(
    textured_library: Path,
    tmp_path: Path,
) -> None:
    seq = _generate(textured_library, tmp_path / "out", flow=True)
    written = sorted(p.name for p in (seq / "flow").glob("*.png"))
    assert written == _names(seq)[:-1]


def test_no_flow_is_written_unless_asked(
    textured_library: Path,
    tmp_path: Path,
) -> None:
    seq = _generate(textured_library, tmp_path / "out")
    assert not (seq / "flow").exists()


def _flow_errors(seq: Path) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Per class of pixel, how far frame t + 1 sampled where the flow points is from frame
    t, and how far it is with no flow at all.

    The classes are ``background``, each object as ``object <page>`` where it alone covers
    the pixel, and ``overlap``, where two objects or more do and the front one must win.
    Only pixels well inside the same surface at both ends count: no edge, no occlusion.
    """
    names = _names(seq)
    orders = read_paint_order(seq / "layers" / "paint_order.json")
    ys, xs = np.mgrid[0:SIZE, 0:SIZE].astype(np.float32)
    errors: dict[str, list[np.ndarray]] = {}
    standing: dict[str, list[np.ndarray]] = {}
    for t in range(FRAMES - 1):
        now = _rgb(seq / "all_in_focus" / names[t])
        nxt = _rgb(seq / "all_in_focus" / names[t + 1])
        flow, valid = read_flow_png(seq / "flow" / names[t])
        front_now, covering = _front(seq, names[t], orders[t])
        front_next, _ = _front(seq, names[t + 1], orders[t + 1])
        x, y = xs + flow[..., 0], ys + flow[..., 1]
        inside = valid & (x >= 0) & (x <= SIZE - 2) & (y >= 0) & (y <= SIZE - 2)
        xi = np.clip(np.round(x), 0, SIZE - 1).astype(int)
        yi = np.clip(np.round(y), 0, SIZE - 1).astype(int)
        check = (
            inside
            & _interior(front_now)
            & (front_next[yi, xi] == front_now)
            & _interior(front_next)[yi, xi]
        )
        sampled = _bilinear(nxt, np.clip(x, 0, SIZE - 2), np.clip(y, 0, SIZE - 2))
        error = np.abs(sampled - now).mean(axis=-1)
        still = np.abs(nxt - now).mean(axis=-1)
        classes = {"background": front_now < 0, "overlap": covering >= 2}
        for page in np.unique(front_now[front_now >= 0]):
            classes[f"object {page}"] = (front_now == page) & (covering == 1)
        for label, members in classes.items():
            errors.setdefault(label, []).append(error[check & members])
            standing.setdefault(label, []).append(still[check & members])
    return {
        label: (np.concatenate(errors[label]), np.concatenate(standing[label]))
        for label in errors
    }


def _assert_exact(label: str, error: np.ndarray, still: np.ndarray) -> None:
    # Resampling an 8-bit frame twice costs well under a level; ignoring the motion costs
    # several, so a flow that is off would show.
    assert np.median(error) < 1.0, f"{label}: median error {np.median(error):.2f}"
    assert np.median(error) < np.median(still) / 4, (
        f"{label}: error {np.median(error):.2f} against {np.median(still):.2f} "
        "with no flow"
    )


def test_flow_carries_each_pixel_to_where_its_surface_is_next(
    textured_library: Path,
    tmp_path: Path,
) -> None:
    seq = _generate(textured_library, tmp_path / "out", layers=True, flow=True)
    # Each surface apart, so that the background's many pixels cannot hide a wrong flow
    # on one object.
    checked = {
        label: errors
        for label, errors in _flow_errors(seq).items()
        if label != "overlap" and errors[0].size > 300
    }
    assert {"background", "object 0", "object 1"} <= set(checked), sorted(checked)
    for label, (error, still) in checked.items():
        _assert_exact(label, error, still)


def test_where_objects_overlap_the_flow_is_the_front_one_s(
    textured_library: Path,
    tmp_path: Path,
) -> None:
    # Seed 12 overlaps its two objects over thousands of pixels; seed 3 barely does.
    seq = _generate(textured_library, tmp_path / "out", 12, layers=True, flow=True)
    error, still = _flow_errors(seq)["overlap"]
    assert error.size > 1000, f"only {error.size} overlapping pixels to check"
    _assert_exact("overlap", error, still)


def test_writing_a_sequence_again_without_flow_drops_its_old_flow(
    textured_library: Path,
    tmp_path: Path,
) -> None:
    seq = _generate(textured_library, tmp_path / "out", flow=True)
    assert (seq / "flow").is_dir()
    _generate(textured_library, tmp_path / "out")
    assert not (seq / "flow").exists()


def test_the_command_writes_flow(textured_library: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    main(
        [
            "--library-root",
            str(textured_library),
            "--output",
            str(out),
            "--count",
            "1",
            "--frames",
            str(FRAMES),
            "--size",
            str(SIZE),
            "--n-objects-max",
            "2",
            "--flow",
        ],
    )
    seq = out / "sequences" / "0001"
    assert len(list((seq / "flow").glob("*.png"))) == FRAMES - 1
