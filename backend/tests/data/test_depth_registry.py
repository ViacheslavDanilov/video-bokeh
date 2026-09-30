from __future__ import annotations

import numpy as np
import pytest
import torch
from PIL import Image

from video_bokeh.library.depth import ESTIMATORS
from video_bokeh.library.depth.base import DepthEstimator


def test_estimators_is_a_dict() -> None:
    assert isinstance(ESTIMATORS, dict)


def test_protocol_has_required_methods() -> None:
    assert hasattr(DepthEstimator, "load")
    assert hasattr(DepthEstimator, "infer")


@pytest.mark.parametrize(("key", "cls"), sorted(ESTIMATORS.items()))
def test_every_registered_estimator_conforms(key: str, cls: type) -> None:
    # A model added to the registry without the interface would only fail once Stage A
    # had loaded its weights; this catches it for free.
    assert cls.name == key
    assert callable(getattr(cls, "load", None))
    assert callable(getattr(cls, "infer", None))


@pytest.mark.parametrize("key", ["da2-small", "da2-base", "da2-large"])
def test_da2_variants_are_registered(key: str) -> None:
    assert key in ESTIMATORS


@pytest.mark.parametrize(
    ("key", "hf_id"),
    [
        ("da2-small", "depth-anything/Depth-Anything-V2-Small-hf"),
        ("da2-base", "depth-anything/Depth-Anything-V2-Base-hf"),
        ("da2-large", "depth-anything/Depth-Anything-V2-Large-hf"),
        ("depth-pro", "apple/DepthPro-hf"),
    ],
)
def test_transformers_models_carry_correct_hf_id(key: str, hf_id: str) -> None:
    assert ESTIMATORS[key].hf_model_id == hf_id


@pytest.mark.parametrize("key", ["da2-small", "depth-pro"])
def test_transformers_infer_returns_correct_shape_and_dtype(monkeypatch, key) -> None:
    from video_bokeh.library.depth import _transformers as mod

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

    est = ESTIMATORS[key]()
    est.load(torch.device("cpu"))
    out = est.infer([Image.new("RGB", (64, 64)), Image.new("RGB", (32, 24))])

    assert len(out) == 2
    assert out[0].shape == (64, 64)
    assert out[1].shape == (24, 32)
    assert out[0].dtype == np.float32
