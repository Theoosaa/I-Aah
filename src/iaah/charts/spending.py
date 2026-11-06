"""Where the money goes in detail: fixed vs. variable costs, top merchants, the calendar."""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Final

import matplotlib as mpl
from matplotlib.axes import Axes
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Colormap, Normalize
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

from iaah.charts.chart import Chart, DrillKind, DrillTarget, message_chart
from iaah.charts.style import (
    BASE_FONT,
    CALENDAR_COLORMAP,
    EURO_AXIS,
    FIXED_COLOR,
    INK_ON_DARK,
    MERCHANT_COLOR,
    SMALL_FONT,
    TINY_FONT,
    VARIABLE_COLOR,
    ChartTheme,
    add_axes,
    euro,
    grid,
    month_label,
    new_figure,
    short,
    show_message,
    themed,
)
from iaah.core.analysis.ledger import MONTHS_PER_YEAR
from iaah.core.analysis.recurring import RecurringPayment, RecurringReport
from iaah.core.analysis.timeline import DAYS_PER_WEEK, CalendarGrid
from iaah.core.analysis.totals import MerchantTotal

MAX_PAYMENTS: Final = 10
PAYMENT_LABEL_CHARS: Final = 22  # shares the line with the next month
DONUT_WIDTH: Final = 0.42
START_ANGLE: Final = 90
LEGEND_BELOW: Final = (0.5, -0.15)
LEGEND_COLUMNS: Final = 2
CELL_SIZE: Final = 1.0
CELL_MIDDLE: Final = CELL_SIZE / 2
CELL_EDGE: Final = 1.0
MIN_COLOR_SCALE: Final = 1.0  # euro; keeps the colormap sane for days with cents only
COLORBAR_FRACTION: Final = 0.03
WEEKDAYS: Final = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
FIRST_OF_MONTH: Final = 1
STOPPED: Final = "beendet"

NOT_DETECTABLE: Final = (
    "Die Fixkosten-Erkennung braucht mindestens zwei Monate.\n"
    "Wähle ein ganzes Jahr oder den gesamten Zeitraum."
)
NO_SPENDING: Final = "Keine Ausgaben im Zeitraum."
NO_RECURRING: Final = "Keine wiederkehrenden Zahlungen erkannt."


# -- fixed costs ------------------------------------------------------------------------------


def fixed_costs_chart(report: RecurringReport, theme: ChartTheme) -> Chart:
    """Fixed vs. variable spending as a donut, beside the detected payments per month."""
    if not report.detectable:
        return message_chart(NOT_DETECTABLE, theme)
    with themed(theme):
        figure = new_figure()
        _fixed_share(add_axes(figure, theme, 1, 2, 1), report, theme)
        targets = _payment_bars(add_axes(figure, theme, 1, 2, 2), report.payments, theme)
    return Chart(figure, tuple(targets))


def _fixed_share(axes: Axes, report: RecurringReport, theme: ChartTheme) -> None:
    if report.fixed + report.variable > 0:
        axes.pie([float(report.fixed), float(report.variable)],
                 colors=[FIXED_COLOR, VARIABLE_COLOR], autopct=_share, startangle=START_ANGLE,
                 wedgeprops={"width": DONUT_WIDTH, "edgecolor": theme.face},
                 textprops={"fontsize": SMALL_FONT, "color": INK_ON_DARK})  # fmt: skip
    axes.legend(["Fixkosten", "Variabel"], loc="lower center", bbox_to_anchor=LEGEND_BELOW,
                ncol=LEGEND_COLUMNS)  # fmt: skip
    monthly = report.monthly_fixed
    axes.set_title(f"Fixkosten ≈ {euro(monthly)}/Monat\n= {euro(monthly * MONTHS_PER_YEAR)}/Jahr",
                   fontsize=BASE_FONT)  # fmt: skip


def _payment_bars(
    axes: Axes, payments: Sequence[RecurringPayment], theme: ChartTheme
) -> list[DrillTarget]:
    shown = list(reversed(payments[:MAX_PAYMENTS]))  # largest at the top
    if not shown:
        show_message(axes, NO_RECURRING, theme)
        return []
    monthly = [float(payment.monthly) for payment in shown]
    bars = axes.barh(range(len(shown)), monthly, color=FIXED_COLOR)
    for row, payment in enumerate(shown):
        axes.text(monthly[row], row, f" {euro(payment.monthly)}/M · {euro(payment.yearly)}/J",
                  va="center", fontsize=TINY_FONT)  # fmt: skip
    axes.set_yticks(range(len(shown)), [_payment_label(payment) for payment in shown])
    axes.set_xlabel(f"≈ {EURO_AXIS} / Monat")
    axes.set_title("Erkannte Fixkosten (nächste Buchung ≈)", fontsize=BASE_FONT)
    grid(axes, theme, "x")
    pairs = zip(bars, shown, strict=True)
    return [DrillTarget(bar, DrillKind.MERCHANT, payment.merchant) for bar, payment in pairs]


def _payment_label(payment: RecurringPayment) -> str:
    upcoming = payment.next_month
    when = month_label(upcoming) if upcoming else STOPPED
    return f"{short(payment.label, PAYMENT_LABEL_CHARS)}  ({when})"


def _share(share: float) -> str:
    return f"{share:.0f} %"


# -- merchants --------------------------------------------------------------------------------


