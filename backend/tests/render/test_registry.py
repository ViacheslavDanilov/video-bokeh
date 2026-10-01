"""``--renderer`` names a registered bokeh renderer or a class of the user's own."""

from __future__ import annotations

from pathlib import Path

import pytest

from video_bokeh.core._plugins import missing_methods
from video_bokeh.render import RENDERERS, resolve_renderer


@pytest.mark.parametrize(("key", "cls"), sorted(RENDERERS.items()))
def test_every_registered_renderer_conforms(key: str, cls: type) -> None:
    assert cls.name == key
    assert missing_methods(cls, ("render",)) == []


def test_import_path_resolves_a_custom_renderer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "my_renderers.py").write_text(
        "class Mine:\n    def render(self, sequence_dirs, strength, focus_disparity):\n"
        "        pass\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    assert resolve_renderer("my_renderers:Mine").__name__ == "Mine"


def test_unknown_renderer_lists_the_registered_ones() -> None:
    with pytest.raises(ValueError, match="any-to-bokeh"):
        resolve_renderer("blur-o-matic")
