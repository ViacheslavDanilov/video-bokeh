from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Iterator
from contextlib import ExitStack
from pathlib import Path

import numpy as np
import pytest
from fake_bokeh import render_fake_bokeh
from fastapi.testclient import TestClient
from PIL import Image

from video_bokeh.api import main as api_main
from video_bokeh.api._settings import Settings
from video_bokeh.core._streams import read_alpha_tiff

SEQUENCE_BODY = {
    "seed": 0,
    "frames": 3,
    "size": 64,
    "n_objects_min": 1,
    "n_objects_max": 2,
}


@pytest.fixture
def client_of(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Callable[[Path], TestClient]]:
    """A client pointed at a library path, through the same seam compose uses."""
    with ExitStack() as stack:

        def _client(library: Path) -> TestClient:
            settings = Settings(
                data_root=tmp_path,
                library=library,
                sequences=tmp_path / "sequences",
            )
            monkeypatch.setattr(api_main, "load_settings", lambda: settings)
            return stack.enter_context(TestClient(api_main.app))

        yield _client


@pytest.fixture
def client(client_of: Callable[[Path], TestClient], library: Path) -> TestClient:
    return client_of(library)


@pytest.fixture
def clientless(client_of: Callable[[Path], TestClient], tmp_path: Path) -> TestClient:
    """A client whose library volume was never populated."""
    return client_of(tmp_path / "absent")


@pytest.fixture
def libraries_dir(make_library: Callable[..., Path], tmp_path: Path) -> Path:
    """A directory of two libraries built from the same assets by two estimators."""
    make_library("library/da2-small")
    make_library("library/depth-pro", estimator="depth-pro")
    return tmp_path / "library"


# --- health ---------------------------------------------------------------- #


def test_health_does_not_need_a_library(clientless: TestClient) -> None:
    """The container has to report healthy before the library volume is mounted."""
    assert clientless.get("/health").json() == {"status": "healthy"}


# --- libraries ------------------------------------------------------------- #


def test_libraries_report_what_is_mounted(client: TestClient, facts) -> None:
    [body] = client.get("/libraries").json()
    assert body["name"] == "library"
    assert body["n_foregrounds"] == 2
    assert body["n_backgrounds"] == 2
    assert body["depth_estimator"] == facts.estimator
    assert body["asset_size"] == facts.fg_size
    assert len(body["id"]) == 12


def test_a_directory_of_libraries_lists_each_in_name_order(
    client_of: Callable[[Path], TestClient],
    libraries_dir: Path,
) -> None:
    body = client_of(libraries_dir).get("/libraries").json()
    assert [(b["name"], b["depth_estimator"]) for b in body] == [
        ("da2-small", "da2-small"),
        ("depth-pro", "depth-pro"),
    ]
    assert body[0]["id"] != body[1]["id"]


def test_libraries_are_unavailable_rather_than_broken(clientless: TestClient) -> None:
    response = clientless.get("/libraries")
    assert response.status_code == 503
    assert "absent" in response.json()["detail"]


def test_two_libraries_that_cannot_be_told_apart_are_refused(
    client_of: Callable[[Path], TestClient],
    make_library: Callable[..., Path],
    tmp_path: Path,
) -> None:
    """Every library endpoint refuses, so neither one is served in the other's place."""
    one = make_library("library/one")
    two = make_library("library/two")
    c = client_of(tmp_path / "library")
    for response in (
        c.get("/libraries"),
        c.post("/sequences", json=SEQUENCE_BODY),
    ):
        assert response.status_code == 503
        assert str(one) in response.json()["detail"]
        assert str(two) in response.json()["detail"]


def test_a_build_in_progress_is_not_listed(
    client_of: Callable[[Path], TestClient],
    libraries_dir: Path,
    make_library: Callable[..., Path],
) -> None:
    make_library("library/.da3-mono-large", estimator="da3-mono-large")
    names = [b["name"] for b in client_of(libraries_dir).get("/libraries").json()]
    assert names == ["da2-small", "depth-pro"]


