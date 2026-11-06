"""Generic import of bank CSV exports (ING, Sparkasse, DKB, …).

Banks differ in encoding, delimiter, preamble lines, column names and number format. The
table is decoded and sniffed, the header row is found by keywords (and confirmed by a booking
below it), columns are mapped automatically, and the decimal style is decided per column. The
GUI can show the table and let the user correct header row and mapping.
"""

import csv
import io
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Final

from iaah.core.errors import CsvMappingError, StatementParseError
from iaah.core.models import StatementInfo, Transaction
from iaah.core.parsing.diagnostics import ParsedStatement, ParseReport
from iaah.core.parsing.ing import account_from_iban, is_valid_iban
from iaah.core.text import (
    DecimalStyle,
    decode_text,
    detect_decimal_style,
    parse_amount,
    parse_flexible_date,
)

DELIMITERS: Final = (";", ",", "\t", "|")
SNIFF_SAMPLE_CHARS: Final = 4000
HEADER_SEARCH_ROWS: Final = 20
HEADER_PROBE_ROWS: Final = 5  # rows below a header candidate that may hold the first booking
PAYEE_FALLBACK_CHARS: Final = 30
MIN_COLUMNS: Final = 2
_WORD_SPLIT: Final = re.compile(r"[^a-z0-9äöüß]+")


class CsvField(StrEnum):
    """The columns a booking needs."""

    DATE = "date"
    AMOUNT = "amount"
    PAYEE = "payee"
    PURPOSE = "purpose"


class _MatchQuality(IntEnum):
    """How well a header cell matches a keyword; lower is better."""

    EXACT = 0
    WORD_START = 1
    SUBSTRING = 2


REQUIRED_FIELDS: Final = (CsvField.DATE, CsvField.AMOUNT)

# Header keywords per field, most specific first. Fields are mapped in this order, and a column
# taken by one field is not offered to the next.
FIELD_KEYWORDS: Final[dict[CsvField, tuple[str, ...]]] = {
    CsvField.DATE: ("buchungstag", "buchungsdatum", "buchung", "datum", "valuta", "date"),
    CsvField.AMOUNT: ("betrag", "umsatz", "amount", "wert"),
    CsvField.PAYEE: (
        "auftraggeber", "empfänger", "empfaenger", "begünstigt", "beguenstigt",
        "zahlungspflicht", "beteiligter", "name", "payee",
    ),
    CsvField.PURPOSE: ("verwendungszweck", "vwz", "buchungstext", "verwendung", "zweck", "text"),
}  # fmt: skip
# Generic keywords match only as a whole word: "buchung" must not claim "Buchungstext" as the
# date column, nor "wert" claim "Wertstellung" as the amount column. ("datum" may still match
# inside compounds such as "Wertstellungsdatum".)
WHOLE_WORD_KEYWORDS: Final = frozenset({"buchung", "date", "wert", "name", "text"})

type ColumnMapping = Mapping[CsvField, int]
type Row = tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CsvTable:
    """A decoded CSV file: all non-empty rows plus how they were read."""

    rows: tuple[Row, ...]
    delimiter: str
    encoding: str


def read_csv(path: Path) -> ParsedStatement:
    """Read a bank CSV export with automatic header and column detection."""
    return import_table(load_table(path), path.name)


def load_table(path: Path) -> CsvTable:
    """Read and decode a CSV file (for the manual mapping dialog)."""
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise StatementParseError(f"cannot read {path}") from error
    return decode_table(raw)


def decode_table(raw: bytes) -> CsvTable:
    """Decode bytes with the first fitting encoding and the best delimiter.

    Delimiters are tried from the most consistent column count down; the first one under which
    a header row can be found wins (balance lines in a preamble can make the wrong delimiter
    look consistent). Without any header the most consistent delimiter is kept.
    """
    text, encoding = decode_text(raw)
    ranked = _rank_delimiters(text[:SNIFF_SAMPLE_CHARS])
    tables = (CsvTable(_split(text, delimiter), delimiter, encoding) for delimiter in ranked)
    first = next(tables)
    if find_header(first.rows) is not None:
        return first
    return next((table for table in tables if find_header(table.rows) is not None), first)


def find_header(rows: Sequence[Row]) -> int | None:
    """Index of the header row: it names date and amount columns, and one of the next rows
    parses as a booking with that mapping.

    The second condition rejects preamble lines that merely contain keywords, such as ING's
    ``Umsatzanzeige;Datei erstellt am …`` ("umsatz", "date").
    """
    for index, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        mapping = guess_mapping(row)
        if _maps_required(mapping) and _booking_follows(rows, index, mapping):
            return index
    return None


def guess_mapping(header: Row) -> dict[CsvField, int]:
    """Map fields to columns by header keywords; unknown fields are left out."""
    cells = [cell.strip().lower() for cell in header]
    mapping: dict[CsvField, int] = {}
    for field, keywords in FIELD_KEYWORDS.items():
        column = _best_column(cells, keywords, taken=set(mapping.values()))
        if column is not None:
            mapping[field] = column
    return mapping


