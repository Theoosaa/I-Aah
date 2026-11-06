"""One-way import of the legacy app's ``settings.json`` and ``data.json`` (I-Aah 3).

The legacy files are only read, never changed. ``migrate`` is pure (dicts in, catalog +
library + report out); ``read_legacy`` is the thin file wrapper. The report lists everything
that could not be carried over, and every booking whose automatic category differs from
before – matching moved from uppercase substrings to normalized token starts.

Offer the migration only while the new app holds no data (``DataStore.has_data``): it builds
a fresh library and does not merge into an existing one.
"""

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

from iaah.core.assignments import (
    Assignment,
    Categorizer,
    ManualAssignments,
    SplitPart,
    validate_split,
)
from iaah.core.categories import (
    FALLBACK_KINDS,
    PALETTE,
    UNKNOWN_COLOR,
    Category,
    CategoryCatalog,
    CategoryKind,
    CategoryRole,
    normalize_keyword,
)
from iaah.core.category_io import with_fallbacks
from iaah.core.crypto import Cipher, is_encrypted, unlock
from iaah.core.errors import CategoryError, PasswordRequiredError, SplitError, StorageError
from iaah.core.library import Library, StoredStatement
from iaah.core.models import StatementInfo, Transaction
from iaah.core.parsing.ing import BOOKING_TYPES, split_booking_type
from iaah.core.text import CENT, normalize_text

SETTINGS_FILE: Final = "settings.json"
DATA_FILE: Final = "data.json"
ENCODING: Final = "utf-8"

# Field names of the legacy files (German, as the legacy app wrote them).
L_CATEGORIES: Final = "categories"
L_RULES: Final = "rules"
L_BUDGETS: Final = "budgets"
L_OVERRIDES: Final = "overrides"
L_TRANSACTIONS: Final = "transactions"
L_STATEMENTS: Final = "statements"
L_NAME: Final = "name"
L_COLOR: Final = "color"
L_EXCLUDE: Final = "exclude"
L_KEYWORD: Final = "keyword"
L_CATEGORY: Final = "category"
L_REGEX: Final = "regex"
L_MIN: Final = "min"
L_MAX: Final = "max"
L_DATE: Final = "datum"
L_TYPE: Final = "buchungsart"
L_PAYEE: Final = "empfaenger"
L_PURPOSE: Final = "zweck"
L_AMOUNT: Final = "betrag"
L_SOURCE: Final = "quelle"
L_ACCOUNT: Final = "konto"
L_IBAN: Final = "iban"
L_PERIOD: Final = "monat"
L_OPENING: Final = "alter_saldo"
L_CLOSING: Final = "neuer_saldo"

LEGACY_UNASSIGNED: Final = "Nicht zugeordnet"
LEGACY_INCOME: Final = "Einkommen"
LEGACY_OTHER: Final = "Sonstiges"
LEGACY_KEY_SEPARATOR: Final = "|"
KEY_PARTS: Final = 3
KEY_AMOUNT_PART: Final = 1
PAYEE_GLUE: Final = "/"  # legacy payee "/Dauerauftrag X" was glued to its booking type
SPACE: Final = " "
# Second halves of compound booking types ("/Dauerauftrag", "/Rente").
GLUED_TYPE_ENDS: Final = tuple(
    booking_type[booking_type.index(PAYEE_GLUE) :]
    for booking_type in BOOKING_TYPES
    if PAYEE_GLUE in booking_type
)
NO_COLOR: Final = ""  # placeholder until free palette colors are handed out
LEGACY_ROLES: Final[dict[str, CategoryRole]] = {
    LEGACY_INCOME: CategoryRole.INCOME_FALLBACK,
    LEGACY_OTHER: CategoryRole.EXPENSE_FALLBACK,
}
# Legacy default names whose counterpart in the new default catalog is spelled differently;
# used to take over the default's color and keywords (the user's name is kept).
LEGACY_NAME_ALIASES: Final[dict[str, str]] = {
    "Miete & Wohnen": "Wohnen",
    "Restaurant/Cafe": "Restaurant & Café",
    "Sparen/Anlage": "Sparen & Anlage",
}
# Colors the legacy app assigned by default; a category still having its default color gets
# the new pastel color instead (a color the user picked is kept).
LEGACY_DEFAULT_COLORS: Final[dict[str, str]] = {
    "Einkommen": "#2e7d32", "Miete & Wohnen": "#6d4c41", "Lebensmittel": "#43a047",
    "Restaurant/Cafe": "#fb8c00", "Transport": "#1e88e5", "Versicherung": "#8e24aa",
    "Abonnements": "#d81b60", "Freizeit": "#00acc1", "Shopping": "#5e35b1",
    "Gesundheit": "#e53935", "Bargeld": "#757575", "Sparen/Anlage": "#00897b",
    "Sonstiges": "#546e7a", "Nicht zugeordnet": "#bdbdbd",
}  # fmt: skip
_HEX_COLOR: Final = re.compile(r"#[0-9a-fA-F]{6}")