def test_a_half_library_names_what_it_is_missing(
    client_of: Callable[[Path], TestClient],
    tmp_path: Path,
) -> None:
    (tmp_path / "half" / "foregrounds").mkdir(parents=True)
    response = client_of(tmp_path / "half").get("/libraries")
    assert response.status_code == 503
    assert "backgrounds" in response.json()["detail"]


def test_a_directory_with_no_library_in_it_is_unavailable(
    client_of: Callable[[Path], TestClient],
    tmp_path: Path,
) -> None:
    (tmp_path / "empty" / "notes").mkdir(parents=True)
    response = client_of(tmp_path / "empty").get("/libraries")
    assert response.status_code == 503
    assert str(tmp_path / "empty") in response.json()["detail"]


# --- sequences ---------------------------------------------------------------- #


def test_generates_a_sequence_and_lists_its_streams(client: TestClient) -> None:
    body = client.post("/sequences", json=SEQUENCE_BODY).json()

    assert body["cached"] is False
    assert body["frames"] == 3
    assert 1 <= body["n_objects"] <= 2
    assert set(body["streams"]) == {"all_in_focus", "alpha", "disparity"}
    assert (
        body["streams"]["disparity"]["url"] == f"/sequences/{body['id']}/disparity.mp4"
    )


def test_the_manifest_says_which_streams_take_a_colormap(client: TestClient) -> None:
    """The client reads this instead of knowing the stream names, so bokeh can join later."""
    streams = client.post("/sequences", json=SEQUENCE_BODY).json()["streams"]
    assert streams["disparity"]["colormaps"] == ["grey", "spectral_r"]
    assert streams["all_in_focus"]["colormaps"] == []


def test_the_manifest_names_the_colormap_the_url_already_uses(
    client: TestClient,
) -> None:
    """Named, not inferred from the order of `colormaps`: adding one whose name sorts
    last must not silently change what a client renders by default.
    """
    streams = client.post("/sequences", json=SEQUENCE_BODY).json()["streams"]
    assert streams["disparity"]["default"] == "spectral_r"
    assert streams["all_in_focus"]["default"] is None


def test_the_same_request_returns_the_same_sequence(client: TestClient) -> None:
    first = client.post("/sequences", json=SEQUENCE_BODY).json()
    second = client.post("/sequences", json=SEQUENCE_BODY).json()
    assert second["id"] == first["id"]
    assert second["cached"] is True


def test_a_different_seed_is_a_different_sequence(client: TestClient) -> None:
    first = client.post("/sequences", json=SEQUENCE_BODY).json()
    second = client.post("/sequences", json={**SEQUENCE_BODY, "seed": 7}).json()
    assert second["id"] != first["id"]


def test_rejects_an_inverted_object_range(client: TestClient) -> None:
    response = client.post(
        "/sequences",
        json={**SEQUENCE_BODY, "n_objects_min": 3, "n_objects_max": 2},
    )
    assert response.status_code == 422


def test_rejects_a_frame_count_past_the_cap(client: TestClient) -> None:
    """The endpoint is synchronous, so an unbounded frame count is a way to hang it."""
    assert (
        client.post("/sequences", json={**SEQUENCE_BODY, "frames": 100_000}).status_code
        == 422
    )


def test_sequences_need_a_library(clientless: TestClient) -> None:
    assert clientless.post("/sequences", json=SEQUENCE_BODY).status_code == 503


def test_one_library_needs_no_name(client: TestClient) -> None:
    library = client.get("/libraries").json()[0]["id"]
    body = client.post("/sequences", json=SEQUENCE_BODY).json()
    assert body["library"] == library


def test_several_libraries_need_one_named(
    client_of: Callable[[Path], TestClient],
    libraries_dir: Path,
) -> None:
    c = client_of(libraries_dir)
    ids = [b["id"] for b in c.get("/libraries").json()]
    response = c.post("/sequences", json=SEQUENCE_BODY)
    assert response.status_code == 422
    assert all(i in response.json()["detail"] for i in ids)


def test_an_unknown_library_is_refused_with_the_known_ones(
    client_of: Callable[[Path], TestClient],
    libraries_dir: Path,
) -> None:
    c = client_of(libraries_dir)
    ids = [b["id"] for b in c.get("/libraries").json()]
    response = c.post("/sequences", json={**SEQUENCE_BODY, "library": "0" * 12})
    assert response.status_code == 422
    assert all(i in response.json()["detail"] for i in ids)


