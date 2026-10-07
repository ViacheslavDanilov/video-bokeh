"""The launcher's patches: a chunked VAE encoder, against a small encoder shaped like
any-to-bokeh's, and the UNet and image encoder moved off the card while decoding.
"""

from __future__ import annotations

import pytest

from video_bokeh.render._a2b_launch import (
    cap_loader_workers,
    chunk_encoder,
    offload_while_decoding,
)

torch = pytest.importorskip("torch")
nn = torch.nn


class _Encoder(nn.Module):
    """any-to-bokeh's ``models.vae.Encoder`` in miniature: per-frame convolutions and
    GroupNorm, and with ``cache_flag`` each down block's input kept for the decoder.
    """

    def __init__(self) -> None:
        super().__init__()
        self.conv_in = nn.Conv2d(3, 8, 3, padding=1)
        self.down_blocks = nn.ModuleList(
            nn.Sequential(nn.Conv2d(8, 8, 3, stride=2, padding=1), nn.GroupNorm(4, 8))
            for _ in range(3)
        )
        self.conv_out = nn.Conv2d(8, 4, 3, padding=1)

    def forward(self, sample, cache_flag=False):
        sample = self.conv_in(sample)
        blocks = []
        for block in self.down_blocks:
            if cache_flag:
                blocks.append(sample)
            sample = block(sample)
        if cache_flag:
            self.residual_down_blocks = blocks
        return self.conv_out(sample)


@pytest.fixture
def encoders() -> tuple[_Encoder, _Encoder]:
    # A fresh subclass per test, so one test's patch never wraps another's.
    class _Chunked(_Encoder):
        pass

    torch.manual_seed(0)
    whole = _Encoder().eval()
    chunk_encoder(_Chunked, chunk=4)
    chunked = _Chunked().eval()
    chunked.load_state_dict(whole.state_dict())
    return whole, chunked


@pytest.mark.parametrize("cache_flag", [False, True])
def test_chunks_give_the_whole_batch_s_latents(encoders, cache_flag: bool) -> None:
    whole, chunked = encoders
    # Ten frames: two full chunks and a short one.
    frames = torch.randn(10, 3, 32, 32)
    with torch.no_grad():
        expected = whole(frames, cache_flag)
        actual = chunked(frames, cache_flag)
    torch.testing.assert_close(actual, expected)
    if cache_flag:
        assert len(chunked.residual_down_blocks) == len(whole.residual_down_blocks)
        for got, want in zip(
            chunked.residual_down_blocks,
            whole.residual_down_blocks,
            strict=True,
        ):
            torch.testing.assert_close(got, want)


def test_without_cache_flag_the_cached_blocks_stay(encoders) -> None:
    """The pipeline encodes the reference frames with ``cache_flag`` and the CoC maps
    without it, and the decoder then reads the reference frames' blocks.
    """
    _, chunked = encoders
    with torch.no_grad():
        chunked(torch.randn(10, 3, 32, 32), cache_flag=True)
        cached = list(chunked.residual_down_blocks)
        chunked(torch.randn(10, 3, 32, 32), cache_flag=False)
    assert all(
        a is b for a, b in zip(chunked.residual_down_blocks, cached, strict=True)
    )


class _Model:
    def __init__(self, log: list[str], name: str) -> None:
        self.log, self.name = log, name

    def to(self, device: str) -> _Model:
        self.log.append(f"{self.name} to {device}")
        return self


def test_the_unet_and_image_encoder_leave_the_card_while_decoding() -> None:
    log: list[str] = []

    class Pipeline:
        def __init__(self) -> None:
            self.unet = _Model(log, "unet")
            self.image_encoder = _Model(log, "image_encoder")

        def decode_latents(self, *args, **kwargs):
            log.append("decode")
            if kwargs.get("fail"):
                raise RuntimeError("decode failed")
            return args

    offload_while_decoding(Pipeline)
    pipe = Pipeline()
    assert pipe.decode_latents(1, 2) == (1, 2)
    assert log == [
        "unet to cpu",
        "image_encoder to cpu",
        "decode",
        "unet to cuda",
        "image_encoder to cuda",
    ]
    log.clear()
    with pytest.raises(RuntimeError, match="decode failed"):
        pipe.decode_latents(fail=True)
    assert log[-2:] == ["unet to cuda", "image_encoder to cuda"]


def test_the_data_loader_starts_no_workers() -> None:
    """The demo asks for 64, each holding whole sequences in shared memory."""

    class Loader(torch.utils.data.DataLoader):
        pass

    cap_loader_workers(Loader)
    assert Loader(list(range(4)), num_workers=64).num_workers == 0
    assert Loader(list(range(4))).num_workers == 0


def test_the_cap_leaves_fewer_workers_alone() -> None:
    class Loader(torch.utils.data.DataLoader):
        pass

    cap_loader_workers(Loader, workers=2)
    assert Loader(list(range(4)), num_workers=64).num_workers == 2
    assert Loader(list(range(4)), num_workers=1).num_workers == 1
