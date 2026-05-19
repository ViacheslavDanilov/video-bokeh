from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from data._sequence_geometry import replay_scene
from data.generate_sequences import SampleConfig, SequenceSpec, render_sequence

EXPECTED_HASHES = {
    "all_in_focus/01.png": "f34de956da675dd522ab81b71c2bdd8e509306cede5fd4c058677d9036e4a995",
    "alpha/01.png": "b4b86eb958bfffd186e0b4a41adc46aa8cdd9a896a9a9ce0643e93e0a3ae4ca6",
    "alpha_layers/01.png": "a24ebf50d64527435328921bb1f33325dc5cf35a8e901f512c35bccdf77d0830",
    "all_in_focus/02.png": "216d7a24c4d2f930f58c5fb7fc611d585ea870cbfbfc81f025a31b97df6e588a",
    "alpha/02.png": "67d3eef75c06b38dc8db1119134c2f96a768935f3361d4de09148e40ec7b00f0",
    "alpha_layers/02.png": "55088e12ef9829a4d4fe1d27fd8e12b565fbdae89faa9a3241e4d1d3a36bb2ff",
}


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def tiny_spec() -> SequenceSpec:
    return SequenceSpec(
        seq_id=1,
        seed=42,
        n_frames=2,
        size=128,
        bg_ref="testval/h_5ea69f46.jpg",
        object_refs=["WL/WLjuUIyRNn.png", "1Q/1Q5iguFTYX.png"],
    )


def _fixture_roots() -> tuple[Path, Path]:
    fg_root = Path("data/magick_dev")
    bg_root = Path("data/bg-20k_dev")
    if not fg_root.exists() or not bg_root.exists():
        pytest.skip("fixture data missing; run from backend/")
    return fg_root, bg_root


def test_render_sequence_byte_identical(
    tiny_spec: SequenceSpec,
    tmp_path: Path,
) -> None:
    fg_root, bg_root = _fixture_roots()

    out_dir = tmp_path / "0001"
    render_sequence(tiny_spec, fg_root, bg_root, out_dir, SampleConfig())

    for rel, expected in EXPECTED_HASHES.items():
        path = out_dir / rel
        assert path.exists(), f"missing output: {rel}"
        assert _hash(path) == expected, f"hash mismatch for {rel}"


def test_replay_scene_returns_aligned_data(
    tiny_spec: SequenceSpec,
) -> None:
    fg_root, bg_root = _fixture_roots()

    replay = replay_scene(tiny_spec, fg_root, bg_root, SampleConfig())

    assert len(replay.frames) == tiny_spec.n_frames
    assert len(replay.object_depths) == len(tiny_spec.object_refs)
    assert len(replay.channel_refs) == len(tiny_spec.object_refs)
    assert len(replay.object_easings) == len(tiny_spec.object_refs)
    assert replay.object_depths == sorted(replay.object_depths, reverse=True)

    for frame in replay.frames:
        assert frame.bg_rgb.mode == "RGB"
        assert frame.bg_rgb.size == (tiny_spec.size, tiny_spec.size)
        assert len(frame.object_rgbas) == len(tiny_spec.object_refs)
        for rgba in frame.object_rgbas:
            assert rgba.mode == "RGBA"
            assert rgba.size == (tiny_spec.size, tiny_spec.size)


def test_render_sequence_overwrites_stale_channel_metadata(
    tiny_spec: SequenceSpec,
    tmp_path: Path,
) -> None:
    fg_root, bg_root = _fixture_roots()
    tiny_spec.channel_refs = ["stale/ref.png", "other/stale.png"]
    tiny_spec.object_depths = [0.1, 0.2]

    render_sequence(tiny_spec, fg_root, bg_root, tmp_path / "0001", SampleConfig())

    assert tiny_spec.channel_refs != ["stale/ref.png", "other/stale.png"]
    assert tiny_spec.object_depths != [0.1, 0.2]
