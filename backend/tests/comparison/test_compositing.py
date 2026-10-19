"""Compositing in gamma values for the reference renderers: Dr.Bokeh's layer composite and the
edit to MPIB's ray-tracing kernel, without their CUDA stacks."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "comparison"))

from common import GAMMA, composite_near_to_far  # noqa: E402
from mpib_kernel import per_ray_kernel  # noqa: E402

#: The shape of MPIB's kernel around what the edit touches: the per-pixel sums, the loop over
#: aperture samples, the loop over layers nearest first, and the division at the end.
KERNEL = """
            float num = 0;
            float sumR = 0;
            for (int i = 0; i < samples; ++i) {
                float alpha_prev = 1;
                for (int l = 0; l < SIZE_1(images); ++l) {
                    if (inside) {
                        sumR += f * alpha_prev;
                        sumG += f * alpha_prev;
                        sumB += f * alpha_prev;
                        num += alpha_curr * alpha_prev;
                        alpha_prev *= (1 - alpha_curr);
                    }
                }
            }
            bokeh[OFFSET_4(bokeh, b, 0, y, x)] = sumR / num;
            bokeh[OFFSET_4(bokeh, b, 1, y, x)] = sumG / num;
"""


def _layer(color: float, occupancy: float, weight: float = 2.0):
    """A layer of one pixel: its color scattered with ``weight``, and its occupancy."""
    return (
        np.array([color * weight]),
        np.array([weight]),
        np.array([occupancy]),
    )


def test_an_opaque_near_layer_hides_the_rest() -> None:
    out = composite_near_to_far([_layer(0.3, 1.0), _layer(0.9, 1.0)])
    assert out == pytest.approx([0.3])


def test_a_partial_layer_mixes_in_linear_light_by_default() -> None:
    out = composite_near_to_far([_layer(0.2, 0.25), _layer(0.6, 1.0)])
    assert out == pytest.approx([0.25 * 0.2 + 0.75 * 0.6])


def test_composited_in_gamma_values_each_layer_returns_to_gamma_first() -> None:
    near, far = 0.2, 0.6  # linear light
    out = composite_near_to_far(
        [_layer(near, 0.25), _layer(far, 1.0)], power=1.0 / GAMMA
    )
    expected = 0.25 * near ** (1 / GAMMA) + 0.75 * far ** (1 / GAMMA)
    assert out == pytest.approx([expected])
    # mixed in linear light and then brought to gamma values, the edge comes out lighter
    linear = composite_near_to_far([_layer(near, 0.25), _layer(far, 1.0)])
    assert out < linear ** (1 / GAMMA)


def test_the_kernel_closes_each_ray_before_the_average() -> None:
    edited = per_ray_kernel(KERNEL, GAMMA)
    for channel in "RGB":
        assert f"ray{channel} += f * alpha_prev;" in edited
        assert f"sum{channel} += f * alpha_prev;" not in edited
        assert (
            f"sum{channel} += powf(fmaxf(ray{channel} / rayNum, 0.0f), 2.200000f) * rayNum;"
            in edited
        )
    assert "rayNum += alpha_curr * alpha_prev;" in edited
    # each ray starts from nothing, and is closed after its layer loop, inside the sample loop
    start = edited.index("float rayR = 0, rayG = 0, rayB = 0, rayNum = 0;")
    assert edited.index("float alpha_prev = 1;") < start
    layers_end = edited.index("alpha_prev *= (1 - alpha_curr);")
    close = edited.index("if (rayNum > 0)")
    assert layers_end < close < edited.index("= sumR / num;")
    assert edited.count("num += rayNum;") == 1


def test_a_power_of_one_keeps_the_rays_in_the_colors_own_space() -> None:
    assert "powf(fmaxf(rayR / rayNum, 0.0f), 1.000000f)" in per_ray_kernel(KERNEL, 1.0)


def test_a_kernel_of_another_shape_is_refused() -> None:
    with pytest.raises(ValueError, match="sumG"):
        per_ray_kernel(KERNEL.replace("sumG += f * alpha_prev;", ""), GAMMA)
    with pytest.raises(ValueError, match="loops"):
        per_ray_kernel(KERNEL.replace("= sumR / num;", "= sumR;"), GAMMA)
