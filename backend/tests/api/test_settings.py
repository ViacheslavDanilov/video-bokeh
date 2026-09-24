from pathlib import Path

import pytest

from video_bokeh.api._settings import (
    LibraryUnavailableError,
    Settings,
    load_settings,
    require_library,
)


def test_defaults_to_the_data_directory() -> None:
    settings = load_settings({})
    assert settings.data_root == Path("data")
    assert settings.library == Path("data/library")
    assert settings.scenes == Path("data/scenes")


def test_data_root_moves_library_and_scenes_together() -> None:
    settings = load_settings({"VIDEO_BOKEH_DATA_ROOT": "/mnt/big"})
    assert settings.library == Path("/mnt/big/library")
    assert settings.scenes == Path("/mnt/big/scenes")


def test_library_can_be_named_independently() -> None:
    """A flat library like data/library_dev is named directly, not under the root."""
    settings = load_settings(
        {
            "VIDEO_BOKEH_DATA_ROOT": "/mnt/big",
            "VIDEO_BOKEH_LIBRARY": "/elsewhere/da2-large",
        },
    )
    assert settings.library == Path("/elsewhere/da2-large")
    assert settings.scenes == Path("/mnt/big/scenes")


def test_empty_variable_is_treated_as_unset() -> None:
    """Compose writes an empty value when a .env key exists with no value."""
    settings = load_settings({"VIDEO_BOKEH_DATA_ROOT": "", "VIDEO_BOKEH_LIBRARY": ""})
    assert settings.data_root == Path("data")
    assert settings.library == Path("data/library")


def test_require_library_accepts_a_real_library(tmp_path: Path) -> None:
    (tmp_path / "foregrounds").mkdir()
    (tmp_path / "backgrounds").mkdir()
    settings = Settings(
        data_root=tmp_path,
        library=tmp_path,
        scenes=tmp_path / "scenes",
    )
    assert require_library(settings) == tmp_path


def test_require_library_names_the_path_it_could_not_use(tmp_path: Path) -> None:
    missing = tmp_path / "nothing-here"
    settings = Settings(data_root=tmp_path, library=missing, scenes=tmp_path / "scenes")
    with pytest.raises(LibraryUnavailableError) as excinfo:
        require_library(settings)
    assert str(missing) in str(excinfo.value)


def test_require_library_rejects_a_directory_that_is_not_a_library(
    tmp_path: Path,
) -> None:
    """A path that exists but holds no assets is a configuration error, not an empty library."""
    (tmp_path / "foregrounds").mkdir()
    settings = Settings(
        data_root=tmp_path,
        library=tmp_path,
        scenes=tmp_path / "scenes",
    )
    with pytest.raises(LibraryUnavailableError) as excinfo:
        require_library(settings)
    assert "backgrounds" in str(excinfo.value)
