"""Bookings as a table: CSV for any spreadsheet, and a formatted Excel workbook.

One row per entry, so a split booking yields one row per part. Texts written by other people –
payee and purpose come from the sender of a transfer – are defused: a cell starting like a
formula (``=``, ``+``, ``-``, ``@``) is prefixed with an apostrophe in the CSV and stored as
plain text in Excel, so opening the export can never run a formula.
"""

import csv
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path
from typing import Final

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from iaah.core.analysis.ledger import Entry
from iaah.core.categories import CategoryKind
from iaah.core.text import clean_display, format_plain_german
from iaah.export.files import write_export

COLUMNS: Final = (
    "Datum", "Konto", "Buchungsart", "Empfänger", "Verwendungszweck", "Betrag", "Kategorie", "Art",
)  # fmt: skip
COLUMN_WIDTHS: Final = (12, 13, 22, 32, 60, 14, 22, 11)
KIND_LABELS: Final[dict[CategoryKind, str]] = {
    CategoryKind.EXPENSE: "Ausgabe",
    CategoryKind.INCOME: "Einnahme",
    CategoryKind.IGNORED: "Ignoriert",
}
DATE_FORMAT: Final = "%d.%m.%Y"
CSV_DELIMITER: Final = ";"
CSV_ENCODING: Final = "utf-8-sig"  # the BOM makes Excel read umlauts and € correctly
FORMULA_STARTS: Final = ("=", "+", "-", "@", "\t", "\r")
TEXT_GUARD: Final = "'"
SHEET_TITLE: Final = "Buchungen"
EXCEL_DATE_FORMAT: Final = "DD.MM.YYYY"
EXCEL_EURO_FORMAT: Final = '#,##0.00 "€";[Red]-#,##0.00 "€"'
EXCEL_TEXT: Final = "s"  # openpyxl data type: plain string, never a formula
HEADER_ROW: Final = 1
FREEZE_BELOW_HEADER: Final = "A2"
DATE_COLUMN: Final = COLUMNS.index("Datum") + 1
AMOUNT_COLUMN: Final = COLUMNS.index("Betrag") + 1
TEXT_COLUMNS: Final = tuple(
    number for number in range(1, len(COLUMNS) + 1) if number not in (DATE_COLUMN, AMOUNT_COLUMN)
)  # in the order of BookingRow.texts


@dataclass(frozen=True, slots=True)
class BookingRow:
    """One line of the export."""

    day: date
    account: str
    booking_type: str
    payee: str
    purpose: str
    amount: Decimal
    category: str
    kind: str

    @property
    def texts(self) -> tuple[str, ...]:
        """The text cells, in column order (date and amount excluded)."""
        return (self.account, self.booking_type, self.payee, self.purpose, self.category, self.kind)


def booking_rows(entries: Iterable[Entry]) -> list[BookingRow]:
    """Rows for ``entries`` in booking-date order (stable for equal dates)."""
    return [
        BookingRow(
            day=entry.day,
            account=entry.transaction.account,
            booking_type=clean_display(entry.transaction.booking_type),
            payee=clean_display(entry.transaction.payee),
            purpose=clean_display(entry.transaction.purpose),
            amount=entry.amount,
            category=entry.category,
            kind=KIND_LABELS[entry.kind],
        )
        for entry in sorted(entries, key=lambda entry: entry.day)
    ]


def defuse(text: str) -> str:
    """Prefix text that a spreadsheet would read as a formula."""
    return TEXT_GUARD + text if text.startswith(FORMULA_STARTS) else text


# -- CSV --------------------------------------------------------------------------------------


def render_bookings_csv(rows: Sequence[BookingRow]) -> str:
    """German CSV: semicolons, decimal comma, ``TT.MM.JJJJ`` dates."""
    buffer = StringIO()
    writer = csv.writer(buffer, delimiter=CSV_DELIMITER)
    writer.writerow(COLUMNS)
    for row in rows:
        account, booking_type, payee, purpose, category, kind = (defuse(t) for t in row.texts)
        writer.writerow([
            row.day.strftime(DATE_FORMAT), account, booking_type, payee, purpose,
            format_plain_german(row.amount), category, kind,
        ])  # fmt: skip
    return buffer.getvalue()


def write_bookings_csv(rows: Sequence[BookingRow], path: Path) -> None:
    """Write the CSV with a BOM, so Excel shows umlauts and € correctly."""
    write_export(path, render_bookings_csv(rows).encode(CSV_ENCODING))


# -- Excel ------------------------------------------------------------------------------------


def bookings_workbook(rows: Sequence[BookingRow]) -> Workbook:
    """A workbook with real dates and numbers, euro format, frozen header and filter."""
    workbook = Workbook()
    sheet = workbook.worksheets[0]
    sheet.title = SHEET_TITLE
    sheet.append(COLUMNS)
    for cell in sheet[HEADER_ROW]:
        cell.font = Font(bold=True)
    for line, row in enumerate(rows, start=HEADER_ROW + 1):
        _write_row(sheet, line, row)
    for index, width in enumerate(COLUMN_WIDTHS, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = FREEZE_BELOW_HEADER
    sheet.auto_filter.ref = sheet.dimensions
    return workbook


def _write_row(sheet: Worksheet, line: int, row: BookingRow) -> None:
    sheet.cell(line, DATE_COLUMN, row.day).number_format = EXCEL_DATE_FORMAT
    sheet.cell(line, AMOUNT_COLUMN, row.amount).number_format = EXCEL_EURO_FORMAT
    for column, text in zip(TEXT_COLUMNS, row.texts, strict=True):
        # Plain string even if it starts with "=" – openpyxl would store a formula. Control
        # characters (possible in sender-written text) are not allowed in the file format.
        cell = sheet.cell(line, column, ILLEGAL_CHARACTERS_RE.sub("", text))
        cell.data_type = EXCEL_TEXT


def write_bookings_excel(rows: Sequence[BookingRow], path: Path) -> None:
    """Save the workbook as ``.xlsx``."""
    buffer = BytesIO()
    bookings_workbook(rows).save(buffer)
    write_export(path, buffer.getvalue())
