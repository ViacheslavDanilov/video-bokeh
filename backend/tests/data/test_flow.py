"""Optical flow out of Stage B: written on request, and exact.

Every layer moves by a known homography per frame, so the flow is computed rather than
estimated. The test that holds it samples the next frame where the flow points and gets
the frame back, on a textured scene where a wrong flow could not hide.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageFilter

from video_bokeh.core._library import write_background, write_foreground
from video_bokeh.core._streams import (
    read_alpha_tiff,
    read_flow_png,
    read_mask_png,
    read_paint_order,
)
from video_bokeh.scenes._compositor import iter_frames, occlusion_mask
from video_bokeh.scenes.generate import generate_dataset, main, sample_sequence

FRAMES, SIZE = 6, 96


def _texture(rng: np.random.Generator, n: int) -> np.ndarray:
    """Smooth random color, so a misplaced sample shows and bilinear sampling holds."""
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
    assert not (seq / "flow_back").exists()


def test_backward_flow_is_written_for_every_frame_but_the_first(
    textured_library: Path,
    tmp_path: Path,
) -> None:
    seq = _generate(textured_library, tmp_path / "out", flow_back=True)
    written = sorted(p.name for p in (seq / "flow_back").glob("*.png"))
    assert written == _names(seq)[1:]
    assert not (seq / "flow").exists()


def test_a_one_frame_sequence_writes_no_flow_either_way(
    textured_library: Path,
    tmp_path: Path,
) -> None:
    generate_dataset(
        textured_library,
        tmp_path / "out",
        count=1,
        n_frames=1,
        size=SIZE,
        seed=3,
        n_objects_min=2,
        n_objects_max=2,
        flow=True,
        flow_back=True,
    )
    seq = tmp_path / "out" / "sequences" / "0001"
    assert _names(seq) == ["01.png"]
    assert not (seq / "flow").exists()
    assert not (seq / "flow_back").exists()


def test_backward_flow_undoes_forward_flow_on_the_same_surface(
    textured_library: Path,
    tmp_path: Path,
) -> None:
    """Where frame t's forward flow lands in frame t + 1, that frame's backward flow
    points back, on pixels well inside the same surface at both ends.
    """
    seq = _generate(
        textured_library, tmp_path / "out", layers=True, flow=True, flow_back=True
    )
    names = _names(seq)
    orders = read_paint_order(seq / "layers" / "paint_order.json")
    ys, xs = np.mgrid[0:SIZE, 0:SIZE].astype(np.float32)
    checked = 0
    for t in range(FRAMES - 1):
        flow, valid = read_flow_png(seq / "flow" / names[t])
        back, back_valid = read_flow_png(seq / "flow_back" / names[t + 1])
        front_now, _ = _front(seq, names[t], orders[t])
        front_next, _ = _front(seq, names[t + 1], orders[t + 1])
        x, y = xs + flow[..., 0], ys + flow[..., 1]
        inside = valid & (x >= 0) & (x <= SIZE - 2) & (y >= 0) & (y <= SIZE - 2)
        xi = np.clip(np.round(x), 0, SIZE - 1).astype(int)
        yi = np.clip(np.round(y), 0, SIZE - 1).astype(int)
        same = (
            inside
            & _interior(front_now)
            & (front_next[yi, xi] == front_now)
            & _interior(front_next)[yi, xi]
            & back_valid[yi, xi]
        )
        # The backward field is sampled bilinearly where the forward flow lands, so the
        # two differ by that interpolation and the 1/64 px quantization; a flow of the
        # wrong surface differs by pixels.
        returned = _bilinear(back, np.clip(x, 0, SIZE - 2), np.clip(y, 0, SIZE - 2))
        error = np.abs(returned + flow).max(axis=-1)[same]
        assert np.median(error) < 0.1, f"frame {t}: median {np.median(error):.3f}"
        checked += int(same.sum())
    assert checked > 10000


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
    seq = _generate(
        textured_library,
        tmp_path / "out",
        flow=True,
        flow_back=True,
        occlusion=True,
        occlusion_back=True,
    )
    assert (seq / "flow").is_dir() and (seq / "flow_back").is_dir()
    assert (seq / "occlusion").is_dir() and (seq / "occlusion_back").is_dir()
    _generate(textured_library, tmp_path / "out")
    assert not (seq / "flow").exists()
    assert not (seq / "flow_back").exists()
    assert not (seq / "occlusion").exists()
    assert not (seq / "occlusion_back").exists()


def test_occlusion_marks_a_covered_pixel_and_one_that_leaves_the_frame() -> None:
    """A 4 x 4 frame, by columns: object 0 holds columns 0 and 1, the background column
    2, and object 1 column 3. In the next frame object 0 holds columns 1 and 2, the
    background column 0, and object 1 stays on column 3.
    """
    front_now = np.full((4, 4), -1)
    front_now[:, :2] = 0
    front_now[:, 3] = 1
    front_next = np.full((4, 4), -1)
    front_next[:, 1:3] = 0
    front_next[:, 3] = 1
    flow = np.zeros((4, 4, 2), dtype=np.float32)

    # Covered: object 0 moves one pixel right onto its own next columns, the
    # background's column lands on column 1, which object 0 then holds.
    flow[front_now == 0, 0] = 1.0
    flow[front_now == -1, 0] = -1.0
    expected = np.zeros((4, 4), dtype=bool)
    expected[:, 2] = True
    assert np.array_equal(occlusion_mask(front_now, front_next, flow), expected)

    # Leaves the frame: the background's column moves three pixels left, to column -1.
    flow[front_now == -1, 0] = -3.0
    assert np.array_equal(occlusion_mask(front_now, front_next, flow), expected)

    # Covered by the other object: object 0 moves two pixels right, so its column 1
    # lands on column 3, which object 1 holds, while its column 0 lands on itself.
    flow[front_now == 0, 0] = 2.0
    occluded = occlusion_mask(front_now, front_next, flow)
    assert occluded[:, 1].all() and not occluded[:, 0].any()


def test_a_landing_at_the_edge_rounds_to_the_nearest_pixel() -> None:
    front = np.zeros((1, 4), dtype=int)
    flow = np.zeros((1, 4, 2), dtype=np.float32)
    flow[0, 3, 0] = 0.4  # column 3 lands at 3.4: still column 3, inside
    flow[0, 2, 0] = 1.6  # column 2 lands at 3.6: column 4, outside
    assert occlusion_mask(front, front, flow).tolist() == [[False, False, True, False]]


def test_a_surface_uncovered_since_the_previous_frame_is_marked_backward() -> None:
    """A 1 x 6 frame. Object 0 held columns 1 and 2 in the previous frame and moved one
    pixel right, so it holds 2 and 3 now, and the background shows again at column 1.
    Read backward, the background pixel at column 1 lands on object 0's old column 1, so
    it is marked; object 0's columns land on its own old columns 1 and 2, so are not.
    The forward mask of the previous frame does not mark column 1.
    """
    front_prev = np.array([[-1, 0, 0, -1, -1, -1]])
    front_now = np.array([[-1, -1, 0, 0, -1, -1]])
    flow_back = np.zeros((1, 6, 2), dtype=np.float32)
    flow_back[front_now == 0, 0] = -1.0
    marked = occlusion_mask(front_now, front_prev, flow_back)
    assert marked.tolist() == [[False, True, False, False, False, False]]
    flow = np.zeros((1, 6, 2), dtype=np.float32)
    flow[front_prev == 0, 0] = 1.0
    assert not occlusion_mask(front_prev, front_now, flow)[0, 1]


def test_a_still_scene_occludes_nothing() -> None:
    front = np.array([[-1, 0], [1, 1]])
    assert not occlusion_mask(front, front, np.zeros((2, 2, 2), np.float32)).any()


def test_occlusion_is_written_for_every_frame_but_the_last(
    textured_library: Path,
    tmp_path: Path,
) -> None:
    seq = _generate(textured_library, tmp_path / "out", occlusion=True)
    written = sorted(p.name for p in (seq / "occlusion").glob("*.png"))
    assert written == _names(seq)[:-1]
    assert not (seq / "flow").exists()
    mask = read_mask_png(seq / "occlusion" / written[0])
    assert mask.shape == (SIZE, SIZE) and mask.dtype == bool


def test_occlusion_agrees_with_the_written_alphas_and_flow(
    textured_library: Path,
    tmp_path: Path,
) -> None:
    """Read back from the files, a pixel is marked exactly when the surface the alpha
    pages put in front at its landing point differs from its own, or it lands outside.
    """
    seq = _generate(
        textured_library, tmp_path / "out", 12, layers=True, flow=True, occlusion=True
    )
    names = _names(seq)
    orders = read_paint_order(seq / "layers" / "paint_order.json")
    marked = 0
    for t in range(FRAMES - 1):
        flow, _ = read_flow_png(seq / "flow" / names[t])
        front_now, _ = _front(seq, names[t], orders[t])
        front_next, _ = _front(seq, names[t + 1], orders[t + 1])
        expected = occlusion_mask(front_now, front_next, flow)
        mask = read_mask_png(seq / "occlusion" / names[t])
        # The files hold the alphas at 8 bits and the flow in 1/64 px, so a pixel at
        # the 0.5 alpha threshold or at a rounding boundary may differ.
        assert (mask != expected).mean() < 0.002
        marked += int(mask.sum())
    assert 0 < marked < FRAMES * SIZE * SIZE / 2


def test_occlusion_back_is_written_for_every_frame_but_the_first(
    textured_library: Path,
    tmp_path: Path,
) -> None:
    seq = _generate(textured_library, tmp_path / "out", occlusion_back=True)
    written = sorted(p.name for p in (seq / "occlusion_back").glob("*.png"))
    assert written == _names(seq)[1:]
    assert not (seq / "occlusion").exists() and not (seq / "flow_back").exists()
    mask = read_mask_png(seq / "occlusion_back" / written[0])
    assert mask.shape == (SIZE, SIZE) and mask.dtype == bool


def test_occlusion_back_agrees_with_the_written_alphas_and_backward_flow(
    textured_library: Path,
    tmp_path: Path,
) -> None:
    """Read back from the files, a pixel of frame t is marked exactly when the surface
    the alpha pages put in front at its landing point in frame t - 1 differs from its
    own, or it lands outside. The mask is the backward one: it is not the forward mask of
    the previous frame read the other way round.
    """
    seq = _generate(
        textured_library,
        tmp_path / "out",
        12,
        layers=True,
        flow=True,
        flow_back=True,
        occlusion=True,
        occlusion_back=True,
    )
    names = _names(seq)
    orders = read_paint_order(seq / "layers" / "paint_order.json")
    marked = 0
    differs = 0
    for t in range(1, FRAMES):
        flow_back, _ = read_flow_png(seq / "flow_back" / names[t])
        front_now, _ = _front(seq, names[t], orders[t])
        front_prev, _ = _front(seq, names[t - 1], orders[t - 1])
        expected = occlusion_mask(front_now, front_prev, flow_back)
        mask = read_mask_png(seq / "occlusion_back" / names[t])
        assert (mask != expected).mean() < 0.002
        marked += int(mask.sum())
        differs += int((mask != read_mask_png(seq / "occlusion" / names[t - 1])).sum())
    assert 0 < marked < FRAMES * SIZE * SIZE / 2
    assert differs > 0


def test_asking_for_the_backward_mask_leaves_the_forward_streams_as_they_were(
    textured_library: Path,
    tmp_path: Path,
) -> None:
    before = _generate(textured_library, tmp_path / "a", 12, flow=True, occlusion=True)
    after = _generate(
        textured_library,
        tmp_path / "b",
        12,
        flow=True,
        flow_back=True,
        occlusion=True,
        occlusion_back=True,
    )
    for stream in ("all_in_focus", "alpha", "disparity", "flow", "occlusion"):
        for path in sorted((before / stream).iterdir()):
            assert path.read_bytes() == (after / stream / path.name).read_bytes()


def test_a_single_frame_has_no_backward_mask(
    textured_library: Path,
    tmp_path: Path,
) -> None:
    generate_dataset(
        textured_library,
        tmp_path / "out",
        count=1,
        n_frames=1,
        size=SIZE,
        seed=3,
        n_objects_min=2,
        n_objects_max=2,
        occlusion_back=True,
    )
    assert not (tmp_path / "out" / "sequences" / "0001" / "occlusion_back").exists()


def _scene(library: Path):  # noqa: ANN202
    return sample_sequence(
        library,
        seed=3,
        n_frames=FRAMES,
        size=SIZE,
        n_objects_min=2,
        n_objects_max=2,
    )


def test_a_still_scene_marks_nothing_in_either_direction(
    textured_library: Path,
) -> None:
    scene = _scene(textured_library)
    still = replace(
        scene,
        bg_pose_end=scene.bg_pose_start,
        objects=[replace(o, pose_end=o.pose_start) for o in scene.objects],
    )
    frames = list(
        iter_frames(
            still, flow=True, flow_back=True, occlusion=True, occlusion_back=True
        )
    )
    assert frames[1].occlusion_back is not None and frames[0].occlusion is not None
    for frame in frames:
        for mask in (frame.occlusion, frame.occlusion_back):
            assert mask is None or not mask.any()
        for field in (frame.flow, frame.flow_back):
            assert field is None or np.abs(field).max() < 1e-3


def test_a_backward_stream_is_computed_only_when_asked_for(
    textured_library: Path,
) -> None:
    scene = _scene(textured_library)
    forward = list(iter_frames(scene, flow=True, occlusion=True))
    assert all(f.flow_back is None and f.occlusion_back is None for f in forward)
    backward = list(iter_frames(scene, occlusion_back=True))
    assert all(f.flow_back is None and f.occlusion is None for f in backward)
    assert backward[0].occlusion_back is None
    assert backward[1].occlusion_back is not None


def _command(library: Path, out: Path, *flags: str) -> list[str]:
    return [
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
        "--n-objects-max",
        "2",
        *flags,
    ]


def _folders(seq: Path) -> set[str]:
    motion = ("flow", "flow_back", "occlusion", "occlusion_back")
    return {name for name in motion if (seq / name).is_dir()}


@pytest.mark.parametrize(
    ("flow", "occlusion", "folders"),
    [
        ("forward", "forward", {"flow", "occlusion"}),
        ("backward", "backward", {"flow_back", "occlusion_back"}),
        ("both", "both", {"flow", "flow_back", "occlusion", "occlusion_back"}),
        ("forward", "both", {"flow", "occlusion", "occlusion_back"}),
        ("both", "backward", {"flow", "flow_back", "occlusion_back"}),
    ],
)
def test_the_command_writes_the_directions_it_is_given(
    textured_library: Path,
    tmp_path: Path,
    flow: str,
    occlusion: str,
    folders: set[str],
) -> None:
    out = tmp_path / "out"
    flags = ("--flow", flow, "--occlusion", occlusion)
    assert main(_command(textured_library, out, *flags)) == 0
    seq = out / "sequences" / "0001"
    assert _folders(seq) == folders
    for name in folders:
        assert len(list((seq / name).glob("*.png"))) == FRAMES - 1
    flags_written = json.loads((out / "run.json").read_text())["flags"]
    for name in ("flow", "flow_back", "occlusion", "occlusion_back"):
        assert flags_written[name] is (name in folders)


def test_the_command_writes_no_motion_without_the_flags(
    textured_library: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    assert main(_command(textured_library, out)) == 0
    assert _folders(out / "sequences" / "0001") == set()


@pytest.mark.parametrize(
    "flags",
    [
        ("--flow",),
        ("--occlusion",),
        ("--flow", "sideways"),
        ("--occlusion", "back"),
        ("--flow-back",),
    ],
)
def test_the_command_refuses_a_missing_or_unknown_direction(
    textured_library: Path, tmp_path: Path, flags: tuple[str, ...]
) -> None:
    with pytest.raises(SystemExit) as exit_:
        main(_command(textured_library, tmp_path / "out", *flags))
    assert exit_.value.code == 2
    assert not (tmp_path / "out" / "sequences").exists()
