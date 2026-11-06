"""ING statement semantics on synthetic pages (no real statement data)."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Final

import pytest

from iaah.core.errors import StatementParseError
from iaah.core.parsing.diagnostics import ParsedStatement
from iaah.core.parsing.ing import (
    classify_line,
    is_valid_iban,
    parse_statement_pages,
    read_statement,
    split_booking_type,
)
from iaah.core.parsing.layout import Line, LineKind, LineStatus, Word
from iaah.core.text import BROKEN_UMLAUT

CHAR_WIDTH: Final = 5.0
LEFT: Final = 70.0
AMOUNT_RIGHT: Final = 550.0
LINE_HEIGHT: Final = 10.0
# The standard documentation example IBAN (valid checksum, not a real account).
EXAMPLE_IBAN: Final = "DE89 3704 0044 0532 0130 00"


def _words(text: str, x0: float, top: float) -> list[Word]:
    words: list[Word] = []
    for token in text.split():
        width = len(token) * CHAR_WIDTH
        words.append(Word(token, x0, x0 + width, top, top + LINE_HEIGHT))
        x0 += width + CHAR_WIDTH
    return words


def _head(text: str, amount: str, top: float) -> list[Word]:
    amount_x0 = AMOUNT_RIGHT - len(amount) * CHAR_WIDTH
    return _words(text, LEFT, top) + _words(amount, amount_x0, top)


def _page() -> list[Word]:
    return [
        *_words("Girokonto Nummer 5400000001", LEFT, 40),
        *_words("Kontoauszug März 2026", LEFT, 52),
        *_words("Alter Saldo 1.000,00 Euro", 310, 64),
        *_words("Neuer Saldo 1.050,00 Euro", 310, 76),
        *_words(f"IBAN {EXAMPLE_IBAN}", 310, 88),
        *_head("01.03.2026 Gutschrift Arbeitgeber GmbH", "100,00", 120),
        *_words("01.03.2026 Gehalt März", LEFT, 132),
        *_head("02.03.2026 Lastschrift VISA REWE 435 HANNOVER", "-50,00", 160),
        *_words("NR XXXX 0010 KAUFUMSATZ 01.03 50,00", LEFT, 172),
        *_words("Seite 1 von 1", 310, 184),
        *_words("ING-DiBa AG Theodor-Heuss-Allee 2", LEFT, 400),
    ]


def _parse(*pages: list[Word]) -> ParsedStatement:
    return parse_statement_pages(list(pages), "auszug.pdf")


@pytest.fixture
def statement() -> ParsedStatement:
    return _parse(_page())


def test_bookings_are_read(statement: ParsedStatement) -> None:
    income, expense = statement.transactions
    assert (income.booking_date, income.booking_type) == (date(2026, 3, 1), "Gutschrift")
    assert (income.payee, income.purpose) == ("Arbeitgeber GmbH", "Gehalt März")
    assert income.amount == Decimal("100.00")
    assert expense.payee == "VISA REWE 435 HANNOVER"
    assert expense.purpose == "NR XXXX 0010 KAUFUMSATZ 01.03 50,00"
    assert expense.amount == Decimal("-50.00")
    assert {txn.source for txn in statement.transactions} == {"auszug.pdf"}


def test_metadata_and_reconciliation(statement: ParsedStatement) -> None:
    info = statement.info
    assert (info.account, info.period) == ("5400000001", "2026-03")
    assert info.iban == EXAMPLE_IBAN.replace(" ", "")
    assert (info.opening_balance, info.closing_balance) == (Decimal("1000.00"), Decimal("1050.00"))
    assert info.total == Decimal("50.00")
    assert info.reconciles is True


def test_account_falls_back_to_iban_and_bic_is_not_swallowed() -> None:
    page = [*_words(f"IBAN {EXAMPLE_IBAN} BIC INGDDEFFXXX", 310, 88)]
    info = _parse(page).info
    assert info.iban == "DE89370400440532013000"
    assert info.account == "0532013000"


def test_placement_covers_head_and_details(statement: ParsedStatement) -> None:
    placement = statement.transactions[0].placement
    assert placement is not None
    assert placement.head.page == 1
    assert (placement.head.bbox[0], placement.head.bbox[2]) == (LEFT, AMOUNT_RIGHT)
    (details,) = placement.details
    assert details.bbox[1] == 132


def test_every_line_is_diagnosed(statement: ParsedStatement) -> None:
    counts = statement.report.counts()
    assert counts[LineStatus.HEAD] == 2
    assert counts[LineStatus.DETAIL] == 2
    assert counts[LineStatus.NOISE] == 6
    assert counts[LineStatus.END] == 1  # "Neuer Saldo" in the page header
    assert sum(counts.values()) == 11
    assert not statement.report.has_problems


def test_unreadable_booking_is_reported_not_merged() -> None:
    page = [
        *_head("01.03.2026 Lastschrift A", "-1,00", 100),
        *_words("Zweck A", LEFT, 112),
        *_head("02.03.2026 Lastschrift B", "-1,2", 124),
        *_words("Zweck B", LEFT, 136),
    ]
    statement = _parse(page)
    (only,) = statement.transactions
    assert only.purpose == "Zweck A"
    assert len(statement.report.with_status(LineStatus.BAD_HEAD)) == 1
    assert statement.report.has_problems


def test_detail_line_with_date_and_amount_is_suspicious() -> None:
    page = _head("01.03.2026 Lastschrift A", "-1,00", 100) + _words(
        "05.03.2026 Karte B -2,00 Rest", LEFT, 112
    )
    report = _parse(page).report
    assert [d.line.text for d in report.suspicious] == ["05.03.2026 Karte B -2,00 Rest"]


def test_bookings_continue_across_pages_with_global_block_index() -> None:
    page_two = [
        *_words("Seite 2 von 2", 310, 30),
        *_words("Fortsetzung Zweck", LEFT, 50),
        *_head("03.03.2026 Lastschrift Bäcker", "-3,20", 100),
    ]
    statement = _parse(_page(), page_two)
    assert len(statement.transactions) == 3
    assert statement.transactions[1].purpose.endswith("Fortsetzung Zweck")
    assert statement.report.with_status(LineStatus.HEAD)[-1].block == 2
    last = statement.transactions[-1].placement
    assert last is not None
    assert last.head.page == 2


def test_closing_balance_ends_the_booking_list() -> None:
    # Regression from the real statement: customer information on the page after the closing
    # balance was appended to the last booking.
    last_page = [
        *_head("31.03.2026 Lastschrift Letzte", "-9,00", 600),
        *_words("Zweck", LEFT, 612),
        *_words("Neuer Saldo 1.041,00", 310, 624),
    ]
    info_page = [*_words("Freistellungsauftrag 801,00", LEFT, 60)]
    (txn,) = _parse(last_page, info_page).transactions
    assert txn.purpose == "Zweck"
    assert txn.placement is not None
    assert {region.page for region in txn.placement.regions} == {1}


def test_value_dated_purpose_with_amount_stays_purpose() -> None:
    # Does not reach the amount column, so it is neither a head nor an unreadable head.
    page = _head("01.03.2026 Dauerauftrag Vermieter", "-450,00", 100) + _words(
        "01.03.2026 Miete 450,00", LEFT, 112
    )
    statement = _parse(page)
    (txn,) = statement.transactions
    assert txn.purpose == "Miete 450,00"
    assert statement.report.with_status(LineStatus.BAD_HEAD) == ()


def test_bare_valuta_line_is_not_part_of_the_purpose() -> None:
    page = _head("01.03.2026 Lastschrift A", "-1,00", 100) + _words("01.03.2026", LEFT, 112)
    (txn,) = _parse(page).transactions
    assert txn.purpose == ""


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Gehalt/Rente Firma", ("Gehalt/Rente", "Firma")),
        ("Gutschrift/Dauerauftrag Max", ("Gutschrift/Dauerauftrag", "Max")),
        ("Lastschrift VISA REWE", ("Lastschrift", "VISA REWE")),
        (f"Echtzeit{BROKEN_UMLAUT}berweisung Max", (f"Echtzeit{BROKEN_UMLAUT}berweisung", "Max")),
        ("Rentenversicherung X", ("Rentenversicherung", "X")),
        ("Zins/Dividende ING", ("Zins/Dividende", "ING")),
        ("Lastschrift", ("Lastschrift", "Lastschrift")),
        ("Einzelwort", ("", "Einzelwort")),
    ],
)
def test_split_booking_type(text: str, expected: tuple[str, str]) -> None:
    assert split_booking_type(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("01.07.2026 Lastschrift REWE -11,49", LineKind.HEAD),
        ("01.07.2026 Gutschrift Firma 1.234,56", LineKind.HEAD),
        ("01.07.2026 Gutschrift Firma 1234,56", LineKind.HEAD),
        ("31.02.2026 Lastschrift REWE -11,49", LineKind.BAD_HEAD),
        ("01.07.2026 Lastschrift REWE -11,4", LineKind.BAD_HEAD),
        # A value-dated purpose line may start with a booking-type word; it stays text.
        ("01.03.2026 Gehalt März", LineKind.TEXT),
        ("01.07.2026 NR XXXX 0010 KAUFUMSATZ 11.49", LineKind.TEXT),
        ("Mandat: ABC", LineKind.TEXT),
        ("Seite 2 von 6", LineKind.NOISE),
        ("Alter Saldo 15.908,17 Euro", LineKind.NOISE),
        ("Kunden-Information", LineKind.NOISE),
        ("Neuer Saldo 17.196,49 Euro", LineKind.END),
    ],
)
def test_classify_line_reaching_the_amount_column(text: str, expected: LineKind) -> None:
    line = Line(page=1, text=text, x0=LEFT, x1=AMOUNT_RIGHT, top=100, bottom=110)
    assert classify_line(line) is expected


def test_line_ending_left_of_the_amount_column_is_never_a_head() -> None:
    line = Line(page=1, text="01.07.2026 Lastschrift REWE -11,49", x0=LEFT, x1=300, top=0, bottom=1)
    assert classify_line(line) is LineKind.TEXT


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        ("DE89370400440532013000", True),
        ("DE89370400440532013001", False),
        ("DE8937040044053201300", False),
        ("de89370400440532013000", False),
    ],
)
def test_is_valid_iban(candidate: str, expected: bool) -> None:
    assert is_valid_iban(candidate) is expected


def test_unreadable_file_raises(tmp_path: Path) -> None:
    broken = tmp_path / "kaputt.pdf"
    broken.write_bytes(b"not a pdf")
    with pytest.raises(StatementParseError):
        read_statement(broken)
