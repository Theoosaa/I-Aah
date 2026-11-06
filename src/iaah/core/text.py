"""Text, amount and date helpers for German bank data.

``normalize_text`` folds text for *matching*; ``clean_display`` repairs text for *showing*.
"""

import re
import unicodedata
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Final

CENT: Final = Decimal("0.01")
MINUS: Final = "-"
COMMA: Final = ","
DOT: Final = "."
# The ING statement font renders some umlauts as U+FFFD REPLACEMENT CHARACTER.
BROKEN_UMLAUT: Final = chr(0xFFFD)
NO_BREAK_SPACE: Final = chr(0xA0)
MAX_DECIMAL_DIGITS: Final = 2


class DecimalStyle(StrEnum):
    """Which separator marks the decimals of an amount."""

    GERMAN = "german"  # 1.234,56
    ENGLISH = "english"  # 1,234.56


_TRANSLITERATION: Final = str.maketrans(
    {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"}
)
_ENGLISH_TO_GERMAN_SEPARATORS: Final = str.maketrans({COMMA: DOT, DOT: COMMA})
_WHITESPACE: Final = re.compile(r"\s+")
_CURRENCY_MARKERS: Final = ("€", "EUR", NO_BREAK_SPACE, " ")

# Only these known words are repaired, so an unknown broken umlaut is never replaced by a
# wrong guess.
_BROKEN_UMLAUTS: Final[dict[str, str]] = {
    f"Echtzeit{BROKEN_UMLAUT}berweisung": "Echtzeitüberweisung",
    f"{BROKEN_UMLAUT}berweisung": "Überweisung",
    f"f{BROKEN_UMLAUT}r": "für",
    f"F{BROKEN_UMLAUT}r": "Für",
    f"Geb{BROKEN_UMLAUT}hr": "Gebühr",
    f"zur{BROKEN_UMLAUT}ck": "zurück",
    f"R{BROKEN_UMLAUT}ck": "Rück",
    f"verg{BROKEN_UMLAUT}tung": "vergütung",
    f"M{BROKEN_UMLAUT}ller": "Müller",
    f"K{BROKEN_UMLAUT}ln": "Köln",
    f"M{BROKEN_UMLAUT}nchen": "München",
    f"Gesch{BROKEN_UMLAUT}ft": "Geschäft",
    f"H{BROKEN_UMLAUT}ndler": "Händler",
    f"Geb{BROKEN_UMLAUT}ude": "Gebäude",
}

_GERMAN_AMOUNT: Final = re.compile(
    r"^(?P<sign>[+-]?)(?P<units>\d{1,3}(?:\.\d{3})*|\d+),(?P<cents>\d{2})$"
)
# Strict digit layouts per style: grouped or plain units, at most two decimals.
_NUMBER_LAYOUTS: Final[dict[DecimalStyle, re.Pattern[str]]] = {
    DecimalStyle.GERMAN: re.compile(r"^(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2})?$"),
    DecimalStyle.ENGLISH: re.compile(r"^(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?$"),
}
# A sign may stand in front or behind the number, not both.
_SIGNED: Final = re.compile(r"^(?P<lead>[+-]?)(?P<number>[\d.,]+)(?P<trail>[+-]?)$")
_DECIMAL_TAIL: Final = re.compile(r"(?P<separator>[.,])(?P<digits>\d+)[+-]?$")
# Whole numbers with a thousands group only: "2,000" is English, "2.000" German.
_THOUSANDS_ONLY: Final = re.compile(
    r"^[+-]?\d{1,3}(?P<separator>[.,])\d{3}(?:(?P=separator)\d{3})*[+-]?$"
)
_GERMAN_DATE_FORMATS: Final = ("%d.%m.%Y", "%d.%m.%y")
_FLEXIBLE_DATE_FORMATS: Final = (*_GERMAN_DATE_FORMATS, "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y")


def normalize_text(text: str) -> str:
    """Fold text for keyword matching and keys.

    Known broken umlauts are repaired first; then lower case, German umlauts transliterated
    the way banks print them (``ü`` → ``ue``, ``ß`` → ``ss``), other accents removed and
    whitespace collapsed.
    """
    transliterated = clean_display(text).translate(_TRANSLITERATION)
    decomposed = unicodedata.normalize("NFKD", transliterated)
    unaccented = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _WHITESPACE.sub(" ", unaccented).strip().lower()


def clean_display(text: str) -> str:
    """Repair umlauts that the ING statement font breaks."""
    for broken, fixed in _BROKEN_UMLAUTS.items():
        text = text.replace(broken, fixed)
    return text


def format_euro(amount: Decimal) -> str:
    """Format an amount the German way, e.g. ``Decimal("-1234.5")`` → ``"-1.234,50 €"``."""
    rounded = amount.quantize(CENT)
    german = f"{abs(rounded):,.2f}".translate(_ENGLISH_TO_GERMAN_SEPARATORS)
    sign = MINUS if rounded < 0 else ""
    return f"{sign}{german} €"


def parse_german_amount(raw: str) -> Decimal:
    """Parse a German amount such as ``"-1.234,56 €"``; raise ``ValueError`` otherwise."""
    match = _GERMAN_AMOUNT.match(_strip_currency(raw))
    if match is None:
        raise ValueError(f"not a German amount: {raw!r}")
    value = Decimal(f"{match['units'].replace(DOT, '')}{DOT}{match['cents']}")
    return -value if match["sign"] == MINUS else value


def detect_decimal_style(values: Iterable[str]) -> DecimalStyle:
    """Guess the style of a column of amounts.

    A value ending in a separator plus one or two digits decides. Otherwise a whole number
    with thousands groups decides (``"2,000"`` English, ``"2.000"`` German). Without any
    evidence the column is German, as German banks write it.
    """
    cleaned = [_strip_currency(value) for value in values]
    for value in cleaned:
        tail = _DECIMAL_TAIL.search(value)
        if tail and len(tail["digits"]) <= MAX_DECIMAL_DIGITS:
            return _style_of_decimal_separator(tail["separator"])
    for value in cleaned:
        grouped = _THOUSANDS_ONLY.match(value)
        if grouped:
            return _style_of_decimal_separator(DOT if grouped["separator"] == COMMA else COMMA)
    return DecimalStyle.GERMAN


def parse_amount(raw: str, style: DecimalStyle = DecimalStyle.GERMAN) -> Decimal | None:
    """Parse an amount in ``style`` with a sign in front or behind; ``None`` if invalid."""
    signed = _SIGNED.match(_strip_currency(raw))
    if signed is None or (signed["lead"] and signed["trail"]):
        return None
    number = signed["number"]
    if not _NUMBER_LAYOUTS[style].match(number):
        return None
    thousands, decimal = (DOT, COMMA) if style is DecimalStyle.GERMAN else (COMMA, DOT)
    try:
        value = Decimal(number.replace(thousands, "").replace(decimal, DOT))
    except InvalidOperation:
        return None
    return -value if MINUS in (signed["lead"], signed["trail"]) else value


def parse_german_date(raw: str) -> date:
    """Parse ``DD.MM.YYYY`` or ``DD.MM.YY``; raise ``ValueError`` otherwise."""
    parsed = _parse_date(raw, _GERMAN_DATE_FORMATS)
    if parsed is None:
        raise ValueError(f"not a German date: {raw!r}")
    return parsed


def parse_flexible_date(raw: str) -> date | None:
    """Parse the date formats found in bank CSV exports, or return ``None``."""
    return _parse_date(raw, _FLEXIBLE_DATE_FORMATS)


def _style_of_decimal_separator(separator: str) -> DecimalStyle:
    return DecimalStyle.GERMAN if separator == COMMA else DecimalStyle.ENGLISH


def _strip_currency(raw: str) -> str:
    cleaned = raw.strip()
    for marker in _CURRENCY_MARKERS:
        cleaned = cleaned.replace(marker, "")
    return cleaned


def _parse_date(raw: str, formats: tuple[str, ...]) -> date | None:
    text = raw.strip()
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None
