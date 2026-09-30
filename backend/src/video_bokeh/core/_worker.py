"""Run a model in its own environment, as a worker process speaking JSON lines.

Some models cannot share our lock: their pins contradict ours. They run under their own
interpreter instead, and the stage interface hides that. The protocol is one JSON object
per line: the worker announces ``{"ready": true}`` once its model is loaded, then answers
each request with one reply, or with ``{"error": "..."}``. When stdin closes, the worker
exits.

A worker keeps file descriptor 1 for the protocol alone. It duplicates fd 1 for its
replies and points fd 1 at stderr, so that nothing else can write there: not a model's
logging, not native code, not a child process.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

#: Enough of the worker's stderr to show why it failed, not a whole model load.
_STDERR_TAIL = 4000


class WorkerError(RuntimeError):
    """The worker refused a request, or exited, with its reason."""


def interpreter(env_var: str, default: Path, setup: str) -> Path:
    """The interpreter a worker runs under: ``env_var`` if set, else ``default``.

    Raises before anything starts when it is missing, naming ``setup``, the script that
    builds that environment.
    """
    python = Path(os.environ.get(env_var, default))
    if not python.exists():
        raise RuntimeError(
            f"no interpreter at {python}: run {setup}, or set {env_var}",
        )
    return python


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
