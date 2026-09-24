from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from video_bokeh.api import main as api_main
from video_bokeh.api._settings import Settings, load_settings


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    settings = Settings(
        data_root=tmp_path,
        library=tmp_path / "library",
        scenes=tmp_path / "scenes",
    )
    monkeypatch.setattr(api_main, "load_settings", lambda: settings)
    return TestClient(api_main.app)


def test_the_frontend_origin_is_allowed_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The page and the API run on different ports, so every request is cross-origin."""
    client = _client(tmp_path, monkeypatch)
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert (
        response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    )


def test_an_unknown_origin_is_not_allowed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    response = client.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_the_preflight_a_browser_sends_is_answered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /scenes carries a JSON content type, which makes the browser preflight it."""
    client = _client(tmp_path, monkeypatch)
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


def test_origins_come_from_the_environment() -> None:
    assert load_settings(
        {"CORS_ORIGINS": "https://a.example,https://b.example"},
    ).cors_origins == (
        "https://a.example",
        "https://b.example",
    )


def test_blank_entries_and_padding_are_ignored() -> None:
    assert load_settings({"CORS_ORIGINS": " https://a.example , ,"}).cors_origins == (
        "https://a.example",
    )


def test_an_unset_variable_falls_back_to_the_dev_frontend() -> None:
    assert load_settings({}).cors_origins == ("http://localhost:3000",)
