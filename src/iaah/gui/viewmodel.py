"""What the widgets show, prepared without tkinter: filters, table rows, sorting, filter
options, KPI cards and the hit test of the PDF review page.

Everything here is a pure function of the workspace and plain values, so it is tested without a
display; widgets only put the prepared strings on screen.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any, Final

from iaah.core.analysis.ledger import ZERO, Entry, Period, in_period, months_of
from iaah.core.analysis.totals import (
    MIN_BUDGET_MONTHS,
    BudgetLevel,
    Change,
    Kpis,
    budget_status,
    expense_by_category,
    kpi_changes,
    kpis,
)
from iaah.core.assignments import AssignmentSource, Categorizer, Resolution
from iaah.core.categories import CategoryCatalog, CategoryKind
from iaah.core.geometry import to_target_box
from iaah.core.migration import DropReason, MigrationReport
from iaah.core.models import Transaction
from iaah.core.parsing.diagnostics import ParseReport
from iaah.core.parsing.layout import LineStatus
from iaah.core.text import clean_display, format_euro, normalize_text, parse_amount

DATE_FORMAT: Final = "%d.%m.%Y"
PURPOSE_CHARS: Final = 80
PERCENT: Final = 100
SPLIT_SEPARATOR: Final = " + "


class Direction(StrEnum):
    """The *Typ* filter."""

    ALL = "Alle"
    OUT = "Nur Ausgaben"
    IN = "Nur Einnahmen"


class Marker(StrEnum):
    """How a booking got its category, as a symbol in the table."""

    KEYWORD = ""
    FALLBACK = "?"  # nothing matched: an open booking
    MANUAL = "✎"
    SPLIT = "÷"


MARKERS: Final[dict[AssignmentSource, Marker]] = {
    AssignmentSource.KEYWORD: Marker.KEYWORD,
    AssignmentSource.FALLBACK: Marker.FALLBACK,
    AssignmentSource.MANUAL: Marker.MANUAL,
    AssignmentSource.SPLIT: Marker.SPLIT,
}


class Column(StrEnum):
    """Sortable table columns."""

    DATE = "date"
    TYPE = "type"
    PAYEE = "payee"
    PURPOSE = "purpose"
    AMOUNT = "amount"
    CATEGORY = "category"


@dataclass(slots=True)
class Filters:
    """The filter bar of the transactions tab; empty strings mean "all"."""

    period: Period = field(default_factory=Period.all_time)
    category: str = ""
    account: str = ""
    direction: Direction = Direction.ALL
    text: str = ""
    minimum: Decimal | None = None  # absolute amount
    maximum: Decimal | None = None
    only_open: bool = False


@dataclass(frozen=True, slots=True)
class Row:
    """One booking as the table shows it."""

    index: int  # position in library.transactions – the booking's identity
    transaction: Transaction
    resolution: Resolution
    color: str

    @property
    def marker(self) -> Marker:
        """Symbol for how the category was decided."""
        return MARKERS[self.resolution.source]

    @property
    def cells(self) -> tuple[str, ...]:
        """Datum, Buchungsart, Empfänger, Verwendungszweck, Betrag, Kategorie."""
        txn = self.transaction
        return (
            txn.booking_date.strftime(DATE_FORMAT),
            clean_display(txn.booking_type),
            clean_display(txn.payee),
            clean_display(txn.purpose)[:PURPOSE_CHARS],
            format_euro(txn.amount),
            f"{self.marker} {category_text(self.resolution)}".strip(),
        )

    @property
    def is_open(self) -> bool:
        """Caught by a fallback category – nobody decided it yet."""
        return self.resolution.source is AssignmentSource.FALLBACK


def category_text(resolution: Resolution) -> str:
    """``Lebensmittel`` or, for a split, ``Lebensmittel + Gesundheit``."""
    return SPLIT_SEPARATOR.join(part.category for part in resolution.parts)


def decision_text(resolution: Resolution) -> str:
    """How the category was decided, in words for the detail panel."""
    if resolution.source is AssignmentSource.KEYWORD:
        return f"Stichwort „{resolution.keyword}“ → {resolution.category}"
    if resolution.source is AssignmentSource.FALLBACK:
        return f"Kein Stichwort passt – Auffang-Kategorie {resolution.category}"
    if resolution.source is AssignmentSource.MANUAL:
        return f"Von Hand zugeordnet (automatisch wäre: {resolution.auto_category})"
    parts = SPLIT_SEPARATOR.join(f"{p.category} {format_euro(p.amount)}" for p in resolution.parts)
    return f"Aufgeteilt: {parts}"


def booking_details(txn: Transaction) -> str:
    """The full texts of a booking for the detail panel."""
    lines = (
        f"{day_label(txn.booking_date)}   {format_euro(txn.amount)}",
        clean_display(txn.booking_type),
        clean_display(txn.payee),
        clean_display(txn.purpose),
        f"Konto {txn.account}" if txn.account else "",
        f"Quelle: {txn.source}",
    )
    return "\n".join(line for line in lines if line)


def build_rows(
    transactions: Sequence[Transaction],
    resolutions: Sequence[Resolution],
    catalog: CategoryCatalog,
    filters: Filters,
) -> list[Row]:
    """The bookings that pass ``filters``, in library order; ``resolutions`` are their
    categories (``Session.resolutions`` caches them)."""
    needle = normalize_text(filters.text)
    return [
        Row(index, txn, resolution, catalog.color_of(resolution.category))
        for index, (txn, resolution) in enumerate(zip(transactions, resolutions, strict=True))
        if _cheap_checks(txn, filters) and _costly_checks(txn, resolution, filters, needle)
    ]


def _cheap_checks(txn: Transaction, filters: Filters) -> bool:
    return (
        filters.period.contains(txn.booking_date)
        and (not filters.account or txn.account == filters.account)
        and _direction_matches(txn.amount, filters.direction)
        and _amount_in_range(abs(txn.amount), filters.minimum, filters.maximum)
    )


def _costly_checks(txn: Transaction, resolution: Resolution, filters: Filters, needle: str) -> bool:
    return (
        (not filters.only_open or resolution.source is AssignmentSource.FALLBACK)
        and (not filters.category or filters.category in _categories(resolution))
        and (
            not needle or needle in normalize_text(f"{txn.payee} {txn.purpose} {txn.booking_type}")
        )
    )


def _categories(resolution: Resolution) -> set[str]:
    return {part.category for part in resolution.parts}


def _direction_matches(amount: Decimal, direction: Direction) -> bool:
    if direction is Direction.OUT:
        return amount < 0
    if direction is Direction.IN:
        return amount > 0
    return True


def _amount_in_range(amount: Decimal, minimum: Decimal | None, maximum: Decimal | None) -> bool:
    return (minimum is None or amount >= minimum) and (maximum is None or amount <= maximum)


SORT_KEYS: Final[dict[Column, Callable[[Row], tuple[Any, int]]]] = {
    Column.DATE: lambda row: (row.transaction.booking_date, row.index),
    Column.TYPE: lambda row: (normalize_text(row.transaction.booking_type), row.index),
    Column.PAYEE: lambda row: (normalize_text(row.transaction.payee), row.index),
    Column.PURPOSE: lambda row: (normalize_text(row.transaction.purpose), row.index),
    Column.AMOUNT: lambda row: (row.transaction.amount, row.index),
    Column.CATEGORY: lambda row: (normalize_text(category_text(row.resolution)), row.index),
}


def sort_rows(rows: Iterable[Row], column: Column, descending: bool) -> list[Row]:
    """Rows sorted by a column; equal values keep library order."""
    return sorted(rows, key=SORT_KEYS[column], reverse=descending)


@dataclass(frozen=True, slots=True)
class ViewTotals:
    """The status line of the transactions tab, for the filtered view."""

    count: int
    income: Decimal
    expense: Decimal
    open: int


def view_totals(rows: Sequence[Row], category: str = "") -> ViewTotals:
    """Count, money in, money out and open bookings of the rows. Under a category filter only
    the matching part of a split booking counts, as in the drill-down."""
    amounts = [_amount_in(row, category) for row in rows]
    income = sum((amount for amount in amounts if amount > 0), ZERO)
    expense = sum((amount for amount in amounts if amount < 0), ZERO)
    return ViewTotals(len(rows), income, expense, sum(row.is_open for row in rows))


def _amount_in(row: Row, category: str) -> Decimal:
    if not category:
        return row.transaction.amount
    return sum((p.amount for p in row.resolution.parts if p.category == category), ZERO)


def next_open(rows: Sequence[Row], after: int | None) -> int | None:
    """The next open booking after the one with index ``after`` in the view, wrapping around."""
    if not rows:
        return None
    start = next((pos + 1 for pos, row in enumerate(rows) if row.index == after), 0)
    ordered = [*rows[start:], *rows[:start]]
    return next((row.index for row in ordered if row.is_open), None)


# -- filter options ---------------------------------------------------------------------------


def periods(transactions: Iterable[Transaction]) -> list[Period]:
    """All time, then the years and months with bookings, newest first."""
    months = sorted({txn.month for txn in transactions}, reverse=True)
    years = sorted({int(month[:4]) for month in months}, reverse=True)
    return [
        Period.all_time(),
        *(Period.of_year(year) for year in years),
        *(Period.parse(month) for month in months),
    ]


def accounts(transactions: Iterable[Transaction]) -> list[str]:
    """Accounts that occur, sorted."""
    return sorted({txn.account for txn in transactions if txn.account})


# -- KPI cards --------------------------------------------------------------------------------


class Trend(StrEnum):
    """Whether a change is good news."""

    GOOD = "good"
    BAD = "bad"
    NEUTRAL = "neutral"


@dataclass(frozen=True, slots=True)
class Delta:
    """A KPI's change against the previous period."""

    arrow: str  # "▲" or "▼"
    text: str  # "12 %" or "3 %-Pkt." or a plain difference
    trend: Trend


