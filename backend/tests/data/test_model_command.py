"""The command a model's own Python runs under: its venv, or its Docker image."""

from __future__ import annotations

import getpass
import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from video_bokeh.core import _worker as worker
from video_bokeh.core._worker import model_command

_SETUP = "scripts/setup_x.sh"


def _calls(log: Path) -> list[list[str]]:
    return [json.loads(line) for line in log.read_text().splitlines()]


def _pairs(argv: list[str], flag: str) -> list[str]:
    return [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == flag]


def test_local_runs_the_venv_s_interpreter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VIDEO_BOKEH_RUNNER", raising=False)
    python = tmp_path / "python"
    python.touch()
    assert model_command("X_PYTHON", python, _SETUP, "video-bokeh-x") == [str(python)]


def test_local_without_the_venv_names_the_setup_script(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VIDEO_BOKEH_RUNNER", "local")
    with pytest.raises(RuntimeError, match="scripts/setup_x.sh"):
        model_command("X_PYTHON", tmp_path / "missing", _SETUP, "video-bokeh-x")


def test_an_unknown_runner_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VIDEO_BOKEH_RUNNER", "podman")
    with pytest.raises(ValueError, match="VIDEO_BOKEH_RUNNER"):
        model_command("X_PYTHON", Path("/x"), _SETUP, "video-bokeh-x")


def test_docker_runs_the_image_s_python_with_the_gpu(
    fake_docker: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FAKE_DOCKER_IMAGES", "video-bokeh-x")
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    data = tmp_path / "data"
    argv = model_command(
        "X_PYTHON",
        tmp_path / "unused",
        _SETUP,
        "video-bokeh-x",
        mounts=[data],
        workdir=data,
    )
    assert argv[:2] == ["docker", "run"]
    image = argv.index("video-bokeh-x")
    assert argv[image + 1 :] == ["python"]
    flags = argv[2:image]
    assert "--rm" in flags and "-i" in flags
    assert _pairs(flags, "--gpus") == ["all"]
    assert _pairs(flags, "--user") == [f"{os.getuid()}:{os.getgid()}"]
    # Every path keeps its own name inside the container: each mount is at its own
    # path, and every path the model needs lies inside one.
    volumes = [v.split(":") for v in _pairs(flags, "-v")]
    assert all(host == inside for host, inside in volumes)
    repo = Path(__file__).resolve().parents[3]
    for path in (data, repo, Path(tempfile.gettempdir()), tmp_path / "hf"):
        assert any(path.is_relative_to(host) for host, _ in volumes), path
    assert f"HF_HOME={tmp_path / 'hf'}" in _pairs(flags, "-e")
    assert _pairs(flags, "-w") == [str(data)]
    # The demo's data loader starts many workers; Docker's default 64 MiB /dev/shm
    # would kill them.
    assert any(f.startswith("--shm-size") for f in flags) or "--ipc" in flags


def test_docker_mounts_a_path_once(
    fake_docker: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FAKE_DOCKER_IMAGES", "video-bokeh-x")
    repo = Path(__file__).resolve().parents[3]
    argv = model_command(
        "X_PYTHON",
        tmp_path,
        _SETUP,
        "video-bokeh-x",
        mounts=[repo / "backend" / "data", repo],
    )
    targets = [v.split(":")[1] for v in _pairs(argv, "-v")]
    assert len(targets) == len(set(targets))
    # A path under another mount is already inside the container.
    assert str(repo / "backend" / "data") not in targets


def test_docker_without_the_image_says_how_to_build_it(
    fake_docker: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_DOCKER_IMAGES", "")
    with pytest.raises(RuntimeError, match="video-bokeh-x.*make images"):
        model_command("X_PYTHON", Path("/x"), _SETUP, "video-bokeh-x")


def test_the_fake_docker_runs_the_command(
    fake_docker: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The fixture the end-to-end tests stand on: what docker would run, it runs."""
    monkeypatch.setenv("FAKE_DOCKER_IMAGES", "video-bokeh-x")
    argv = model_command(
        "X_PYTHON",
        tmp_path,
        _SETUP,
        "video-bokeh-x",
        workdir=tmp_path,
    )
    out = subprocess.run(
        [*argv, "-c", "import os; print(os.getcwd())"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert out == str(tmp_path)
    assert _calls(fake_docker)[-1][0] == "run"


def test_an_unreachable_daemon_is_not_blamed_on_the_image(
    fake_docker: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FAKE_DOCKER_DOWN", "1")
    with pytest.raises(RuntimeError, match="permission denied") as exc:
        model_command("X_PYTHON", Path("/x"), _SETUP, "video-bokeh-x")
    assert "make images" not in str(exc.value)


@pytest.fixture
def outside(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_docker: Path,
) -> Path:
    """A repository, a temporary directory and a cache that cover nothing else."""
    monkeypatch.setenv("FAKE_DOCKER_IMAGES", "video-bokeh-x")
    monkeypatch.setattr(worker, "_REPO", tmp_path / "repo")
    monkeypatch.setattr(worker.tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    for name in ("repo", "tmp", "disk2"):
        (tmp_path / name).mkdir()
    return tmp_path


def _resolves(argv: list[str], path: Path) -> bool:
    """Whether ``path``, as the container is told it, lands on a mount of its target."""
    for spec in _pairs(argv, "-v"):
        host, inside = map(Path, spec.split(":"))
        if path.is_relative_to(inside):
            return (host / path.relative_to(inside)).resolve() == path.resolve()
    return False


def test_a_symlink_inside_a_mount_is_mounted_where_it_points(outside: Path) -> None:
    """Data on a second disk, linked from inside the repository."""
    link = outside / "repo" / "data"
    link.symlink_to(outside / "disk2")
    argv = model_command("X_PYTHON", outside, _SETUP, "video-bokeh-x", mounts=[link])
    assert f"{outside / 'disk2'}:{outside / 'disk2'}" in _pairs(argv, "-v")


def test_a_symlink_outside_every_mount_keeps_its_own_name(
    outside: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Hugging Face cache linked to a bigger disk: the container is told the link."""
    link = outside / "hf-link"
    link.symlink_to(outside / "disk2")
    monkeypatch.setenv("HF_HOME", str(link))
    argv = model_command("X_PYTHON", outside, _SETUP, "video-bokeh-x")
    assert f"HF_HOME={link}" in _pairs(argv, "-e")
    assert _resolves(argv, link)


def test_a_symlinked_temporary_directory_still_holds_the_workdir(
    outside: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = outside / "tmp-link"
    link.symlink_to(outside / "disk2")
    monkeypatch.setattr(worker.tempfile, "gettempdir", lambda: str(link))
    work = link / "run"
    work.mkdir()
    argv = model_command("X_PYTHON", outside, _SETUP, "video-bokeh-x", workdir=work)
    assert _resolves(argv, work)


def test_the_home_is_the_user_s_own(outside: Path) -> None:
    argv = model_command("X_PYTHON", outside, _SETUP, "video-bokeh-x")
    (home,) = [e.split("=", 1)[1] for e in _pairs(argv, "-e") if e.startswith("HOME=")]
    assert Path(home).is_relative_to(outside / "home")
    assert Path(home).stat().st_mode & 0o777 == 0o700
    assert _resolves(argv, Path(home))


def test_the_container_knows_the_user_s_name(outside: Path) -> None:
    """The uid has no passwd entry in the image, and torch's cache path asks for a name
    through getpass, which then reads the environment alone.
    """
    argv = model_command("X_PYTHON", outside, _SETUP, "video-bokeh-x")
    env = _pairs(argv, "-e")
    assert f"USER={getpass.getuser()}" in env
    assert f"LOGNAME={getpass.getuser()}" in env
