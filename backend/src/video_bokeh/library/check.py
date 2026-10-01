"""Will a depth estimator run on this machine? Ask before a library build, not during one.

    python -m video_bokeh.library.check [--model NAME ...] [--device auto] [--measure]

For each depth estimator: whether its environment is in place, how much memory its weights
take, and a verdict against the memory of the device Stage A would use. ``--measure`` runs
one image through each ready estimator, each in a process of its own, and reports what it
actually took.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import huggingface_hub
import torch

from video_bokeh.library._device import select_device
from video_bokeh.library.build import DEFAULT_SIZE
from video_bokeh.library.depth import ESTIMATORS, DepthEstimator, resolve_estimator

#: Every built-in estimator holds its weights in float32, whatever dtype its checkpoint
#: ships in: the transformers ones are cast on load, and Depth Anything 3's checkpoint is
#: float32 already. Its autocast lowers the precision of activations, not of weights.
_FLOAT32_BYTES = 4
#: Binary, the unit a machine's memory is sold in: a "36 GB" Mac holds 36 GiB.
_GIB = 2**30

READY = "ready"
ENVIRONMENT_MISSING = "environment missing"
WEIGHTS_EXCEED_MEMORY = "weights exceed memory"


@dataclass(frozen=True)
class Weights:
    params: int
    #: Whether a load would read them from disk rather than download them first.
    cached: bool

    @property
    def bytes(self) -> int:
        return self.params * _FLOAT32_BYTES


@dataclass(frozen=True)
class Device:
    resolved: torch.device
    #: Bytes: VRAM on CUDA, system memory on MPS and the CPU, which MPS shares.
    total: int
    #: Free VRAM on CUDA; the system's free memory is not reported.
    free: int | None
    #: Why the requested device is not the one resolved, when it is not.
    absent_reason: str | None


@dataclass(frozen=True)
class Report:
    spec: str
    #: Why the estimator cannot run here, or None.
    environment_problem: str | None
    weights: Weights | None
    verdict: str


@dataclass(frozen=True)
class Measurement:
    load_s: float
    per_image_s: float
    memory: int | None


def _header_params(path: Path) -> int:
    """Parameters in one safetensors file, read from its header alone."""
    with path.open("rb") as handle:
        (length,) = struct.unpack("<Q", handle.read(8))
        header = json.loads(handle.read(length))
    total = 0
    for name, tensor in header.items():
        if name == "__metadata__":
            continue
        count = 1
        for dim in tensor["shape"]:
            count *= dim
        total += count
    return total


def _cached(repo: str, filename: str) -> Path | None:
    found = huggingface_hub.try_to_load_from_cache(repo, filename)
    return Path(found) if isinstance(found, str) else None


def _cached_params(repo: str) -> int | None:
    """Parameters of a checkpoint in the local Hugging Face cache, sharded or not."""
    single = _cached(repo, "model.safetensors")
    if single is not None:
        return _header_params(single)
    index = _cached(repo, "model.safetensors.index.json")
    if index is None:
        return None
    shards = sorted(set(json.loads(index.read_text())["weight_map"].values()))
    paths = [_cached(repo, shard) for shard in shards]
    if any(path is None for path in paths):
        return None
    return sum(_header_params(path) for path in paths if path is not None)


def _hub_params(repo: str) -> int | None:
    """Parameters the Hub reports for a checkpoint, or None offline or when it has none."""
    try:
        metadata = huggingface_hub.get_safetensors_metadata(repo)
    except Exception:
        # Offline, gated, missing, or no safetensors: all of them read as unknown.
        return None
    return sum(metadata.parameter_count.values())


def weights_of(estimator: type[DepthEstimator]) -> Weights | None:
    repo = getattr(estimator, "hf_model_id", "")
    if not repo:
        return None
    params = _cached_params(repo)
    if params is not None:
        return Weights(params=params, cached=True)
    params = _hub_params(repo)
    return Weights(params=params, cached=False) if params is not None else None


def _system_memory() -> int:
    return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")


def describe_device(prefer: str) -> Device:
    """The device Stage A's ``--device prefer`` would use, and its memory."""
    resolved = select_device(prefer)
    absent_reason = None
    if prefer not in ("auto", resolved.type):
        absent_reason = (
            f"{prefer} is not available here; Stage A would use {resolved.type}"
        )
    if resolved.type == "cuda":
        free, total = torch.cuda.mem_get_info(resolved)
        return Device(resolved, total=total, free=free, absent_reason=absent_reason)
    return Device(
        resolved,
        total=_system_memory(),
        free=None,
        absent_reason=absent_reason,
    )


