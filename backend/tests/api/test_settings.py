from pathlib import Path

import pytest

from video_bokeh.api._settings import (
    LibraryUnavailableError,
    Settings,
    find_libraries,
    load_settings,
)


def test_defaults_to_the_data_directory() -> None:
    settings = load_settings({})
    assert settings.data_root == Path("data")
    assert settings.library == Path("data/library")
    assert settings.sequences == Path("data/sequences")


def test_data_root_moves_library_and_sequences_together() -> None:
    settings = load_settings({"VIDEO_BOKEH_DATA_ROOT": "/mnt/big"})
    assert settings.library == Path("/mnt/big/library")
    assert settings.sequences == Path("/mnt/big/sequences")


def test_library_can_be_named_independently() -> None:
    """A flat library like data/library_dev is named directly, not under the root."""
    settings = load_settings(
        {
            "VIDEO_BOKEH_DATA_ROOT": "/mnt/big",
            "VIDEO_BOKEH_LIBRARY": "/elsewhere/da2-large",
        },
    )
    assert settings.library == Path("/elsewhere/da2-large")
    assert settings.sequences == Path("/mnt/big/sequences")


def test_empty_variable_is_treated_as_unset() -> None:
    """Compose writes an empty value when a .env key exists with no value."""
    settings = load_settings({"VIDEO_BOKEH_DATA_ROOT": "", "VIDEO_BOKEH_LIBRARY": ""})
    assert settings.data_root == Path("data")
    assert settings.library == Path("data/library")


def _settings(library: Path) -> Settings:
    return Settings(
        data_root=library.parent,
        library=library,
        sequences=library.parent / "sequences",
    )


def _library(root: Path) -> Path:
    (root / "foregrounds").mkdir(parents=True)
    (root / "backgrounds").mkdir()
    return root


def test_a_flat_library_is_the_one_library(tmp_path: Path) -> None:
    library = _library(tmp_path / "library_dev")
    assert find_libraries(_settings(library)) == [library]


def test_a_directory_of_libraries_lists_each_in_name_order(tmp_path: Path) -> None:
    root = tmp_path / "library"
    depth_pro = _library(root / "depth-pro")
    da2 = _library(root / "da2-large")
    assert find_libraries(_settings(root)) == [da2, depth_pro]


def test_a_build_in_progress_is_not_a_library(tmp_path: Path) -> None:
    """A build still in progress sits under a dot-prefixed name until it is renamed."""
    root = tmp_path / "library"
    da2 = _library(root / "da2-large")
    _library(root / ".depth-pro")
    assert find_libraries(_settings(root)) == [da2]


def test_entries_that_are_not_libraries_are_skipped(tmp_path: Path) -> None:
    root = tmp_path / "library"
    da2 = _library(root / "da2-large")
    (root / "notes").mkdir()
    (root / "README").write_text("not a library")
    assert find_libraries(_settings(root)) == [da2]


def test_names_the_path_it_could_not_use(tmp_path: Path) -> None:
    missing = tmp_path / "nothing-here"
    with pytest.raises(LibraryUnavailableError) as excinfo:
        find_libraries(_settings(missing))
    assert str(missing) in str(excinfo.value)


def test_a_directory_with_no_library_in_it_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "library"
    (root / "notes").mkdir(parents=True)
    with pytest.raises(LibraryUnavailableError) as excinfo:
        find_libraries(_settings(root))
    assert str(root) in str(excinfo.value)


def test_a_half_library_names_what_it_is_missing(tmp_path: Path) -> None:
    """A path holding foregrounds/ alone is a broken library, not a directory of them."""
    (tmp_path / "foregrounds").mkdir()
    with pytest.raises(LibraryUnavailableError) as excinfo:
        find_libraries(_settings(tmp_path))
    assert "backgrounds" in str(excinfo.value)


def test_bokeh_is_rendered_unless_turned_off() -> None:
    assert load_settings({}).render_bokeh is True
    assert load_settings({"VIDEO_BOKEH_RENDER_BOKEH": "0"}).render_bokeh is False
    assert load_settings({"VIDEO_BOKEH_RENDER_BOKEH": "false"}).render_bokeh is False
    assert load_settings({"VIDEO_BOKEH_RENDER_BOKEH": "1"}).render_bokeh is True
