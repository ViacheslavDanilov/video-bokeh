"""`--model` names a registered estimator or a class of the user's own."""

from __future__ import annotations

from pathlib import Path

import pytest

from video_bokeh.library.build import _build_parser
from video_bokeh.library.depth import ESTIMATORS, resolve_estimator

_REQUIRED = ["--fg-data-root", "fg", "--bg-data-root", "bg", "--output", "out"]

_CUSTOM = """
class MyEstimator:
    name = "my-model"

    def load(self, device):
        pass

    def infer(self, images):
        return []


class NotAnEstimator:
    name = "nope"
"""


@pytest.fixture
def custom_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    # A module outside this package, the way a user's own model would live.
    (tmp_path / "my_estimators.py").write_text(_CUSTOM, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    return "my_estimators"


def test_registered_name_resolves_to_its_class() -> None:
    assert resolve_estimator("da2-small") is ESTIMATORS["da2-small"]


def test_import_path_resolves_to_a_custom_class(custom_module: str) -> None:
    cls = resolve_estimator(f"{custom_module}:MyEstimator")
    assert cls.__name__ == "MyEstimator"
    assert cls.name == "my-model"


def test_unknown_name_lists_the_registered_ones() -> None:
    with pytest.raises(ValueError, match="da2-large"):
        resolve_estimator("da2-huge")


def test_missing_module_is_named() -> None:
    with pytest.raises(ValueError, match="no_such_module"):
        resolve_estimator("no_such_module:Estimator")


def test_missing_class_is_named(custom_module: str) -> None:
    with pytest.raises(ValueError, match="Missing"):
        resolve_estimator(f"{custom_module}:Missing")


def test_class_without_the_interface_is_refused(custom_module: str) -> None:
    with pytest.raises(ValueError, match="load"):
        resolve_estimator(f"{custom_module}:NotAnEstimator")


def test_cli_keeps_the_string_it_was_given(custom_module: str) -> None:
    # The library metadata records it, so a library built with a custom class says
    # which one.
    spec = f"{custom_module}:MyEstimator"
    args = _build_parser().parse_args([*_REQUIRED, "--model", spec])
    assert args.model == spec


def test_cli_rejects_an_unknown_model(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        _build_parser().parse_args([*_REQUIRED, "--model", "da2-huge"])
    assert exc.value.code == 2
    assert "da2-huge" in capsys.readouterr().err
