# Portions adapted from budgets (MIT, © 2026 nikluep) – see LICENSES/budgets-MIT.txt
"""A copy of a statement PDF with every booking underlaid in its category color, plus legend.

The boxes come from the parser's placements, so no second pass over the PDF is needed. A split
booking is drawn as stripes, one per part and as wide as its share. The color goes *under* the
original text at 40 % opacity, so the statement stays readable.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Final

from pypdf import PageObject, PdfReader, PdfWriter
from pypdf.errors import PyPdfError
from reportlab.lib.colors import HexColor, black
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from iaah.core.assignments import Categorizer
from iaah.core.errors import StatementParseError
from iaah.core.geometry import to_target_box
from iaah.core.models import BBox, Placement, Transaction
from iaah.core.text import format_euro
from iaah.export.files import write_export

OPACITY: Final = 0.4
POINTS_PER_POINT: Final = 1.0  # placements are in PDF points already
FONT: Final = "Helvetica"
BOLD_FONT: Final = "Helvetica-Bold"
TITLE_SIZE: Final = 16
TEXT_SIZE: Final = 11
MARGIN: Final = 50.0
TITLE_GAP: Final = 40.0
SWATCH: Final = 14.0
SWATCH_GAP: Final = 10.0
ROW_HEIGHT: Final = SWATCH + 10.0
SWATCH_DROP: Final = 3.0  # swatch bottom below the text baseline
COUNT_X: Final = 300.0
SUM_RIGHT: Final = A4[0] - MARGIN
LEGEND_TITLE: Final = "Legende: Kategorie-Farben"
BOOKING: Final = "Buchung"
BOOKINGS: Final = "Buchungen"
NAME_CHARS: Final = 36  # fits between swatch and count column at TEXT_SIZE
ELLIPSIS: Final = "…"
FONT_ENCODING: Final = "cp1252"  # what the standard PDF fonts can draw (WinAnsi)
FULL_TURN: Final = 360
SUFFIX: Final = "_markiert"


@dataclass(frozen=True, slots=True)
class Stripe:
    """Part of a booking's box: a category color and its share of the width (0–1)."""

    color: str
    share: Decimal


@dataclass(frozen=True, slots=True)
class Mark:
    """Where to draw a booking and in which colors."""

    placement: Placement
    stripes: tuple[Stripe, ...]


@dataclass(frozen=True, slots=True)
class LegendRow:
    """A category on the legend page: how many bookings (or split parts) and their sum."""

    category: str
    color: str
    bookings: int
    total: Decimal


@dataclass(frozen=True, slots=True)
class MarkResult:
    """What ``write_marked_pdf`` did."""

    marked: int  # bookings drawn
    skipped: int  # bookings without placement or only on pages the PDF does not have
    legend: tuple[LegendRow, ...]


def marks_for(transactions: Iterable[Transaction], categorizer: Categorizer) -> list[Mark]:
    """A mark per booking that has a placement; splits become one stripe per part."""
    marks: list[Mark] = []
    for txn in transactions:
        if txn.placement is None:
            continue
        parts = categorizer.resolve(txn).parts
        whole = sum((abs(part.amount) for part in parts), Decimal(0)) or Decimal(1)
        stripes = tuple(
            Stripe(categorizer.catalog.color_of(part.category), abs(part.amount) / whole)
            for part in parts
        )
        marks.append(Mark(txn.placement, stripes))
    return marks


def legend_for(transactions: Iterable[Transaction], categorizer: Categorizer) -> list[LegendRow]:
    """The categories of the placed bookings, in catalog order."""
    counts: dict[str, int] = defaultdict(int)
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for txn in transactions:
        if txn.placement is None:
            continue
        for part in categorizer.resolve(txn).parts:
            counts[part.category] += 1
            totals[part.category] += part.amount
    catalog = categorizer.catalog
    return [
        LegendRow(name, catalog.color_of(name), counts[name], totals[name])
        for name in catalog.names()
        if name in counts
    ]


def mark_pdf(pdf: bytes, marks: Sequence[Mark], legend: Sequence[LegendRow]) -> tuple[bytes, int]:
    """The marked copy of ``pdf`` and the number of marks that landed on an existing page."""
    try:
        reader = PdfReader(BytesIO(pdf))
        pages = list(reader.pages)
    except (PyPdfError, ValueError, OSError) as error:
        raise StatementParseError("not a readable PDF") from error
    # Rotated pages are left unmarked: pdfplumber reports their coordinates rotated.
    drawable = {number for number, page in enumerate(pages, 1) if page.rotation % FULL_TURN == 0}
    writer = PdfWriter()
    for number, page in enumerate(pages, start=1):
        attached = writer.add_page(page)  # pypdf 7 merges only into attached pages
        boxes = _boxes_on_page(marks, number) if number in drawable else []
        if boxes:
            attached.merge_page(_overlay(attached, boxes), over=False)
    for legend_page in _legend_pages(legend):
        writer.add_page(legend_page)
    output = BytesIO()
    writer.write(output)
    return output.getvalue(), sum(1 for mark in marks if _drawn(mark, drawable))


