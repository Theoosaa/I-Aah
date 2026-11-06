"""Entries, periods and month arithmetic – the common input of every analysis function.

Categorization happens once (``build_entries``); afterwards analysis works on ``Entry``
objects that already carry category and kind, so it never needs the catalog.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Final, Self

from iaah.core.assignments import Categorizer
from iaah.core.categories import CategoryKind
from iaah.core.merchants import merchant_key
from iaah.core.models import Transaction

MONTHS_PER_YEAR: Final = 12
_YEAR: Final = re.compile(r"(?P<year>\d{4})")
_MONTH: Final = re.compile(r"(?P<year>\d{4})-(?P<month>\d{2})")


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

    @property
    def counted(self) -> bool:
        """Whether the entry counts at all (ignored categories never do)."""
        return self.kind is not CategoryKind.IGNORED


def build_entries(transactions: Iterable[Transaction], categorizer: Categorizer) -> list[Entry]:
    """Resolve every booking once and expand splits into entries."""
    entries: list[Entry] = []
    for txn in transactions:
        for part in categorizer.resolve(txn).parts:
            kind = categorizer.catalog.kind_of(part.category)
            entries.append(Entry(txn, part.category, kind, part.amount))
    return entries


class PeriodKind(StrEnum):
    """Granularity of a period."""

    ALL = "all"
    YEAR = "year"
    MONTH = "month"


@dataclass(frozen=True, slots=True)
class Period:
    """All time, one calendar year, or one month. ``str()`` gives ``""``, ``"2026"`` or
    ``"2026-07"``; ``parse`` reads the same forms."""

    kind: PeriodKind
    year: int = 0
    month: int = 0

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
        if not 1 <= month <= MONTHS_PER_YEAR:
            raise ValueError(f"invalid month: {month}")
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

    def contains(self, day: date) -> bool:
        """Whether ``day`` lies in the period."""
        if self.kind is PeriodKind.ALL:
            return True
        if self.kind is PeriodKind.YEAR:
            return day.year == self.year
        return (day.year, day.month) == (self.year, self.month)

    def previous(self) -> Self | None:
        """The period before (previous year or month); ``None`` for all time."""
        if self.kind is PeriodKind.ALL:
            return None
        if self.kind is PeriodKind.YEAR:
            return type(self).of_year(self.year - 1)
        year, month = divmod(self.year * MONTHS_PER_YEAR + self.month - 2, MONTHS_PER_YEAR)
        return type(self).of_month(year, month + 1)

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
    year, number = (int(part) for part in month.split("-"))
    year, index = divmod(year * MONTHS_PER_YEAR + number, MONTHS_PER_YEAR)
    return f"{year:04d}-{index + 1:02d}"


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
    """Drill-down: the entries of one merchant (``merchants.merchant_key`` key)."""
    return [entry for entry in entries if merchant_key(entry.transaction) == merchant]


def counted(entries: Sequence[Entry]) -> list[Entry]:
    """Entries that count (not in an ignored category)."""
    return [entry for entry in entries if entry.counted]
