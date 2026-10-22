#!/usr/bin/env python3
"""Time each compared bokeh renderer per frame, with loading and disk I/O left out.

Runs inside ``comparison/envs/render``, as the adapters do (see ``comparison/README.md``),
and calls their functions rather than their command lines. For every sequence under
``--data-root`` that holds layers and ``bokeh/focus.json``, ``run``

1. reads the frames to be timed and prepares the method's inputs in memory, as its adapter
   does, with the focus and the strength that our renderer recorded; with ``--size``,
   every stream is first resampled to that size by nearest neighbor;
2. renders the first ``--warmup`` frames and discards them;
3. renders each frame, up to ``--frames``: its inputs are copied to the device, and only
   the render call is timed, from a synchronize before it to a synchronize after it.

Loading the models, reading, preparing, copying and writing are therefore outside the time.
Each sequence appends one JSON line to ``--output``: the method, device and size, the
sequence's seed and object count, each frame's milliseconds, the peak memory on the card,
and, where the sequence holds the method's own frames at that size, how far the first timed
frame is from them, in 8-bit levels.

Any-to-Bokeh runs in its own environment and renders clips of frames, not single frames:
``bench_a2b.py`` times each call of its pipeline, and each frame a clip returns takes the
clip's time over its frame count. Its demo resizes every input to 1024 x 576, so it takes no
``--size``. Its first sequence is rendered once more before the others, and discarded.

Before it starts, ``run`` waits until no other process holds memory on the card, and it
records any that it sees after each sequence. ``summary`` reads the JSON lines and writes
two CSVs: one row per method, device, size and sequence, and one per method, device and
size over every timed frame. ``env`` prints the machine and the software versions.

Usage:
    comparison/envs/render/bin/python comparison/bench_speed.py run --method ours \\
        --device cuda --data-root data/speed --size 2048 --output speed.jsonl
    comparison/envs/render/bin/python comparison/bench_speed.py summary speed.jsonl \\
        --out-dir .
    comparison/envs/render/bin/python comparison/bench_speed.py env > environment.json
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import os
import platform
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from common import (
    GAMMA,
    REFERENCE_WIDTH,
    LayeredFrame,
    composite_frame,
    focus_record,
    frames_with_focus,
    renderable_sequences,
)
from PIL import Image

from video_bokeh.core._seq_io import frame_names, sequence_seed

HERE = Path(__file__).resolve().parent
#: Each method's frames, as its adapter writes them; the first timed frame is checked
#: against them.
STREAMS = {
    "ours": "bokeh",
    "ours_one_frame": "bokeh_ours_one_frame",
    "drbokeh": "bokeh_drbokeh",
    "mpib_rt": "bokeh_mpib_rt",
    "mpib_rt_cg": "bokeh_mpib_rt_cg",
    "bokehme": "bokeh_bokehme",
    "bokehme_classical": "bokeh_bokehme_classical",
}
METHODS = (*STREAMS, "any_to_bokeh")
_CUPY = "is a CuPy kernel, and its CPU branch raises NotImplementedError"
#: Why a method does not run on the CPU.
GPU_ONLY = {
    "drbokeh": "its CPU scatter is a Python loop over every pixel and every kernel tap",
    "mpib_rt": f"its ray tracer {_CUPY}",
    "mpib_rt_cg": f"its ray tracer {_CUPY}",
    "bokehme": f"its classical scatter {_CUPY}",
    "bokehme_classical": f"its classical scatter {_CUPY}",
    "any_to_bokeh": "its demo moves the pipeline to cuda:0 and runs it in float16",
}


@dataclass(frozen=True)
class Frame:
    """One frame as any method takes it, at the size it is rendered."""

    name: str
    zf: float
    strength: float
    layers: LayeredFrame
    rgb: np.ndarray  # (3, H, W), the all-in-focus frame
    disparity: np.ndarray  # (H, W), the composite disparity


@dataclass(frozen=True)
class Method:
    """How a method takes a frame, renders it, and gives back its colors."""

    #: The render call's arguments, from a frame, on the CPU.
    prepare: Callable[[Frame], dict]
    #: The render call, on arguments already on the device.
    render: Callable[[dict], torch.Tensor]
    #: The output as the adapter saves it, ``(H, W, 3)`` in ``[0, 1]``.
    to_rgb: Callable[[torch.Tensor], np.ndarray]


def resample(a: np.ndarray, size: int) -> np.ndarray:
    """``a`` with its last two axes, a square, taken to ``size`` by nearest neighbor.

    The result keeps the order of ``a``'s strides, so that a frame stored channel by
    channel or pixel by pixel is stored the same way at every size.
    """
    n = a.shape[-1]
    if a.shape[-2] != n:
        raise ValueError(f"frames must be square, got {a.shape[-2]} x {n}")
    if n == size:
        return a
    index = np.arange(size) * n // size
    out = np.empty_like(a, shape=a.shape[:-2] + (size, size))
    out[...] = a[..., index, :][..., index]
    return out


def read_frames(seq: Path, size: int | None) -> Iterator[Frame]:
    """Each frame of ``seq``, every stream at ``size``, or at its own when None."""
    strength = float(focus_record(seq)["strength"])
    for name, zf, layers in frames_with_focus(seq):
        rgb, disparity = composite_frame(seq, name)
        s = size or rgb.shape[1]

        def at(a: np.ndarray, s: int = s) -> np.ndarray:
            return resample(a, s).astype(np.float32)

        yield Frame(
            name=name,
            zf=zf,
            strength=strength,
            layers=LayeredFrame(
                background=at(layers.background),
                background_disparity=at(layers.background_disparity),
                object_rgbs=at(layers.object_rgbs),
                object_alphas=at(layers.object_alphas),
                object_disparities=at(layers.object_disparities),
                paint_order=layers.paint_order,
            ),
            rgb=at(rgb.transpose(2, 0, 1)),
            disparity=at(disparity),
        )


def _chw_to_rgb(out: torch.Tensor) -> np.ndarray:
    return out[0].permute(1, 2, 0).cpu().numpy()


def ours(one_frame: bool) -> Method:
    """Our renderer on the layers, as Stage C gives them, or on the all-in-focus frame
    alone, as one layer, as ``run_ours_one_frame.py`` gives it."""
    from video_bokeh.layered import render_bokeh

    def prepare(f: Frame) -> dict:
        if one_frame:
            h, w = f.disparity.shape
            layers = {
                "background": torch.from_numpy(f.rgb[None]),
                "background_disparity": torch.from_numpy(f.disparity[None, None]),
                "object_rgbs": torch.zeros(1, 0, 3, h, w),
                "object_alphas": torch.zeros(1, 0, h, w),
                "object_disparities": torch.zeros(1, 0, h, w),
                "paint_order": torch.zeros(1, 0, dtype=torch.long),
            }
        else:
            frame = f.layers

            # Stacked as Stage C's render_sequence stacks a chunk of frames.
            def stacked(a: np.ndarray) -> torch.Tensor:
                return torch.from_numpy(np.stack([a], dtype=np.float32))

            layers = {
                "background": stacked(frame.background),
                "background_disparity": stacked(frame.background_disparity),
                "object_rgbs": stacked(frame.object_rgbs),
                "object_alphas": stacked(frame.object_alphas),
                "object_disparities": stacked(frame.object_disparities),
                "paint_order": torch.tensor([frame.paint_order], dtype=torch.long),
            }
        return {
            **layers,
            "focus_disparity": torch.tensor([f.zf]),
            "strength": f.strength,
        }

    return Method(prepare, lambda x: render_bokeh(**x), _chw_to_rgb)


def drbokeh(device: torch.device) -> Method:
    """Dr.Bokeh as published, compositing in linear light: what
    ``Multi_Layer_Renderer.inference`` runs, without its copies to and from the card."""
    from run_drbokeh import Multi_Layer_Renderer, _layers_near_to_far, _lens_size

    renderers: dict[int, Multi_Layer_Renderer] = {}

    def prepare(f: Frame) -> dict:
        layers = _layers_near_to_far(f.layers)
        k = f.strength * layers[0].shape[1] / REFERENCE_WIDTH
        lens = _lens_size(layers, f.zf, k)
        if lens not in renderers:
            renderers[lens] = Multi_Layer_Renderer(lens).to(device)
        gamma = [
            np.concatenate([layer[..., :3] ** GAMMA, layer[..., 3:]], axis=2)
            for layer in layers
        ]
        rgbad = torch.cat(
            [torch.tensor(layer.transpose(2, 0, 1))[None] for layer in gamma], dim=1
        ).float()
        # inference() puts the focus on every layer's disparity channel.
        focal = torch.zeros_like(rgbad)
        focal[:, 4::5] = f.zf
        return {
            "lens": lens,
            "rgbad": rgbad,
            "lens_effect": torch.ones(1, 1) * k,
            "focal": focal,
        }

    def render(x: dict) -> torch.Tensor:
        return renderers[x["lens"]](x["rgbad"], x["lens_effect"], x["focal"])

    def to_rgb(out: torch.Tensor) -> np.ndarray:
        return np.clip(_chw_to_rgb(out), 0.0, 1.0) ** (1.0 / GAMMA)

    return Method(prepare, render, to_rgb)


def mpib(device: torch.device, composite: str) -> Method:
    """MPIB's ray tracer as ``run_mpib_rt.py`` runs it, in either compositing space."""
    import run_mpib_rt
    from run_mpib_rt import (
        _KERNEL,
        MIN_DISPARITY,
        SAMPLES_PER_SIDE,
        ModuleRenderRT,
        layers_near_to_far,
        per_ray_kernel,
    )

    run_mpib_rt.bokeh_generator.kernel_Render_updateOutput = (
        per_ray_kernel(_KERNEL, GAMMA) if composite == "gamma" else _KERNEL
    )
    power = 1.0 if composite == "gamma" else GAMMA
    renderer = ModuleRenderRT().to(device)

    def prepare(f: Frame) -> dict:
        images, alphas, coffs = layers_near_to_far(f.layers, torch.device("cpu"), power)
        return {
            "images": images,
            "alphas": alphas,
            "coffs": coffs,
            "k": f.strength * images.shape[-1] / REFERENCE_WIDTH,
            "depth_focus": 1.0 / max(f.zf, MIN_DISPARITY),
        }

    def render(x: dict) -> torch.Tensor:
        return renderer(
            x["images"],
            x["alphas"],
            x["coffs"],
            x["k"],
            x["depth_focus"],
            SAMPLES_PER_SIDE,
        )

    def to_rgb(out: torch.Tensor) -> np.ndarray:
        return _chw_to_rgb(torch.nan_to_num(out).clamp(0, 1)) ** (1.0 / GAMMA)

    return Method(prepare, render, to_rgb)


