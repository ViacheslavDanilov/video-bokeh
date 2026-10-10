"""Layer-wise bokeh: blur each layer by its distance from the focus, then composite.

Each layer is blurred on its own, so a pixel spreads its circle of confusion only within
its own layer. The background never bleeds into an object, and a blurred object in front
thins out at its edges to show the whole background behind it. That is the point of
rendering from layers rather than from the composite, where what is behind an object is
gone.

Within a layer every pixel scatters a disk whose radius grows with its distance from the
focus. Radii are binned ``radius_step`` pixels wide, every bin is one convolution with a
disk of its pixels' mean radius, and pixels under half a pixel stay sharp. Each layer is
then divided by how much its bins covered each pixel, so the seams between bins and the
frame's edge neither thin nor darken it. The convolutions run by FFT, whose cost does not
grow with the radius.

The blur runs in linear light. The blurred layers are composited in the frame's own
values, as Stage B composites, so a layer in focus composites exactly as it did there.
"""

from __future__ import annotations

import math

import torch
import torch.nn.functional as F
from torch import Tensor

#: The frame width at which ``strength`` is the radius, in pixels, of a pixel one unit of
#: disparity from the focus. any-to-bokeh renders 1024 pixels wide and calls it ``k``.
REFERENCE_WIDTH = 1024

#: A radius below this many pixels leaves the pixel sharp: its disk is the pixel itself.
_SHARP = 0.5
#: A disk of radius ``r`` covers pixels out to ``r`` plus half a pixel, partly.
_HALF_PIXEL = 0.5
_EPS = 1e-6


def render_bokeh(
    background: Tensor,
    background_disparity: Tensor,
    object_rgbs: Tensor,
    object_alphas: Tensor,
    object_disparities: Tensor,
    paint_order: Tensor,
    focus_disparity: Tensor,
    strength: float,
    radius_step: float = 1.0,
    gamma: float = 2.2,
) -> Tensor:
    """Render the bokeh of a batch of frames from their layers.

    Shapes follow the loader's ``layers`` stream, with frames as the batch dimension ``B``
    and ``N`` objects: ``background`` (B, 3, H, W) and ``background_disparity``
    (B, 1, H, W); ``object_rgbs`` (B, N, 3, H, W), ``object_alphas`` and
    ``object_disparities`` (B, N, H, W); ``paint_order`` (B, N), the objects far to
    near; ``focus_disparity`` (B,). Colours, alphas and disparities in ``[0, 1]``.

    A pixel at disparity ``d`` spreads a disk of radius
    ``strength * |d - focus| * W / REFERENCE_WIDTH`` pixels. ``radius_step`` is the width
    of a radius bin, in pixels. ``gamma`` is the power that makes the colours linear for
    the blur; 1 blurs them as they are.

    Returns the frames, (B, 3, H, W) in ``[0, 1]``, on the inputs' device.
    """
    if radius_step <= 0:
        raise ValueError(f"radius_step must be positive, got {radius_step}")
    if gamma <= 0:
        raise ValueError(f"gamma must be positive, got {gamma}")
    if strength < 0:
        raise ValueError(f"strength must not be negative, got {strength}")
    scale = strength * background.shape[-1] / REFERENCE_WIDTH
    focus = focus_disparity.reshape(-1, 1, 1, 1).to(background)

    def radius(disparity: Tensor) -> Tensor:
        return scale * (disparity - focus).abs()

    out, _ = _blur_layer(
        background,
        None,
        radius(background_disparity),
        radius_step,
        gamma,
    )
    n_objects = object_rgbs.shape[1]
    if n_objects == 0:
        return out.clamp(0.0, 1.0)
    blurred = [
        _blur_object(
            object_rgbs[:, k],
            object_alphas[:, k : k + 1],
            radius(object_disparities[:, k : k + 1]),
            radius_step,
            gamma,
        )
        for k in range(n_objects)
    ]
    colours = torch.stack([c for c, _ in blurred], dim=1)
    alphas = torch.stack([a for _, a in blurred], dim=1)
    frames = torch.arange(out.shape[0], device=out.device)
    for n in range(n_objects):
        k = paint_order[:, n]
        a = alphas[frames, k]
        out = a * colours[frames, k] + (1.0 - a) * out
    return out.clamp(0.0, 1.0)


