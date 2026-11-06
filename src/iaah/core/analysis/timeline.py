"""Balances over time, the spending calendar and gaps between imported months."""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Final

from iaah.core.analysis.ledger import ZERO, Entry, Period, month_range
from iaah.core.categories import CategoryKind
from iaah.core.models import StatementInfo, Transaction

DAYS_PER_WEEK: Final = 7
ONE_DAY: Final = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class BalancePoint:
    """A balance at the end of a day."""

    day: date
    balance: Decimal


@dataclass(frozen=True, slots=True)
class CalendarGrid:
    """Spending per day laid out as weeks: 7 rows (Monday first) × ``weeks`` columns.

    Days inside the range without spending are zero; cells before the first or after the last
    day are ``None``.
    """

    start: date  # Monday of the first week
    cells: tuple[tuple[Decimal | None, ...], ...]

    @property
    def weeks(self) -> int:
        """Number of columns."""
        return len(self.cells[0])

    def week_start(self, week: int) -> date:
        """Monday of column ``week``."""
        return self.start + timedelta(weeks=week)

    def day_at(self, row: int, week: int) -> date:
        """The date of a cell (for drill-down on click)."""
        return self.week_start(week) + timedelta(days=row)


def cumulative_flow(transactions: Iterable[Transaction]) -> list[BalancePoint]:
    """Running sum of all bookings, one point per day – the balance relative to the start."""
    ordered = sorted(transactions, key=lambda txn: txn.booking_date)
    return _end_of_day(ordered, ZERO)


def statements_in_period(
    statements: Iterable[StatementInfo], period: Period
) -> list[StatementInfo]:
    """Statements whose period lies in ``period`` (all of them for all time; statements without
    a stated period only then)."""
    if period.bounds() is None:
        return list(statements)
    return [info for info in statements if info.period and _overlaps(info.period, period)]


def account_balances(
    statements: Iterable[StatementInfo], transactions: Iterable[Transaction]
) -> dict[str, list[BalancePoint]]:
    """The real balance per account: each statement's opening balance plus its bookings.

    Bookings belong to a statement through ``Transaction.source``. Statements without an
    opening balance (CSV exports) are skipped. Statements are taken in period order; each
    starts with its opening balance on the first day of its period, or on its first booking
    day if that is earlier.
    """
    by_source: dict[str, list[Transaction]] = defaultdict(list)
    for txn in transactions:
        by_source[txn.source].append(txn)

    balances: dict[str, list[BalancePoint]] = defaultdict(list)
    for info in sorted(statements, key=lambda info: (info.period, info.source)):
        bookings = sorted(by_source.get(info.source, []), key=lambda txn: txn.booking_date)
        if info.opening_balance is None or not bookings:
            continue
        first_day = bookings[0].booking_date
        start = min(_period_start(info.period) or first_day, first_day)
        balances[info.account].append(BalancePoint(start, info.opening_balance))
        balances[info.account].extend(_end_of_day(bookings, info.opening_balance))
    return dict(balances)


def daily_spending(entries: Iterable[Entry]) -> dict[date, Decimal]:
    """Money spent per day in expense categories – gross: refunds are not subtracted, so the
    calendar shows how much went out each day."""
    spent: dict[date, Decimal] = defaultdict(Decimal)
    for entry in entries:
        if entry.kind is CategoryKind.EXPENSE and entry.amount < 0:
            spent[entry.day] -= entry.amount
    return dict(spent)


def calendar_grid(
    daily: Mapping[date, Decimal], bounds: tuple[date, date] | None = None
) -> CalendarGrid | None:
    """Lay daily spending out as weeks.

    ``bounds`` (e.g. ``Period.bounds()``) sets the range; without it the range runs from the
    first to the last day with spending. ``None`` if there is no range at all.
    """
    if bounds is None and not daily:
        return None
    first, last = bounds or (min(daily), max(daily))
    start = first - timedelta(days=first.weekday())
    weeks = (last - start).days // DAYS_PER_WEEK + 1
    rows: list[list[Decimal | None]] = [[None] * weeks for _ in range(DAYS_PER_WEEK)]
    day = first
    while day <= last:
        rows[day.weekday()][(day - start).days // DAYS_PER_WEEK] = daily.get(day, ZERO)
        day += ONE_DAY
    return CalendarGrid(start, tuple(tuple(row) for row in rows))


def missing_months(months: Iterable[str]) -> list[str]:
    """Months between the first and the last given month that are not among them."""
    present = sorted(set(months))
    if not present:
        return []
    return [month for month in month_range(present[0], present[-1]) if month not in present]


def _end_of_day(bookings: Sequence[Transaction], start: Decimal) -> list[BalancePoint]:
    """Balance after the last booking of each day; ``bookings`` must be sorted by date."""
    by_day: dict[date, Decimal] = {}
    running = start
    for txn in bookings:
        running += txn.amount
        by_day[txn.booking_date] = running
    return [BalancePoint(day, balance) for day, balance in by_day.items()]


def _period_start(period: str) -> date | None:
    bounds = Period.parse(period).bounds() if period else None
    return bounds[0] if bounds else None


def _overlaps(statement_period: str, period: Period) -> bool:
    statement_bounds = Period.parse(statement_period).bounds()
    selected = period.bounds()
    if statement_bounds is None or selected is None:
        return True
    return statement_bounds[0] <= selected[1] and selected[0] <= statement_bounds[1]
