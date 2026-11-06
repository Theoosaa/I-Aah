"""Income, expenses and everything derived from them.

One definition everywhere: ignored categories never count; income is the net sum of income
entries, expense the negated net sum of expense entries. A refund (money back in an expense
category) therefore lowers that category's spending instead of counting as income.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Final

from iaah.core.analysis.ledger import FIRST_MONTH, MONTHS_PER_YEAR, ZERO, Entry, months_of
from iaah.core.categories import CategoryKind
from iaah.core.merchants import merchant_key, merchant_label

BUDGET_WARNING_RATIO: Final = Decimal("0.8")  # above 80 % of the budget: yellow
BUDGET_FULL_RATIO: Final = Decimal(1)  # above 100 %: red


@dataclass(frozen=True, slots=True)
class Totals:
    """Income and expense of a set of entries (both net, normally positive)."""

    income: Decimal = ZERO
    expense: Decimal = ZERO

    @property
    def net(self) -> Decimal:
        """What is left: income minus expense."""
        return self.income - self.expense

    @property
    def savings_rate(self) -> Decimal | None:
        """Net as a fraction of income (``0.25`` = 25 %); ``None`` without income."""
        return self.net / self.income if self.income > 0 else None


@dataclass(frozen=True, slots=True)
class Kpis:
    """The KPI tiles: totals plus the monthly average over the months with bookings."""

    totals: Totals
    months: int

    @property
    def average_monthly_expense(self) -> Decimal:
        """Expense per month with bookings (zero without months)."""
        return self.totals.expense / self.months if self.months else ZERO


@dataclass(frozen=True, slots=True)
class Change:
    """Difference to a previous value; ``ratio`` is relative (``0.1`` = +10 %)."""

    difference: Decimal
    ratio: Decimal | None


@dataclass(frozen=True, slots=True)
class KpiChanges:
    """KPI tiles compared with the previous period."""

    income: Change
    expense: Change
    net: Change
    savings_rate_points: Decimal | None  # difference of the rates; 0.05 = +5 percentage points


@dataclass(frozen=True, slots=True)
class MonthFlow:
    """Cash flow of one month."""

    month: str
    totals: Totals


@dataclass(frozen=True, slots=True)
class CategoryChange:
    """A category's spending now and in the previous period."""

    category: str
    current: Decimal
    previous: Decimal


@dataclass(frozen=True, slots=True)
class MonthlySeries:
    """Spending per category per month; every series has one value per month. A month in
    which refunds exceed spending shows zero, so stacked bars never go below the axis."""

    months: tuple[str, ...]
    series: dict[str, tuple[Decimal, ...]]


@dataclass(frozen=True, slots=True)
class MerchantTotal:
    """Money spent at one merchant."""

    merchant: str  # grouping key (merchants.merchant_key), used for drill-down
    label: str  # for display
    amount: Decimal


@dataclass(frozen=True, slots=True)
class MoneyFlow:
    """Where income went: spending per category and what was saved."""

    income: Decimal
    outflows: tuple[tuple[str, Decimal], ...]  # category, amount; largest first
    saved: Decimal  # income minus all outflows, zero if they exceed income


class BudgetLevel(StrEnum):
    """Traffic light of a budget."""

    OK = "ok"
    WARNING = "warning"
    OVER = "over"


@dataclass(frozen=True, slots=True)
class BudgetStatus:
    """A category's spending against its budget for the period."""

    category: str
    limit: Decimal  # monthly budget times months in the period
    spent: Decimal
    ratio: Decimal  # spent as a fraction of the limit
    level: BudgetLevel


def totals(entries: Iterable[Entry]) -> Totals:
    """Net income and expense; ignored entries do not count."""
    income = expense = ZERO
    for entry in entries:
        if entry.kind is CategoryKind.INCOME:
            income += entry.amount
        elif entry.kind is CategoryKind.EXPENSE:
            expense -= entry.amount
    return Totals(income, expense)


def kpis(entries: Sequence[Entry]) -> Kpis:
    """Totals plus the number of months with bookings."""
    return Kpis(totals(entries), len(months_of(entries)))


def change(current: Decimal, previous: Decimal) -> Change:
    """How much ``current`` differs from ``previous``."""
    difference = current - previous
    return Change(difference, difference / abs(previous) if previous else None)


def kpi_changes(current: Kpis, previous: Kpis) -> KpiChanges | None:
    """Deltas for the KPI tiles; ``None`` if the previous period has no bookings (the tiles
    then show no delta, as in the legacy app)."""
    if previous.months == 0:
        return None
    now, before = current.totals, previous.totals
    rates = (now.savings_rate, before.savings_rate)
    points = rates[0] - rates[1] if rates[0] is not None and rates[1] is not None else None
    return KpiChanges(
        income=change(now.income, before.income),
        expense=change(now.expense, before.expense),
        net=change(now.net, before.net),
        savings_rate_points=points,
    )


