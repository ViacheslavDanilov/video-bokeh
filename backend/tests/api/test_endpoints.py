from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from video_bokeh.api import main as api_main
from video_bokeh.api._settings import Settings

SCENE_BODY = {
    "seed": 0,
    "frames": 3,
    "size": 64,
    "n_objects_min": 1,
    "n_objects_max": 2,
}


@pytest.fixture
def client(
    library: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """A client pointed at the fixture library, through the same seam compose uses."""
    settings = Settings(
        data_root=tmp_path,
        library=library,
        scenes=tmp_path / "scenes",
    )
    monkeypatch.setattr(api_main, "load_settings", lambda: settings)
    with TestClient(api_main.app) as c:
        yield c


@pytest.fixture
def clientless(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A client whose library volume was never populated."""
    settings = Settings(
        data_root=tmp_path,
        library=tmp_path / "absent",
        scenes=tmp_path / "scenes",
    )
    monkeypatch.setattr(api_main, "load_settings", lambda: settings)
    with TestClient(api_main.app) as c:
        yield c


# --- health ---------------------------------------------------------------- #


def test_health_does_not_need_a_library(clientless: TestClient) -> None:
    """The container has to report healthy before the library volume is mounted."""
    assert clientless.get("/health").json() == {"status": "healthy"}


# --- library --------------------------------------------------------------- #


def test_library_reports_what_is_mounted(client: TestClient, facts) -> None:
    body = client.get("/library").json()
    assert body["n_foregrounds"] == 2
    assert body["n_backgrounds"] == 2
    assert body["depth_model"] == facts.estimator
    assert body["asset_size"] == facts.fg_size
    assert len(body["id"]) == 12


def test_library_is_unavailable_rather_than_broken(clientless: TestClient) -> None:
    response = clientless.get("/library")
    assert response.status_code == 503
    assert "absent" in response.json()["detail"]


# --- scenes ---------------------------------------------------------------- #


def test_generates_a_scene_and_lists_its_streams(client: TestClient) -> None:
    body = client.post("/scenes", json=SCENE_BODY).json()

    assert body["cached"] is False
    assert body["frames"] == 3
    assert 1 <= body["n_objects"] <= 2
    assert set(body["streams"]) == {"all_in_focus", "alpha", "disparity"}
    assert body["streams"]["disparity"]["url"] == f"/scenes/{body['id']}/disparity.mp4"


def test_the_manifest_says_which_streams_take_a_colormap(client: TestClient) -> None:
    """The client reads this instead of knowing the stream names, so bokeh can join later."""
    streams = client.post("/scenes", json=SCENE_BODY).json()["streams"]
    assert streams["disparity"]["colormaps"] == ["grey", "spectral_r"]
    assert streams["all_in_focus"]["colormaps"] == []


def test_the_manifest_names_the_colormap_the_url_already_uses(
    client: TestClient,
) -> None:
    """Named, not inferred from the order of `colormaps`: adding one whose name sorts
    last must not silently change what a client renders by default.
    """
    streams = client.post("/scenes", json=SCENE_BODY).json()["streams"]
    assert streams["disparity"]["default"] == "spectral_r"
    assert streams["all_in_focus"]["default"] is None


def test_the_same_request_returns_the_same_scene(client: TestClient) -> None:
    first = client.post("/scenes", json=SCENE_BODY).json()
    second = client.post("/scenes", json=SCENE_BODY).json()
    assert second["id"] == first["id"]
    assert second["cached"] is True


def test_a_different_seed_is_a_different_scene(client: TestClient) -> None:
    first = client.post("/scenes", json=SCENE_BODY).json()
    second = client.post("/scenes", json={**SCENE_BODY, "seed": 7}).json()
    assert second["id"] != first["id"]


def test_rejects_an_inverted_object_range(client: TestClient) -> None:
    response = client.post(
        "/scenes",
        json={**SCENE_BODY, "n_objects_min": 3, "n_objects_max": 2},
    )
    assert response.status_code == 422


def test_rejects_a_frame_count_past_the_cap(client: TestClient) -> None:
    """The endpoint is synchronous, so an unbounded frame count is a way to hang it."""
    assert (
        client.post("/scenes", json={**SCENE_BODY, "frames": 100_000}).status_code
        == 422
    )


def test_scenes_need_a_library(clientless: TestClient) -> None:
    assert clientless.post("/scenes", json=SCENE_BODY).status_code == 503


# --- videos ---------------------------------------------------------------- #


def test_serves_a_stream_as_video(client: TestClient) -> None:
    scene = client.post("/scenes", json=SCENE_BODY).json()
    response = client.get(f"/scenes/{scene['id']}/all_in_focus.mp4")
    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"
    assert len(response.content) > 0


def test_disparity_is_served_in_colour(client: TestClient) -> None:
    scene = client.post("/scenes", json=SCENE_BODY).json()
    assert client.get(f"/scenes/{scene['id']}/disparity.mp4").status_code == 200


def test_the_encode_is_kept_for_the_next_request(
    client: TestClient,
    tmp_path: Path,
) -> None:
    scene = client.post("/scenes", json=SCENE_BODY).json()
    client.get(f"/scenes/{scene['id']}/all_in_focus.mp4")
    encoded = tmp_path / "scenes" / scene["id"] / "all_in_focus.mp4"
    assert encoded.is_file()
    stamp = encoded.stat().st_mtime_ns

    client.get(f"/scenes/{scene['id']}/all_in_focus.mp4")
    assert encoded.stat().st_mtime_ns == stamp


def test_alpha_is_served_with_one_colour_per_object(client: TestClient) -> None:
    """Each page is an object, so the video shows identity rather than one silhouette."""
    scene = client.post("/scenes", json=SCENE_BODY).json()
    response = client.get(f"/scenes/{scene['id']}/alpha.mp4")
    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"
    assert len(response.content) > 0


def test_an_unknown_stream_has_no_video(client: TestClient) -> None:
    scene = client.post("/scenes", json=SCENE_BODY).json()
    assert client.get(f"/scenes/{scene['id']}/depth.mp4").status_code == 404


def test_an_unknown_scene_is_not_found(client: TestClient) -> None:
    assert client.get("/scenes/0123456789abcdef/all_in_focus.mp4").status_code == 404


@pytest.mark.parametrize(
    "scene_id",
    [
        "not-a-hash",
        "../../etc",
        "..%2F..%2Fetc",
        "0123456789abcdefff",
        "ABCDEF0123456789",
    ],
)
def test_a_scene_id_that_is_not_a_hash_never_reaches_the_filesystem(
    client: TestClient,
    scene_id: str,
) -> None:
    """The route constrains the id to the hash alphabet, which is also what stops it
    naming a path outside scenes/. Rejected before any path is built from it.
    """
    response = client.get(f"/scenes/{scene_id}/all_in_focus.mp4")
    assert response.status_code in (404, 422), response.status_code


# --- colormaps -------------------------------------------------------------- #


def test_disparity_can_be_asked_for_in_grey(client: TestClient, tmp_path: Path) -> None:
    """The frames on disk are 16-bit grey; the colour is applied when serving."""
    scene = client.post("/scenes", json=SCENE_BODY).json()
    response = client.get(
        f"/scenes/{scene['id']}/disparity.mp4",
        params={"colormap": "grey"},
    )
    assert response.status_code == 200
    assert (tmp_path / "scenes" / scene["id"] / "disparity.grey.mp4").is_file()


def test_each_colormap_is_cached_separately(client: TestClient, tmp_path: Path) -> None:
    scene = client.post("/scenes", json=SCENE_BODY).json()
    client.get(f"/scenes/{scene['id']}/disparity.mp4")
    client.get(f"/scenes/{scene['id']}/disparity.mp4", params={"colormap": "grey"})
    written = sorted(
        p.name for p in (tmp_path / "scenes" / scene["id"]).glob("disparity*.mp4")
    )
    assert written == ["disparity.grey.mp4", "disparity.mp4"]


def test_an_unknown_colormap_is_rejected(client: TestClient) -> None:
    scene = client.post("/scenes", json=SCENE_BODY).json()
    response = client.get(
        f"/scenes/{scene['id']}/disparity.mp4",
        params={"colormap": "nope"},
    )
    assert response.status_code == 422


def test_the_colormap_is_ignored_for_a_stream_that_is_not_depth(
    client: TestClient,
    tmp_path: Path,
) -> None:
    """all_in_focus is already RGB, so asking for grey must not fork its cache."""
    scene = client.post("/scenes", json=SCENE_BODY).json()
    client.get(f"/scenes/{scene['id']}/all_in_focus.mp4", params={"colormap": "grey"})
    written = sorted(
        p.name for p in (tmp_path / "scenes" / scene["id"]).glob("all_in_focus*.mp4")
    )
    assert written == ["all_in_focus.mp4"]


def test_a_half_encoded_video_is_never_served(
    client: TestClient,
    tmp_path: Path,
) -> None:
    """Encoding writes beside the destination and renames, so a request arriving while
    another encode runs cannot be handed a truncated file. Two panes on one stream, or
    a reload during the first encode, both reach this.
    """
    scene = client.post("/scenes", json=SCENE_BODY).json()
    scene_dir = tmp_path / "scenes" / scene["id"]
    client.get(f"/scenes/{scene['id']}/all_in_focus.mp4")

    leftovers = [p.name for p in scene_dir.glob(".all_in_focus-*")]
    assert leftovers == [], leftovers
    assert (scene_dir / "all_in_focus.mp4").stat().st_size > 0


def test_a_request_that_would_exhaust_memory_is_refused(client: TestClient) -> None:
    """240 frames at 1024 px took 97 s and 9.7 GB, and put the machine into swap.

    Each limit on its own is harmless; the product is not, because render_scene holds
    every frame at once. A synchronous endpoint must not let one caller do that.
    """
    response = client.post(
        "/scenes",
        json={**SCENE_BODY, "frames": 240, "size": 1024},
    )
    assert response.status_code == 422
    detail = str(response.json()["detail"])
    assert "megapixels" in detail
    assert "frames or fewer" in detail


def test_the_heaviest_shape_anyone_has_measured_still_fits(client: TestClient) -> None:
    """80 frames at 1024 px is 11 s and 2.9 GB -- heavy, but a thing people do."""
    from video_bokeh.api.main import SceneParams

    SceneParams(seed=0, frames=80, size=1024, n_objects_min=1, n_objects_max=5)


def test_the_loopback_spelling_of_the_dev_frontend_is_allowed_too() -> None:
    """A browser treats localhost and 127.0.0.1 as different origins."""
    from video_bokeh.api._settings import load_settings

    assert "http://127.0.0.1:3000" in load_settings({}).cors_origins


def test_the_scene_names_a_colour_for_every_object(client: TestClient) -> None:
    """The legend reads these rather than keeping its own copy of the palette, so it
    cannot drift from what the alpha video paints.
    """
    body = client.post("/scenes", json=SCENE_BODY).json()
    colors = body["object_colors"]
    assert len(colors) == body["n_objects"]
    assert all(c.startswith("#") and len(c) == 7 for c in colors), colors
    assert len(set(colors)) == len(colors), "objects must be told apart"