@dataclass(frozen=True, slots=True)
class KpiView:
    """The five KPI cards of a period."""

    figures: Kpis
    income: Delta | None
    expense: Delta | None
    net: Delta | None
    savings_rate: Delta | None


def kpi_view(entries: Sequence[Entry], period: Period) -> KpiView:
    """KPIs of ``period`` with deltas against the period before (none for all time)."""
    current = kpis(in_period(entries, period))
    previous = period.previous()
    changes = kpi_changes(current, kpis(in_period(entries, previous))) if previous else None
    if changes is None:
        return KpiView(current, None, None, None, None)
    return KpiView(
        current,
        _delta(changes.income, higher_is_better=True),
        _delta(changes.expense, higher_is_better=False),
        _delta(changes.net, higher_is_better=True),
        _points(changes.savings_rate_points),
    )


def _delta(change: Change, higher_is_better: bool) -> Delta:
    arrow = "▲" if change.difference >= 0 else "▼"
    if change.ratio is None:  # no previous value: the plain difference
        text = format_euro(abs(change.difference))
    else:
        text = f"{abs(change.ratio) * PERCENT:.0f} %"
    return Delta(arrow, text, _trend(change.difference, higher_is_better))


def _points(points: Decimal | None) -> Delta | None:
    if points is None:
        return None
    arrow = "▲" if points >= 0 else "▼"
    return Delta(arrow, f"{abs(points) * PERCENT:.0f} %-Pkt.", _trend(points, True))


