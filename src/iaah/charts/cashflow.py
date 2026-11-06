"""Money over time: cash flow per month, running balances and the year-over-year comparison."""

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, Final

from matplotlib.axes import Axes
from matplotlib.dates import DateFormatter

from iaah.charts.chart import Chart, message_chart
from iaah.charts.style import (
    EURO_AXIS,
    EXPENSE_COLOR,
    FILL_ALPHA,
    INCOME_COLOR,
    LABEL_ROTATION,
    LINE_WIDTH,
    MONTH_ABBREVIATIONS,
    NET_COLOR,
    RATE_COLOR,
    SMALL_FONT,
    THIN_LINE,
    ChartTheme,
    add_axes,
    grid,
    month_axis,
    new_figure,
    percent,
    themed,
)
from iaah.core.analysis.timeline import BalancePoint
from iaah.core.analysis.totals import MonthFlow

BAR_WIDTH: Final = 0.38
RATE_OFFSET: Final = (0, 9)  # points above the net marker
MIN_YEARS: Final = 2
ACCOUNT_SUFFIX_DIGITS: Final = 4
DATE_FORMAT: Final = "%d.%m.%y"
STEPS: Final = "steps-post"  # a balance holds until the next booking
MARKER: Final = "o"

NO_BOOKINGS: Final = "Keine Buchungen im Zeitraum."
NO_BALANCE: Final = (
    "Kein Kontostand in den Auszügen des Zeitraums.\n"
    "Nur PDF-Kontoauszüge nennen „Alter Saldo“ und „Neuer Saldo“."
)
TOO_FEW_YEARS: Final = "Der Jahresvergleich braucht Auszüge aus mindestens zwei Jahren."
UNNAMED_ACCOUNT: Final = "Konto"


def cashflow_chart(flows: Sequence[MonthFlow], theme: ChartTheme) -> Chart:
    """Income and expense bars per month, the net as a line, the savings rate above it."""
    if not flows:
        return message_chart(NO_BOOKINGS, theme)
    with themed(theme):
        figure = new_figure()
        axes = add_axes(figure, theme)
        _draw_cashflow(axes, flows, theme)
    return Chart(figure)


def _draw_cashflow(axes: Axes, flows: Sequence[MonthFlow], theme: ChartTheme) -> None:
    positions = range(len(flows))
    net = [float(flow.totals.net) for flow in flows]
    axes.bar([p - BAR_WIDTH / 2 for p in positions], [float(f.totals.income) for f in flows],
             BAR_WIDTH, label="Einnahmen", color=INCOME_COLOR)  # fmt: skip
    axes.bar([p + BAR_WIDTH / 2 for p in positions], [float(f.totals.expense) for f in flows],
             BAR_WIDTH, label="Ausgaben", color=EXPENSE_COLOR)  # fmt: skip
    axes.plot(positions, net, color=NET_COLOR, marker=MARKER, linewidth=LINE_WIDTH,
              label="Netto (gespart)")  # fmt: skip
    axes.axhline(0, color=theme.muted, linewidth=THIN_LINE)
    _annotate_rates(axes, flows, net)
    month_axis(axes, [flow.month for flow in flows])
    axes.set_ylabel(EURO_AXIS)
    axes.set_title("Cashflow je Monat – was bleibt übrig? (% = Sparquote)")
    axes.legend()
    grid(axes, theme, "y")


def _annotate_rates(axes: Axes, flows: Sequence[MonthFlow], net: Sequence[float]) -> None:
    """The savings rate above each net marker (months without income have none)."""
    for position, flow in enumerate(flows):
        rate = flow.totals.savings_rate
        if rate is None:
            continue
        axes.annotate(percent(rate), (position, net[position]), textcoords="offset points",
                      xytext=RATE_OFFSET, ha="center", fontsize=SMALL_FONT, color=RATE_COLOR,
                      fontweight="bold")  # fmt: skip


def cumulative_chart(points: Sequence[BalancePoint], theme: ChartTheme) -> Chart:
    """Running sum of all bookings – the balance relative to the start of the period."""
    if not points:
        return message_chart(NO_BOOKINGS, theme)
    with themed(theme):
        figure = new_figure()
        axes = add_axes(figure, theme)
        days = _dates(points)
        values = [float(point.balance) for point in points]
        axes.plot(days, values, color=NET_COLOR, drawstyle=STEPS, linewidth=LINE_WIDTH)
        axes.fill_between(days, values, step="post", alpha=FILL_ALPHA, color=NET_COLOR)
        axes.axhline(0, color=theme.muted, linewidth=THIN_LINE)
        axes.set_ylabel(f"Summe der Buchungen ({EURO_AXIS})")
        axes.set_title("Saldo-Verlauf (relativ zum Beginn des Zeitraums)")
        _date_axis(axes)
        grid(axes, theme)
    return Chart(figure)


def balance_chart(balances: Mapping[str, Sequence[BalancePoint]], theme: ChartTheme) -> Chart:
    """The real balance per account, from the statements' opening balances."""
    if not any(balances.values()):
        return message_chart(NO_BALANCE, theme)
    with themed(theme):
        figure = new_figure()
        axes = add_axes(figure, theme)
        for account, points in balances.items():
            axes.plot(_dates(points), [float(point.balance) for point in points], drawstyle=STEPS,
                      linewidth=LINE_WIDTH, label=account_label(account))  # fmt: skip
        axes.axhline(0, color=theme.muted, linewidth=THIN_LINE)
        axes.set_ylabel(f"Kontostand ({EURO_AXIS})")
        axes.set_title("Echter Kontostand-Verlauf")
        if len(balances) > 1:
            axes.legend()
        _date_axis(axes)
        grid(axes, theme)
    return Chart(figure)


def years_chart(years: Mapping[int, Sequence[Decimal | None]], theme: ChartTheme) -> Chart:
    """Expense per calendar month, one line per year; months without bookings leave a gap."""
    if len(years) < MIN_YEARS:
        return message_chart(TOO_FEW_YEARS, theme)
    with themed(theme):
        figure = new_figure()
        axes = add_axes(figure, theme)
        months = range(len(MONTH_ABBREVIATIONS))
        for year, values in years.items():
            line = [float("nan") if value is None else float(value) for value in values]
            axes.plot(months, line, marker=MARKER, linewidth=LINE_WIDTH, label=str(year))
        axes.set_xticks(months, MONTH_ABBREVIATIONS)
        axes.set_ylim(bottom=0)  # differences of a few euros must not look dramatic
        axes.set_ylabel(f"Ausgaben ({EURO_AXIS})")
        axes.set_title("Jahresvergleich – Ausgaben je Monat")
        axes.legend(loc="lower right")  # the lines run high: the axis starts at zero
        grid(axes, theme)
    return Chart(figure)


def account_label(account: str) -> str:
    """``"…1234"`` – enough to tell accounts apart without showing the number."""
    return f"…{account[-ACCOUNT_SUFFIX_DIGITS:]}" if account else UNNAMED_ACCOUNT


def _dates(points: Sequence[BalancePoint]) -> Any:  # noqa: ANN401 – see docstring
    """The days as x values. matplotlib plots dates natively; only its type stubs restrict x
    to numbers, hence ``Any`` here – and nowhere else."""
    return [point.day for point in points]


def _date_axis(axes: Axes) -> None:
    formatter = DateFormatter(DATE_FORMAT)  # type: ignore[no-untyped-call]  # no stubs
    axes.xaxis.set_major_formatter(formatter)
    axes.tick_params(axis="x", labelrotation=LABEL_ROTATION)
