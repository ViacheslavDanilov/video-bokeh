"""any-to-bokeh launcher: runs under that model's own venv, never imported by video_bokeh.

Started as ``python _a2b_launch.py <inference_demo.py> <demo arguments>``, it makes the
VAE encoder take its frames a few at a time and its float32 convolutions exact, moves the
UNet and the image encoder off the card while the VAE decodes, then runs the demo
unchanged. Chunks, the allocator and the offload change only where and in how many calls
the work runs; TF32 off makes the encoder's float32 exact, as the demo meant it.

The demo encodes 16 frames at 1024x576 in one call, and the pipeline upcasts the VAE to
float32 for it. The first down block's activations alone are then 4.5 GiB, and the call
ran out of memory on a 32 GiB RTX 5090 on 2026-10-07. The encoder treats every frame on
its own (convolutions, GroupNorm over each frame's channels), so encoding in chunks and
concatenating gives the same latents. With ``cache_flag`` the encoder also keeps each
down block's input for the decoder; those are concatenated in the same frame order.

cuDNN runs float32 convolutions in TF32 by default, and picks its algorithm by batch size,
so under TF32 the chunked encoder no longer matched the whole one. Measured on the real
VAE, 16 random frames at 1024x576 on the RTX 5090, as the largest difference over the
latent moments and the cached blocks: chunked against whole 0.0023 in strict float32;
under TF32 0.72, and even the demo's own whole-batch call 0.16 off strict float32. TF32
is therefore off. Only the encoder is affected: the UNet and the decoder run in float16.

The decoder then needs about 14 GiB for its eight frames, next to 11.6 GiB already held,
the encoder's cached blocks among them. One 80-frame sequence on the RTX 5090, chunked
encoder and expandable segments: 29.6 GiB at peak, in 68 s. With the UNet and the image
encoder, which the decoder does not use, moved to the CPU meanwhile: 24.9 GiB, in 80 s.
The slower run leaves room for whatever else the card is showing.
"""

import os
import runpy
import sys
from pathlib import Path
from typing import Any

#: Frames per encoder call. Four keeps the largest activation at 1.1 GiB in float32.
CHUNK = 4


def chunk_encoder(encoder_cls: Any, chunk: int = CHUNK) -> None:
    """Make ``encoder_cls.forward`` encode at most ``chunk`` frames per call."""
    forward = encoder_cls.forward

    def chunked(self, sample, cache_flag=False):
        if sample.shape[0] <= chunk:
            return forward(self, sample, cache_flag)
        import torch

        outputs, caches = [], []
        for part in sample.split(chunk):
            outputs.append(forward(self, part, cache_flag))
            if cache_flag:
                caches.append(self.residual_down_blocks)
        if cache_flag:
            self.residual_down_blocks = [
                torch.cat(level) for level in zip(*caches, strict=True)
            ]
        return torch.cat(outputs)

    encoder_cls.forward = chunked


def offload_while_decoding(pipeline_cls: Any) -> None:
    """Keep the pipeline's UNet and image encoder on the CPU while its VAE decodes."""
    decode_latents = pipeline_cls.decode_latents

    def offloaded(self, *args, **kwargs):
        self.unet.to("cpu")
        self.image_encoder.to("cpu")
        try:
            return decode_latents(self, *args, **kwargs)
        finally:
            self.unet.to("cuda")
            self.image_encoder.to("cuda")

    pipeline_cls.decode_latents = offloaded


def main() -> None:
    demo = Path(sys.argv[1]).resolve()
    # The demo puts its checkout root on sys.path itself; the patch needs it first.
    sys.path.insert(0, str(demo.parents[1]))
    # Read when CUDA starts. Without it, 4.3 GiB sat reserved but unusable in pieces
    # when the decoder asked for 4.5.
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    import torch
    from models.vae import Encoder  # ty: ignore[unresolved-import]
    from pipelines.any2bokeh_pipe import (  # ty: ignore[unresolved-import]
        StableVideoDiffusionPipeline,
    )

    chunk_encoder(Encoder)
    offload_while_decoding(StableVideoDiffusionPipeline)
    torch.backends.cudnn.allow_tf32 = False
    sys.argv = [str(demo), *sys.argv[2:]]
    runpy.run_path(str(demo), run_name="__main__")


if __name__ == "__main__":
    # Run as a script, this file's own directory comes first on sys.path, and its
    # siblings (run.py, base.py) must not shadow the demo's own modules.
    del sys.path[0]
    # Nor does the read-only submodule get __pycache__ directories.
    sys.dont_write_bytecode = True
    main()