def monthly_cashflow(entries: Sequence[Entry]) -> list[MonthFlow]:
    """Totals per month with bookings, oldest first."""
    by_month: dict[str, list[Entry]] = defaultdict(list)
    for entry in entries:
        by_month[entry.month].append(entry)
    return [MonthFlow(month, totals(by_month[month])) for month in sorted(by_month)]


def expense_by_category(entries: Iterable[Entry]) -> dict[str, Decimal]:
    """Net spending per expense category, largest first; categories at or below zero
    (fully refunded) are left out."""
    spent: dict[str, Decimal] = defaultdict(Decimal)
    for entry in entries:
        if entry.kind is CategoryKind.EXPENSE:
            spent[entry.category] -= entry.amount
    return _positive_descending(spent)


def category_comparison(
    current: Iterable[Entry], previous: Iterable[Entry], limit: int
) -> list[CategoryChange]:
    """Spending per category now vs. before – the ``limit`` largest current categories."""
    now, before = expense_by_category(current), expense_by_category(previous)
    rows = [CategoryChange(n, now.get(n, ZERO), before.get(n, ZERO)) for n in now | before]
    rows.sort(key=lambda row: (-row.current, -row.previous, row.category))
    return rows[:limit]


def monthly_by_category(entries: Sequence[Entry], top: int | None = None) -> MonthlySeries:
    """Spending per expense category per month; categories ordered by total, optionally only
    the ``top`` largest."""
    months = tuple(months_of(entries))
    order = list(expense_by_category(entries))[:top]
    cells: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for entry in entries:
        if entry.kind is CategoryKind.EXPENSE:
            cells[entry.category, entry.month] -= entry.amount
    series = {name: tuple(max(cells[name, m], ZERO) for m in months) for name in order}
    return MonthlySeries(months, series)


def top_merchants(entries: Iterable[Entry], limit: int) -> list[MerchantTotal]:
    """The merchants that received the most money in expense categories."""
    spent: dict[str, Decimal] = defaultdict(Decimal)
    labels: dict[str, str] = {}
    for entry in entries:
        if entry.kind is not CategoryKind.EXPENSE:
            continue
        key = merchant_key(entry.transaction)
        spent[key] -= entry.amount
        labels.setdefault(key, merchant_label(entry.transaction))
    ranked = list(_positive_descending(spent).items())[:limit]
    return [MerchantTotal(key, labels[key], amount) for key, amount in ranked]


def money_flow(entries: Sequence[Entry]) -> MoneyFlow:
    """Income split into spending per category and savings (for the Sankey chart)."""
    income = totals(entries).income
    outflows = tuple(expense_by_category(entries).items())
    spent = sum((amount for _, amount in outflows), ZERO)
    return MoneyFlow(income, outflows, max(income - spent, ZERO))


def year_over_year(entries: Sequence[Entry]) -> dict[int, tuple[Decimal | None, ...]]:
    """Expense per calendar month for every year; ``None`` for months without bookings."""
    by_month: dict[str, list[Entry]] = defaultdict(list)
    for entry in entries:
        by_month[entry.month].append(entry)
    years = sorted({entry.day.year for entry in entries})
    return {
        year: tuple(
            _month_expense(by_month, year, month)
            for month in range(FIRST_MONTH, MONTHS_PER_YEAR + 1)
        )
        for year in years
    }


def budget_status(
    entries: Sequence[Entry], budgets: Mapping[str, Decimal], months: int
) -> list[BudgetStatus]:
    """Each budgeted category against ``budget × months`` (at least one month), fullest
    first. ``months`` is the length of the selected period, which the caller knows best."""
    spent = expense_by_category(entries)
    statuses = [
        _status(name, budget * max(months, 1), spent.get(name, ZERO))
        for name, budget in budgets.items()
        if budget > 0
    ]
    return sorted(statuses, key=lambda status: (-status.ratio, status.category))


def _status(category: str, limit: Decimal, spent: Decimal) -> BudgetStatus:
    ratio = spent / limit
    if ratio > BUDGET_FULL_RATIO:
        level = BudgetLevel.OVER
    elif ratio > BUDGET_WARNING_RATIO:
        level = BudgetLevel.WARNING
    else:
        level = BudgetLevel.OK
    return BudgetStatus(category, limit, spent, ratio, level)


def _month_expense(by_month: Mapping[str, list[Entry]], year: int, month: int) -> Decimal | None:
    bookings = by_month.get(f"{year:04d}-{month:02d}")
    return totals(bookings).expense if bookings else None


def _positive_descending(amounts: Mapping[str, Decimal]) -> dict[str, Decimal]:
    positive = ((name, amount) for name, amount in amounts.items() if amount > 0)
    return dict(sorted(positive, key=lambda item: item[1], reverse=True))
