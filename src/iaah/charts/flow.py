"""Sankey chart: income on the left flows into the spending categories and the savings."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from matplotlib.axes import Axes
from matplotlib.patches import PathPatch
from matplotlib.path import Path

from iaah.charts.chart import Chart, DrillKind, DrillTarget, message_chart
from iaah.charts.style import (
    BASE_FONT,
    INCOME_COLOR,
    SMALL_FONT,
    ChartTheme,
    add_axes,
    color_of,
    euro,
    new_figure,
    short,
    themed,
)
from iaah.core.analysis.totals import MoneyFlow
from iaah.core.categories import UNKNOWN_COLOR

SOURCE_X: Final = 0.0  # income bar from here …
LEFT_X: Final = 0.08  # … to here, where the bands start
MID_X: Final = 0.5  # control points of the band curves
RIGHT_X: Final = 0.92  # bands end here
LABEL_X: Final = 0.93
TOP: Final = 1.0
GAP: Final = 0.02  # between bands on the right
BAND_ALPHA: Final = 0.55
INCOME_LABEL_Y: Final = 1.02
X_LIMITS: Final = (-0.02, 1.4)
Y_TOP: Final = 1.06
SAVED: Final = "Gespart"
OTHERS: Final = "Übrige Kategorien"
MAX_CATEGORY_BANDS: Final = 12  # more would leave the gaps no room
NO_SPENDING: Final = "Keine Ausgaben im Zeitraum."
BAND_CODES: Final = (
    Path.MOVETO, Path.LINETO, Path.CURVE4, Path.CURVE4, Path.CURVE4,
    Path.LINETO, Path.CURVE4, Path.CURVE4, Path.CURVE4,
)  # fmt: skip


@dataclass(frozen=True, slots=True)
class _Stream:
    label: str
    amount: Decimal
    color: str
    category: str | None  # the category to drill into; None for savings and grouped bands


def sankey_chart(flow: MoneyFlow, colors: Mapping[str, str], theme: ChartTheme) -> Chart:
    """Where the income went: one band per spending category plus the savings."""
    if not flow.outflows:
        return message_chart(NO_SPENDING, theme)
    streams = _streams(flow, colors)
    total = float(sum((stream.amount for stream in streams), Decimal(0)))
    scale = max(float(flow.income), total)  # left side: the larger of income and outflows
    with themed(theme):
        figure = new_figure()
        axes = add_axes(figure, theme)
        axes.axis("off")
        targets, lowest = _draw_streams(axes, streams, scale, total)
        _draw_income(axes, flow.income, scale)
        axes.set_xlim(*X_LIMITS)
        axes.set_ylim(min(0.0, lowest) - GAP, Y_TOP)
        axes.set_title("Geldfluss: Einnahmen → Ausgaben & Ersparnis")
    return Chart(figure, tuple(targets))


def _streams(flow: MoneyFlow, colors: Mapping[str, str]) -> list[_Stream]:
    """One band per category – beyond ``MAX_CATEGORY_BANDS`` the smallest ones share a band,
    so the gaps never eat the available height – plus the savings."""
    shown, rest = flow.outflows[: MAX_CATEGORY_BANDS - 1], flow.outflows[MAX_CATEGORY_BANDS - 1 :]
    if len(rest) == 1:
        shown, rest = flow.outflows, ()
    streams = [_Stream(short(name), amount, color_of(colors, name), name) for name, amount in shown]
    if rest:
        other = sum((amount for _, amount in rest), Decimal(0))
        streams.append(_Stream(f"{OTHERS} ({len(rest)})", other, UNKNOWN_COLOR, None))
    if flow.saved > 0:
        streams.append(_Stream(SAVED, flow.saved, INCOME_COLOR, None))
    return streams


def _draw_streams(
    axes: Axes, streams: Sequence[_Stream], scale: float, total: float
) -> tuple[list[DrillTarget], float]:
    """Bands from the income bar to the right, stacked top-down; returns the clickable bands
    and the lowest right edge."""
    available = TOP - GAP * (len(streams) - 1)
    left = right = TOP
    targets: list[DrillTarget] = []
    for stream in streams:
        left_height = float(stream.amount) / scale
        right_height = float(stream.amount) / total * available
        band = _band(axes, (left, left - left_height), (right, right - right_height), stream.color)
        axes.text(LABEL_X, right - right_height / 2, f"{stream.label}  {euro(stream.amount)}",
                  va="center", fontsize=SMALL_FONT)  # fmt: skip
        if stream.category is not None:
            targets.append(DrillTarget(band, DrillKind.CATEGORY, stream.category))
        left -= left_height
        right -= right_height + GAP
    return targets, right


def _band(
    axes: Axes, left: tuple[float, float], right: tuple[float, float], color: str
) -> PathPatch:
    """A curved band from ``left`` (top, bottom) to ``right`` (top, bottom)."""
    (left_top, left_bottom), (right_top, right_bottom) = left, right
    vertices = [
        (LEFT_X, left_bottom), (LEFT_X, left_top), (MID_X, left_top), (MID_X, right_top),
        (RIGHT_X, right_top), (RIGHT_X, right_bottom), (MID_X, right_bottom),
        (MID_X, left_bottom), (LEFT_X, left_bottom),
    ]  # fmt: skip
    patch = PathPatch(Path(vertices, BAND_CODES), facecolor=color, edgecolor="none",
                      alpha=BAND_ALPHA)  # fmt: skip
    axes.add_patch(patch)
    return patch


def _draw_income(axes: Axes, income: Decimal, scale: float) -> None:
    bottom = TOP - float(income) / scale
    corners = [(SOURCE_X, TOP), (LEFT_X, TOP), (LEFT_X, bottom), (SOURCE_X, bottom)]
    axes.add_patch(
        PathPatch(Path([*corners, corners[0]]), facecolor=INCOME_COLOR, edgecolor="none")
    )
    axes.text((SOURCE_X + LEFT_X) / 2, INCOME_LABEL_Y, f"Einnahmen {euro(income)}",
              ha="center", fontsize=BASE_FONT, fontweight="bold")  # fmt: skip
