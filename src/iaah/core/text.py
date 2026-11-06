"""Text, amount and date helpers for German bank data.

``normalize_text`` folds text for *matching*; ``clean_display`` repairs text for *showing*.
"""

import functools
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
NORMALIZE_CACHE_SIZE: Final = 1 << 16  # distinct texts kept; a few years of bookings fit


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
_BROKEN_UMLAUTS_FOLDED: Final = {
    broken.lower(): fixed.lower() for broken, fixed in _BROKEN_UMLAUTS.items()
}

# Encodings of German bank and Excel exports, tried in order; latin-1 never fails.
TEXT_ENCODINGS: Final = ("utf-8-sig", "cp1252", "latin-1")

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


@functools.lru_cache(maxsize=NORMALIZE_CACHE_SIZE)
def normalize_text(text: str) -> str:
    """Fold text for keyword matching and keys. Idempotent, and cached: the same payees and
    purposes are folded again and again while categorizing.

    Lower case first, then known broken umlauts repaired (in any letter case), German umlauts
    transliterated the way banks print them (``ü`` → ``ue``, ``ß`` → ``ss``), compatibility
    forms decomposed and accents removed (``™`` → ``tm``), lower case again – decomposition can
    produce capitals –, and whitespace collapsed.
    """
    folded = text.lower()
    for broken, fixed in _BROKEN_UMLAUTS_FOLDED.items():
        folded = folded.replace(broken, fixed)
    decomposed = unicodedata.normalize("NFKD", folded.translate(_TRANSLITERATION))
    unaccented = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _WHITESPACE.sub(" ", unaccented.lower()).strip()


def decode_text(raw: bytes) -> tuple[str, str]:
    """Decode bytes with the first fitting encoding; returns text and encoding name."""
    for encoding in TEXT_ENCODINGS:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise AssertionError("unreachable: latin-1 decodes any byte sequence")


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


def is_whole_cents(amount: Decimal) -> bool:
    """Whether ``amount`` is a finite amount without fractions of a cent (and not so large
    that it cannot be represented in cents)."""
    if not amount.is_finite():
        return False
    try:
        return amount == amount.quantize(CENT)
    except InvalidOperation:  # more digits than the decimal context can hold
        return False


def format_plain_german(amount: Decimal) -> str:
    """Two decimals with a decimal comma and no grouping (``"-1234,50"``) – for CSV cells,
    which spreadsheets must read as numbers."""
    return f"{amount.quantize(CENT)}".replace(DOT, COMMA)


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
