"""Fixtures shared across the test packages."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Stands in for the docker CLI. It records each call's argv in $FAKE_DOCKER_LOG, one JSON
# list per line. `image inspect <image>` succeeds for the images in $FAKE_DOCKER_IMAGES,
# and $FAKE_DOCKER_DOWN makes every call fail as an unreachable daemon does.
# `run` takes its flags up to the image, then runs the command after it here, from the
# directory -w names, with the -e variables set, so a fake model behind it runs as it would
# in the container.
_FAKE_DOCKER = """#!{python}
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_DOCKER_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
if os.environ.get("FAKE_DOCKER_DOWN"):
    sys.exit("permission denied while trying to connect to the docker API")
if args[:2] == ["image", "inspect"]:
    if args[2] in os.environ.get("FAKE_DOCKER_IMAGES", "").split():
        sys.exit(0)
    sys.exit("Error response from daemon: No such image: " + args[2])
assert args[0] == "run", args
i, cwd, env = 1, None, dict(os.environ)
while args[i].startswith("-"):
    flag = args[i]
    if "=" in flag:
        i += 1
        continue
    if flag in ("--rm", "-i", "--init"):
        i += 1
        continue
    value = args[i + 1]
    if flag == "-w":
        cwd = value
    elif flag == "-e":
        key, _, val = value.partition("=")
        env[key] = val
    i += 2
command = args[i + 1:]
if command[0] == "python":
    command[0] = sys.executable
os.chdir(cwd or os.getcwd())
os.execvpe(command[0], command, env)
"""


@pytest.fixture(autouse=True)
def _in_process_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts with the default runner, whatever the shell exported."""
    monkeypatch.delenv("VIDEO_BOKEH_RUNNER", raising=False)


@pytest.fixture
def fake_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake docker first on PATH; returns its log. The docker runner is selected."""
    bin_dir = tmp_path / "fake-docker-bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(_FAKE_DOCKER.format(python=sys.executable), encoding="utf-8")
    docker.chmod(0o755)
    log = tmp_path / "docker.log"
    log.touch()
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(log))
    monkeypatch.setenv("VIDEO_BOKEH_RUNNER", "docker")
    return log
