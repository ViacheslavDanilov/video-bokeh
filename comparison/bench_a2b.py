"""Time Any-to-Bokeh's pipeline calls: runs under that model's own venv, for bench_speed.py.

Started as ``python bench_a2b.py <inference_demo.py> <demo arguments>``, with
``BENCH_A2B_TIMES`` naming a file. Of the changes ``a2b_launch.py`` makes for the
comparison, it keeps two: the VAE encoder takes its frames in chunks, without which the demo
does not fit the card, and the data loader runs in this process. It leaves out two more. The
UNet and the image encoder stay on the card while the VAE decodes, as a sequence of 24 frames
fits beside them, and moving them would only add copies to the time. TF32 stays at torch's
default, as the demo runs it; ``a2b_launch.py`` turns it off only so that the chunked encoder
matches the whole one exactly. It then wraps the pipeline's call in a CUDA synchronize on
either side and runs the demo unchanged. Each call appends a JSON line: the row of the demo's
CSV it rendered, its seconds, the frames it returned and the peak memory that torch allocated
on the card since that row began.
"""

import json
import os
import runpy
import sys
import time
from pathlib import Path


def time_calls(pipeline_cls, out: Path) -> None:
    """Make each call of ``pipeline_cls`` append its time to ``out``."""
    import torch

    call = pipeline_cls.__call__
    row = 0

    def timed(self, *args, **kwargs):
        nonlocal row
        torch.cuda.synchronize()
        start = time.perf_counter()
        result = call(self, *args, **kwargs)
        torch.cuda.synchronize()
        seconds = time.perf_counter() - start
        record = {
            "row": row,
            "seconds": seconds,
            "frames": len(result[0][0]),
            "peak_mib": round(torch.cuda.max_memory_allocated() / 2**20, 1),
            "torch": torch.__version__,
        }
        with out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        # The demo's last call for a sequence is the one told so.
        if kwargs.get("is_last_batch"):
            row += 1
            torch.cuda.reset_peak_memory_stats()
        return result

    pipeline_cls.__call__ = timed


def main() -> None:
    from a2b_launch import cap_loader_workers, chunk_encoder

    # The demo's modules come from its checkout, never from this folder.
    del sys.path[0]
    demo = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(demo.parents[1]))
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    import torch
    from models.vae import Encoder  # ty: ignore[unresolved-import]
    from pipelines.any2bokeh_pipe import (  # ty: ignore[unresolved-import]
        StableVideoDiffusionPipeline,
    )

    chunk_encoder(Encoder)
    cap_loader_workers(torch.utils.data.DataLoader)
    time_calls(StableVideoDiffusionPipeline, Path(os.environ["BENCH_A2B_TIMES"]))
    sys.argv = [str(demo), *sys.argv[2:]]
    runpy.run_path(str(demo), run_name="__main__")


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    main()
