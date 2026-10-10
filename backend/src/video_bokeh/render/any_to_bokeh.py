"""any-to-bokeh, run in its own environment through its own demo script.

The vendored code needs Python 3.10, ``transformers==4.32.1`` and an NVIDIA card, so it
runs under the venv ``scripts/setup_third_party.sh`` builds, as one program per batch of
sequences. Its inputs and its ``output/`` go to a temporary directory, so the read-only
submodule stays clean. ``_a2b_launch.py`` starts the demo, with its VAE encoder taking a
few frames per call so that it fits a 32 GiB card. ``VIDEO_BOKEH_A2B_ROOT`` and
``VIDEO_BOKEH_A2B_PYTHON`` point at another checkout or interpreter. With
``VIDEO_BOKEH_RUNNER=docker`` it runs in the ``video-bokeh-a2b`` image instead of the venv.

The demo writes a lossy mp4 per sequence at a fixed 1024x576. Each frame is resized back
to the sequence's own size; a lossless path is later work, once a GPU run can check it.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, ClassVar, cast

import imageio.v2 as imageio
from PIL import Image

from video_bokeh.bridge.any_to_bokeh import (
    SequenceInputs,
    list_png_frames,
    write_inputs,
)
from video_bokeh.core._streams import write_bokeh
from video_bokeh.core._worker import model_command, run_script

# backend/third_party/any-to-bokeh; parents[3] is backend/.
_DEFAULT_ROOT = Path(__file__).resolve().parents[3] / "third_party" / "any-to-bokeh"
_SETUP = "scripts/setup_third_party.sh"
_LAUNCH = Path(__file__).with_name("_a2b_launch.py")

#: The demo groups frames eight at a time, four overlapping. Its dataset cannot group a
#: sequence of eight frames or fewer, and nine to twelve make exactly two groups, which
#: its pipeline decodes in one call that drops the trailing frames, so the reshape after
#: it fails. Both fail after the model has loaded. Checked on 2026-10-01: the dataset
#: class on generated sequences, and the pipeline's ``decode_latents`` over 9 to 200
#: frames with a pass-through VAE, which failed at 9 to 12 and nowhere else.
_MIN_FRAMES = 13


class AnyToBokeh:
    """any-to-bokeh, with ``strength`` passed through as its ``k``.

    With no ``focus_disparity``, the focus follows one object, drawn by area, as the bridge
    chooses it; ``bokeh/focus.json`` records which.
    """

    name: ClassVar[str] = "any-to-bokeh"
    #: The image ``make images`` builds, for ``VIDEO_BOKEH_RUNNER=docker``.
    docker_image: ClassVar[str] = "video-bokeh-a2b"
    min_frames: ClassVar[int] = _MIN_FRAMES

    def render(
        self,
        sequence_dirs: list[Path],
        strength: float,
        focus_disparity: float | None,
    ) -> None:
        _refuse_short(sequence_dirs)
        # Absolute, because the demo runs from a temporary directory.
        root = Path(os.environ.get("VIDEO_BOKEH_A2B_ROOT", _DEFAULT_ROOT)).absolute()
        with tempfile.TemporaryDirectory(prefix="any-to-bokeh-") as tmp:
            work = Path(tmp)
            command = model_command(
                "VIDEO_BOKEH_A2B_PYTHON",
                root / ".venv" / "bin" / "python",
                _SETUP,
                self.docker_image,
                mounts=[root, *sequence_dirs],
                workdir=work,
            )
            checkpoints = root / "checkpoints"
            for sub in ("unet", "vae"):
                if not (checkpoints / sub).is_dir():
                    raise RuntimeError(
                        f"no any-to-bokeh checkpoint at {checkpoints / sub}: "
                        f"run {_SETUP}",
                    )

            csv_path = work / "inputs.csv"
            written = write_inputs(
                sequence_dirs,
                videos_root=work / "videos",
                disp_root=work / "disp",
                csv_path=csv_path,
                k=f"{strength:g}",
                focus="object",
                focus_disparity=focus_disparity,
            )
            # The demo writes output/ relative to its working directory.
            run_script(
                [
                    *command,
                    str(_LAUNCH),
                    str(root / "test" / "inference_demo.py"),
                    "--val_csv_path",
                    str(csv_path),
                    "--unet_path",
                    str(checkpoints / "unet"),
                    "--vae_path",
                    str(checkpoints / "vae"),
                ],
                cwd=work,
            )
            outputs = [work / "output" / f"{i}.mp4" for i in range(len(sequence_dirs))]
            # Every count is checked before any frame is written, so a short output
            # leaves no sequence rendered while its neighbours are not.
            for video, seq in zip(outputs, sequence_dirs, strict=True):
                _check_length(video, seq)
            for video, seq, inputs in zip(
                outputs,
                sequence_dirs,
                written,
                strict=True,
            ):
                _write_bokeh(video, seq, inputs, strength)


def _frame_names(seq: Path) -> list[str]:
    return [p.name for p in list_png_frames(seq / "all_in_focus")]


def _refuse_short(sequence_dirs: list[Path]) -> None:
    """Refuse the batch up front if any sequence is too short for the demo to group.

    One short sequence fails the whole batch inside the demo, minutes in, so it is named
    here instead, before the model loads.
    """
    short = [
        f"{seq.name} has {n} frames"
        for seq in sequence_dirs
        if (n := len(_frame_names(seq))) < _MIN_FRAMES
    ]
    if short:
        raise ValueError(
            f"any-to-bokeh needs at least {_MIN_FRAMES} frames per sequence: "
            f"{'; '.join(short)}. Regenerate them with video_bokeh.scenes.generate "
            f"--frames {_MIN_FRAMES} or more.",
        )


def _check_length(video: Path, seq: Path) -> None:
    reader = imageio.get_reader(video)
    try:
        # ``cast`` because imageio types the reader as its base class, and only the
        # ffmpeg plugin's reader can count frames without decoding them.
        frames = cast(Any, reader).count_frames()
    finally:
        reader.close()
    expected = len(_frame_names(seq))
    if frames != expected:
        raise RuntimeError(
            f"any-to-bokeh returned {frames} frames for {expected} in {seq.name}",
        )


def _write_bokeh(
    video: Path,
    seq: Path,
    inputs: SequenceInputs,
    strength: float,
) -> None:
    """Decode one sequence's video into ``bokeh/``, which appears whole or not at all.

    ``focus.json`` beside the frames says what was in focus: the object, by alpha page,
    or null, and each frame's in-focus disparity. It also names the renderer and the
    strength it ran at.
    """
    names = _frame_names(seq)
    with Image.open(seq / "all_in_focus" / names[0]) as first:
        size = first.size
    reader = imageio.get_reader(video)
    try:
        frames = (
            (
                name,
                Image.fromarray(frame)
                .convert("RGB")
                .resize(size, Image.Resampling.BICUBIC),
            )
            for name, frame in zip(names, reader.iter_data(), strict=True)
        )
        record = {
            "object": inputs.focus_object,
            "zf": inputs.zf,
            "renderer": AnyToBokeh.name,
            "strength": strength,
        }
        write_bokeh(seq, frames, record)
    finally:
        reader.close()
