"""The colormap is a lookup table, not a dependency.

`Spectral_r` is what the Depth Anything V2 repository draws its qualitative figures
with, so our disparity renders sit next to the published ones without a reader
re-learning the colour coding. matplotlib is a dev dependency and is used here, and
only here, to prove the table is faithful -- the runtime must not import it.
"""

from __future__ import annotations

import numpy as np
import pytest

from video_bokeh.preview._colormap import COLORMAPS, apply_colormap


def test_matches_matplotlib_spectral_r() -> None:
    mpl = pytest.importorskip("matplotlib")
    cmap = mpl.colormaps["Spectral_r"]
    x = np.linspace(0.0, 1.0, 256, dtype=np.float32)
    expected = (np.asarray(cmap(x))[:, :3] * 255).round().astype(np.uint8)
    got = apply_colormap(x.reshape(1, -1))[0]
    assert np.abs(got.astype(int) - expected.astype(int)).max() == 0


def test_near_is_red_and_far_is_blue() -> None:
    ends = apply_colormap(np.array([[0.0, 1.0]], dtype=np.float32))[0]
    far, near = ends[0], ends[1]
    assert near[0] > near[2], "disparity 1.0 (closest) must read red"
    assert far[2] > far[0], "disparity 0.0 (farthest) must read blue"


def test_grey_is_linear_and_monotone() -> None:
    x = np.linspace(0.0, 1.0, 64, dtype=np.float32)
    got = apply_colormap(x.reshape(1, -1), "grey")[0]
    assert (np.diff(got[:, 0].astype(int)) >= 0).all()
    assert got[0, 0] == 0 and got[-1, 0] == 255
    assert (got[:, 0] == got[:, 1]).all() and (got[:, 1] == got[:, 2]).all()


def test_values_outside_the_unit_range_are_clipped() -> None:
    got = apply_colormap(np.array([[-0.5, 1.5]], dtype=np.float32))[0]
    ends = apply_colormap(np.array([[0.0, 1.0]], dtype=np.float32))[0]
    assert (got[0] == ends[0]).all() and (got[1] == ends[1]).all()


def test_unknown_name_is_rejected() -> None:
    with pytest.raises(KeyError):
        apply_colormap(np.zeros((1, 1), dtype=np.float32), "viridis")


def test_runtime_does_not_import_matplotlib() -> None:
    import subprocess
    import sys

    code = (
        "import sys\n"
        "import video_bokeh.preview._colormap\n"
        "import video_bokeh.preview.pack\n"
        "sys.exit(1 if 'matplotlib' in sys.modules else 0)\n"
    )
    assert COLORMAPS  # the module under test is the one imported above
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, "the colormap must not pull matplotlib at runtime"