def import_table(
    table: CsvTable,
    source: str,
    mapping: ColumnMapping | None = None,
    header_row: int | None = None,
) -> ParsedStatement:
    """Turn a table into a statement.

    Without ``mapping`` the header row and columns are detected automatically; with it, rows
    after ``header_row`` (or all rows if ``None``) are read with the given mapping.
    """
    if mapping is None:
        header_row = find_header(table.rows)
        if header_row is None:
            raise CsvMappingError("no header row with date and amount columns found")
        mapping = guess_mapping(table.rows[header_row])
    first_data_row = 0 if header_row is None else header_row + 1
    iban = find_iban(table.rows[:first_data_row])
    return parse_rows(table.rows, mapping, source, first_data_row, iban)


def find_iban(rows: Sequence[Row]) -> str:
    """The account's IBAN from the lines above the header (ING writes ``IBAN;DE12 …``), so
    CSV bookings carry the same account as the PDF statements; empty if there is none."""
    for row in rows:
        for cell in row:
            candidate = "".join(cell.split()).upper()
            if is_valid_iban(candidate):
                return candidate
    return ""


def parse_rows(
    rows: Sequence[Row],
    mapping: ColumnMapping,
    source: str,
    first_row: int = 0,
    iban: str = "",
) -> ParsedStatement:
    """Read bookings from ``rows[first_row:]``; rows without a valid date or amount are
    skipped and reported by their index in ``rows``."""
    if not _maps_required(mapping):
        missing = [field for field in REQUIRED_FIELDS if field not in mapping]
        raise CsvMappingError(f"columns not mapped: {', '.join(missing)}")

    data = list(enumerate(rows))[first_row:]
    style = detect_decimal_style(_cell(row, mapping, CsvField.AMOUNT) for _, row in data)
    account = account_from_iban(iban)
    transactions: list[Transaction] = []
    skipped: list[int] = []
    for index, row in data:
        txn = _row_to_transaction(row, mapping, source, style, account)
        if txn is None:
            skipped.append(index)
        else:
            transactions.append(txn)

    total = sum((t.amount for t in transactions), Decimal(0))
    info = StatementInfo(source=source, account=account, iban=iban, total=total)
    return ParsedStatement(info, tuple(transactions), ParseReport(skipped_rows=tuple(skipped)))


def _row_to_transaction(
    row: Row, mapping: ColumnMapping, source: str, style: DecimalStyle, account: str = ""
) -> Transaction | None:
    booking_date = parse_flexible_date(_cell(row, mapping, CsvField.DATE))
    amount = parse_amount(_cell(row, mapping, CsvField.AMOUNT), style)
    if booking_date is None or amount is None:
        return None
    purpose = _cell(row, mapping, CsvField.PURPOSE)
    payee = _cell(row, mapping, CsvField.PAYEE) or purpose[:PAYEE_FALLBACK_CHARS]
    return Transaction(
        booking_date=booking_date,
        booking_type="",
        payee=payee,
        purpose=purpose,
        amount=amount,
        source=source,
        account=account,
    )


def _maps_required(mapping: ColumnMapping) -> bool:
    return all(field in mapping for field in REQUIRED_FIELDS)


def _booking_follows(rows: Sequence[Row], index: int, mapping: ColumnMapping) -> bool:
    probe = rows[index + 1 : index + 1 + HEADER_PROBE_ROWS]
    style = detect_decimal_style(_cell(row, mapping, CsvField.AMOUNT) for row in probe)
    return any(_row_to_transaction(row, mapping, "", style) for row in probe)


def _cell(row: Row, mapping: ColumnMapping, field: CsvField) -> str:
    column = mapping.get(field)
    if column is None or column >= len(row):
        return ""
    return row[column].strip()


def _best_column(cells: Sequence[str], keywords: Sequence[str], taken: set[int]) -> int | None:
    """The free column matched by the most specific keyword; among its matches the best
    quality, then the leftmost column."""
    candidates = [
        (priority, quality, column)
        for priority, keyword in enumerate(keywords)
        for column, cell in enumerate(cells)
        if column not in taken and (quality := _match_quality(cell, keyword)) is not None
    ]
    return min(candidates)[2] if candidates else None


def _match_quality(cell: str, keyword: str) -> _MatchQuality | None:
    if cell == keyword:
        return _MatchQuality.EXACT
    words = _WORD_SPLIT.split(cell)
    if keyword in WHOLE_WORD_KEYWORDS:
        return _MatchQuality.WORD_START if keyword in words else None
    if any(word.startswith(keyword) for word in words):
        return _MatchQuality.WORD_START
    if keyword in cell:
        return _MatchQuality.SUBSTRING
    return None


def _split(text: str, delimiter: str) -> tuple[Row, ...]:
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return tuple(tuple(row) for row in reader if any(cell.strip() for cell in row))


def _rank_delimiters(sample: str) -> list[str]:
    """Delimiters ordered by how many rows they split into one common column count (≥ 2);
    ties keep the order of ``DELIMITERS``."""
    lines = [line for line in sample.splitlines() if line.strip()]
    return sorted(DELIMITERS, key=lambda delimiter: _consistency(lines, delimiter), reverse=True)


def _consistency(lines: Sequence[str], delimiter: str) -> tuple[int, int]:
    """(rows sharing the most common width ≥ 2, that width); (0, 0) if nothing splits."""
    widths = Counter(len(row) for row in csv.reader(lines, delimiter=delimiter))
    candidates = [(count, width) for width, count in widths.items() if width >= MIN_COLUMNS]
    return max(candidates, default=(0, 0))
