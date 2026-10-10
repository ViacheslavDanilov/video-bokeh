"""Optical flow in colour: the wheel optical-flow papers draw, one scale per sequence, and a
video as long as the sequence's other streams.

The expected colours are the reference wheel's (Baker et al.; RAFT's ``flow_viz``) worked by
hand: a direction lands at a fixed place on its 55 colours.
"""

from __future__ import annotations

import imageio.v2 as iio
import numpy as np
import pytest

from video_bokeh.core._streams import write_flow_png
from video_bokeh.preview._flow import flow_to_rgb
from video_bokeh.preview.pack import encode_stream


def _flow(u: float, v: float, size: int = 4) -> np.ndarray:
    return np.full((size, size, 2), (u, v), dtype=np.float32)


def test_still_is_white() -> None:
    assert (flow_to_rgb(_flow(0, 0), 1.0) == 255).all()


def test_the_fastest_rightward_motion_is_pure_red() -> None:
    assert tuple(flow_to_rgb(_flow(3, 0), 3.0)[0, 0]) == (255, 0, 0)


@pytest.mark.parametrize(
    ("u", "v", "colour"),
    [
        (0, 1, (255, 229, 0)),  # down: between the wheel's red and yellow
        (-1, 0, (0, 209, 255)),  # left: past cyan, towards blue
        (0, -1, (88, 0, 255)),  # up: between blue and magenta
    ],
)
def test_each_direction_lands_on_its_place_on_the_wheel(
    u: float,
    v: float,
    colour: tuple[int, int, int],
) -> None:
    assert tuple(flow_to_rgb(_flow(u, v), 1.0)[0, 0]) == colour


def test_the_fastest_motion_is_saturated_at_its_own_speed() -> None:
    """The scale is the fastest pixel's float32 speed, which can come back a rounding error
    past 1 for that pixel: it must not darken as a pixel faster than the scale does.
    """
    flow = _flow(3, 3)
    top = float(np.hypot(*flow.reshape(-1, 2).T).max())
    assert tuple(flow_to_rgb(flow, top)[0, 0]) == (255, 114, 0)


def test_slower_is_paler_rather_than_another_hue() -> None:
    assert tuple(flow_to_rgb(_flow(1, 0), 2.0)[0, 0]) == (255, 127, 127)


def _encode(tmp_path, flows: list[np.ndarray]) -> list[np.ndarray]:
    flow_dir = tmp_path / "flow"
    flow_dir.mkdir()
    for i, flow in enumerate(flows, start=1):
        write_flow_png(flow_dir / f"{i:02d}.png", flow)
    out = tmp_path / "flow.mp4"
    encode_stream(
        sorted(flow_dir.glob("*.png")),
        out,
        fps=24,
        quality=10,
        stream="flow",
        colormap="spectral_r",
    )
    with iio.get_reader(out) as reader:
        return [np.asarray(frame, dtype=np.int32) for frame in reader]


def test_the_video_has_a_still_frame_for_the_last_frame_which_has_no_flow(
    tmp_path,
) -> None:
    """N frames have N - 1 flow fields; the video still has N, so it plays in step with
    the sequence's other streams.
    """
    video = _encode(tmp_path, [_flow(2, 0, 16), _flow(2, 0, 16)])
    assert len(video) == 3
    assert video[-1].min() > 240, "the last frame has no motion, so it is white"


def test_one_scale_serves_the_whole_sequence(tmp_path) -> None:
    """A slow frame beside a fast one is pale, not as saturated as the fast one: the
    colours do not flicker from frame to frame.
    """
    slow, fast = _encode(tmp_path, [_flow(1, 0, 16), _flow(4, 0, 16)])[:2]
    assert slow[8, 8, 1] > 150, "a quarter of the top speed is mostly white"
    assert fast[8, 8, 1] < 60, "the top speed is saturated red"