def merchants_chart(merchants: Sequence[MerchantTotal], theme: ChartTheme) -> Chart:
    """The merchants that received the most money."""
    if not merchants:
        return message_chart(NO_SPENDING, theme)
    shown = list(reversed(merchants))  # largest at the top
    amounts = [float(merchant.amount) for merchant in shown]
    with themed(theme):
        figure = new_figure()
        axes = add_axes(figure, theme)
        bars = axes.barh(range(len(shown)), amounts, color=MERCHANT_COLOR)
        for row, merchant in enumerate(shown):
            axes.text(amounts[row], row, f" {euro(merchant.amount)}", va="center",
                      fontsize=TINY_FONT)  # fmt: skip
        labels = [short(merchant.label) for merchant in shown]
        axes.set_yticks(range(len(shown)), labels)
        axes.set_xlabel(EURO_AXIS)
        axes.set_title("Top-Empfänger nach Ausgaben")
        grid(axes, theme, "x")
    pairs = zip(bars, shown, strict=True)
    return Chart(figure, tuple(DrillTarget(b, DrillKind.MERCHANT, m.merchant) for b, m in pairs))


# -- calendar ---------------------------------------------------------------------------------


def calendar_chart(calendar: CalendarGrid | None, theme: ChartTheme) -> Chart:
    """Spending per day as colored cells: weeks left to right, Monday at the top."""
    if calendar is None:
        return message_chart(NO_SPENDING, theme)
    colormap = mpl.colormaps[CALENDAR_COLORMAP]
    norm = Normalize(0.0, max(_highest(calendar), MIN_COLOR_SCALE))
    with themed(theme):
        figure = new_figure()
        axes = add_axes(figure, theme)
        targets = _cells(axes, calendar, colormap, norm, theme)
        _calendar_axes(axes, calendar)
        _colorbar(figure, axes, colormap, norm, theme)
    return Chart(figure, tuple(targets))


def _cells(
    axes: Axes, calendar: CalendarGrid, colormap: Colormap, norm: Normalize, theme: ChartTheme
) -> list[DrillTarget]:
    """One rectangle per day of the range; days with spending are clickable. Cells are added
    as plain artists: the limits are set explicitly, and ``add_patch`` would recompute them
    for every one of the up to a few thousand cells."""
    targets: list[DrillTarget] = []
    for row, week, amount in _filled(calendar):
        cell = Rectangle((week, row), CELL_SIZE, CELL_SIZE, edgecolor=theme.face,
                         facecolor=colormap(norm(float(amount))), linewidth=CELL_EDGE)  # fmt: skip
        cell.set_clip_path(axes.patch)
        axes.add_artist(cell)
        if amount > 0:
            day = calendar.day_at(row, week)
            targets.append(DrillTarget(cell, DrillKind.DAY, day.isoformat()))
    return targets


def _filled(calendar: CalendarGrid) -> list[tuple[int, int, Decimal]]:
    return [
        (row, week, amount)
        for row, cells in enumerate(calendar.cells)
        for week, amount in enumerate(cells)
        if amount is not None
    ]


def _highest(calendar: CalendarGrid) -> float:
    return max((float(amount) for _, _, amount in _filled(calendar)), default=0.0)


def _calendar_axes(axes: Axes, calendar: CalendarGrid) -> None:
    axes.set_xlim(0, calendar.weeks * CELL_SIZE)
    axes.set_ylim(DAYS_PER_WEEK * CELL_SIZE, 0)  # Monday at the top
    axes.set_aspect("equal")
    axes.set_yticks([row + CELL_MIDDLE for row in range(DAYS_PER_WEEK)], WEEKDAYS)
    starts = _month_starts(calendar)
    axes.set_xticks([week for week, _ in starts], [label for _, label in starts])
    axes.tick_params(length=0)
    for spine in axes.spines.values():
        spine.set_visible(False)
    axes.set_title("Kalender-Heatmap der Tagesausgaben")


def _month_starts(calendar: CalendarGrid) -> list[tuple[int, str]]:
    """Every column in which a month of the range begins, labeled like ``Jul 26``. The first
    column always gets a label: the month beginning in it, else the month of its first day
    (a range starting on 29 April and 1 May in the same column reads "Mai")."""
    starts: list[tuple[int, str]] = []
    for week in range(calendar.weeks):
        days = _days_in_range(calendar, week)
        firsts = [day for day in days if day.day == FIRST_OF_MONTH]
        if firsts or not starts:
            starts.append((week, month_label(f"{(firsts or days)[0]:%Y-%m}")))
    return starts


def _days_in_range(calendar: CalendarGrid, week: int) -> list[date]:
    """The days of column ``week`` that belong to the range (not padding cells)."""
    return [
        calendar.day_at(row, week)
        for row in range(DAYS_PER_WEEK)
        if calendar.cells[row][week] is not None
    ]


def _colorbar(
    figure: Figure, axes: Axes, colormap: Colormap, norm: Normalize, theme: ChartTheme
) -> None:
    bar = figure.colorbar(ScalarMappable(norm, colormap), ax=axes, fraction=COLORBAR_FRACTION)
    bar.set_label(f"Ausgaben je Tag ({EURO_AXIS})", fontsize=SMALL_FONT)
    bar.ax.tick_params(colors=theme.text, labelsize=SMALL_FONT)
    bar.outline.set_visible(False)
