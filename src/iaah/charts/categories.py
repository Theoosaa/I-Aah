"""Spending per category: donut, comparison with the previous period, trend, stacked months
and the budget traffic light."""

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Final

from matplotlib.axes import Axes
from matplotlib.patches import Wedge

from iaah.charts.chart import Chart, DrillKind, DrillTarget, message_chart
from iaah.charts.style import (
    CENTER,
    EURO_AXIS,
    INK_ON_PASTEL,
    LINE_WIDTH,
    PREVIOUS_COLOR,
    SMALL_FONT,
    TINY_FONT,
    ChartTheme,
    add_axes,
    color_of,
    euro,
    grid,
    month_axis,
    new_figure,
    percent,
    short,
    themed,
)
from iaah.core.analysis.totals import BudgetLevel, BudgetStatus, CategoryChange, MonthlySeries

DONUT_WIDTH: Final = 0.42
PERCENT_DISTANCE: Final = 0.78
START_ANGLE: Final = 90
MIN_LABELED_SHARE: Final = 3.0  # percent
LEGEND_ANCHOR: Final = (1.0, CENTER)
BAR_HEIGHT: Final = 0.4
BUDGET_BAR_HEIGHT: Final = 0.6
OVERSHOOT_ALPHA: Final = 0.5
MIN_TREND_MONTHS: Final = 2
MARKER: Final = "o"
BUDGET_COLORS: Final[dict[BudgetLevel, str]] = {
    BudgetLevel.OK: "#2e7d32",
    BudgetLevel.WARNING: "#f9a825",
    BudgetLevel.OVER: "#c62828",
}

NO_SPENDING: Final = "Keine Ausgaben im Zeitraum."
TOO_FEW_MONTHS: Final = (
    "Zu wenige Monate für einen Verlauf.\nWähle ein ganzes Jahr oder den gesamten Zeitraum."
)
NO_BUDGETS: Final = "Noch keine Budgets gesetzt.\nLege sie im Tab „Budgets“ fest."


def donut_chart(
    amounts: Mapping[str, Decimal], colors: Mapping[str, str], theme: ChartTheme
) -> Chart:
    """Share of each category in the spending, their sum in the middle. A category whose
    refunds outweigh its spending (negative amount) cannot be a slice; it is named below the
    ring, so the chart still explains a difference to the KPI total."""
    spending = {name: amount for name, amount in amounts.items() if amount > 0}
    note = _surplus_note({name: -amount for name, amount in amounts.items() if amount < 0})
    if not spending:
        return message_chart(f"{NO_SPENDING}\n{note}" if note else NO_SPENDING, theme)
    with themed(theme):
        figure = new_figure()
        axes = add_axes(figure, theme)
        wedges = _ring(axes, spending, colors, theme)
        axes.legend(wedges, [f"{short(name)}  ({euro(spending[name])})" for name in spending],
                    loc="center left", bbox_to_anchor=LEGEND_ANCHOR)  # fmt: skip
        axes.set_title("Ausgaben nach Kategorie")
        axes.set_xlabel(note)
    pairs = zip(wedges, spending, strict=True)
    return Chart(figure, tuple(DrillTarget(w, DrillKind.CATEGORY, n) for w, n in pairs))


def _surplus_note(surplus: Mapping[str, Decimal]) -> str:
    """Names the categories with more refunds than spending ("" if there are none)."""
    if not surplus:
        return ""
    notes = ", ".join(f"{short(name)} ({euro(amount)})" for name, amount in surplus.items())
    return f"Mehr erstattet als ausgegeben: {notes}"


def _ring(
    axes: Axes, spending: Mapping[str, Decimal], colors: Mapping[str, str], theme: ChartTheme
) -> list[Wedge]:
    drawn = axes.pie(
        [float(amount) for amount in spending.values()],
        colors=[color_of(colors, name) for name in spending],
        autopct=_share_label, startangle=START_ANGLE, pctdistance=PERCENT_DISTANCE,
        wedgeprops={"width": DONUT_WIDTH, "edgecolor": theme.face},
    )  # fmt: skip
    for label in drawn.texts[-1]:  # the percent labels (autopct come last)
        label.set(fontsize=SMALL_FONT, color=INK_ON_PASTEL)
    total = sum(spending.values(), Decimal(0))
    axes.text(0, 0, f"gesamt\n{euro(total)}", ha="center", va="center", fontweight="bold")
    return drawn.wedges


