"""Text normalization, display repair, amount/date parsing and euro formatting."""

from datetime import date
from decimal import Decimal

import pytest

from iaah.core.text import (
    BROKEN_UMLAUT,
    DecimalStyle,
    clean_display,
    decode_text,
    detect_decimal_style,
    format_euro,
    normalize_text,
    parse_amount,
    parse_flexible_date,
    parse_german_amount,
    parse_german_date,
)

GERMAN = DecimalStyle.GERMAN
ENGLISH = DecimalStyle.ENGLISH


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ÜSTRA Hannover", "uestra hannover"),
        ("UESTRA  Hannover", "uestra hannover"),
        ("Straße", "strasse"),
        ("Café  Crème", "cafe creme"),
        ("  REWE\tSAGT   DANKE ", "rewe sagt danke"),
        (f"M{BROKEN_UMLAUT}ller", "mueller"),
        (f"F{BROKEN_UMLAUT}r Dich", "fuer dich"),
    ],
)
def test_normalize_text(raw: str, expected: str) -> None:
    assert normalize_text(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        f"BEITRAG F{BROKEN_UMLAUT}R VEREIN",
        "SØSTRENE GRENE",
        "Straße  ÄRØ",
        f"x{BROKEN_UMLAUT}y",
        "Shop™",  # NFKD produces capitals ("TM")
        "№ 5",
        f"{chr(0x210C)}annover",  # BLACK-LETTER CAPITAL H
    ],
)
def test_normalize_text_is_idempotent(raw: str) -> None:
    once = normalize_text(raw)
    assert normalize_text(once) == once


def test_compatibility_forms_are_lower_case() -> None:
    assert normalize_text("Brand™ Store") == "brandtm store"


def test_broken_umlaut_repair_ignores_letter_case() -> None:
    assert normalize_text(f"BEITRAG F{BROKEN_UMLAUT}R VEREIN") == "beitrag fuer verein"


def test_decode_text_falls_back_to_cp1252() -> None:
    assert decode_text("Bäckerei €".encode("cp1252")) == ("Bäckerei €", "cp1252")
    assert decode_text("﻿Bäckerei".encode()) == ("Bäckerei", "utf-8-sig")


def test_clean_display_repairs_known_words_only() -> None:
    assert clean_display(f"Echtzeit{BROKEN_UMLAUT}berweisung") == "Echtzeitüberweisung"
    assert clean_display(f"Unbekannt{BROKEN_UMLAUT}") == f"Unbekannt{BROKEN_UMLAUT}"


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (Decimal("-1234.5"), "-1.234,50 €"),
        (Decimal("0"), "0,00 €"),
        (Decimal("1288.32"), "1.288,32 €"),
        (Decimal("-0.001"), "0,00 €"),
        (Decimal("1234567.891"), "1.234.567,89 €"),
    ],
)
def test_format_euro(amount: Decimal, expected: str) -> None:
    assert format_euro(amount) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("-85,32", Decimal("-85.32")),
        ("1.234,56", Decimal("1234.56")),
        ("-1.234,56 €", Decimal("-1234.56")),
        ("+12,00", Decimal("12.00")),
        ("0,00", Decimal("0.00")),
    ],
)
def test_parse_german_amount(raw: str, expected: Decimal) -> None:
    assert parse_german_amount(raw) == expected


@pytest.mark.parametrize("raw", ["", "12.34", "1,2", "abc", "1.23,45"])
def test_parse_german_amount_rejects(raw: str) -> None:
    with pytest.raises(ValueError, match="not a German amount"):
        parse_german_amount(raw)


@pytest.mark.parametrize(
    ("raw", "style", "expected"),
    [
        ("-12,34", GERMAN, Decimal("-12.34")),
        ("12,34-", GERMAN, Decimal("-12.34")),
        ("1.234,56", GERMAN, Decimal("1234.56")),
        ("2.000 €", GERMAN, Decimal("2000")),
        ("-1.234", GERMAN, Decimal("-1234")),
        ("1 234,56 EUR", GERMAN, Decimal("1234.56")),
        ("1,234.56", ENGLISH, Decimal("1234.56")),
        ("12.5", ENGLISH, Decimal("12.5")),
        ("2,000", ENGLISH, Decimal("2000")),
    ],
)
def test_parse_amount(raw: str, style: DecimalStyle, expected: Decimal) -> None:
    assert parse_amount(raw, style) == expected


@pytest.mark.parametrize(
    ("raw", "style"),
    [
        ("", GERMAN),
        ("abc", GERMAN),
        ("nan", GERMAN),
        ("Infinity", GERMAN),
        ("1e5", GERMAN),
        ("1.2.3", GERMAN),
        ("12.5", GERMAN),
        ("1,234.56", GERMAN),
        ("1.234,56", ENGLISH),
        ("12,345", GERMAN),  # at most two decimals
        ("-12-", GERMAN),  # sign on both sides
        ("+12-", GERMAN),
    ],
)
def test_parse_amount_rejects(raw: str, style: DecimalStyle) -> None:
    assert parse_amount(raw, style) is None


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["", "2.000", "-12,34"], GERMAN),
        (["1,234.56", "-3.5"], ENGLISH),
        (["2.000", "1.500"], GERMAN),
        (["2,000", "15,000"], ENGLISH),  # whole English thousands
        (["2,000", "1,50"], GERMAN),  # a decimal tail beats thousands groups
        (["12,34-"], GERMAN),
        (["12"], GERMAN),
        ([], GERMAN),
    ],
)
def test_detect_decimal_style(values: list[str], expected: DecimalStyle) -> None:
    assert detect_decimal_style(values) is expected


@pytest.mark.parametrize("raw", ["14.03.2026", "14.03.26"])
def test_parse_german_date(raw: str) -> None:
    assert parse_german_date(raw) == date(2026, 3, 14)


def test_parse_german_date_rejects() -> None:
    with pytest.raises(ValueError, match="not a German date"):
        parse_german_date("31.02.2026")


@pytest.mark.parametrize("raw", ["14.03.2026", "2026-03-14", "14/03/2026", "14-03-2026"])
def test_parse_flexible_date(raw: str) -> None:
    assert parse_flexible_date(raw) == date(2026, 3, 14)


def test_parse_flexible_date_rejects() -> None:
    assert parse_flexible_date("März") is None
