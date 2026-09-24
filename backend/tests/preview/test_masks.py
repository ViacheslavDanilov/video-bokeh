from __future__ import annotations

import numpy as np
import pytest

from video_bokeh.preview._masks import OBJECT_COLORS, object_color, render_object_masks


def _square(size: int, lo: int, hi: int) -> np.ndarray:
    a = np.zeros((size, size), dtype=np.float32)
    a[lo:hi, lo:hi] = 1.0
    return a


def test_each_object_gets_its_own_colour() -> None:
    masks = render_object_masks([_square(16, 0, 4), _square(16, 8, 12)])
    assert tuple(masks[1, 1]) == OBJECT_COLORS[0]
    assert tuple(masks[9, 9]) == OBJECT_COLORS[1]


def test_everything_outside_every_mask_is_black() -> None:
    masks = render_object_masks([_square(16, 0, 4)])
    assert tuple(masks[15, 15]) == (0, 0, 0)


def test_colour_follows_the_page_index_not_the_order_on_screen() -> None:
    """The page index is the object's identity for the whole clip, so an object that
    moves must keep its colour. That is what makes a crossing readable.
    """
    first = render_object_masks([_square(16, 0, 4), _square(16, 8, 12)])
    # The same two objects, having swapped places on screen.
    second = render_object_masks([_square(16, 8, 12), _square(16, 0, 4)])
    assert tuple(first[1, 1]) == tuple(second[9, 9]) == OBJECT_COLORS[0]
    assert tuple(first[9, 9]) == tuple(second[1, 1]) == OBJECT_COLORS[1]


def test_a_later_page_covers_an_earlier_one_where_they_overlap() -> None:
    """Masks are amodal, so silhouettes overlap and something has to win."""
    masks = render_object_masks([_square(16, 0, 8), _square(16, 4, 12)])
    assert tuple(masks[6, 6]) == OBJECT_COLORS[1]
    assert tuple(masks[1, 1]) == OBJECT_COLORS[0]


def test_a_soft_edge_does_not_leave_a_halo() -> None:
    """Warping filters the alpha against the background, so the fringe is not the
    object and painting it would outline everything in its own colour.
    """
    a = np.zeros((8, 8), dtype=np.float32)
    a[2:6, 2:6] = 1.0
    a[1, 1] = 0.2
    masks = render_object_masks([a])
    assert tuple(masks[3, 3]) == OBJECT_COLORS[0]
    assert tuple(masks[1, 1]) == (0, 0, 0)


def test_more_objects_than_colours_wrap_rather_than_crash() -> None:
    assert object_color(len(OBJECT_COLORS)) == OBJECT_COLORS[0]


def test_pages_of_different_shapes_are_an_error() -> None:
    with pytest.raises(ValueError, match="expected"):
        render_object_masks([_square(8, 0, 4), _square(16, 0, 4)])


def test_no_pages_at_all_is_an_error() -> None:
    with pytest.raises(ValueError, match="at least one object"):
        render_object_masks([])
