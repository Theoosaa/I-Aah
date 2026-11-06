"""One way to build any chart: ``build_chart(kind, data, theme)``.

``ChartInput`` bundles what the charts need – all categorized entries, the selected period,
statements, colors and budgets – so the GUI and the PDF report never call the analysis
functions themselves.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final, Self

from iaah.charts.cashflow import balance_chart, cashflow_chart, cumulative_chart, years_chart
from iaah.charts.categories import (
    budget_chart,
    comparison_chart,
    donut_chart,
    stacked_chart,
    trend_chart,
)
from iaah.charts.chart import Chart, ChartKind, message_chart
from iaah.charts.flow import sankey_chart
from iaah.charts.spending import calendar_chart, fixed_costs_chart, merchants_chart
from iaah.charts.style import ChartTheme, period_label
from iaah.core.analysis.ledger import Entry, Period, in_period, months_of, transactions_of
from iaah.core.analysis.recurring import recurring_payments
from iaah.core.analysis.timeline import (
    account_balances,
    calendar_grid,
    cumulative_flow,
    daily_spending,
    statements_in_period,
)
from iaah.core.analysis.totals import (
    MIN_BUDGET_MONTHS,
    budget_status,
    category_comparison,
    category_totals,
    money_flow,
    monthly_by_category,
    monthly_cashflow,
    top_merchants,
    year_over_year,
)
from iaah.core.categories import CategoryCatalog, CategoryKind
from iaah.core.models import StatementInfo, Transaction
from iaah.core.workspace import Workspace

COMPARISON_LIMIT: Final = 10
TREND_CATEGORIES: Final = 5
MERCHANT_LIMIT: Final = 12
NO_PREVIOUS: Final = (
    "Kein Vorzeitraum zum Vergleichen.\nWähle oben einen einzelnen Monat oder ein Jahr."
)


@dataclass(frozen=True, slots=True)
class ChartInput:
    """Everything the charts read; ``period`` selects which entries count."""

    period: Period
    all_entries: Sequence[Entry]
    statements: Sequence[StatementInfo] = ()
    transactions: Sequence[Transaction] = ()  # all bookings, for the real balance
    colors: Mapping[str, str] = field(default_factory=dict)
    budgets: Mapping[str, Decimal] = field(default_factory=dict)

    @classmethod
    def of_workspace(cls, workspace: Workspace, period: Period) -> Self:
        """The input for a workspace: its entries, statements, colors and budgets."""
        catalog = workspace.catalog
        return cls(
            period=period,
            all_entries=workspace.entries(),
            statements=[stored.info for stored in workspace.library.statements],
            transactions=list(workspace.library.transactions),
            colors=category_colors(catalog),
            budgets={c.name: c.budget for c in catalog if c.budget is not None},
        )

    @property
    def entries(self) -> list[Entry]:
        """Entries of the selected period."""
        return in_period(self.all_entries, self.period)


def category_colors(catalog: CategoryCatalog) -> dict[str, str]:
    """Color per category name, as the builders take them."""
    return {category.name: category.color for category in catalog}


type Builder = Callable[[ChartInput, ChartTheme], Chart]


def build_chart(kind: ChartKind, data: ChartInput, theme: ChartTheme) -> Chart:
    """Run the analysis ``kind`` needs and draw it."""
    return BUILDERS[kind](data, theme)


def _overview(data: ChartInput, theme: ChartTheme) -> Chart:
    return cashflow_chart(monthly_cashflow(data.entries), theme)


def _categories(data: ChartInput, theme: ChartTheme) -> Chart:
    return donut_chart(category_totals(data.entries, CategoryKind.EXPENSE), data.colors, theme)


def _flow(data: ChartInput, theme: ChartTheme) -> Chart:
    return sankey_chart(money_flow(data.entries), data.colors, theme)


def _comparison(data: ChartInput, theme: ChartTheme) -> Chart:
    previous = data.period.previous()
    if previous is None:
        return message_chart(NO_PREVIOUS, theme)
    earlier = in_period(data.all_entries, previous)
    rows = category_comparison(data.entries, earlier, COMPARISON_LIMIT)
    labels = (period_label(data.period), period_label(previous))
    return comparison_chart(rows, labels, data.colors, theme)


def _trend(data: ChartInput, theme: ChartTheme) -> Chart:
    return trend_chart(monthly_by_category(data.entries, TREND_CATEGORIES), data.colors, theme)


def _stacked(data: ChartInput, theme: ChartTheme) -> Chart:
    return stacked_chart(monthly_by_category(data.entries), data.colors, theme)


def _years(data: ChartInput, theme: ChartTheme) -> Chart:
    return years_chart(year_over_year(data.all_entries), theme)


def _fixed_costs(data: ChartInput, theme: ChartTheme) -> Chart:
    return fixed_costs_chart(recurring_payments(data.entries), theme)


def _budget(data: ChartInput, theme: ChartTheme) -> Chart:
    entries = data.entries
    months = max(len(months_of(entries)), MIN_BUDGET_MONTHS)  # title and limits agree
    return budget_chart(budget_status(entries, data.budgets, months), months, theme)


def _merchants(data: ChartInput, theme: ChartTheme) -> Chart:
    return merchants_chart(top_merchants(data.entries, MERCHANT_LIMIT), theme)


def _calendar(data: ChartInput, theme: ChartTheme) -> Chart:
    daily = daily_spending(data.entries)
    return calendar_chart(calendar_grid(daily, data.period.bounds()) if daily else None, theme)


def _balance(data: ChartInput, theme: ChartTheme) -> Chart:
    statements = statements_in_period(data.statements, data.period)
    return balance_chart(account_balances(statements, data.transactions), theme)


def _cumulative(data: ChartInput, theme: ChartTheme) -> Chart:
    return cumulative_chart(cumulative_flow(transactions_of(data.entries)), theme)


BUILDERS: Final[dict[ChartKind, Builder]] = {
    ChartKind.OVERVIEW: _overview,
    ChartKind.CATEGORIES: _categories,
    ChartKind.FLOW: _flow,
    ChartKind.COMPARISON: _comparison,
    ChartKind.TREND: _trend,
    ChartKind.STACKED: _stacked,
    ChartKind.YEARS: _years,
    ChartKind.FIXED_COSTS: _fixed_costs,
    ChartKind.BUDGET: _budget,
    ChartKind.MERCHANTS: _merchants,
    ChartKind.CALENDAR: _calendar,
    ChartKind.BALANCE: _balance,
    ChartKind.CUMULATIVE: _cumulative,
}
