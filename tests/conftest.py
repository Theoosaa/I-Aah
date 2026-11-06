"""Shared synthetic data: a small workspace spanning two years, and an ING-like statement PDF."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from typing import Final

import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from iaah.core.assignments import SplitPart
from iaah.core.category_io import default_catalog
from iaah.core.library import Library, StoredStatement
from iaah.core.models import StatementInfo, Transaction
from iaah.core.workspace import Workspace

ACCOUNT: Final = "1234567890"
MONTHS: Final = ((2025, 11), (2025, 12), (2026, 1), (2026, 2))
OPENING: Final = Decimal("1000.00")

# (day, booking type, payee, purpose, amount) per month
MONTHLY: Final = (
    (1, "Gehalt/Rente", "Arbeitgeber GmbH", "Gehalt", "2500.00"),
    (2, "Lastschrift", "Hausverwaltung Nord", "Miete", "-900.00"),
    (3, "Lastschrift", "NETFLIX.COM", "Abo", "-12.99"),
    (5, "Lastschrift", "REWE Markt", "Einkauf", "-54.30"),
    (12, "Lastschrift", "REWE Markt", "Einkauf", "-61.15"),
    (15, "Lastschrift", "Trade Republic", "Sparplan", "-200.00"),
    (20, "Lastschrift", "AMAZON EU", "Bestellung", "-89.99"),
)


def _transactions_of(year: int, month: int) -> list[Transaction]:
    source = f"auszug-{year}-{month:02d}.pdf"
    return [
        Transaction(date(year, month, day), kind, payee, purpose, Decimal(amount), source, ACCOUNT)
        for day, kind, payee, purpose, amount in MONTHLY
    ]


EXTRA: Final = (  # February: a refund, and a booking that the workspace splits
    (21, "Gutschrift", "AMAZON EU", "Erstattung", "30.00"),
    (22, "Lastschrift", "Drogerie am Eck", "Einkauf", "-40.00"),
)
SPLIT: Final = (
    SplitPart("Lebensmittel", Decimal("-25.00")),
    SplitPart("Gesundheit", Decimal("-15.00")),
)


def sample_transactions() -> list[Transaction]:
    """Four months of bookings, plus a refund and a booking that is split later (the last)."""
    transactions = [txn for year, month in MONTHS for txn in _transactions_of(year, month)]
    source = "auszug-2026-02.pdf"
    transactions.extend(
        Transaction(date(2026, 2, day), kind, payee, purpose, Decimal(amount), source, ACCOUNT)
        for day, kind, payee, purpose, amount in EXTRA
    )
    return transactions


def _statement(year: int, month: int, transactions: list[Transaction]) -> StoredStatement:
    source = f"auszug-{year}-{month:02d}.pdf"
    total = sum((t.amount for t in transactions if t.source == source), Decimal(0))
    info = StatementInfo(source, ACCOUNT, "", f"{year}-{month:02d}", OPENING, OPENING + total,
                         total)  # fmt: skip
    return StoredStatement(info)


@pytest.fixture
def workspace() -> Workspace:
    """Default catalog with budgets, four months of bookings, one split booking."""
    catalog = default_catalog()
    catalog.set_budget("Lebensmittel", Decimal("100.00"))
    catalog.set_budget("Shopping", Decimal("150.00"))
    transactions = sample_transactions()
    statements = [_statement(year, month, transactions) for year, month in MONTHS]
    library = Library(statements, transactions)
    library.assignments.set_split(transactions[-1], SPLIT)
    return Workspace(catalog, library)


# -- a synthetic ING statement ---------------------------------------------------------------

LEFT: Final = 70.0
TEXT_X: Final = 120.0
AMOUNT_RIGHT: Final = 553.0  # right-aligned amount column, as on real ING statements
LINE: Final = 12.0
FONT: Final = "Helvetica"
FONT_SIZE: Final = 9
PAGE_TOP: Final = 780.0
PAGE_BOTTOM: Final = 120.0

# (date, head text, amount, purpose lines); the third booking's purpose continues on page 2
PDF_BOOKINGS: Final = (
    ("01.07.2026", "Gehalt/Rente Arbeitgeber GmbH", "2.500,00", ("Gehalt Juli",)),
    ("02.07.2026", "Lastschrift REWE Markt", "-54,30", ("Einkauf", "Filiale 0815")),
    ("03.07.2026", "Lastschrift Drogerie am Eck", "-40,00", ("Einkauf",)),
)
PDF_OPENING: Final = "1.000,00"
PDF_CLOSING: Final = "3.405,70"


def statement_pdf_bytes(closing: str = PDF_CLOSING) -> bytes:
    """Two A4 pages laid out like an ING statement; the last booking's purpose continues on
    page 2, followed by the closing balance."""
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=A4)
    canvas.setFont(FONT, FONT_SIZE)
    y = _header(canvas)
    for index, (day, head, amount, purpose) in enumerate(PDF_BOOKINGS):
        y = _booking(canvas, y, (day, head, amount), purpose, last=index == len(PDF_BOOKINGS) - 1)
    canvas.drawString(LEFT, y - LINE, "Neuer Saldo")
    canvas.drawRightString(AMOUNT_RIGHT, y - LINE, f"{closing} Euro")
    canvas.save()
    return buffer.getvalue()


def _header(canvas: Canvas) -> float:
    lines = ("Girokonto Nummer 1234567890", "Kontoauszug Juli 2026")
    y = PAGE_TOP
    for text in lines:
        canvas.drawString(LEFT, y, text)
        y -= LINE
    canvas.drawString(LEFT, y, "Alter Saldo")
    canvas.drawRightString(AMOUNT_RIGHT, y, f"{PDF_OPENING} Euro")
    return y - 2 * LINE


def _booking(
    canvas: Canvas, y: float, head: tuple[str, str, str], purpose: tuple[str, ...], last: bool
) -> float:
    day, text, amount = head
    canvas.drawString(LEFT, y, day)
    canvas.drawString(TEXT_X, y, text)
    canvas.drawRightString(AMOUNT_RIGHT, y, amount)
    for line in purpose:
        y -= LINE
        canvas.drawString(TEXT_X, y, line)
    if last:  # continue the purpose on the next page
        canvas.showPage()
        canvas.setFont(FONT, FONT_SIZE)
        y = PAGE_TOP
        canvas.drawString(TEXT_X, y, "Fortsetzung Seite 2")
    return y - 2 * LINE


@pytest.fixture
def build_statement_pdf() -> Callable[[str], bytes]:
    """The builder itself, for statements with another closing balance."""
    return statement_pdf_bytes


@pytest.fixture
def statement_pdf(tmp_path: Path) -> Path:
    """The synthetic statement as a file."""
    path = tmp_path / "Girokonto_Kontoauszug_202607.pdf"
    path.write_bytes(statement_pdf_bytes())
    return path
