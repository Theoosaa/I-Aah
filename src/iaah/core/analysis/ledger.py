"""Entries, periods and month arithmetic – the common input of every analysis function.

Categorization happens once (``build_entries``); afterwards analysis works on ``Entry``
objects that already carry category and kind, so it never needs the catalog.
"""

import calendar
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Final, Self

from iaah.core.assignments import Categorizer
from iaah.core.categories import CategoryKind
from iaah.core.merchants import merchant_key
from iaah.core.models import Transaction

ZERO: Final = Decimal(0)
MONTHS_PER_YEAR: Final = 12
FIRST_MONTH: Final = 1
FIRST_DAY: Final = 1
_YEAR: Final = re.compile(r"(?P<year>\d{4})", re.ASCII)
_MONTH: Final = re.compile(r"(?P<year>\d{4})-(?P<month>\d{2})", re.ASCII)


@dataclass(frozen=True, slots=True)
class Entry:
    """One categorized part of a booking; a split booking yields one entry per part."""

    transaction: Transaction
    category: str
    kind: CategoryKind
    amount: Decimal  # signed like the booking

    @property
    def day(self) -> date:
        """Booking date."""
        return self.transaction.booking_date

    @property
    def month(self) -> str:
        """Booking month as ``YYYY-MM``."""
        return self.transaction.month


def build_entries(transactions: Iterable[Transaction], categorizer: Categorizer) -> list[Entry]:
    """Resolve every booking once and expand splits into consecutive entries."""
    entries: list[Entry] = []
    for txn in transactions:
        for part in categorizer.resolve(txn).parts:
            kind = categorizer.catalog.kind_of(part.category)
            entries.append(Entry(txn, part.category, kind, part.amount))
    return entries


def bookings(entries: Iterable[Entry]) -> list[tuple[Transaction, list[Entry]]]:
    """Entries grouped back into their bookings, in order of first appearance.

    Transactions are compared by identity, so two identical bookings stay two, and the result
    does not depend on how the entries were sorted or filtered.
    """
    groups: dict[int, tuple[Transaction, list[Entry]]] = {}
    for entry in entries:
        groups.setdefault(id(entry.transaction), (entry.transaction, []))[1].append(entry)
    return list(groups.values())


def transactions_of(entries: Iterable[Entry]) -> list[Transaction]:
    """The bookings behind ``entries`` (each once), e.g. for balance charts of a period."""
    return [txn for txn, _ in bookings(entries)]


class PeriodKind(StrEnum):
    """Granularity of a period."""

    ALL = "all"
    YEAR = "year"
    MONTH = "month"


@dataclass(frozen=True, slots=True)
class Period:
    """All time, one calendar year, or one month. ``str()`` gives ``""``, ``"2026"`` or
    ``"2026-07"``; ``parse`` reads the same forms. Unused fields are zero."""

    kind: PeriodKind
    year: int = 0
    month: int = 0

    def __post_init__(self) -> None:
        if self.kind is not PeriodKind.MONTH and self.month:
            raise ValueError(f"only a month period has a month: {self.month}")
        if self.kind is PeriodKind.MONTH and not FIRST_MONTH <= self.month <= MONTHS_PER_YEAR:
            raise ValueError(f"invalid month: {self.month}")
        if (self.kind is PeriodKind.ALL) != (self.year == 0):
            raise ValueError(f"invalid year for {self.kind}: {self.year}")

    @classmethod
    def all_time(cls) -> Self:
        """Every booking."""
        return cls(PeriodKind.ALL)

    @classmethod
    def of_year(cls, year: int) -> Self:
        """A calendar year."""
        return cls(PeriodKind.YEAR, year)

    @classmethod
    def of_month(cls, year: int, month: int) -> Self:
        """A calendar month."""
        return cls(PeriodKind.MONTH, year, month)

    @classmethod
    def parse(cls, text: str) -> Self:
        """Read ``""``, ``"2026"`` or ``"2026-07"``; raise ``ValueError`` otherwise."""
        stripped = text.strip()
        if not stripped:
            return cls.all_time()
        if match := _YEAR.fullmatch(stripped):
            return cls.of_year(int(match["year"]))
        if match := _MONTH.fullmatch(stripped):
            return cls.of_month(int(match["year"]), int(match["month"]))
        raise ValueError(f"not a period: {text!r}")

    def bounds(self) -> tuple[date, date] | None:
        """First and last day; ``None`` for all time."""
        if self.kind is PeriodKind.ALL:
            return None
        if self.kind is PeriodKind.YEAR:
            return _first_day(self.year, FIRST_MONTH), _last_day(self.year, MONTHS_PER_YEAR)
        return _first_day(self.year, self.month), _last_day(self.year, self.month)

    def contains(self, day: date) -> bool:
        """Whether ``day`` lies in the period."""
        bounds = self.bounds()
        return bounds is None or bounds[0] <= day <= bounds[1]

    def previous(self) -> Self | None:
        """The period before (previous year or month); ``None`` for all time."""
        if self.kind is PeriodKind.ALL:
            return None
        if self.kind is PeriodKind.YEAR:
            return type(self).of_year(self.year - 1)
        year, month = _from_index(_month_index(self.year, self.month) - 1)
        return type(self).of_month(year, month)

    def __str__(self) -> str:
        if self.kind is PeriodKind.ALL:
            return ""
        if self.kind is PeriodKind.YEAR:
            return f"{self.year:04d}"
        return f"{self.year:04d}-{self.month:02d}"


def in_period(entries: Iterable[Entry], period: Period) -> list[Entry]:
    """Entries whose booking date lies in ``period``."""
    return [entry for entry in entries if period.contains(entry.day)]


def months_of(entries: Iterable[Entry]) -> list[str]:
    """Distinct booking months, sorted."""
    return sorted({entry.month for entry in entries})


def next_month(month: str) -> str:
    """The month after ``YYYY-MM``."""
    period = Period.parse(month)
    return str(Period.of_month(*_from_index(_month_index(period.year, period.month) + 1)))


def month_range(first: str, last: str) -> list[str]:
    """All months from ``first`` to ``last`` inclusive (empty if ``first > last``)."""
    months: list[str] = []
    current = first
    while current <= last:
        months.append(current)
        current = next_month(current)
    return months


def entries_of_category(entries: Iterable[Entry], category: str) -> list[Entry]:
    """Drill-down: the entries of one category."""
    return [entry for entry in entries if entry.category == category]


def entries_of_merchant(entries: Iterable[Entry], merchant: str) -> list[Entry]:
    """Drill-down for the top-merchants chart: the *expense* entries of one merchant
    (``merchants.merchant_key``), so the list adds up to the bar."""
    return [
        entry
        for entry in entries
        if entry.kind is CategoryKind.EXPENSE and merchant_key(entry.transaction) == merchant
    ]


def entries_of_day(entries: Iterable[Entry], day: date) -> list[Entry]:
    """Drill-down for the calendar: the entries booked on ``day``."""
    return [entry for entry in entries if entry.day == day]


def _first_day(year: int, month: int) -> date:
    return date(year, month, FIRST_DAY)


def _last_day(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _month_index(year: int, month: int) -> int:
    """Months since year 0, so neighbouring months differ by one."""
    return year * MONTHS_PER_YEAR + (month - FIRST_MONTH)


def _from_index(index: int) -> tuple[int, int]:
    year, offset = divmod(index, MONTHS_PER_YEAR)
    return year, offset + FIRST_MONTH
