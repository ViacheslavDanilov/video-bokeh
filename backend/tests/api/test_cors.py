from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from video_bokeh.api._settings import Settings, load_settings
from video_bokeh.api.main import create_app


def _settings(tmp_path: Path, origins: tuple[str, ...] | None = None) -> Settings:
    kwargs = {} if origins is None else {"cors_origins": origins}
    return Settings(
        data_root=tmp_path,
        library=tmp_path / "library",
        scenes=tmp_path / "scenes",
        **kwargs,
    )


def _client(tmp_path: Path, origins: tuple[str, ...]) -> TestClient:
    """Build an app with known origins.

    Patching ``load_settings`` cannot work here: middleware is installed when the app
    object is built, so a test that patched after import would assert about whatever
    was in the environment at import time. It would then pass or fail depending on the
    shell it ran from, which is how the first version of these tests went green while
    proving nothing.
    """
    return TestClient(create_app(_settings(tmp_path, origins)))


def test_a_configured_origin_is_allowed(tmp_path: Path) -> None:
    client = _client(tmp_path, ("https://lab.example",))
    response = client.get("/health", headers={"Origin": "https://lab.example"})
    assert response.headers.get("access-control-allow-origin") == "https://lab.example"


def test_an_origin_that_was_not_configured_is_refused(tmp_path: Path) -> None:
    client = _client(tmp_path, ("https://lab.example",))
    response = client.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_every_configured_origin_is_allowed(tmp_path: Path) -> None:
    client = _client(tmp_path, ("https://a.example", "https://b.example"))
    for origin in ("https://a.example", "https://b.example"):
        response = client.get("/health", headers={"Origin": origin})
        assert response.headers.get("access-control-allow-origin") == origin


def test_the_preflight_a_browser_sends_is_answered(tmp_path: Path) -> None:
    """POST /scenes carries a JSON content type, so a browser preflights it."""
    client = _client(tmp_path, ("http://localhost:3000",))
    response = client.options(
        "/scenes",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert (
        response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    )


def test_an_app_built_with_defaults_allows_the_dev_frontend(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert (
        response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    )


def test_origins_come_from_the_environment() -> None:
    settings = load_settings({"CORS_ORIGINS": "https://a.example,https://b.example"})
    assert settings.cors_origins == ("https://a.example", "https://b.example")


def test_blank_entries_and_padding_are_ignored() -> None:
    assert load_settings({"CORS_ORIGINS": " https://a.example , ,"}).cors_origins == (
        "https://a.example",
    )


def test_an_unset_variable_falls_back_to_the_dev_frontend() -> None:
    assert load_settings({}).cors_origins == ("http://localhost:3000",)
