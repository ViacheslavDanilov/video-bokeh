"""Measure one depth estimator in a process of its own, for ``video_bokeh.library.check``.

``python -m video_bokeh.library._measure <estimator> <device> <sys.path as JSON>`` puts the
caller's import path in front of its own, loads the estimator, runs one
warm-up and one timed image at Stage A's default size, and prints one JSON line on stdout:
``{"load_s": ..., "per_image_s": ..., "memory": ...}``.

A process of its own because none of the memory figures can be reset inside one: the peak
resident set never falls, MPS keeps no peak at all, and whatever an earlier estimator
imported and allocated would be charged to the next.
"""

from __future__ import annotations

import json
import resource
import sys
import time

import numpy as np
import torch
from PIL import Image

from video_bokeh.library.build import DEFAULT_SIZE
from video_bokeh.library.depth import resolve_estimator


def peak_memory(device: torch.device) -> int:
    """Bytes this process holds on ``device``, as well as each backend can say.

    CUDA keeps a true peak. MPS keeps none, so this is what its driver still holds after
    the run, which its caching allocator keeps close to the peak. On the CPU it is the
    peak resident set, which counts nothing an MPS tensor holds: on 2026-10-01 a 2 GB
    MPS tensor moved it by 13 MB.
    """
    if device.type == "cuda":
        return int(torch.cuda.max_memory_allocated(device))
    if device.type == "mps":
        return int(torch.mps.driver_allocated_memory())
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Bytes on macOS, kibibytes on Linux.
    return int(rss if sys.platform == "darwin" else rss * 1024)


def _synchronize(device: torch.device) -> None:
    if device.type == "cuda":
        torch.cuda.synchronize(device)
    elif device.type == "mps":
        torch.mps.synchronize()


def _image() -> Image.Image:
    rng = np.random.default_rng(0)
    pixels = rng.integers(0, 256, (DEFAULT_SIZE, DEFAULT_SIZE, 3), dtype=np.uint8)
    return Image.fromarray(pixels)


def main(argv: list[str]) -> int:
    spec, device = argv[0], torch.device(argv[1])
    sys.path[:0] = [p for p in json.loads(argv[2]) if p not in sys.path]
    estimator = resolve_estimator(spec)()

    start = time.perf_counter()
    estimator.load(device)
    # A copy of the weights still in flight belongs to the load, not to the warm-up.
    _synchronize(device)
    load_s = time.perf_counter() - start

    image = _image()
    estimator.infer([image])
    _synchronize(device)
    start = time.perf_counter()
    estimator.infer([image])
    _synchronize(device)
    per_image_s = time.perf_counter() - start

    # An estimator that keeps its weights in another process reports that process.
    elsewhere = getattr(estimator, "peak_memory", None)
    memory = elsewhere() if elsewhere is not None else peak_memory(device)
    close = getattr(estimator, "close", None)
    if close is not None:
        close()

    print(json.dumps({"load_s": load_s, "per_image_s": per_image_s, "memory": memory}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
