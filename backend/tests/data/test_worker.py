"""A model in its own environment is a worker process speaking JSON lines."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from video_bokeh.core._worker import WorkerError, WorkerProcess

# What a real worker does: keeps fd 1 for the protocol, so that the model's own output,
# even native code writing straight to fd 1, lands on stderr.
_ECHO = """
import json, os, sys
reply = os.fdopen(os.dup(1), "w")
os.dup2(2, 1)
sys.stdout = sys.stderr
print("a model's own chatter")
os.write(1, b"native code writing to fd 1\\n")
reply.write(json.dumps({"ready": True}) + "\\n"); reply.flush()
for line in sys.stdin:
    req = json.loads(line)
    if req.get("fail"):
        reply.write(json.dumps({"error": "bad request"}) + "\\n")
    elif req.get("crash"):
        print("worker died here", file=sys.stderr)
        sys.exit(3)
    else:
        reply.write(json.dumps({"echo": req}) + "\\n")
    reply.flush()
"""

# A worker that forgot to protect fd 1.
_CHATTY = """
import json, sys
print(json.dumps({"ready": True}), flush=True)
for line in sys.stdin:
    print("log line from the model", flush=True)
"""

_DIES_ON_START = """
import sys
print("cannot load weights", file=sys.stderr)
sys.exit(1)
"""


def _script(tmp_path: Path, body: str) -> list[str]:
    path = tmp_path / "worker.py"
    path.write_text(body, encoding="utf-8")
    return [sys.executable, str(path)]


def test_request_gets_its_reply(tmp_path: Path) -> None:
    worker = WorkerProcess(_script(tmp_path, _ECHO))
    try:
        assert worker.request({"n": 1}) == {"echo": {"n": 1}}
        assert worker.request({"n": 2}) == {"echo": {"n": 2}}
    finally:
        worker.close()


def test_an_error_reply_raises(tmp_path: Path) -> None:
    worker = WorkerProcess(_script(tmp_path, _ECHO))
    try:
        with pytest.raises(WorkerError, match="bad request"):
            worker.request({"fail": True})
    finally:
        worker.close()


def test_a_worker_that_dies_on_start_says_why(tmp_path: Path) -> None:
    with pytest.raises(WorkerError, match="cannot load weights"):
        WorkerProcess(_script(tmp_path, _DIES_ON_START))


def test_a_worker_that_dies_mid_request_says_why(tmp_path: Path) -> None:
    worker = WorkerProcess(_script(tmp_path, _ECHO))
    try:
        with pytest.raises(WorkerError, match="worker died here"):
            worker.request({"crash": True})
    finally:
        worker.close()


def test_output_that_is_not_the_protocol_raises(tmp_path: Path) -> None:
    worker = WorkerProcess(_script(tmp_path, _CHATTY))
    try:
        with pytest.raises(WorkerError, match="log line from the model"):
            worker.request({"n": 1})
    finally:
        worker.close()


def test_close_after_the_worker_died_is_quiet(tmp_path: Path) -> None:
    worker = WorkerProcess(_script(tmp_path, _ECHO))
    with pytest.raises(WorkerError):
        worker.request({"crash": True})
    worker.close()
    assert worker.returncode == 3


def test_close_ends_the_process(tmp_path: Path) -> None:
    worker = WorkerProcess(_script(tmp_path, _ECHO))
    worker.close()
    assert worker.returncode == 0