def assess(spec: str, device: Device) -> Report:
    estimator = resolve_estimator(spec)
    check_environment = getattr(estimator, "environment_problem", None)
    problem = check_environment() if check_environment is not None else None
    weights = weights_of(estimator)
    if problem is not None:
        verdict = ENVIRONMENT_MISSING
    elif weights is not None and weights.bytes > device.total:
        verdict = WEIGHTS_EXCEED_MEMORY
    else:
        verdict = READY
    return Report(spec, problem, weights, verdict)


class MeasurementFailed(RuntimeError):
    """The child process measuring an estimator did not finish: out of memory, say."""


def measure(spec: str, device: torch.device) -> Measurement:
    """Run ``spec`` once in a fresh process and read back what it took."""
    # The child sees the modules this process sees, a user's own estimator included. An
    # argument rather than PYTHONPATH, which would reach Depth Anything 3's worker too and
    # put this Python's standard library in front of its own.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "video_bokeh.library._measure",
            spec,
            str(device),
            json.dumps(sys.path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    lines = result.stdout.strip().splitlines()
    if result.returncode != 0 or not lines:
        raise MeasurementFailed(
            f"measuring failed (exit {result.returncode}):\n"
            f"{result.stderr.strip()[-2000:]}",
        )
    # The last line: an estimator may print to stdout on its own account.
    figures = json.loads(lines[-1])
    return Measurement(
        load_s=figures["load_s"],
        per_image_s=figures["per_image_s"],
        memory=figures["memory"],
    )


def _gib(n: int | None) -> str:
    return "unknown" if n is None else f"{n / _GIB:.1f} GiB"


def _device_line(device: Device) -> str:
    kind = device.resolved.type
    if kind == "cuda":
        name = torch.cuda.get_device_name(device.resolved)
        return (
            f"Device: cuda, {name}, {_gib(device.total)} VRAM, {_gib(device.free)} free"
        )
    if kind == "mps":
        return (
            f"Device: mps, {_gib(device.total)} of system memory, shared with the CPU"
        )
    return f"Device: cpu, {_gib(device.total)} of system memory"


def _weights_cell(weights: Weights | None) -> str:
    if weights is None:
        return "unknown"
    return f"{_gib(weights.bytes)}, {'cached' if weights.cached else 'not downloaded'}"


def _measure_cells(report: Report, measured: Measurement | None) -> list[str]:
    if measured is None:
        return ["-", "-", "-"]
    load = f"{measured.load_s:.1f} s"
    # Judged from the cache before the run: the load had the weights to fetch first.
    if report.weights is not None and not report.weights.cached:
        load += " (download)"
    return [load, f"{measured.per_image_s:.2f} s", _gib(measured.memory)]


def _table(rows: list[list[str]]) -> str:
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    return "\n".join(
        "  ".join(
            cell.ljust(width) for cell, width in zip(row, widths, strict=True)
        ).rstrip()
        for row in rows
    )


_CAVEAT = (
    "`ready` means the environment is in place and the weights fit in the device's\n"
    f"memory. That is necessary, not sufficient: inference at {DEFAULT_SIZE} px needs memory\n"
    "for activations, the intermediate results of a forward pass, on top, which nothing\n"
    "here estimates. --measure runs one image through each ready estimator and reports\n"
    "what it took."
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        # The docstring's usage line and paragraphs are laid out for reading as they are.
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--model",
        action="append",
        help="a registered estimator or package.module:ClassName, repeatable "
        "(default: every registered estimator)",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cuda", "mps", "cpu"),
        default="auto",
    )
    parser.add_argument(
        "--measure",
        action="store_true",
        help=f"run one {DEFAULT_SIZE} px image through each ready estimator, each in "
        "its own process, and report load time, seconds per image and memory",
    )
    args = parser.parse_args(argv)

    device = describe_device(args.device)
    print(_device_line(device))
    if device.absent_reason is not None:
        print(f"  {device.absent_reason}")
    print()

    header = ["depth estimator", "environment", "weights, float32", "verdict"]
    if args.measure:
        header += ["load", "per image", "memory"]
    rows = [header]
    reasons: list[str] = []
    all_ready = True
    for spec in args.model or sorted(ESTIMATORS):
        report = assess(spec, device)
        all_ready &= report.verdict == READY
        row = [spec, "missing" if report.environment_problem else "in place"]
        row += [_weights_cell(report.weights), report.verdict]
        if report.environment_problem is not None:
            reasons.append(f"{spec}: {report.environment_problem}")
        if args.measure:
            # One estimator running out of memory must not hide what the others took.
            try:
                measured = (
                    measure(spec, device.resolved) if report.verdict == READY else None
                )
                row += _measure_cells(report, measured)
            except MeasurementFailed as exc:
                all_ready = False
                row += ["failed", "-", "-"]
                reasons.append(f"{spec}: {exc}")
        rows.append(row)
    print(_table(rows))
    for reason in reasons:
        print(f"\n{reason}")
    print(f"\n{_CAVEAT}")
    return 0 if all_ready else 1


if __name__ == "__main__":
    sys.exit(main())