def _blur_object(
    rgb: Tensor,
    alpha: Tensor,
    radius: Tensor,
    radius_step: float,
    gamma: float,
) -> tuple[Tensor, Tensor]:
    """``_blur_layer`` over a window around the object in each frame, not the frame.

    An object usually covers a small part of the frame. Everything its blur touches,
    coverage included, lies within twice its widest disk of its alpha mask, so a window
    that much wider than the object gives what the whole frame would. The windows are
    one size in every frame, so the frames still blur as one batch.
    """
    colour, alpha_out = torch.zeros_like(rgb), torch.zeros_like(alpha)
    shown = alpha[:, 0] > 0
    if not bool(shown.any()):
        return colour, alpha_out
    reach = 2 * math.ceil(float(radius[alpha > 0].max()) + _HALF_PIXEL) + 1
    height, width = shown.shape[-2:]
    rows = _spans(shown.any(dim=2), reach, height)
    cols = _spans(shown.any(dim=1), reach, width)
    size_h = max(hi - lo for lo, hi in rows)
    size_w = max(hi - lo for lo, hi in cols)
    starts = [
        (min(top, height - size_h), min(left, width - size_w))
        for (top, _), (left, _) in zip(rows, cols, strict=True)
    ]

    def window(t: Tensor) -> Tensor:
        return torch.stack(
            [
                t[f, :, y : y + size_h, x : x + size_w]
                for f, (y, x) in enumerate(starts)
            ],
        )

    blurred, blurred_alpha = _blur_layer(
        window(rgb),
        window(alpha),
        window(radius),
        radius_step,
        gamma,
    )
    for f, (y, x) in enumerate(starts):
        colour[f, :, y : y + size_h, x : x + size_w] = blurred[f]
        alpha_out[f, :, y : y + size_h, x : x + size_w] = blurred_alpha[f]
    return colour, alpha_out


def _spans(present: Tensor, reach: int, length: int) -> list[tuple[int, int]]:
    """Per frame, the rows or columns where ``present`` holds, widened by ``reach``.

    A frame where nothing is present gets an empty span at 0.
    """
    spans = []
    for line in present.tolist():
        hits = [i for i, hit in enumerate(line) if hit]
        if not hits:
            spans.append((0, 0))
            continue
        spans.append((max(hits[0] - reach, 0), min(hits[-1] + 1 + reach, length)))
    return spans


def _blur_layer(
    rgb: Tensor,
    alpha: Tensor | None,
    radius: Tensor,
    radius_step: float,
    gamma: float,
) -> tuple[Tensor, Tensor]:
    """One layer's straight colour and alpha after every pixel scatters its own disk.

    ``rgb`` is (B, 3, H, W), ``alpha`` and ``radius`` (B, 1, H, W). ``alpha`` of None
    is an opaque layer, the background: its alpha is its coverage, which saves one of
    the five channels of every transform. The colour comes back in the frame's own
    values, the alpha at most 1.
    """
    linear = rgb.clamp(0.0, 1.0).pow(gamma)
    ones = torch.ones_like(radius)
    weight = ones if alpha is None else alpha
    if alpha is None:
        # Premultiplied colour is the colour itself, and alpha is the coverage.
        source = torch.cat([linear, ones], dim=1)
    else:
        # Outside its alpha mask a pixel scatters no colour, but it still counts
        # towards how much of the layer covers each pixel, at the radius of the mask
        # beside it.
        radius = _spread_radius(radius, alpha)
        # Premultiplied colour, alpha, and the layer's coverage.
        source = torch.cat([linear * alpha, alpha, ones], dim=1)
    bins = torch.where(
        radius < _SHARP,
        0,
        torch.floor((radius - _SHARP) / radius_step).to(torch.int64) + 1,
    )
    scattered = source * (bins == 0)
    blurred_bins = torch.unique(bins[bins > 0]).tolist()
    if blurred_bins:
        scattered = scattered + _scatter(source, bins, radius, weight, blurred_bins)
    coverage = scattered[:, -1:].clamp(min=_EPS)
    if alpha is None:
        colour = scattered[:, :3] / coverage
        return colour.clamp(0.0, 1.0).pow(1.0 / gamma), ones
    # Only where the bins and the frame's edge leave a pixel short of full coverage: a
    # pixel covered more than once is where blurred neighbours spread over it, and
    # dividing there would thin an edge that is in focus.
    alpha_out = (scattered[:, 3:4] / coverage.clamp(max=1.0)).clamp(max=1.0)
    colour = scattered[:, :3] / scattered[:, 3:4].clamp(min=_EPS)
    return colour.clamp(0.0, 1.0).pow(1.0 / gamma), alpha_out


