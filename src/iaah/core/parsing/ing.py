# Portions adapted from budgets (MIT, © 2026 nikluep) – see LICENSES/budgets-MIT.txt
"""ING-DiBa statement semantics on top of the generic page layout.

This merges the two predecessor parsers: ``layout`` (from budgets) supplies lines and blocks
with bounding boxes; this module (from the legacy I-Aah parser, head pattern after budgets)
classifies lines, splits heads into booking type and payee, and reads the statement metadata.
``read_statement`` is the only function that touches the file system.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Final

import pdfplumber
from pdfplumber.utils.exceptions import PdfminerException

from iaah.core.errors import StatementParseError
from iaah.core.models import Placement, Region, StatementInfo, Transaction
from iaah.core.parsing.diagnostics import ParsedStatement, ParseReport
from iaah.core.parsing.layout import (
    Block,
    Line,
    LineDiagnosis,
    LineKind,
    LineStatus,
    Word,
    group_lines_into_blocks,
    group_words_into_lines,
)
from iaah.core.text import (
    BROKEN_UMLAUT,
    normalize_text,
    parse_german_amount,
    parse_german_date,
)

# Measured on real ING statements: the default word tolerance glues the purpose lines
# together ("NRXXXX0010HANNOVER"); a font-relative tolerance keeps their spaces.
WORD_X_TOLERANCE_RATIO: Final = 0.15

# Measured on real ING statements (A4): every booking head ends at the right-aligned amount
# column (x1 ≈ 553 pt), purpose lines that happen to end in a number stop far left of it.
AMOUNT_COLUMN_MIN_X1: Final = 540.0
# Date in front and something amount-like at the end, valid or not. A head *without* amount
# cannot be told apart from a purpose line that starts with its value date ("01.03.2026 Gehalt
# März"), so only this shape – reaching the amount column – counts as an unreadable head.
HEAD_SHAPE: Final = re.compile(r"^\d{2}\.\d{2}\.\d{4}\s+.+\s+-?\d[\d.]*,\d+$")
# The closing balance ends the list of bookings; nothing after it belongs to a booking.
END_PREFIXES: Final = ("Neuer Saldo",)
HEAD_PATTERN: Final = re.compile(
    r"^(?P<date>\d{2}\.\d{2}\.\d{4})\s+(?P<text>.+?)\s+"
    r"(?P<amount>-?(?:\d{1,3}(?:\.\d{3})+|\d+),\d{2})$"
)
SUSPICIOUS_PATTERN: Final = re.compile(r"^\d{2}\.\d{2}\.\d{2,4}\b.*\d,\d{2}\b")
VALUTA_PREFIX: Final = re.compile(r"^\d{2}\.\d{2}\.\d{4}(?:\s+|$)")

PERIOD_PATTERN: Final = re.compile(r"Kontoauszug\s+(?P<month>\S+)\s+(?P<year>\d{4})")
OPENING_PATTERN: Final = re.compile(r"Alter Saldo\s+(?P<amount>-?[\d.]+,\d{2})")
CLOSING_PATTERN: Final = re.compile(r"Neuer Saldo\s+(?P<amount>-?[\d.]+,\d{2})")
ACCOUNT_PATTERN: Final = re.compile(r"Nummer\s+(?P<account>\d{6,})")
IBAN_LABEL: Final = re.compile(r"\bIBAN:?\s+(?P<rest>.+)$")
IBAN_SHAPE: Final = re.compile(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}")
IBAN_MAX_LENGTH: Final = 34
IBAN_MODULUS: Final = 97
IBAN_CHECK_REMAINDER: Final = 1
IBAN_COUNTRY_AND_CHECK: Final = 4
BASE36: Final = 36
ACCOUNT_DIGITS_IN_IBAN: Final = 10

# Booking types as printed by ING; longest first so "Gehalt/Rente" wins over "Gehalt".
BOOKING_TYPES: Final = tuple(
    sorted(
        (
            "Lastschrift", "Gutschrift", "Gutschrift/Dauerauftrag", "Gehalt/Rente", "Gehalt",
            "Rente", "Ueberweisung", "Überweisung",
            "Echtzeitüberweisung", f"Echtzeit{BROKEN_UMLAUT}berweisung",
            "Dauerauftrag", "Kartenzahlung", "Bargeldauszahlung", "Entgelt", "Zinsen", "Storno",
        ),
        key=len,
        reverse=True,
    )
)  # fmt: skip

# Page header and footer lines that are never part of a booking.
NOISE_PREFIXES: Final = (
    "ING-DiBa", "Seite ", "Datum ", "Auszugsnummer", "Alter Saldo", "Einger", "IBAN ",
    "BIC ", "Girokonto Nummer", "Kontoauszug ", "Buchung Buchung", "Valuta",
    "Kunden-Information", "Steuernummer", "Vorsitzende", "Michael Cl",
)  # fmt: skip

MONTHS: Final[dict[str, int]] = {
    "januar": 1, "februar": 2, "maerz": 3, f"m{BROKEN_UMLAUT}rz": 3, "april": 4,
    "mai": 5, "juni": 6, "juli": 7, "august": 8, "september": 9, "oktober": 10,
    "november": 11, "dezember": 12,
}  # fmt: skip


@dataclass(frozen=True, slots=True)
class _Head:
    booking_date: date
    text: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class _Metadata:
    period: str
    account: str
    iban: str
    opening_balance: Decimal | None
    closing_balance: Decimal | None


def read_statement(path: Path) -> ParsedStatement:
    """Read an ING statement PDF. Raises ``StatementParseError`` if it is no readable PDF."""
    try:
        with pdfplumber.open(path) as pdf:
            pages = [_page_words(page) for page in pdf.pages]
    except (OSError, PdfminerException) as error:
        raise StatementParseError(f"cannot read {path}") from error
    return parse_statement_pages(pages, path.name)


def parse_statement_pages(pages: Sequence[Sequence[Word]], source: str) -> ParsedStatement:
    """Turn the words of each page (page 1 first) into a parsed statement."""
    page_lines = [group_words_into_lines(words, number) for number, words in enumerate(pages, 1)]
    lines = [line for page in page_lines for line in page.lines]
    metadata = _read_metadata([line.text for line in lines])
    grouping = group_lines_into_blocks(lines, classify_line)
    transactions = tuple(_to_transaction(b, source, metadata.account) for b in grouping.blocks)

    info = StatementInfo(
        source=source,
        account=metadata.account,
        iban=metadata.iban,
        period=metadata.period,
        opening_balance=metadata.opening_balance,
        closing_balance=metadata.closing_balance,
        total=sum((txn.amount for txn in transactions), Decimal(0)),
    )
    report = ParseReport(
        lines=grouping.diagnoses,
        dropped_words=sum(page.dropped_words for page in page_lines),
        suspicious=tuple(d for d in grouping.diagnoses if _is_suspicious(d)),
    )
    return ParsedStatement(info, transactions, report)


def classify_line(line: Line) -> LineKind:
    """Classify one line of an ING statement."""
    text = line.text.strip()
    if text.startswith(END_PREFIXES):
        return LineKind.END
    if text.startswith(NOISE_PREFIXES):
        return LineKind.NOISE
    if line.x1 < AMOUNT_COLUMN_MIN_X1:
        return LineKind.TEXT
    if _parse_head(text) is not None:
        return LineKind.HEAD
    if HEAD_SHAPE.match(text):
        return LineKind.BAD_HEAD
    return LineKind.TEXT


def split_booking_type(text: str) -> tuple[str, str]:
    """Split a head text into booking type and payee.

    A known type must be followed by a space (or end the text). Unknown types fall back to the
    first word, as in the legacy parser – this keeps payees, and with them the keys of existing
    manual assignments, unchanged.
    """
    for booking_type in BOOKING_TYPES:
        if text == booking_type:
            return booking_type, text
        if text.startswith(f"{booking_type} "):
            return booking_type, text[len(booking_type) :].strip()
    first, _, rest = text.partition(" ")
    if not rest:
        return "", text
    return first, rest.strip()


def is_valid_iban(candidate: str) -> bool:
    """ISO 13616 check: shape plus mod-97 checksum."""
    if not IBAN_SHAPE.fullmatch(candidate):
        return False
    rearranged = candidate[IBAN_COUNTRY_AND_CHECK:] + candidate[:IBAN_COUNTRY_AND_CHECK]
    digits = "".join(str(int(char, BASE36)) for char in rearranged)
    return int(digits) % IBAN_MODULUS == IBAN_CHECK_REMAINDER


def account_from_iban(iban: str) -> str:
    """The account number inside a German IBAN (its last ten digits) – the account a
    statement shows when it prints no separate number; empty without IBAN."""
    return iban[-ACCOUNT_DIGITS_IN_IBAN:]


def _page_words(page: pdfplumber.page.Page) -> list[Word]:
    raw_words = page.extract_words(x_tolerance_ratio=WORD_X_TOLERANCE_RATIO)
    return [Word.from_pdfplumber(raw) for raw in raw_words]


def _parse_head(text: str) -> _Head | None:
    match = HEAD_PATTERN.match(text)
    if match is None:
        return None
    try:
        booking_date = parse_german_date(match["date"])
    except ValueError:
        return None
    return _Head(booking_date, match["text"].strip(), parse_german_amount(match["amount"]))


def _to_transaction(block: Block, source: str, account: str) -> Transaction:
    head = _parse_head(block.head.text.strip())
    if head is None:  # cannot happen: blocks only start at lines classified as HEAD
        raise StatementParseError(f"block without a valid head line: {block.head.text!r}")
    booking_type, payee = split_booking_type(head.text)
    purpose_parts = (VALUTA_PREFIX.sub("", line.text).strip() for line in block.details)
    head_region = Region(block.head.page, block.head.bbox)
    return Transaction(
        booking_date=head.booking_date,
        booking_type=booking_type,
        payee=payee,
        purpose=" ".join(part for part in purpose_parts if part),
        amount=head.amount,
        source=source,
        account=account,
        placement=Placement(head_region, block.detail_regions),
    )


def _is_suspicious(diagnosis: LineDiagnosis) -> bool:
    if diagnosis.status in (LineStatus.HEAD, LineStatus.BAD_HEAD):
        return False
    return SUSPICIOUS_PATTERN.match(diagnosis.line.text) is not None


def _read_metadata(lines: Sequence[str]) -> _Metadata:
    iban = _read_iban(lines)
    account = _first_group(ACCOUNT_PATTERN, lines, "account") or account_from_iban(iban)
    return _Metadata(
        period=_read_period(lines),
        account=account,
        iban=iban,
        opening_balance=_read_amount(OPENING_PATTERN, lines),
        closing_balance=_read_amount(CLOSING_PATTERN, lines),
    )


def _read_iban(lines: Sequence[str]) -> str:
    for line in lines:
        match = IBAN_LABEL.search(line)
        iban = _longest_valid_iban(match["rest"]) if match else None
        if iban:
            return iban
    return ""


def _longest_valid_iban(text: str) -> str | None:
    """IBANs are printed in groups of four; join groups while the result could be an IBAN."""
    candidate = ""
    best: str | None = None
    for group in text.split():
        candidate += group
        if len(candidate) > IBAN_MAX_LENGTH:
            break
        if is_valid_iban(candidate):
            best = candidate
    return best


def _read_period(lines: Sequence[str]) -> str:
    for line in lines:
        match = PERIOD_PATTERN.search(line)
        month = MONTHS.get(normalize_text(match["month"])) if match else None
        if match and month:
            return f"{match['year']}-{month:02d}"
    return ""


def _read_amount(pattern: re.Pattern[str], lines: Sequence[str]) -> Decimal | None:
    raw = _first_group(pattern, lines, "amount")
    return parse_german_amount(raw) if raw else None


def _first_group(pattern: re.Pattern[str], lines: Sequence[str], group: str) -> str | None:
    for line in lines:
        match = pattern.search(line)
        if match:
            return match[group]
    return None
