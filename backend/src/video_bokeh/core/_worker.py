"""Run a model in its own environment, as a worker process speaking JSON lines.

Some models cannot share our lock: their pins contradict ours. They run under their own
interpreter instead, and the stage interface hides that. The protocol is one JSON object
per line: the worker announces ``{"ready": true}`` once its model is loaded, then answers
each request with one reply, or with ``{"error": "..."}``. When stdin closes, the worker
exits.

A model that cannot be driven that way, such as a vendored demo script, runs to completion
instead, through ``run_script``.

A worker keeps file descriptor 1 for the protocol alone. It duplicates fd 1 for its
replies and points fd 1 at stderr, so that nothing else can write there: not a model's
logging, not native code, not a child process.
"""

from __future__ import annotations

import getpass
import json
import os
import subprocess
import sys
import tempfile
from collections import deque
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

#: Enough of the worker's stderr to show why it failed, not a whole model load.
_STDERR_TAIL = 4000
#: The same, counted in lines, for a script whose output is streamed as it runs.
_SCRIPT_TAIL_LINES = 60


class WorkerError(RuntimeError):
    """A worker refused a request or exited, or a script failed, with the reason."""


def interpreter(env_var: str, default: Path, setup: str) -> Path:
    """The interpreter a worker runs under: ``env_var`` if set, else ``default``.

    Raises before anything starts when it is missing, naming ``setup``, the script that
    builds that environment.
    """
    # Absolute but not resolved: a venv's python is a symlink, and following it would
    # leave the venv. Absolute, because a worker may run from another directory.
    python = Path(os.environ.get(env_var, default)).absolute()
    if not python.exists():
        raise RuntimeError(
            f"no interpreter at {python}: run {setup}, or set {env_var}",
        )
    return python


#: The repository, mounted into every model container. parents[4] is the repository root.
_REPO = Path(__file__).resolve().parents[4]
#: Enough for the any-to-bokeh demo's data loader, which starts 64 worker processes that
#: share tensors through /dev/shm; Docker's default is 64 MiB.
_SHM_SIZE = "16g"


def runner() -> str:
    """``VIDEO_BOKEH_RUNNER``: ``local``, the default, or ``docker``."""
    value = os.environ.get("VIDEO_BOKEH_RUNNER", "local")
    if value not in ("local", "docker"):
        raise ValueError(f"VIDEO_BOKEH_RUNNER must be local or docker, not {value!r}")
    return value


