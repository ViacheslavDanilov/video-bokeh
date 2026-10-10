"""The layer-wise renderer blurs each layer by its distance from the focus, then composites.

Every test builds its layers by hand, small enough to reason about pixel by pixel: a flat
background, a square object, a single bright pixel.
"""

from __future__ import annotations

import math

import pytest
import torch

from video_bokeh.layered import render_bokeh

SIZE = 64
# On a 64-pixel frame, strength 64 spreads a pixel one unit of disparity from the focus into
# a disk of radius 4 pixels: strength * |d - focus| * SIZE / 1024.
STRENGTH = 64.0
RED = (1.0, 0.0, 0.0)
GREEN = (0.0, 1.0, 0.0)
BLUE = (0.0, 0.0, 1.0)


def _flat(colour: tuple[float, float, float]) -> torch.Tensor:
    return torch.tensor(colour).view(1, 3, 1, 1).expand(1, 3, SIZE, SIZE).clone()


def _square(lo: int, hi: int, cols: tuple[int, int] | None = None) -> torch.Tensor:
    alpha = torch.zeros(1, 1, SIZE, SIZE)
    c0, c1 = cols if cols is not None else (lo, hi)
    alpha[..., lo:hi, c0:c1] = 1.0
    return alpha


def _render(
    background: torch.Tensor,
    background_disparity: float | torch.Tensor,
    objects: list[tuple[torch.Tensor, torch.Tensor, float | torch.Tensor]],
    focus: float,
    strength: float = STRENGTH,
    order: list[int] | None = None,
    **kwargs: float,
) -> torch.Tensor:
    """One frame: ``objects`` is (colour, alpha, disparity) per object, far to near."""

    def as_map(d: float | torch.Tensor) -> torch.Tensor:
        return d if isinstance(d, torch.Tensor) else torch.full((1, 1, SIZE, SIZE), d)

    n = len(objects)
    rgbs = (
        torch.stack([c for c, _, _ in objects], dim=1)
        if n
        else torch.zeros(1, 0, 3, SIZE, SIZE)
    )
    alphas = (
        torch.cat([a for _, a, _ in objects], dim=1)
        if n
        else torch.zeros(1, 0, SIZE, SIZE)
    )
    disps = (
        torch.cat([as_map(d) for _, _, d in objects], dim=1)
        if n
        else torch.zeros(1, 0, SIZE, SIZE)
    )
    paint_order = torch.tensor([order if order is not None else list(range(n))])
    return render_bokeh(
        background,
        as_map(background_disparity),
        rgbs,
        alphas,
        disps,
        paint_order,
        torch.tensor([focus]),
        strength,
        **kwargs,
    )[0]


def test_zero_strength_gives_back_the_composite() -> None:
    # Soft, overlapping alphas and a paint order that differs per frame: compositing has
    # to happen in the frame's own values, as Stage B composites, at any gamma.
    g = torch.Generator().manual_seed(0)
    frames, n = 3, 2
    background = torch.rand(frames, 3, SIZE, SIZE, generator=g)
    objects = torch.rand(frames, n, 3, SIZE, SIZE, generator=g)
    alphas = torch.rand(frames, n, SIZE, SIZE, generator=g)
    alphas = alphas * (torch.rand(frames, n, SIZE, SIZE, generator=g) > 0.4)
    order = torch.tensor([[0, 1], [1, 0], [0, 1]])
    expected = background.clone()
    for f in range(frames):
        for k in order[f].tolist():
            a = alphas[f, k]
            expected[f] = a * objects[f, k] + (1 - a) * expected[f]

    out = render_bokeh(
        background,
        torch.rand(frames, 1, SIZE, SIZE, generator=g) * 0.05,
        objects,
        alphas,
        0.3 + torch.rand(frames, n, SIZE, SIZE, generator=g) * 0.3,
        order,
        torch.tensor([0.5, 0.6, 0.7]),
        strength=0.0,
    )
    assert out.shape == (frames, 3, SIZE, SIZE)
    assert torch.allclose(out, expected, atol=1e-5)


def test_an_object_in_focus_stays_sharp_and_the_background_stays_out_of_it() -> None:
    alpha = _square(16, 48)
    out = _render(_flat(RED), 0.0, [(_flat(GREEN), alpha, 0.8)], focus=0.8)
    inside = alpha[0, 0] > 0
    assert torch.allclose(out[:, inside], _flat(GREEN)[0][:, inside], atol=1e-5)
    # The background is blurred but still red wherever the object is not.
    assert torch.allclose(out[:, ~inside], _flat(RED)[0][:, ~inside], atol=1e-5)


def test_a_flat_background_stays_flat_to_the_frame_edge() -> None:
    colour = (0.2, 0.5, 0.7)
    out = _render(_flat(colour), 0.0, [], focus=1.0)
    assert torch.allclose(out, _flat(colour)[0], atol=1e-5)


