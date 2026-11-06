"""Box transform from PDF points into canvas and reportlab coordinates."""

from iaah.core.geometry import to_target_box


def test_canvas_target_scales_and_pads() -> None:
    assert to_target_box((10.0, 20.0, 30.0, 40.0), scale=2.0, padding=1.0) == (
        19.0, 39.0, 61.0, 81.0,
    )  # fmt: skip


def test_reportlab_target_flips_and_stays_normalized() -> None:
    x0, y0, x1, y1 = to_target_box((10.0, 20.0, 30.0, 40.0), 1.0, 2.0, page_height=100.0)
    assert (x0, y0, x1, y1) == (8.0, 58.0, 32.0, 82.0)
    assert x0 < x1
    assert y0 < y1
