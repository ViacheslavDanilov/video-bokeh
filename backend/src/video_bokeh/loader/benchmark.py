"""Measure sequence-stream throughput after draining the DataLoader's prefetch buffer."""

from __future__ import annotations

import argparse
import json
import os
import platform
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path

import torch
from torch.utils.data import DataLoader

from video_bokeh.core._provenance import _git_commit
from video_bokeh.core._streams import BOKEH_STRENGTH
from video_bokeh.library._device import select_device
from video_bokeh.loader import SequenceStream, batch_bokeh
from video_bokeh.loader._stream import DEFAULT_STREAMS


def run_protocol(
    batches: Iterable[Mapping[str, torch.Tensor]],
    clock: Callable[[], float],
    *,
    workers: int,
    min_timed_batches: int = 15,
) -> dict[str, int | float]:
    """Measure collated batches with an injected clock and no device or file I/O.

    Keep one iterator throughout. The clock is read only after warm-up and after the
    timed draws, so a caller can synchronize pending device work before each reading.
    MiB per item counts every input tensor, including collated integer metadata.
    """
    if workers < 0 or min_timed_batches < 1:
        raise ValueError("workers must be nonnegative and min_timed_batches positive")
    warmup_batches = max(1, 2 * workers)
    timed_batches = max(2 * workers, min_timed_batches)
    iterator = iter(batches)
    for _ in range(warmup_batches):
        next(iterator)

    items = total_bytes = 0
    start = clock()
    for _ in range(timed_batches):
        batch = next(iterator)
        items += batch["n_objects"].numel()
        total_bytes += sum(t.numel() * t.element_size() for t in batch.values())
    seconds = clock() - start
    return {
        "warmup_batches": warmup_batches,
        "timed_batches": timed_batches,
        "timed_items": items,
        "timed_seconds": seconds,
        "items_per_second": items / seconds,
        "mib_per_item": total_bytes / items / 2**20,
    }


def _render_batches(
    batches: Iterable[Mapping[str, torch.Tensor]],
    device: torch.device,
    strength: float,
) -> Iterator[Mapping[str, torch.Tensor]]:
    for batch in batches:
        # Discard the render before drawing another batch, as a training loop would.
        # Yield the inputs so memory per item describes what the loader carries.
        batch_bokeh(
            {key: value.to(device, non_blocking=True) for key, value in batch.items()},
            strength=strength,
        )
        yield batch


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library-root", type=Path, required=True)
    parser.add_argument(
        "--streams",
        type=lambda value: tuple(name.strip() for name in value.split(",")),
        default=DEFAULT_STREAMS,
    )
    parser.add_argument("--frames", type=int, default=24)
    parser.add_argument("--size", type=int, default=512)
    parser.add_argument("--objects-min", type=int, default=1)
    parser.add_argument("--objects-max", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--gpu-bokeh", action="store_true")
    parser.add_argument(
        "--device", choices=("auto", "cuda", "mps", "cpu"), default="auto"
    )
    parser.add_argument("--bokeh-strength", type=float, default=BOKEH_STRENGTH)
    parser.add_argument("--min-timed-batches", type=int, default=15)
    parser.add_argument("--unordered", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.workers < 0:
        parser.error("--workers must be nonnegative")
    for name in ("frames", "size", "batch_size", "min_timed_batches"):
        if getattr(args, name) < 1:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    if args.gpu_bokeh and not {"layers", "object_alphas", "focus"} <= set(args.streams):
        parser.error("--gpu-bokeh requires the layers, object_alphas and focus streams")

    device = select_device(args.device) if args.gpu_bokeh else torch.device("cpu")
    if args.gpu_bokeh and args.device not in ("auto", device.type):
        parser.error(f"--device {args.device} is not available")
    try:
        stream = SequenceStream(
            args.library_root,
            n_frames=args.frames,
            size=args.size,
            n_objects_min=args.objects_min,
            n_objects_max=args.objects_max,
            seed=args.seed,
            streams=args.streams,
            bokeh_strength=args.bokeh_strength,
        )
    except ValueError as error:
        parser.error(str(error))
    loader = DataLoader(
        stream,
        batch_size=args.batch_size,
        num_workers=args.workers,
        prefetch_factor=2 if args.workers else None,
        pin_memory=device.type == "cuda",
        in_order=not args.unordered,
    )
    batches = (
        _render_batches(loader, device, args.bokeh_strength)
        if args.gpu_bokeh
        else loader
    )

    def clock() -> float:
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        elif device.type == "mps":
            torch.mps.synchronize()
        return time.perf_counter()

    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)
    numbers = run_protocol(
        batches, clock, workers=args.workers, min_timed_batches=args.min_timed_batches
    )
    peak_gpu_memory_gib = (
        torch.cuda.max_memory_allocated(device) / 2**30
        if device.type == "cuda"
        else None
    )
    for name, value in numbers.items():
        print(f"{name}: {value}")
    if peak_gpu_memory_gib is not None:
        print(f"peak_gpu_memory_gib: {peak_gpu_memory_gib}")
    if args.output is not None:
        record = {
            **{
                key: str(value) if isinstance(value, Path) else value
                for key, value in vars(args).items()
            },
            **numbers,
            "peak_gpu_memory_gib": peak_gpu_memory_gib,
            "torch_version": torch.__version__,
            "resolved_device": device.type,
            "device_name": (
                torch.cuda.get_device_name(device)
                if device.type == "cuda"
                else f"{device.type} ({platform.machine()})"
            ),
            "cpu_count": os.cpu_count(),
            "date": datetime.now(UTC).isoformat(),
            "git_commit": _git_commit(),
        }
        args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