def bokehme(device: torch.device, hybrid: bool) -> Method:
    """BokehMe as ``run_bokehme.py`` runs it: the hybrid, or its classical scatter alone."""
    from run_bokehme import DEMO_ARGS, _load_demo_pipeline, _networks

    namespace = _load_demo_pipeline()
    classical = namespace["ModuleRenderScatter"]().to(device)
    arnet, iunet = _networks(namespace, device) if hybrid else (None, None)

    def prepare(f: Frame) -> dict:
        k = f.strength * f.rgb.shape[-1] / REFERENCE_WIDTH
        defocus = k * (f.disparity - f.zf) / DEMO_ARGS.defocus_scale
        return {
            "image": torch.from_numpy(f.rgb[None]),
            "defocus": torch.from_numpy(defocus.astype(np.float32))[None, None],
        }

    def render(x: dict) -> torch.Tensor:
        if hybrid:
            return namespace["pipeline"](
                classical, arnet, iunet, x["image"], x["defocus"], GAMMA, DEMO_ARGS
            )[0]
        # The first lines of demo.py's pipeline: the scatter, as the pipeline returns it.
        scatter, _ = classical(
            x["image"] ** GAMMA, x["defocus"] * DEMO_ARGS.defocus_scale
        )
        return (scatter ** (1.0 / GAMMA)).clamp(0, 1)

    return Method(prepare, render, _chw_to_rgb)