class DropReason(StrEnum):
    """Why something could not be carried over (or only partly)."""

    UNKNOWN_CATEGORY = "unknown_category"
    UNASSIGNED = "unassigned"  # pointed to "Nicht zugeordnet", which no longer exists
    REGEX = "regex"  # a real regular expression; keywords are plain text now
    AMOUNT_BOUNDS = "amount_bounds"  # kept as keyword, but without its amount limits
    EMPTY = "empty"
    CONFLICT = "conflict"  # keyword already claimed by an earlier rule
    INVALID_SPLIT = "invalid_split"


@dataclass(frozen=True, slots=True)
class DroppedItem:
    """A rule or decision that was dropped or changed, for the report."""

    what: str  # keyword or legacy booking key
    category: str  # empty for splits
    reason: DropReason


@dataclass(frozen=True, slots=True)
class ChangedBooking:
    """A booking whose automatic category differs from the legacy app's."""

    transaction: Transaction
    before: str  # may be "Nicht zugeordnet", which no longer exists
    after: str


@dataclass(slots=True)
class MigrationReport:
    """What the migration did."""

    categories: int = 0
    keywords: int = 0
    assignments: int = 0
    transactions: int = 0
    statements: int = 0
    dropped: list[DroppedItem] = field(default_factory=list)
    changed: list[ChangedBooking] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Migration:
    """The result: the new catalog and library, plus the report."""

    catalog: CategoryCatalog
    library: Library
    report: MigrationReport


@dataclass(frozen=True, slots=True)
class LegacyData:
    """The legacy files' content; ``cipher`` is set if ``data.json`` was encrypted. Nothing of
    it shows in ``repr`` (log lines)."""

    settings: Mapping[str, Any] | None = field(repr=False)
    data: Mapping[str, Any] | None = field(repr=False)
    cipher: Cipher | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class _Rule:
    keyword: str
    category: str
    regex: bool
    minimum: Decimal | None
    maximum: Decimal | None


@dataclass(frozen=True, slots=True)
class _LegacyBooking:
    entry: Mapping[str, Any]
    transaction: Transaction


# -- files ------------------------------------------------------------------------------------


def has_legacy_files(directory: Path) -> bool:
    """Whether ``directory`` holds a legacy ``settings.json`` or ``data.json``."""
    return (directory / SETTINGS_FILE).exists() or (directory / DATA_FILE).exists()


def read_legacy(directory: Path, password: str | None = None) -> LegacyData:
    """Read the legacy files; an encrypted ``data.json`` needs ``password``."""
    settings_blob = _read_bytes(directory / SETTINGS_FILE)  # never encrypted
    settings = _parse_json(settings_blob, SETTINGS_FILE) if settings_blob else None
    blob = _read_bytes(directory / DATA_FILE)
    if blob is None or not is_encrypted(blob):
        return LegacyData(settings, _parse_json(blob, DATA_FILE) if blob else None)
    if password is None:
        raise PasswordRequiredError("legacy data.json is encrypted")
    content, cipher = unlock(blob, password)
    return LegacyData(settings, _parse_json(content, DATA_FILE), cipher)


def _read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes() if path.exists() else None
    except OSError as error:
        raise StorageError(f"cannot read {path}") from error