@pytest.mark.parametrize("gamma", [2.2, 1.0])
def test_a_bright_pixel_keeps_its_energy_in_linear_light(gamma: float) -> None:
    background = torch.zeros(1, 3, SIZE, SIZE)
    background[..., SIZE // 2, SIZE // 2] = 1.0
    out = _render(background, 0.0, [], focus=0.5, strength=192.0, gamma=gamma)
    # One unit of light in each channel, counted in linear light.
    assert out.pow(gamma).sum() == pytest.approx(3.0, abs=1e-3)


def test_a_bright_pixel_spreads_into_a_flat_disk() -> None:
    background = torch.zeros(1, 3, SIZE, SIZE)
    centre = SIZE // 2
    background[..., centre, centre] = 1.0
    # Radius 6: strength * 0.5 * 64 / 1024 = 6.
    out = _render(background, 0.0, [], focus=0.5, strength=192.0, gamma=1.0)

    ys, xs = torch.meshgrid(torch.arange(SIZE), torch.arange(SIZE), indexing="ij")
    distance = torch.sqrt((ys - centre) ** 2 + (xs - centre) ** 2.0)
    assert bool((out[0][distance <= 5.0] > 0).all())
    assert float(out[0][distance >= 7.0].abs().max()) < 1e-6
    lit = out[0][distance <= 5.0]
    assert float(lit.max() - lit.min()) < 1e-5  # a flat disk, not a blob
    # The disk's rim is anti-aliased around radius 6, so its area is close to pi 6^2.
    assert float(lit.mean()) == pytest.approx(1 / (math.pi * 6**2), rel=0.05)


def test_a_blurred_object_in_front_lets_the_background_through_at_its_edge() -> None:
    # The background is in focus; the square in front is not, so its edge thins out.
    alpha = _square(16, 48)
    out = _render(_flat(BLUE), 0.02, [(_flat(RED), alpha, 0.9)], focus=0.02)
    just_inside, just_outside, middle = out[:, 32, 16], out[:, 32, 15], out[:, 32, 32]
    assert just_inside[2] > 0.05 and just_inside[0] > 0.05
    assert just_outside[0] > 0.05
    assert torch.allclose(middle, torch.tensor(RED), atol=1e-5)


def test_an_opaque_object_stays_opaque_across_its_bins() -> None:
    # Disparity ramps across the square, so its pixels fall into several radius bins.
    # Where two bins meet, their blurs must still sum to an opaque object.
    alpha = _square(8, 56)
    ramp = torch.linspace(0.3, 0.9, SIZE).view(1, 1, 1, SIZE).expand(1, 1, SIZE, SIZE)
    out = _render(_flat(BLUE), 0.02, [(_flat(RED), alpha, ramp.clone())], focus=0.02)
    interior = out[:, 16:48, 16:48]
    assert float(interior[2].max()) < 1e-4


def test_an_object_cut_by_the_frame_stays_opaque_at_the_frame_edge() -> None:
    alpha = _square(0, SIZE, cols=(0, 24))
    out = _render(_flat(BLUE), 0.02, [(_flat(RED), alpha, 0.9)], focus=0.02)
    assert float(out[2, 8:56, 0:8].max()) < 1e-4


def test_the_blur_does_not_wrap_around_the_frame() -> None:
    background = _flat(RED)
    background[..., SIZE // 2 :, :] = torch.tensor(BLUE).view(1, 3, 1, 1)
    out = _render(background, 0.0, [], focus=1.0)
    # Wrapping would bring the other half's full colour. What is left is the transform's
    # rounding, about 1e-7, which the inverse gamma lifts to about 1e-3, a quarter of an
    # 8-bit level.
    assert float(out[2, :4].max()) < 1e-3  # no blue at the top
    assert float(out[0, -4:].max()) < 1e-3  # no red at the bottom


def test_the_paint_order_decides_which_object_is_in_front() -> None:
    a, b = _square(10, 40), _square(24, 54)
    objects = [(_flat(RED), a, 0.5), (_flat(GREEN), b, 0.5)]
    red_last = _render(_flat(BLUE), 0.0, objects, focus=0.5, order=[1, 0])
    green_last = _render(_flat(BLUE), 0.0, objects, focus=0.5, order=[0, 1])
    assert torch.allclose(red_last[:, 30, 30], torch.tensor(RED))
    assert torch.allclose(green_last[:, 30, 30], torch.tensor(GREEN))


def test_a_step_wider_than_every_radius_blurs_each_layer_once() -> None:
    # One bin then holds the whole layer, at its mean radius: the same render as an
    # object whose disparity is flat at the radius that mean gives.
    alpha = _square(16, 48)
    ramp = torch.linspace(0.4, 0.8, SIZE).view(1, 1, 1, SIZE).expand(1, 1, SIZE, SIZE)
    mean = float(ramp[0, 0][alpha[0, 0] > 0].mean())
    one_bin = _render(
        _flat(BLUE),
        0.0,
        [(_flat(RED), alpha, ramp.clone())],
        focus=0.0,
        radius_step=100.0,
    )
    flat = _render(_flat(BLUE), 0.0, [(_flat(RED), alpha, mean)], focus=0.0)
    assert torch.allclose(one_bin, flat, atol=1e-4)


@pytest.mark.skipif(not torch.backends.mps.is_available(), reason="needs an MPS device")
def test_mps_renders_what_the_cpu_renders() -> None:
    g = torch.Generator().manual_seed(1)
    args = (
        torch.rand(2, 3, SIZE, SIZE, generator=g),
        torch.rand(2, 1, SIZE, SIZE, generator=g) * 0.05,
        torch.rand(2, 2, 3, SIZE, SIZE, generator=g),
        (torch.rand(2, 2, SIZE, SIZE, generator=g) > 0.5).float(),
        0.3 + torch.rand(2, 2, SIZE, SIZE, generator=g) * 0.4,
        torch.tensor([[0, 1], [1, 0]]),
        torch.tensor([0.1, 0.7]),
    )
    cpu = render_bokeh(*args, strength=STRENGTH)
    mps = render_bokeh(*(t.to("mps") for t in args), strength=STRENGTH)
    assert mps.device.type == "mps"
    # They differ by the devices' rounding, worst where a soft edge divides by a small
    # alpha: a quarter of an 8-bit level at most.
    assert torch.allclose(cpu, mps.cpu(), atol=1e-3)


@pytest.mark.parametrize(
    ("setting", "value"),
    [("radius_step", 0.0), ("radius_step", -1.0), ("gamma", 0.0), ("strength", -1.0)],
)
def test_a_setting_out_of_range_is_refused(setting: str, value: float) -> None:
    with pytest.raises(ValueError, match=setting):
        _render(_flat(BLUE), 0.0, [], focus=0.5, **{setting: value})


def test_a_frame_renders_the_same_alone_as_in_a_batch() -> None:
    # The object moves and grows over three frames, one of them reaching the frame's
    # corner, and the batch blurs them together.
    g = torch.Generator().manual_seed(2)
    boxes = [(4, 20, 6, 18), (30, 60, 20, 58), (0, 12, 50, 64)]
    alphas = torch.zeros(3, 1, SIZE, SIZE)
    for f, (r0, r1, c0, c1) in enumerate(boxes):
        alphas[f, 0, r0:r1, c0:c1] = 0.5 + 0.5 * torch.rand(
            r1 - r0,
            c1 - c0,
            generator=g,
        )
    args = (
        torch.rand(3, 3, SIZE, SIZE, generator=g),
        torch.rand(3, 1, SIZE, SIZE, generator=g) * 0.05,
        torch.rand(3, 1, 3, SIZE, SIZE, generator=g),
        alphas,
        0.5 + torch.rand(3, 1, SIZE, SIZE, generator=g) * 0.3,
        torch.zeros(3, 1, dtype=torch.int64),
        torch.tensor([0.0, 0.2, 0.1]),
    )
    batch = render_bokeh(*args, strength=STRENGTH)
    for f in range(3):
        alone = render_bokeh(*(t[f : f + 1] for t in args), strength=STRENGTH)
        assert torch.allclose(batch[f], alone[0], atol=1e-4)


def test_an_object_s_edge_in_focus_stays_opaque_while_the_rest_blurs() -> None:
    # The square's disparity ramps away from the focus, which sits on its left edge. That
    # edge is sharp, so none of the sharp background behind it may show through.
    alpha = _square(16, 48)
    ramp = torch.linspace(0.3, 0.9, SIZE).view(1, 1, 1, SIZE).expand(1, 1, SIZE, SIZE)
    focus = float(ramp[0, 0, 0, 16])
    out = _render(_flat(BLUE), focus, [(_flat(RED), alpha, ramp.clone())], focus=focus)
    assert float(out[2, 18:46, 16].max()) < 1e-3


def test_the_blurred_end_of_a_sharp_object_fades_as_a_blurred_object_does() -> None:
    # The left half is in focus and the right half four pixels out of it. At the right
    # edge, far from the left half, the object has to fade as if it were all that blurred.
    alpha = _square(16, 48)
    halves = torch.full((1, 1, SIZE, SIZE), 0.5)
    halves[..., 32:] = 0.5 + 4.0 / (STRENGTH * SIZE / 1024)
    half_blurred = _render(_flat(BLUE), 0.5, [(_flat(RED), alpha, halves)], focus=0.5)
    blurred = _render(
        _flat(BLUE),
        0.5,
        [(_flat(RED), alpha, float(halves[0, 0, 0, 40]))],
        focus=0.5,
    )
    edge = slice(42, 54)
    assert torch.allclose(half_blurred[:, 32, edge], blurred[:, 32, edge], atol=0.02)
