from __future__ import annotations

import numpy as np
import pytest
import torch
from PIL import Image

from data.depth import ESTIMATORS
from data.depth.base import DepthEstimator


def test_estimators_is_a_dict() -> None:
    assert isinstance(ESTIMATORS, dict)


def test_protocol_has_required_methods() -> None:
    assert hasattr(DepthEstimator, "load")
    assert hasattr(DepthEstimator, "infer")


@pytest.mark.parametrize("key", ["da2-small", "da2-base", "da2-large"])
def test_da2_variants_are_registered(key: str) -> None:
    assert key in ESTIMATORS


@pytest.mark.parametrize(
    ("key", "hf_id"),
    [
        ("da2-small", "depth-anything/Depth-Anything-V2-Small-hf"),
        ("da2-base", "depth-anything/Depth-Anything-V2-Base-hf"),
        ("da2-large", "depth-anything/Depth-Anything-V2-Large-hf"),
    ],
)
def test_da2_variants_carry_correct_hf_id(key: str, hf_id: str) -> None:
    assert ESTIMATORS[key].hf_model_id == hf_id


def test_da2_infer_returns_correct_shape_and_dtype(monkeypatch) -> None:
    from data.depth import depth_anything_v2 as mod

    class _Inputs(dict):
        def to(self, _device: torch.device) -> _Inputs:
            return self

    class _StubProcessor:
        def __call__(self, images, return_tensors):
            assert len(images) == 2
            assert return_tensors == "pt"
            return _Inputs()

    class _StubOutputs:
        predicted_depth = torch.zeros((2, 16, 16))

    class _StubModel:
        def __call__(self, **_kwargs):
            return _StubOutputs()

        def eval(self):
            return self

        def to(self, _device: torch.device):
            return self

    monkeypatch.setattr(
        mod,
        "AutoImageProcessor",
        type("M", (), {"from_pretrained": staticmethod(lambda _id: _StubProcessor())}),
    )
    monkeypatch.setattr(
        mod,
        "AutoModelForDepthEstimation",
        type("M", (), {"from_pretrained": staticmethod(lambda _id: _StubModel())}),
    )

    est = ESTIMATORS["da2-small"]()
    est.load(torch.device("cpu"))
    out = est.infer([Image.new("RGB", (64, 64)), Image.new("RGB", (32, 24))])

    assert len(out) == 2
    assert out[0].shape == (64, 64)
    assert out[1].shape == (24, 32)
    assert out[0].dtype == np.float32