def write_marked_pdf(
    source: Path, target: Path, transactions: Sequence[Transaction], categorizer: Categorizer
) -> MarkResult:
    """Write the marked copy of ``source`` to ``target``. ``transactions`` must come from
    that file (their placements point into it)."""
    try:
        pdf = source.read_bytes()
    except OSError as error:
        raise StatementParseError(f"cannot read {source}") from error
    legend = legend_for(transactions, categorizer)
    content, marked = mark_pdf(pdf, marks_for(transactions, categorizer), legend)
    write_export(target, content)
    return MarkResult(marked, len(transactions) - marked, tuple(legend))


def marked_name(source: Path) -> Path:
    """``Auszug.pdf`` → ``Auszug_markiert.pdf`` beside the source."""
    return source.with_name(f"{source.stem}{SUFFIX}{source.suffix}")


# -- drawing ----------------------------------------------------------------------------------


def _boxes_on_page(marks: Sequence[Mark], page: int) -> list[tuple[BBox, tuple[Stripe, ...]]]:
    return [
        (region.bbox, mark.stripes)
        for mark in marks
        for region in mark.placement.regions
        if region.page == page
    ]


def _drawn(mark: Mark, pages: set[int]) -> bool:
    return any(region.page in pages for region in mark.placement.regions)


def _overlay(page: PageObject, boxes: Sequence[tuple[BBox, tuple[Stripe, ...]]]) -> PageObject:
    """A transparent page with the colored boxes. pdfplumber's x is already the page's own
    coordinate and its ``top`` is measured so that ``y = height - top``, so no offset of the
    media box is added (a page whose box does not start at 0,0 is tested)."""
    box = page.mediabox
    height = float(box.height)
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=(float(box.right), float(box.top)))
    canvas.setFillAlpha(OPACITY)
    for bbox, stripes in boxes:
        _draw_stripes(canvas, to_target_box(bbox, POINTS_PER_POINT, page_height=height), stripes)
    canvas.save()
    return PdfReader(BytesIO(buffer.getvalue())).pages[0]


def _draw_stripes(canvas: Canvas, box: BBox, stripes: Sequence[Stripe]) -> None:
    """Fill ``box`` left to right, each stripe as wide as its share; the last one takes the
    rest, so rounding never leaves a gap."""
    x0, y0, x1, y1 = box
    start = x0
    for index, stripe in enumerate(stripes):
        end = x1 if index == len(stripes) - 1 else start + (x1 - x0) * float(stripe.share)
        canvas.setFillColor(HexColor(stripe.color))
        canvas.rect(start, y0, end - start, y1 - y0, fill=1, stroke=0)
        start = end


def _legend_pages(legend: Sequence[LegendRow]) -> list[PageObject]:
    """One A4 page per screenful of categories (all of them – not only the first page)."""
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=A4)
    y = _legend_title(canvas)
    for row in legend:
        if y < MARGIN:
            canvas.showPage()
            y = _legend_title(canvas)
        _legend_row(canvas, row, y)
        y -= ROW_HEIGHT
    canvas.save()
    return list(PdfReader(BytesIO(buffer.getvalue())).pages)


def _legend_title(canvas: Canvas) -> float:
    top = A4[1] - MARGIN
    canvas.setFont(BOLD_FONT, TITLE_SIZE)
    canvas.setFillColor(black)
    canvas.drawString(MARGIN, top, LEGEND_TITLE)
    return top - TITLE_GAP


def _legend_row(canvas: Canvas, row: LegendRow, y: float) -> None:
    canvas.setFillColor(HexColor(row.color))
    canvas.rect(MARGIN, y - SWATCH_DROP, SWATCH, SWATCH, fill=1, stroke=0)
    canvas.setFillColor(black)
    canvas.setFont(FONT, TEXT_SIZE)
    canvas.drawString(MARGIN + SWATCH + SWATCH_GAP, y, printable(row.category))
    noun = BOOKING if row.bookings == 1 else BOOKINGS
    canvas.drawString(COUNT_X, y, f"{row.bookings} {noun}")
    canvas.drawRightString(SUM_RIGHT, y, format_euro(row.total))


def printable(name: str) -> str:
    """A category name the legend can show: short enough for its column, and with characters
    the PDF standard font cannot draw replaced by ``?``."""
    short = name if len(name) <= NAME_CHARS else name[: NAME_CHARS - 1] + ELLIPSIS
    return short.encode(FONT_ENCODING, "replace").decode(FONT_ENCODING)
