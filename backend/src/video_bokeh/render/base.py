"""Protocol every bokeh renderer implements."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Protocol, runtime_checkable


@runtime_checkable
class BokehRenderer(Protocol):
    """Writes the bokeh stream of sequences Stage B has written.

    For every sequence it is given, ``render`` writes ``<sequence>/bokeh/<frame>.png``:
    RGB uint8 at the sequence's own size, one file per ``all_in_focus`` frame and named
    like it. A sequence's ``bokeh/`` appears complete or not at all.

    A renderer that cannot take short sequences may say so with a ``min_frames`` class
    attribute; ``render.run --missing`` then leaves them out instead of handing them over.
    """

    name: ClassVar[str]

    def render(
        self,
        sequence_dirs: list[Path],
        strength: float,
        focus_disparity: float | None,
    ) -> None:
        """Render every sequence in ``sequence_dirs``.

        ``strength`` scales the blur, in units each renderer documents.
        ``focus_disparity`` fixes the in-focus disparity, in ``[0, 1]``, for every frame.
        ``None`` lets the renderer choose.
        """