def model_command(
    env_var: str,
    default: Path,
    setup: str,
    image: str,
    *,
    mounts: Iterable[Path] = (),
    workdir: Path | None = None,
) -> list[str]:
    """The command a model's own Python runs under, by ``VIDEO_BOKEH_RUNNER``.

    ``local``, the default, is the interpreter ``interpreter`` finds. ``docker`` is
    ``python`` in ``image``, with the GPU. The repository, the temporary directory, the
    Hugging Face cache and ``mounts`` are mounted at their own paths, so a path means the
    same inside and out, and the container runs as this user, so what it writes is ours.
    ``workdir`` is where it starts. Raises before anything starts when the venv or the
    image is missing.
    """
    if runner() == "local":
        return [str(interpreter(env_var, default, setup))]
    found = subprocess.run(
        ["docker", "image", "inspect", image],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if found.returncode != 0:
        # Only a missing image is the image's fault; an unreachable daemon or a user
        # outside the docker group says so itself.
        if "no such image" in found.stderr.lower():
            raise RuntimeError(f"no Docker image {image}: run make images")
        raise RuntimeError(f"docker cannot inspect {image}: {found.stderr.strip()}")
    hf_home = Path(
        os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"),
    ).absolute()
    hf_home.mkdir(parents=True, exist_ok=True)
    # The user has no home in the image. This one is theirs, not a name in the shared /tmp
    # that someone else could take first.
    home = Path.home() / ".cache" / "video-bokeh-home"
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    argv = ["docker", "run", "--rm", "-i", "--init", "--gpus", "all"]
    # Labelled, so a container left behind by a killed run can be found and stopped.
    argv += ["--label", f"video-bokeh.model={image}"]
    argv += [f"--shm-size={_SHM_SIZE}", "--user", f"{os.getuid()}:{os.getgid()}"]
    argv += ["-e", f"HF_HOME={hf_home}", "-e", f"HOME={home}"]
    # Nor a name: getpass, which torch asks for its cache path, falls back to these.
    user = getpass.getuser()
    argv += ["-e", f"USER={user}", "-e", f"LOGNAME={user}"]
    paths = [_REPO, Path(tempfile.gettempdir()), hf_home, home, *mounts]
    for host, inside in _mounts(paths):
        argv += ["-v", f"{host}:{inside}"]
    if workdir is not None:
        argv += ["-w", str(Path(workdir).absolute())]
    return [*argv, image, "python"]


def _mounts(paths: Iterable[Path]) -> list[tuple[Path, Path]]:
    """Host and container path of each mount, so that every path in ``paths`` resolves.

    A path is mounted where it really is. A symlink, to data on another disk say, is also
    mounted under its own name unless a mounted parent already holds the link: the
    container is handed the link's name, in HF_HOME, -w or an argument.
    """
    given = [Path(os.path.normpath(Path(p).absolute())) for p in paths]
    pairs = [(real, real) for real in _outermost(p.resolve() for p in given)]
    for path in given:
        real = path.resolve()
        if path != real and not any(path.is_relative_to(inside) for _, inside in pairs):
            pairs.append((real, path))
    return pairs


def _outermost(paths: Iterable[Path]) -> list[Path]:
    """Each path once, leaving out any that lies inside another."""
    unique = sorted(set(paths), key=lambda p: len(p.parts))
    kept: list[Path] = []
    for path in unique:
        if not any(path.is_relative_to(outer) for outer in kept):
            kept.append(path)
    return kept


def run_script(argv: list[str], cwd: Path) -> None:
    """Run a program to completion, showing its output as it goes.

    Its stdout and stderr are forwarded to ours line by line, because a model run can take
    minutes and silence looks like a hang. Raises WorkerError with the last lines if it
    exits non-zero.
    """
    tail: deque[str] = deque(maxlen=_SCRIPT_TAIL_LINES)
    with subprocess.Popen(
        argv,
        cwd=cwd,
        # Nothing to read: under docker -i the terminal would otherwise be attached.
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    ) as proc:
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stderr.write(line)
            tail.append(line)
    if proc.returncode != 0:
        raise WorkerError(
            f"{' '.join(argv[:2])} exited with code {proc.returncode}:\n"
            f"{''.join(tail).strip()}",
        )


class WorkerProcess:
    """One worker, started and loaded on construction, alive until ``close``."""

    def __init__(self, argv: list[str]) -> None:
        # A file rather than a pipe: a model can log megabytes while it loads, and a pipe
        # nobody reads until the end would fill and block it.
        self._stderr = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
        self._proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr,
            text=True,
            encoding="utf-8",
        )
        try:
            ready = self._read()
            if not ready.get("ready"):
                raise WorkerError(f"worker did not announce itself ready: {ready}")
        except WorkerError:
            self.close()
            raise

    def request(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Send one request and wait for its reply."""
        stdin = self._proc.stdin
        assert stdin is not None
        try:
            stdin.write(json.dumps(payload) + "\n")
            stdin.flush()
        except BrokenPipeError:
            raise WorkerError(self._exited("before the request")) from None
        reply = self._read()
        if "error" in reply:
            raise WorkerError(str(reply["error"]))
        return reply

    @property
    def returncode(self) -> int | None:
        return self._proc.returncode

    def close(self) -> None:
        """Close stdin, which tells the worker to exit, and wait for it."""
        stdin = self._proc.stdin
        if stdin is not None and not stdin.closed:
            try:
                stdin.close()
            except BrokenPipeError:
                # The worker is gone and the last request is still buffered; closing
                # retries the write. Nothing is left to deliver.
                pass
        try:
            self._proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
        if self._proc.stdout is not None:
            self._proc.stdout.close()
        self._stderr.close()

    def _read(self) -> dict[str, Any]:
        stdout = self._proc.stdout
        assert stdout is not None
        line = stdout.readline()
        if not line:
            self._proc.wait()
            raise WorkerError(self._exited("without replying"))
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            raise WorkerError(
                f"worker wrote something other than the protocol: {line[:200]!r}\n"
                f"{self._stderr_tail()}",
            ) from None

    def _exited(self, when: str) -> str:
        return (
            f"worker exited {when} (code {self._proc.poll()}):\n{self._stderr_tail()}"
        )

    def _stderr_tail(self) -> str:
        self._stderr.flush()
        self._stderr.seek(0)
        return self._stderr.read()[-_STDERR_TAIL:].strip()
