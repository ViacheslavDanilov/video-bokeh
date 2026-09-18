"""Stage B must stay installable without a tensor library.

The whole point of the extras split is that someone can generate scenes on a laptop.
This test fails the moment a torch-dependent import creeps into the base install.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"
_HEAVY = {"torch", "transformers", "scipy", "pandas", "open-clip-torch", "kagglehub"}


def _names(requirements: list[str]) -> set[str]:
    out = set()
    for req in requirements:
        name = req.split(">")[0].split("=")[0].split("[")[0].split(";")[0]
        out.add(name.strip().lower())
    return out


def test_base_install_is_light() -> None:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    base = _names(data["project"]["dependencies"])
    assert base & _HEAVY == set(), (
        f"heavy dependency in the base install: {base & _HEAVY}"
    )


def test_base_install_can_write_the_dataset_formats() -> None:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    base = _names(data["project"]["dependencies"])
    assert {"numpy", "pillow", "tifffile", "imagecodecs"} <= base


def test_every_role_has_an_extra() -> None:
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    extras = set(data["project"].get("optional-dependencies", {}))
    assert {"library", "acquire", "preview", "api"} <= extras


def test_dockerfile_installs_the_api_extra() -> None:
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(
        encoding="utf-8",
    )
    assert "--extra api" in dockerfile, "the image would ship without the pipeline"
    assert "video_bokeh.api.main:app" in dockerfile