def _trend(difference: Decimal, higher_is_better: bool) -> Trend:
    if not difference:
        return Trend.NEUTRAL
    return Trend.GOOD if (difference > 0) == higher_is_better else Trend.BAD


def months_with_bookings(entries: Sequence[Entry], period: Period) -> int:
    """Months of ``period`` that have bookings (the base of the monthly average)."""
    return len(months_of(in_period(entries, period)))


# -- budgets ----------------------------------------------------------------------------------


def budget_from_text(text: str) -> Decimal | None:
    """A typed monthly budget: empty or 0 means none; ``ValueError`` if it is no amount or
    negative."""
    stripped = text.strip()
    if not stripped:
        return None
    amount = parse_amount(stripped)
    if amount is None or amount < 0:
        raise ValueError(f"not a budget: {text!r}")
    return amount or None


def unsaved_budgets(
    shown: Mapping[str, str], current: Mapping[str, str], stored: Mapping[str, Decimal | None]
) -> dict[str, str]:
    """Budget inputs typed since the tab last showed them and not stored yet – they survive the
    next refresh. Everything else shows the stored budget again, so undo and changes made on
    the categories tab are never hidden behind an old input."""
    return {
        name: text
        for name, text in current.items()
        if text.strip() != shown.get(name, "").strip() and not _is_stored(text, stored.get(name))
    }


