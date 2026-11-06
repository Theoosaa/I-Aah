"""Marked statement PDF: overlays per booking, stripes for splits, legend pages."""

from collections.abc import Callable
from dataclasses import replace
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pdfplumber
import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject

from iaah.core.assignments import Categorizer, ManualAssignments, SplitPart
from iaah.core.category_io import default_catalog
from iaah.core.errors import StatementParseError
from iaah.core.models import Placement, Region, Transaction
from iaah.core.parsing.ing import read_statement
from iaah.export.marked_pdf import (
    LegendRow,
    legend_for,
    mark_pdf,
    marked_name,
    marks_for,
    printable,
    write_marked_pdf,
)

RECTANGLE = b" re"


def _categorizer(manual: ManualAssignments | None = None) -> Categorizer:
    return Categorizer(default_catalog(), manual or ManualAssignments())


def _page_texts(pdf: bytes) -> list[str]:
    return [page.extract_text() for page in PdfReader(BytesIO(pdf)).pages]


def _rectangles(pdf: bytes, page: int) -> int:
    content = PdfReader(BytesIO(pdf)).pages[page].get_contents()
    assert content is not None
    return content.get_data().count(RECTANGLE)


def test_marked_copy_has_overlays_and_a_legend(statement_pdf: Path, tmp_path: Path) -> None:
    parsed = read_statement(statement_pdf)
    target = tmp_path / "markiert.pdf"
    result = write_marked_pdf(statement_pdf, target, parsed.transactions, _categorizer())
    assert (result.marked, result.skipped) == (3, 0)
    assert [row.category for row in result.legend] == ["Einkommen", "Lebensmittel", "Sonstiges"]

    marked, original = target.read_bytes(), statement_pdf.read_bytes()
    texts = _page_texts(marked)
    assert len(texts) == 3  # two statement pages + legend
    assert "Legende: Kategorie-Farben" in texts[2]
    assert "Lebensmittel" in texts[2]
    assert "REWE Markt" in texts[0]  # the original text survives
    # three heads and three detail blocks on page 1, one continued detail on page 2
    assert _rectangles(marked, 0) - _rectangles(original, 0) >= 6
    assert _rectangles(marked, 1) - _rectangles(original, 1) >= 1


def test_split_bookings_become_stripes(statement_pdf: Path) -> None:
    txn = read_statement(statement_pdf).transactions[2]  # -40.00
    manual = ManualAssignments()
    manual.set_split(txn, [SplitPart("Lebensmittel", Decimal("-25.00")),
                           SplitPart("Gesundheit", Decimal("-15.00"))])  # fmt: skip
    (mark,) = marks_for([txn], _categorizer(manual))
    catalog = default_catalog()
    assert [stripe.color for stripe in mark.stripes] == [
        catalog.color_of("Lebensmittel"),
        catalog.color_of("Gesundheit"),
    ]
    assert [stripe.share for stripe in mark.stripes] == [Decimal("0.625"), Decimal("0.375")]
    legend = legend_for([txn], _categorizer(manual))
    assert [(row.category, row.bookings, row.total) for row in legend] == [
        ("Lebensmittel", 1, Decimal("-25.00")),
        ("Gesundheit", 1, Decimal("-15.00")),
    ]


def test_bookings_without_placement_or_page_are_skipped(
    statement_pdf: Path, tmp_path: Path
) -> None:
    placed = read_statement(statement_pdf).transactions[0]
    unplaced = Transaction(date(2026, 7, 9), "", "Bar", "", Decimal("-5.00"), "x.csv")
    elsewhere = replace(placed, placement=Placement(Region(99, (0.0, 0.0, 10.0, 10.0))))
    target = tmp_path / "out.pdf"
    result = write_marked_pdf(statement_pdf, target, [placed, unplaced, elsewhere], _categorizer())
    assert (result.marked, result.skipped) == (1, 2)
    assert len(PdfReader(target).pages) == 3


def test_long_legends_continue_on_further_pages(statement_pdf: Path) -> None:
    legend = [LegendRow(f"Kategorie {n}", "#92ca7d", 1, Decimal(1)) for n in range(60)]
    pdf, _ = mark_pdf(statement_pdf.read_bytes(), [], legend)
    texts = _page_texts(pdf)
    assert len(texts) == 4  # two statement pages + two legend pages
    assert "Kategorie 59" in texts[3]


def test_unreadable_pdf_raises(tmp_path: Path) -> None:
    with pytest.raises(StatementParseError):
        mark_pdf(b"no pdf at all", [], [])
    with pytest.raises(StatementParseError):
        write_marked_pdf(tmp_path / "missing.pdf", tmp_path / "out.pdf", [], _categorizer())


def _reboxed(pdf: bytes, left: float, bottom: float, rotate: int = 0) -> bytes:
    """``pdf`` with the media boxes starting at (left, bottom), page 1 optionally rotated."""
    writer = PdfWriter()
    for number, page in enumerate(PdfReader(BytesIO(pdf)).pages):
        box = page.mediabox
        page.mediabox = RectangleObject((left, bottom, float(box.right), float(box.top)))
        if number == 0 and rotate:
            page.rotate(rotate)
        writer.add_page(page)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize("origin", [(0.0, 0.0), (20.0, 30.0)], ids=["origin", "offset"])
def test_marks_cover_their_text(
    build_statement_pdf: Callable[[str], bytes], tmp_path: Path, origin: tuple[float, float]
) -> None:
    source = tmp_path / "auszug.pdf"
    source.write_bytes(_reboxed(build_statement_pdf("3.405,70"), *origin))
    parsed = read_statement(source)
    assert len(parsed.transactions) == 3
    target = tmp_path / "markiert.pdf"
    write_marked_pdf(source, target, parsed.transactions, _categorizer())
    with pdfplumber.open(target) as pdf:
        page = pdf.pages[0]
        rects = page.rects
        words = [w for w in page.extract_words() if w["text"] in {"REWE", "-54,30", "Filiale"}]
    assert len(words) == 3
    for word in words:
        assert any(
            rect["x0"] <= word["x0"] and word["x1"] <= rect["x1"]
            and rect["top"] <= word["top"] and word["bottom"] <= rect["bottom"]
            for rect in rects
        ), word["text"]  # fmt: skip


def test_rotated_pages_are_left_unmarked(statement_pdf: Path) -> None:
    parsed = read_statement(statement_pdf)
    rotated = _reboxed(statement_pdf.read_bytes(), 0.0, 0.0, rotate=90)
    pdf, marked = mark_pdf(rotated, marks_for(parsed.transactions, _categorizer()), [])
    assert marked == 1  # only the booking continued on (unrotated) page 2
    assert _rectangles(pdf, 0) == _rectangles(rotated, 0)


def test_legend_names_are_printable() -> None:
    assert printable("Łódź Café 😀") == "?ód? Café ?"
    long_name = printable("Versicherungen und sonstige Vorsorgeleistungen")
    assert len(long_name) == 36
    assert long_name.endswith("…")


def test_marked_name_sits_beside_the_source() -> None:
    assert marked_name(Path("a/Auszug Juli.pdf")) == Path("a/Auszug Juli_markiert.pdf")
