# Portions adapted from budgets (MIT, © 2026 nikluep) – see LICENSES/budgets-MIT.txt
"""Bounding boxes from PDF points into a drawing target – written once for the marked-PDF
export (reportlab, origin bottom left) and the PDF review tab (Tk canvas, origin top left)."""

from typing import Final

from iaah.core.models import BBox

DEFAULT_PADDING: Final = 2.0  # target units around a booking's text


def to_target_box(
    bbox: BBox,
    scale: float,
    padding: float = DEFAULT_PADDING,
    page_height: float | None = None,
) -> BBox:
    """Scale ``(x0, top, x1, bottom)`` (PDF points, origin top left) and pad it.

    ``scale`` converts points to target units (e.g. render DPI / 72). Without ``page_height``
    the target has its origin top left (a canvas); with it, bottom left (reportlab), and y is
    flipped against that height. The result is always normalized: ``x0 < x1`` and ``y0 < y1``,
    so ``(x0, y0, x1 - x0, y1 - y0)`` is a valid rectangle in either system.
    """
    x0, top, x1, bottom = bbox
    left = x0 * scale - padding
    right = x1 * scale + padding
    if page_height is None:
        return left, top * scale - padding, right, bottom * scale + padding
    return left, page_height - bottom * scale - padding, right, page_height - top * scale + padding