def comparison_chart(
    rows: Sequence[CategoryChange],
    labels: tuple[str, str],
    colors: Mapping[str, str],
    theme: ChartTheme,
) -> Chart:
    """Each category now (colored) beside the previous period (grey); ``labels`` names both."""
    if not rows:
        return message_chart(NO_SPENDING, theme)
    ordered = list(reversed(rows))  # largest at the top
    positions = range(len(ordered))
    with themed(theme):
        figure = new_figure()
        axes = add_axes(figure, theme)
        current = axes.barh([p + BAR_HEIGHT / 2 for p in positions],
                            [float(row.current) for row in ordered], BAR_HEIGHT,
                            color=[color_of(colors, row.category) for row in ordered],
                            label=labels[0])  # fmt: skip
        axes.barh([p - BAR_HEIGHT / 2 for p in positions],
                  [float(row.previous) for row in ordered], BAR_HEIGHT,
                  color=PREVIOUS_COLOR, label=labels[1])  # fmt: skip
        axes.set_yticks(positions, [short(row.category) for row in ordered])
        axes.set_xlabel(EURO_AXIS)
        axes.set_title(f"Kategorien: {labels[0]} vs. {labels[1]}")
        axes.legend(loc="lower right")
        grid(axes, theme, "x")
    bars = zip(current, ordered, strict=True)
    return Chart(figure, tuple(DrillTarget(b, DrillKind.CATEGORY, r.category) for b, r in bars))


def trend_chart(series: MonthlySeries, colors: Mapping[str, str], theme: ChartTheme) -> Chart:
    """Monthly spending of the given categories as lines."""
    if len(series.months) < MIN_TREND_MONTHS:
        return message_chart(TOO_FEW_MONTHS, theme)
    if not series.series:
        return message_chart(NO_SPENDING, theme)
    with themed(theme):
        figure = new_figure()
        axes = add_axes(figure, theme)
        positions = range(len(series.months))
        for name, values in series.series.items():
            axes.plot(positions, [float(v) for v in values], marker=MARKER, label=short(name),
                      linewidth=LINE_WIDTH, color=color_of(colors, name))  # fmt: skip
        month_axis(axes, series.months)
        axes.set_ylabel(f"{EURO_AXIS} / Monat")
        axes.set_title(f"Kategorie-Entwicklung (Top {len(series.series)})")
        axes.legend()
        grid(axes, theme)
    return Chart(figure)


def stacked_chart(series: MonthlySeries, colors: Mapping[str, str], theme: ChartTheme) -> Chart:
    """Spending per month as bars stacked by category."""
    if not series.series:
        return message_chart(NO_SPENDING, theme)
    with themed(theme):
        figure = new_figure()
        axes = add_axes(figure, theme)
        targets = _stack(axes, series, colors)
        month_axis(axes, series.months)
        axes.set_ylabel(EURO_AXIS)
        axes.set_title("Ausgaben je Kategorie je Monat")
        axes.legend(loc="center left", bbox_to_anchor=LEGEND_ANCHOR)
        grid(axes, theme, "y")
    return Chart(figure, tuple(targets))


def _stack(axes: Axes, series: MonthlySeries, colors: Mapping[str, str]) -> list[DrillTarget]:
    positions = range(len(series.months))
    bottom = [0.0] * len(series.months)
    targets: list[DrillTarget] = []
    for name, values in series.series.items():
        heights = [float(value) for value in values]
        bars = axes.bar(positions, heights, bottom=bottom, label=short(name),
                        color=color_of(colors, name))  # fmt: skip
        targets.extend(DrillTarget(bar, DrillKind.CATEGORY, name) for bar in bars)
        bottom = [base + height for base, height in zip(bottom, heights, strict=True)]
    return targets


def budget_chart(statuses: Sequence[BudgetStatus], months: int, theme: ChartTheme) -> Chart:
    """Spending against the budget: the grey track is the limit, the bar what was spent.
    ``months`` is the number the limits were computed for."""
    if not statuses:
        return message_chart(NO_BUDGETS, theme)
    ordered = list(reversed(statuses))  # fullest at the top
    with themed(theme):
        figure = new_figure()
        axes = add_axes(figure, theme)
        targets = [_budget_bar(axes, row, status, theme) for row, status in enumerate(ordered)]
        axes.set_yticks(range(len(ordered)), [short(status.category) for status in ordered])
        axes.set_xlabel(EURO_AXIS)
        axes.set_title(f"Budget-Ampel ({months} Monat(e) im Zeitraum)")
        grid(axes, theme, "x")
    return Chart(figure, tuple(targets))


def _budget_bar(axes: Axes, row: int, status: BudgetStatus, theme: ChartTheme) -> DrillTarget:
    limit, spent = float(status.limit), float(status.spent)
    axes.barh(row, limit, color=theme.track, height=BUDGET_BAR_HEIGHT)
    (bar,) = axes.barh(row, min(spent, limit), color=BUDGET_COLORS[status.level],
                       height=BUDGET_BAR_HEIGHT)  # fmt: skip
    if spent > limit:
        axes.barh(row, spent - limit, left=limit, color=BUDGET_COLORS[BudgetLevel.OVER],
                  height=BUDGET_BAR_HEIGHT, alpha=OVERSHOOT_ALPHA)  # fmt: skip
    text = f"  {euro(status.spent)} / {euro(status.limit)}  ({percent(status.ratio)})"
    axes.text(max(spent, limit), row, text, va="center", fontsize=TINY_FONT)
    return DrillTarget(bar, DrillKind.CATEGORY, status.category)


def _share_label(share: float) -> str:
    """Percent on the wedge; tiny wedges stay unlabeled so labels do not overlap."""
    return f"{share:.0f} %" if share >= MIN_LABELED_SHARE else ""