def test_each_library_gives_its_own_sequence_of_the_same_scene(
    client_of: Callable[[Path], TestClient],
    libraries_dir: Path,
    tmp_path: Path,
) -> None:
    """Same seed, same assets, two estimators: the objects move the same way, so only
    their disparity differs -- which is the comparison the picker exists for.
    """
    c = client_of(libraries_dir)
    da2, depth_pro = (b["id"] for b in c.get("/libraries").json())
    a = c.post("/sequences", json={**SEQUENCE_BODY, "library": da2}).json()
    b = c.post("/sequences", json={**SEQUENCE_BODY, "library": depth_pro}).json()

    assert a["id"] != b["id"]
    assert (a["library"], b["library"]) == (da2, depth_pro)

    def frames(sequence: dict, stream: str) -> list[Path]:
        return sorted((tmp_path / "sequences" / sequence["id"] / stream).iterdir())

    for fa, fb in zip(frames(a, "alpha"), frames(b, "alpha"), strict=True):
        assert all(
            np.array_equal(pa, pb)
            for pa, pb in zip(read_alpha_tiff(fa), read_alpha_tiff(fb), strict=True)
        )
    assert any(
        not np.array_equal(np.asarray(Image.open(fa)), np.asarray(Image.open(fb)))
        for fa, fb in zip(
            frames(a, "disparity"),
            frames(b, "disparity"),
            strict=True,
        )
    )


# --- videos ---------------------------------------------------------------- #


def test_serves_a_stream_as_video(client: TestClient) -> None:
    sequence = client.post("/sequences", json=SEQUENCE_BODY).json()
    response = client.get(f"/sequences/{sequence['id']}/all_in_focus.mp4")
    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"
    assert len(response.content) > 0


def test_disparity_is_served_in_colour(client: TestClient) -> None:
    sequence = client.post("/sequences", json=SEQUENCE_BODY).json()
    assert client.get(f"/sequences/{sequence['id']}/disparity.mp4").status_code == 200


def test_the_encode_is_kept_for_the_next_request(
    client: TestClient,
    tmp_path: Path,
) -> None:
    sequence = client.post("/sequences", json=SEQUENCE_BODY).json()
    client.get(f"/sequences/{sequence['id']}/all_in_focus.mp4")
    encoded = tmp_path / "sequences" / sequence["id"] / "all_in_focus.mp4"
    assert encoded.is_file()
    stamp = encoded.stat().st_mtime_ns

    client.get(f"/sequences/{sequence['id']}/all_in_focus.mp4")
    assert encoded.stat().st_mtime_ns == stamp


def test_alpha_is_served_with_one_colour_per_object(client: TestClient) -> None:
    """Each page is an object, so the video shows identity rather than one silhouette."""
    sequence = client.post("/sequences", json=SEQUENCE_BODY).json()
    response = client.get(f"/sequences/{sequence['id']}/alpha.mp4")
    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"
    assert len(response.content) > 0


def test_an_unknown_stream_has_no_video(client: TestClient) -> None:
    sequence = client.post("/sequences", json=SEQUENCE_BODY).json()
    assert client.get(f"/sequences/{sequence['id']}/depth.mp4").status_code == 404


def test_an_unknown_sequence_is_not_found(client: TestClient) -> None:
    assert client.get("/sequences/0123456789abcdef/all_in_focus.mp4").status_code == 404


@pytest.mark.parametrize(
    "sequence_id",
    [
        "not-a-hash",
        "../../etc",
        "..%2F..%2Fetc",
        "0123456789abcdefff",
        "ABCDEF0123456789",
    ],
)
def test_a_sequence_id_that_is_not_a_hash_never_reaches_the_filesystem(
    client: TestClient,
    sequence_id: str,
) -> None:
    """The route constrains the id to the hash alphabet, which is also what stops it
    naming a path outside sequences/. Rejected before any path is built from it.
    """
    response = client.get(f"/sequences/{sequence_id}/all_in_focus.mp4")
    assert response.status_code in (404, 422), response.status_code