def _is_stored(text: str, budget: Decimal | None) -> bool:
    try:
        return budget_from_text(text) == budget
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class BudgetRow:
    """An expense category on the budgets tab."""

    category: str
    color: str
    budget: Decimal | None  # per month
    average: Decimal  # actual spending per month of the period
    level: BudgetLevel | None  # traffic light; None without budget
    ratio: Decimal | None  # spent as a fraction of the period's limit


def budget_rows(
    entries: Sequence[Entry], catalog: CategoryCatalog, period: Period
) -> list[BudgetRow]:
    """Every expense category with its budget and its actual monthly spending in ``period``."""
    selected = in_period(entries, period)
    months = max(len(months_of(selected)), MIN_BUDGET_MONTHS)
    spent = expense_by_category(selected)
    budgets = {c.name: c.budget for c in catalog if c.budget is not None}
    status = {s.category: s for s in budget_status(selected, budgets, months)}
    return [
        BudgetRow(
            c.name,
            c.color,
            c.budget,
            spent.get(c.name, ZERO) / months,
            status[c.name].level if c.name in status else None,
            status[c.name].ratio if c.name in status else None,
        )
        for c in catalog
        if c.kind is CategoryKind.EXPENSE
    ]


# -- PDF review -------------------------------------------------------------------------------

LINE_REASONS: Final[dict[LineStatus, str]] = {
    LineStatus.BAD_HEAD: "sieht aus wie eine Buchung, unlesbar",
    LineStatus.OUTSIDE_COLUMN: "neben der Buchungsspalte",
    LineStatus.GAP_TOO_LARGE: "zu weit unter der Buchung",
    LineStatus.DETAIL_LIMIT: "zu viele Zeilen für eine Buchung",
}  # lines outside any booking (letterhead, notes) only show up when they look suspicious
SUSPICIOUS: Final = "Datum und Betrag, aber keine Buchung"


@dataclass(frozen=True, slots=True)
class UnusedLine:
    """A line of the statement the parser did not turn into (part of) a booking."""

    page: int
    reason: str
    text: str
    suspicious: bool  # worth a look: might be a missed booking


def unused_lines(report: ParseReport) -> list[UnusedLine]:
    """Suspicious lines first, then lines dropped for a geometric reason (page headers and
    footers, which the parser recognises, are left out)."""
    flagged = {id(diagnosis) for diagnosis in report.suspicious}
    lines = [
        UnusedLine(
            d.line.page,
            SUSPICIOUS if id(d) in flagged else LINE_REASONS[d.status],
            d.line.text,
            id(d) in flagged or d.status is LineStatus.BAD_HEAD,
        )
        for d in report.lines
        if d.status in LINE_REASONS or id(d) in flagged
    ]
    return sorted(lines, key=lambda line: (not line.suspicious, line.page))