def _parse_json(blob: bytes, name: str) -> Mapping[str, Any]:
    try:
        data = json.loads(blob.decode(ENCODING))
    except (ValueError, RecursionError) as error:  # incl. UnicodeDecodeError, JSONDecodeError
        raise StorageError(f"legacy {name} is damaged") from error
    if not isinstance(data, dict):
        raise StorageError(f"legacy {name} has an unexpected format")
    return data


# -- migration --------------------------------------------------------------------------------


def migrate(legacy: LegacyData, defaults: CategoryCatalog) -> Migration:
    """Turn the legacy data into a catalog and a library (see module docstring)."""
    try:
        return _migrate(legacy.settings or {}, legacy.data or {}, defaults)
    except (KeyError, TypeError, ValueError, InvalidOperation, CategoryError) as error:
        raise StorageError(f"legacy files have an unexpected format: {error}") from error


def _migrate(
    settings: Mapping[str, Any], data: Mapping[str, Any], defaults: CategoryCatalog
) -> Migration:
    report = MigrationReport()
    accounts = _accounts_by_source(data.get(L_STATEMENTS, []))
    bookings = [
        _LegacyBooking(entry, _transaction(entry, accounts))
        for entry in data.get(L_TRANSACTIONS, [])
    ]
    rules = [_rule(entry) for entry in settings.get(L_RULES, [])]
    catalog = _catalog(settings, rules, defaults, report)
    key_map = {_legacy_key(b.entry): b.transaction.key for b in bookings}
    assignments = _assignments(settings.get(L_OVERRIDES, {}), key_map, catalog, report)

    transactions = [booking.transaction for booking in bookings]
    statements = [_statement(entry, transactions) for entry in data.get(L_STATEMENTS, [])]
    report.transactions, report.statements = len(transactions), len(statements)
    report.changed = _changed_bookings(bookings, rules, Categorizer(catalog, assignments))
    return Migration(catalog, Library(statements, transactions, assignments), report)