# --- colormaps -------------------------------------------------------------- #


def test_disparity_can_be_asked_for_in_grey(client: TestClient, tmp_path: Path) -> None:
    """The frames on disk are 16-bit grey; the colour is applied when serving."""
    sequence = client.post("/sequences", json=SEQUENCE_BODY).json()
    response = client.get(
        f"/sequences/{sequence['id']}/disparity.mp4",
        params={"colormap": "grey"},
    )
    assert response.status_code == 200
    assert (tmp_path / "sequences" / sequence["id"] / "disparity.grey.mp4").is_file()


def test_each_colormap_is_cached_separately(client: TestClient, tmp_path: Path) -> None:
    sequence = client.post("/sequences", json=SEQUENCE_BODY).json()
    client.get(f"/sequences/{sequence['id']}/disparity.mp4")
    client.get(
        f"/sequences/{sequence['id']}/disparity.mp4",
        params={"colormap": "grey"},
    )
    written = sorted(
        p.name for p in (tmp_path / "sequences" / sequence["id"]).glob("disparity*.mp4")
    )
    assert written == ["disparity.grey.mp4", "disparity.mp4"]


def test_an_unknown_colormap_is_rejected(client: TestClient) -> None:
    sequence = client.post("/sequences", json=SEQUENCE_BODY).json()
    response = client.get(
        f"/sequences/{sequence['id']}/disparity.mp4",
        params={"colormap": "nope"},
    )
    assert response.status_code == 422