def build(method: str, device: torch.device) -> Method:
    if method in ("ours", "ours_one_frame"):
        return ours(one_frame=method == "ours_one_frame")
    if method == "drbokeh":
        return drbokeh(device)
    if method in ("mpib_rt", "mpib_rt_cg"):
        return mpib(device, "gamma" if method == "mpib_rt_cg" else "linear")
    return bokehme(device, hybrid=method == "bokehme")


def other_gpu_processes() -> list[str]:
    """Every other process that holds memory on the card, as ``nvidia-smi`` lists it."""
    out = subprocess.run(
        [
            "nvidia-smi",
            "--query-compute-apps=pid,process_name,used_memory",
            "--format=csv,noheader",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [
        line.strip()
        for line in out.splitlines()
        if line.strip() and int(line.split(",")[0]) != os.getpid()
    ]


def wait_for_card() -> None:
    while busy := other_gpu_processes():
        print(f"  waiting: the card is in use by {busy}", flush=True)
        time.sleep(60)


def _sync(device: torch.device) -> None:
    if device.type == "cuda":
        torch.cuda.synchronize(device)


def time_frames(
    method: Method,
    inputs: list[dict],
    device: torch.device,
    warmup: int,
) -> tuple[list[float], np.ndarray]:
    """Each frame's render time in milliseconds after ``warmup`` discarded renders, and
    the first timed frame's colors."""

    def call(x: dict) -> tuple[float, torch.Tensor]:
        x = {k: v.to(device) if torch.is_tensor(v) else v for k, v in x.items()}
        _sync(device)
        start = time.perf_counter()
        out = method.render(x)
        _sync(device)
        return 1000.0 * (time.perf_counter() - start), out

    for x in inputs[:warmup]:
        call(x)
    ms, first = [], None
    for x in inputs:
        elapsed, out = call(x)
        ms.append(elapsed)
        if first is None:
            if out.device.type != device.type:
                raise RuntimeError(f"rendered on {out.device}, not on {device}")
            first = method.to_rgb(out)
    assert first is not None
    return ms, first


def check(seq: Path, stream: str, name: str, rgb: np.ndarray) -> dict | None:
    """How far ``rgb`` is from the frame the method's adapter wrote, if there is one."""
    path = seq / stream / name
    if not path.is_file():
        return None
    with Image.open(path) as im:
        saved = np.asarray(im.convert("RGB"), dtype=np.int16)
    mine = np.round(np.clip(rgb, 0.0, 1.0) * 255.0).astype(np.int16)
    diff = np.abs(mine - saved)
    return {
        "stream": stream,
        "frame": name,
        "max_levels": int(diff.max()),
        "mean_levels": round(float(diff.mean()), 6),
    }


def _commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=HERE, capture_output=True, text=True
    ).stdout.strip()


def run(args: argparse.Namespace) -> None:
    names = args.seqs.split(",") if args.seqs else None
    seqs = list(renderable_sequences(args.data_root, names))
    base = {"method": args.method, "device": args.device, "commit": _commit()}
    if args.method == "any_to_bokeh":
        for record in run_any_to_bokeh(seqs):
            _append(args.output, {**base, **record})
        return
    device = torch.device(args.device)
    if device.type == "cuda":
        wait_for_card()
    method = build(args.method, device)
    for seq in seqs:
        with torch.no_grad():
            frames = itertools.islice(read_frames(seq, args.size), args.frames)
            inputs = [method.prepare(f) for f in frames]
            if device.type == "cuda":
                torch.cuda.reset_peak_memory_stats(device)
            ms, first = time_frames(method, inputs, device, args.warmup)
        native = composite_frame(seq, frame_names(seq)[0])[0].shape[1]
        size = args.size or native
        record = {
            **base,
            "size": size,
            "sequence": seq.name,
            "seed": sequence_seed(seq),
            "objects": _objects(seq),
            "frames": len(frame_names(seq)),
            "warmup": min(args.warmup, len(inputs)),
            "ms": [round(t, 4) for t in ms],
            "peak_mib": round(torch.cuda.max_memory_allocated(device) / 2**20, 1)
            if device.type == "cuda"
            else None,
            "threads": torch.get_num_threads(),
            "check": check(seq, STREAMS[args.method], frame_names(seq)[0], first)
            if size == native
            else None,
            "others_on_card": other_gpu_processes() if device.type == "cuda" else [],
        }
        _append(args.output, record)
        print(
            f"  {seq.name}: {len(ms)} frames, median {np.median(ms):.2f} ms",
            flush=True,
        )


def _objects(seq: Path) -> int:
    return len(next(frames_with_focus(seq))[2].object_alphas)


def run_any_to_bokeh(seqs: list[Path]) -> Iterator[dict]:
    """Time Any-to-Bokeh's pipeline over ``seqs``, through ``bench_a2b.py``."""
    from run_any_to_bokeh import A2B_PYTHON, A2B_ROOT, MIN_FRAMES, write_inputs

    seqs = [seq for seq in seqs if len(frame_names(seq)) >= MIN_FRAMES]
    wait_for_card()
    with tempfile.TemporaryDirectory(prefix="bench-a2b-") as tmp:
        work = Path(tmp)
        csv_path = write_inputs(seqs, work)
        header, *rows = csv_path.read_text(encoding="utf-8").splitlines()
        # The first sequence twice: its first pass is the warm-up.
        csv_path.write_text(
            "\n".join([header, rows[0], *rows]) + "\n", encoding="utf-8"
        )
        times = work / "times.jsonl"
        subprocess.run(
            [
                str(A2B_PYTHON),
                str(HERE / "bench_a2b.py"),
                str(A2B_ROOT / "test" / "inference_demo.py"),
                "--val_csv_path",
                str(csv_path),
                "--unet_path",
                str(A2B_ROOT / "checkpoints" / "unet"),
                "--vae_path",
                str(A2B_ROOT / "checkpoints" / "vae"),
            ],
            cwd=work,
            check=True,
            env={**os.environ, "BENCH_A2B_TIMES": str(times)},
        )
        calls = [json.loads(line) for line in times.read_text().splitlines()]
    others = other_gpu_processes()
    for row, seq in enumerate(seqs, start=1):
        mine = [c for c in calls if c["row"] == row]
        yield {
            "size": composite_frame(seq, frame_names(seq)[0])[0].shape[1],
            "sequence": seq.name,
            "seed": sequence_seed(seq),
            "objects": _objects(seq),
            "frames": len(frame_names(seq)),
            "warmup": len(frame_names(seqs[0])),
            "ms": [
                round(1000.0 * c["seconds"] / c["frames"], 4)
                for c in mine
                for _ in range(c["frames"])
            ],
            "calls": [[round(c["seconds"], 4), c["frames"]] for c in mine],
            "peak_mib": max(c["peak_mib"] for c in mine),
            "torch": mine[0]["torch"],
            "check": None,
            "others_on_card": others,
        }


def _append(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


def _stats(ms: list[float]) -> dict:
    q1, median, q3 = np.percentile(ms, [25, 50, 75])
    return {
        "frames_timed": len(ms),
        "median_ms": round(float(median), 2),
        "q1_ms": round(float(q1), 2),
        "q3_ms": round(float(q3), 2),
        "iqr_ms": round(float(q3 - q1), 2),
    }


def summary(args: argparse.Namespace) -> None:
    records = [
        json.loads(line)
        for path in args.records
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    order = {m: i for i, m in enumerate(METHODS)}
    records.sort(
        key=lambda r: (
            order[r["method"]],
            r["device"] != "cuda",
            r["size"],
            r["sequence"],
        )
    )
    per_sequence = []
    groups: dict[tuple, list[dict]] = {}
    for r in records:
        per_sequence.append(
            {
                "method": r["method"],
                "device": r["device"],
                "size": r["size"],
                "sequence": r["sequence"],
                "seed": r["seed"],
                "objects": r["objects"],
                "frames": r["frames"],
                "warmup": r["warmup"],
                **_stats(r["ms"]),
                "min_ms": round(min(r["ms"]), 2),
                "max_ms": round(max(r["ms"]), 2),
                "peak_gpu_mib": r["peak_mib"],
                "check_max_levels": r["check"]["max_levels"] if r["check"] else "",
            }
        )
        groups.setdefault((r["method"], r["device"], r["size"]), []).append(r)
    pooled = [
        {
            "method": method,
            "device": device,
            "size": size,
            "sequences": len(rs),
            **_stats([t for r in rs for t in r["ms"]]),
            "peak_gpu_mib": max(r["peak_mib"] or 0 for r in rs) or "",
        }
        for (method, device, size), rs in groups.items()
    ]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in (
        (f"{args.prefix}-sequences.csv", per_sequence),
        (f"{args.prefix}.csv", pooled),
    ):
        with (args.out_dir / name).open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)


def environment() -> dict:
    """The card, the CPU and the software the timings ran on."""
    from run_any_to_bokeh import A2B_PYTHON

    def nvidia_smi(*query: str) -> str:
        return subprocess.run(
            ["nvidia-smi", *query], capture_output=True, text=True, check=True
        ).stdout

    header = nvidia_smi()
    cpuinfo = Path("/proc/cpuinfo").read_text()
    a2b = subprocess.run(
        [
            str(A2B_PYTHON),
            "-c",
            "import json, platform, torch, diffusers; print(json.dumps({'python': "
            "platform.python_version(), 'torch': torch.__version__, 'cuda': "
            "torch.version.cuda, 'diffusers': diffusers.__version__}))",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    import cupy

    return {
        "gpu": torch.cuda.get_device_name(0),
        "gpu_memory_mib": torch.cuda.get_device_properties(0).total_memory // 2**20,
        "driver": nvidia_smi(
            "--query-gpu=driver_version", "--format=csv,noheader"
        ).strip(),
        "driver_cuda": header.split("CUDA Version:")[1].split()[0],
        "cpu": next(
            line.split(":", 1)[1].strip()
            for line in cpuinfo.splitlines()
            if line.startswith("model name")
        ),
        "cpu_count": os.cpu_count(),
        "torch_threads": torch.get_num_threads(),
        "memory_gib": round(
            int(Path("/proc/meminfo").read_text().split()[1]) / 2**20, 1
        ),
        "os": platform.freedesktop_os_release()["PRETTY_NAME"],
        "kernel": platform.release(),
        "render_env": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "cudnn": torch.backends.cudnn.version(),
            "cupy": cupy.__version__,
            "numpy": np.__version__,
        },
        "any_to_bokeh_env": json.loads(a2b),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("run", help="time one method on one device")
    p.add_argument("--method", choices=METHODS, required=True)
    p.add_argument("--device", choices=("cuda", "cpu"), required=True)
    p.add_argument("--data-root", type=Path, required=True)
    p.add_argument("--seqs", default=None, help="comma-separated sequence ids")
    p.add_argument("--size", type=int, default=None, help="render at this size")
    p.add_argument("--warmup", type=int, default=5, help="renders discarded first")
    p.add_argument("--frames", type=int, default=None, help="frames timed per sequence")
    p.add_argument("--output", type=Path, required=True, help="JSON lines, appended")
    p = sub.add_parser("summary", help="write the CSVs from run's JSON lines")
    p.add_argument("records", type=Path, nargs="+")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--prefix", default="method-speed")
    sub.add_parser("env", help="print the machine and the software versions")
    args = parser.parse_args(argv)
    if args.command == "run":
        if args.device == "cpu" and args.method in GPU_ONLY:
            parser.error(f"{args.method} has no CPU run: {GPU_ONLY[args.method]}")
        if args.method == "any_to_bokeh" and (args.size or args.frames):
            parser.error(
                "any_to_bokeh takes no --size or --frames: its demo renders whole "
                "sequences, at 1024 x 576"
            )
        run(args)
    elif args.command == "summary":
        summary(args)
    else:
        print(json.dumps(environment(), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