def _accounts_by_source(statements: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """Account number per statement file; most legacy bookings only carry it on their
    statement, and de-duplication needs it to tell two accounts' identical fees apart."""
    return {str(entry.get(L_SOURCE, "")): str(entry.get(L_ACCOUNT, "")) for entry in statements}


def _transaction(entry: Mapping[str, Any], accounts: Mapping[str, str]) -> Transaction:
    """A legacy booking, its payee re-split like the new parser does, its account taken from
    its statement where the booking has none."""
    booking_type, payee = _resplit(str(entry[L_TYPE]), str(entry[L_PAYEE]))
    source = str(entry.get(L_SOURCE, ""))
    return Transaction(
        booking_date=date.fromisoformat(entry[L_DATE]),
        booking_type=booking_type,
        payee=payee,
        purpose=str(entry.get(L_PURPOSE, "")),
        amount=_money(entry[L_AMOUNT]),
        source=source,
        account=str(entry.get(L_ACCOUNT) or accounts.get(source, "")),
    )


def _resplit(booking_type: str, payee: str) -> tuple[str, str]:
    if not booking_type:
        return booking_type, payee
    glue = "" if payee.startswith(PAYEE_GLUE) else SPACE
    return split_booking_type(f"{booking_type}{glue}{payee}")


def _unglued(payee: str) -> str:
    """A legacy payee without the half of a compound booking type glued to it
    ("/Dauerauftrag X" → "X") – for keys whose booking is gone, so its type is unknown."""
    for glued in GLUED_TYPE_ENDS:
        if payee.startswith(glued + SPACE):
            return payee[len(glued) :].strip()
    return payee


def _legacy_key(entry: Mapping[str, Any]) -> str:
    amount = f"{_money(entry[L_AMOUNT]):.2f}"
    return LEGACY_KEY_SEPARATOR.join((str(entry[L_DATE]), amount, str(entry[L_PAYEE])))


def _statement(entry: Mapping[str, Any], transactions: Sequence[Transaction]) -> StoredStatement:
    source = str(entry.get(L_SOURCE, ""))
    total = sum((txn.amount for txn in transactions if txn.source == source), Decimal(0))
    info = StatementInfo(
        source=source,
        account=str(entry.get(L_ACCOUNT, "")),
        iban=str(entry.get(L_IBAN, "")),
        period=str(entry.get(L_PERIOD, "")),
        opening_balance=_money_or_none(entry.get(L_OPENING)),
        closing_balance=_money_or_none(entry.get(L_CLOSING)),
        total=total,
    )
    return StoredStatement(info)


def _rule(entry: Mapping[str, Any]) -> _Rule:
    return _Rule(
        keyword=str(entry[L_KEYWORD]),
        category=str(entry[L_CATEGORY]),
        regex=bool(entry.get(L_REGEX)),
        minimum=_money_or_none(entry.get(L_MIN)),
        maximum=_money_or_none(entry.get(L_MAX)),
    )


# -- catalog ----------------------------------------------------------------------------------


def _catalog(
    settings: Mapping[str, Any],
    rules: Sequence[_Rule],
    defaults: CategoryCatalog,
    report: MigrationReport,
) -> CategoryCatalog:
    budgets: Mapping[str, Any] = settings.get(L_BUDGETS, {})
    categories = [
        _category(entry, defaults, budgets)
        for entry in settings.get(L_CATEGORIES, [])
        if entry[L_NAME] != LEGACY_UNASSIGNED
    ]
    categories = _with_free_colors(_with_ignored(with_fallbacks(categories, defaults), defaults))
    keywords = _keywords(rules, {category.name for category in categories}, report)
    _add_default_keywords(keywords, categories, defaults)
    catalog = CategoryCatalog(
        replace(category, keywords=tuple(keywords.get(category.name, ())))
        for category in categories
    )
    report.categories = len(catalog)
    report.keywords = sum(len(category.keywords) for category in catalog)
    return catalog


def _category(
    entry: Mapping[str, Any], defaults: CategoryCatalog, budgets: Mapping[str, Any]
) -> Category:
    name = str(entry[L_NAME])
    role = LEGACY_ROLES.get(name)
    if role is not None:
        kind = FALLBACK_KINDS[role]
    else:
        kind = CategoryKind.IGNORED if entry.get(L_EXCLUDE) else CategoryKind.EXPENSE
    budget = budgets.get(name)
    return Category(
        name=name,
        color=_wanted_color(name, str(entry.get(L_COLOR, "")), defaults),
        kind=kind,
        budget=_money(budget) if budget else None,
        role=role,
    )


def _default_name(name: str, defaults: CategoryCatalog) -> str | None:
    """The default category corresponding to a legacy name, if any."""
    for candidate in (name, LEGACY_NAME_ALIASES.get(name, "")):
        if candidate in defaults:
            return candidate
    return None


def _wanted_color(name: str, legacy_color: str, defaults: CategoryCatalog) -> str:
    """Keep a valid color the user picked; an untouched legacy default becomes the default
    catalog's pastel color; otherwise a free color is handed out later."""
    picked = _HEX_COLOR.fullmatch(legacy_color) is not None
    if picked and legacy_color.lower() != LEGACY_DEFAULT_COLORS.get(name, "").lower():
        return legacy_color.lower()
    default_name = _default_name(name, defaults)
    return defaults.color_of(default_name) if default_name else NO_COLOR


def _with_free_colors(categories: list[Category]) -> list[Category]:
    """Give every category without color the next palette color nobody uses."""
    used = {category.color for category in categories}
    result: list[Category] = []
    for category in categories:
        if category.color != NO_COLOR:
            result.append(category)
            continue
        color = next((c for c in PALETTE if c not in used), UNKNOWN_COLOR)
        used.add(color)
        result.append(replace(category, color=color))
    return result


def _with_ignored(categories: list[Category], defaults: CategoryCatalog) -> list[Category]:
    """Without any ignored category, add the default catch-all one(s) – ignored categories
    without keywords ("Ignoriert"), not specialised ones that would duplicate a legacy
    category under another name."""
    if any(category.kind is CategoryKind.IGNORED for category in categories):
        return categories
    names = {category.name for category in categories}
    catch_all = [
        category
        for category in defaults
        if category.kind is CategoryKind.IGNORED
        and not category.keywords
        and category.name not in names
    ]
    return [*categories, *catch_all]


def _keywords(
    rules: Iterable[_Rule], categories: set[str], report: MigrationReport
) -> dict[str, list[str]]:
    """Rule keywords per category; first claim wins, problems go to the report."""
    owners: dict[str, str] = {}
    keywords: dict[str, list[str]] = {}
    for rule in rules:
        reason, keyword = _keyword_of(rule, categories)
        if reason is not None:
            report.dropped.append(DroppedItem(rule.keyword, rule.category, reason))
        if not keyword:  # dropped entirely (AMOUNT_BOUNDS still yields a keyword)
            continue
        if keyword in owners:
            report.dropped.append(DroppedItem(rule.keyword, rule.category, DropReason.CONFLICT))
            continue
        owners[keyword] = rule.category
        keywords.setdefault(rule.category, []).append(keyword)
    return keywords


def _keyword_of(rule: _Rule, categories: set[str]) -> tuple[DropReason | None, str]:
    """The keyword a rule becomes, or why it cannot (AMOUNT_BOUNDS still yields one)."""
    if rule.category == LEGACY_UNASSIGNED:
        return DropReason.UNASSIGNED, ""
    if rule.category not in categories:
        return DropReason.UNKNOWN_CATEGORY, ""
    if rule.regex and re.escape(rule.keyword) != rule.keyword:
        return DropReason.REGEX, ""
    try:
        keyword = normalize_keyword(rule.keyword)
    except CategoryError:
        return DropReason.EMPTY, ""
    bounded = rule.minimum is not None or rule.maximum is not None
    return (DropReason.AMOUNT_BOUNDS if bounded else None), keyword


def _add_default_keywords(
    keywords: dict[str, list[str]], categories: Sequence[Category], defaults: CategoryCatalog
) -> None:
    """Give categories that correspond to a default category (same name or alias) its
    keywords, where no legacy rule claims them. Token-start matching no longer finds "vers"
    inside "lebensvers"; the defaults ("lebensvers", "versicherung") close such gaps."""
    owned = {keyword for listed in keywords.values() for keyword in listed}
    for category in categories:
        default_name = _default_name(category.name, defaults)
        if default_name is None:
            continue
        free = [kw for kw in defaults.keywords_of(default_name) if kw not in owned]
        keywords.setdefault(category.name, []).extend(free)
        owned.update(free)


# -- assignments ------------------------------------------------------------------------------


def _assignments(
    overrides: Mapping[str, Any],
    key_map: Mapping[str, str],
    catalog: CategoryCatalog,
    report: MigrationReport,
) -> ManualAssignments:
    entries: dict[str, Assignment] = {}
    for legacy_key, value in overrides.items():
        assignment, reason = _assignment(legacy_key, value, catalog)
        if assignment is None:
            category = value if isinstance(value, str) else ""
            report.dropped.append(DroppedItem(legacy_key, category, reason or DropReason.EMPTY))
            continue
        entries[key_map.get(legacy_key) or _rebuilt_key(legacy_key)] = assignment
    report.assignments = len(entries)
    return ManualAssignments(entries)


def _rebuilt_key(legacy_key: str) -> str:
    """A legacy key without booking: its payee part unglued and normalized like
    ``Transaction.key``, so the decision applies when the statement is imported again."""
    parts = legacy_key.split(LEGACY_KEY_SEPARATOR, KEY_PARTS - 1)
    if len(parts) != KEY_PARTS:
        return legacy_key
    booking_date, amount, payee = parts
    return LEGACY_KEY_SEPARATOR.join((booking_date, amount, normalize_text(_unglued(payee))))


def _assignment(
    legacy_key: str, value: object, catalog: CategoryCatalog
) -> tuple[Assignment | None, DropReason | None]:
    if isinstance(value, str):
        if value == LEGACY_UNASSIGNED:
            return None, DropReason.UNASSIGNED
        return (value, None) if value in catalog else (None, DropReason.UNKNOWN_CATEGORY)
    if not isinstance(value, list):
        return None, DropReason.INVALID_SPLIT
    fallback = catalog.fallback(CategoryRole.EXPENSE_FALLBACK).name
    parts = _merged_parts(
        (
            fallback if p[L_CATEGORY] == LEGACY_UNASSIGNED else str(p[L_CATEGORY]),
            _money(p[L_AMOUNT]),
        )
        for p in value
    )
    if not all(part.category in catalog for part in parts):
        return None, DropReason.UNKNOWN_CATEGORY
    amount = _amount_of_key(legacy_key) or sum((part.amount for part in parts), Decimal(0))
    try:
        return validate_split(amount, _absorb_rounding(parts, amount)), None
    except SplitError:
        return None, DropReason.INVALID_SPLIT


def _merged_parts(parts: Iterable[tuple[str, Decimal]]) -> list[SplitPart]:
    """Parts of one category added up (two "unassigned" remainders, for example)."""
    merged: dict[str, Decimal] = {}
    for category, amount in parts:
        merged[category] = merged.get(category, Decimal(0)) + amount
    return [SplitPart(category, amount) for category, amount in merged.items()]


def _absorb_rounding(parts: list[SplitPart], amount: Decimal) -> list[SplitPart]:
    """The legacy dialog stored parts like -6.665; rounded to cents they may miss the booking
    by a cent or two, which the largest part absorbs."""
    difference = amount - sum((part.amount for part in parts), Decimal(0))
    if not difference or abs(difference) > CENT * len(parts):
        return parts
    largest = max(range(len(parts)), key=lambda index: abs(parts[index].amount))
    fixed = parts[largest]
    return [
        SplitPart(fixed.category, fixed.amount + difference) if index == largest else part
        for index, part in enumerate(parts)
    ]


def _amount_of_key(legacy_key: str) -> Decimal | None:
    parts = legacy_key.split(LEGACY_KEY_SEPARATOR)
    if len(parts) < KEY_PARTS:
        return None
    try:
        return _money(parts[KEY_AMOUNT_PART])
    except InvalidOperation:
        return None


# -- report: automatic categories before and after ----------------------------------------------


def _changed_bookings(
    bookings: Sequence[_LegacyBooking], rules: Sequence[_Rule], categorizer: Categorizer
) -> list[ChangedBooking]:
    """Bookings without manual decision whose automatic category differs. "Nicht zugeordnet"
    and the new expense fallback count as the same for money going out."""
    fallback = categorizer.catalog.fallback(CategoryRole.EXPENSE_FALLBACK).name
    changed: list[ChangedBooking] = []
    for booking in bookings:
        txn = booking.transaction
        if categorizer.resolve(txn).is_manual:
            continue
        before = _legacy_category(booking.entry, rules)
        after = categorizer.auto(txn).category
        if before != after and not (before == LEGACY_UNASSIGNED and after == fallback):
            changed.append(ChangedBooking(txn, before, after))
    return changed


def _legacy_category(entry: Mapping[str, Any], rules: Sequence[_Rule]) -> str:
    """What the legacy app showed: the longest rule whose keyword is an uppercase substring of
    the *legacy* payee and purpose (or whose regex matches) within its amount bounds; else
    "Einkommen" for money in and "Nicht zugeordnet" for money out."""
    amount = _money(entry[L_AMOUNT])
    text = f"{entry[L_PAYEE]} {entry.get(L_PURPOSE, '')}".upper()
    matching = [rule for rule in rules if _legacy_matches(rule, text, abs(amount))]
    best = max(matching, key=lambda rule: len(rule.keyword), default=None)
    if best is not None:
        return best.category
    return LEGACY_INCOME if amount > 0 else LEGACY_UNASSIGNED


def _legacy_matches(rule: _Rule, text: str, amount: Decimal) -> bool:
    if rule.minimum is not None and amount < rule.minimum:
        return False
    if rule.maximum is not None and amount > rule.maximum:
        return False
    if rule.regex:
        try:
            return re.search(rule.keyword, text, re.IGNORECASE) is not None
        except re.error:
            return False
    return rule.keyword.upper() in text


def _money(value: object) -> Decimal:
    """A legacy float amount as exact cents (legacy files store floats like -11.49)."""
    return Decimal(str(value)).quantize(CENT)


def _money_or_none(value: object) -> Decimal | None:
    return None if value is None else _money(value)