@dataclass(frozen=True, slots=True)
class ReviewBox:
    """A booking drawn on the review page."""

    index: int  # position in the statement's transactions
    color: str
    changed: bool  # the user's decision differs from the automatic category


def review_rows(
    transactions: Sequence[Transaction], categorizer: Categorizer
) -> list[tuple[str, ...]]:
    """Datum, Empfänger, Betrag, Kategorie of a statement's bookings for the review list."""
    return [
        (
            day_label(txn.booking_date),
            clean_display(txn.payee),
            format_euro(txn.amount),
            category_text(categorizer.resolve(txn)),
        )
        for txn in transactions
    ]


def position_of(transactions: Sequence[Transaction], txn: Transaction) -> int | None:
    """Where a library booking sits among a statement's freshly parsed bookings."""
    return next((n for n, parsed in enumerate(transactions) if parsed.key == txn.key), None)


def review_boxes(
    transactions: Sequence[Transaction], categorizer: Categorizer, before: bool
) -> list[ReviewBox]:
    """Colors of a statement's bookings: automatic (``before``) or current, with the bookings
    a decision changed marked."""
    boxes: list[ReviewBox] = []
    for index, txn in enumerate(transactions):
        resolution = categorizer.resolve(txn)
        category = resolution.auto_category if before else resolution.category
        changed = resolution.is_manual and resolution.differs_from_auto
        boxes.append(ReviewBox(index, categorizer.catalog.color_of(category), changed))
    return boxes


def booking_at(
    transactions: Sequence[Transaction], page: int, point: tuple[float, float], scale: float
) -> int | None:
    """Index of the booking whose region on ``page`` contains ``point`` (canvas pixels, top
    left origin) at ``scale`` pixels per PDF point."""
    x, y = point
    for index, txn in enumerate(transactions):
        regions = txn.placement.regions if txn.placement else ()
        for region in regions:
            if region.page != page:
                continue
            x0, y0, x1, y1 = to_target_box(region.bbox, scale)
            if x0 <= x <= x1 and y0 <= y <= y1:
                return index
    return None


def day_label(day: date) -> str:
    """``01.07.2026``."""
    return day.strftime(DATE_FORMAT)


# -- migration report -------------------------------------------------------------------------

DROP_REASONS: Final[dict[DropReason, str]] = {
    DropReason.UNKNOWN_CATEGORY: "Kategorie gibt es nicht",
    DropReason.UNASSIGNED: "zeigte auf „Nicht zugeordnet“",
    DropReason.REGEX: "regulärer Ausdruck – bitte als Stichwort neu anlegen",
    DropReason.AMOUNT_BOUNDS: "übernommen, aber ohne Betragsgrenzen",
    DropReason.EMPTY: "leer",
    DropReason.CONFLICT: "Stichwort gehörte schon einer anderen Kategorie",
    DropReason.INVALID_SPLIT: "Aufteilung ergab nicht den Buchungsbetrag",
}


def migration_text(report: MigrationReport) -> str:
    """What the migration did, for the report window."""
    lines = [
        "Übernommen aus der alten I-Aah-Version:",
        f"  {report.categories} Kategorien mit {report.keywords} Stichwörtern",
        f"  {report.transactions} Buchungen aus {report.statements} Auszügen",
        f"  {report.assignments} manuelle Zuordnungen",
        "",
    ]
    if report.dropped:
        lines.append("Nicht oder nur teilweise übernommen:")
        lines += [
            f"  {item.what} → {item.category or '–'}: {DROP_REASONS[item.reason]}"
            for item in report.dropped
        ]
        lines.append("")
    if report.changed:
        lines.append(
            "Buchungen mit anderer automatischer Kategorie als bisher (Stichwörter "
            "passen jetzt nur noch auf Wortanfänge):"
        )
        lines += [
            f"  {day_label(c.transaction.booking_date)}  {clean_display(c.transaction.payee)}"
            f": {c.before} → {c.after}"
            for c in report.changed
        ]
    return "\n".join(lines)