def _spread_radius(radius: Tensor, alpha: Tensor) -> Tensor:
    """``radius`` inside the alpha mask, and outside it the largest radius of the mask
    within reach, so the coverage around an edge is the edge's own.

    It grows out one pixel a step, as far as the widest disk reaches twice, which is as
    far as coverage matters. Pixels beyond take the layer's mean radius. A maximum,
    rather than an average, is the same on every device.
    """
    inside = alpha > 0
    total = alpha.sum(dim=(2, 3), keepdim=True)
    mean = (radius * alpha).sum(dim=(2, 3), keepdim=True) / total.clamp(min=_EPS)
    if not bool(inside.any()):
        return mean.expand_as(radius)
    filled = torch.where(inside, radius, 0.0)
    known = inside.to(radius.dtype)
    steps = 2 * math.ceil(float(radius[inside].max()) + _HALF_PIXEL) + 1
    for _ in range(steps):
        reached = F.max_pool2d(known, 3, stride=1, padding=1)
        grown = F.max_pool2d(filled, 3, stride=1, padding=1)
        filled = torch.where(known > 0, filled, torch.where(reached > 0, grown, filled))
        known = reached
    return torch.where(known > 0, filled, mean)


def _scatter(
    source: Tensor,
    bins: Tensor,
    radius: Tensor,
    weight: Tensor,
    bin_ids: list[int],
) -> Tensor:
    """The sum over ``bin_ids`` of each bin's pixels convolved with its own disk.

    A bin's disk takes the mean radius of its pixels, weighted by ``weight`` and frame by
    frame: the alpha mask, so pixels outside it cannot pull the radius. A bin that holds
    only such pixels takes their plain mean. The bins' spectra are summed before one
    inverse transform. The padding makes the convolution linear: nothing wraps from one
    edge of the frame to the other.
    """
    height, width = source.shape[-2:]
    masks = [bins == b for b in bin_ids]
    radii = []
    for m in masks:
        total = (weight * m).sum(dim=(1, 2, 3))
        weighted = (radius * weight * m).sum(dim=(1, 2, 3)) / total.clamp(min=_EPS)
        plain = (radius * m).sum(dim=(1, 2, 3)) / m.sum(dim=(1, 2, 3)).clamp(min=1)
        radii.append(torch.where(total > _EPS, weighted, plain))
    half = math.ceil(max(float(r.max()) for r in radii) + _HALF_PIXEL)
    size_h, size_w = _fft_size(height + 2 * half), _fft_size(width + 2 * half)
    spectrum = None
    for mask, r in zip(masks, radii, strict=True):
        kernels = _disks(r, half)
        kernel_spectrum = torch.fft.rfft2(
            F.pad(
                kernels,
                (0, size_w - kernels.shape[-1], 0, size_h - kernels.shape[-2]),
            ),
        )
        term = (
            torch.fft.rfft2(
                F.pad(source * mask, (0, size_w - width, 0, size_h - height)),
            )
            * kernel_spectrum[:, None]
        )
        spectrum = term if spectrum is None else spectrum + term
    full = torch.fft.irfft2(spectrum, s=(size_h, size_w))
    # Each disk sits at the kernel's centre, ``half`` from its corner.
    shifted = torch.roll(full, shifts=(-half, -half), dims=(-2, -1))
    return shifted[..., :height, :width].clamp(min=0.0)


def _disks(radii: Tensor, half: int) -> Tensor:
    """One disk per radius, (B, 2 half + 1, 2 half + 1), each summing to one.

    A pixel's weight is how much of it the disk covers, so the rim is anti-aliased and a
    radius of 0 is the pixel itself.
    """
    axis = torch.arange(-half, half + 1, dtype=radii.dtype, device=radii.device)
    distance = torch.sqrt(axis[:, None] ** 2 + axis[None, :] ** 2)
    disks = (radii[:, None, None] + _HALF_PIXEL - distance).clamp(0.0, 1.0)
    return disks / disks.sum(dim=(1, 2), keepdim=True)


def _fft_size(n: int) -> int:
    """The smallest size at least ``n`` whose only prime factors are 2, 3 and 5."""
    while True:
        m = n
        for p in (2, 3, 5):
            while m % p == 0:
                m //= p
        if m == 1:
            return n
        n += 1