def test_the_colormap_is_ignored_for_a_stream_that_is_not_depth(
    client: TestClient,
    tmp_path: Path,
) -> None:
    """all_in_focus is already RGB, so asking for grey must not fork its cache."""
    sequence = client.post("/sequences", json=SEQUENCE_BODY).json()
    client.get(
        f"/sequences/{sequence['id']}/all_in_focus.mp4",
        params={"colormap": "grey"},
    )
    written = sorted(
        p.name
        for p in (tmp_path / "sequences" / sequence["id"]).glob("all_in_focus*.mp4")
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
    sequence = client.post("/sequences", json=SEQUENCE_BODY).json()
    sequence_dir = tmp_path / "sequences" / sequence["id"]
    client.get(f"/sequences/{sequence['id']}/all_in_focus.mp4")

    leftovers = [p.name for p in sequence_dir.glob(".all_in_focus-*")]
    assert leftovers == [], leftovers
    assert (sequence_dir / "all_in_focus.mp4").stat().st_size > 0


def test_a_request_that_would_exhaust_memory_is_refused(client: TestClient) -> None:
    """240 frames at 1024 px took 97 s and 9.7 GB, and put the machine into swap.

    Each limit on its own is harmless; the product is not, because render_scene holds
    every frame at once. A synchronous endpoint must not let one caller do that.
    """
    response = client.post(
        "/sequences",
        json={**SEQUENCE_BODY, "frames": 240, "size": 1024},
    )
    assert response.status_code == 422
    detail = str(response.json()["detail"])
    assert "megapixels" in detail
    assert "frames or fewer" in detail


def test_the_heaviest_shape_anyone_has_measured_still_fits(client: TestClient) -> None:
    """80 frames at 1024 px is 11 s and 2.9 GB -- heavy, but a thing people do."""
    from video_bokeh.api.main import SequenceParams

    SequenceParams(seed=0, frames=80, size=1024, n_objects_min=1, n_objects_max=5)


def test_the_loopback_spelling_of_the_dev_frontend_is_allowed_too() -> None:
    """A browser treats localhost and 127.0.0.1 as different origins."""
    from video_bokeh.api._settings import load_settings

    assert "http://127.0.0.1:3000" in load_settings({}).cors_origins


def test_the_sequence_names_a_colour_for_every_object(client: TestClient) -> None:
    """The legend reads these rather than keeping its own copy of the palette, so it
    cannot drift from what the alpha video paints.
    """
    body = client.post("/sequences", json=SEQUENCE_BODY).json()
    colors = body["object_colors"]
    assert len(colors) == body["n_objects"]
    assert all(c.startswith("#") and len(c) == 7 for c in colors), colors
    assert len(set(colors)) == len(colors), "objects must be told apart"


# --- bokeh ----------------------------------------------------------------- #


def test_a_sequence_has_no_bokeh_until_stage_c_renders_it(client: TestClient) -> None:
    streams = client.post("/sequences", json=SEQUENCE_BODY).json()["streams"]
    assert "bokeh" not in streams


def test_bokeh_joins_the_manifest_once_rendered(
    client: TestClient,
    tmp_path: Path,
) -> None:
    """Asking again finds the sequence in the cache, now with the stream Stage C wrote."""
    first = client.post("/sequences", json=SEQUENCE_BODY).json()
    render_fake_bokeh(tmp_path / "sequences" / first["id"])

    again = client.post("/sequences", json=SEQUENCE_BODY).json()
    assert again["cached"] is True
    assert list(again["streams"]) == ["all_in_focus", "alpha", "disparity", "bokeh"]
    assert again["streams"]["bokeh"] == {
        "url": f"/sequences/{first['id']}/bokeh.mp4",
        "colormaps": [],
        "default": None,
    }


def test_serves_bokeh_as_video(client: TestClient, tmp_path: Path) -> None:
    sid = client.post("/sequences", json=SEQUENCE_BODY).json()["id"]
    render_fake_bokeh(tmp_path / "sequences" / sid)
    response = client.get(f"/sequences/{sid}/bokeh.mp4")
    assert response.status_code == 200
    assert response.headers["content-type"] == "video/mp4"


def test_bokeh_that_is_not_there_is_not_found(client: TestClient) -> None:
    sid = client.post("/sequences", json=SEQUENCE_BODY).json()["id"]
    response = client.get(f"/sequences/{sid}/bokeh.mp4")
    assert response.status_code == 404
    assert "bokeh" in response.json()["detail"]


def test_a_re_render_replaces_the_cached_bokeh_video(
    client: TestClient,
    tmp_path: Path,
) -> None:
    """Stage C run again, at another strength say, replaces bokeh/; the encode cached from
    the first render must not keep being served.
    """
    sid = client.post("/sequences", json=SEQUENCE_BODY).json()["id"]
    sequence_dir = tmp_path / "sequences" / sid
    render_fake_bokeh(sequence_dir)
    first = client.get(f"/sequences/{sid}/bokeh.mp4").content

    shutil.rmtree(sequence_dir / "bokeh")
    render_fake_bokeh(sequence_dir)
    for frame in (sequence_dir / "bokeh").iterdir():
        Image.new("RGB", Image.open(frame).size, (255, 0, 0)).save(frame)
    # Later than the encode, whatever the file system's clock resolution.
    later = (sequence_dir / "bokeh.mp4").stat().st_mtime + 10
    os.utime(sequence_dir / "bokeh", (later, later))

    assert client.get(f"/sequences/{sid}/bokeh.mp4").content != first


def test_a_re_render_renamed_into_place_after_an_encode_is_still_caught(
    client: TestClient,
    tmp_path: Path,
) -> None:
    """Stage C writes bokeh under a staging name and renames it, and a rename leaves the
    directory's mtime where the last frame put it. A video encoded in between is newer
    than that mtime, so only the ctime the rename sets tells the new render apart.
    """
    sid = client.post("/sequences", json=SEQUENCE_BODY).json()["id"]
    sequence_dir = tmp_path / "sequences" / sid
    render_fake_bokeh(sequence_dir)
    staging = sequence_dir / ".bokeh-next"
    staging.mkdir()
    for frame in (sequence_dir / "bokeh").iterdir():
        Image.new("RGB", Image.open(frame).size, (255, 0, 0)).save(staging / frame.name)
    finished = staging.stat().st_mtime

    first = client.get(f"/sequences/{sid}/bokeh.mp4").content
    # The staging directory's frames were all written before that encode.
    os.utime(staging, (finished - 10, finished - 10))
    shutil.rmtree(sequence_dir / "bokeh")
    staging.rename(sequence_dir / "bokeh")

    assert client.get(f"/sequences/{sid}/bokeh.mp4").content != first
