"""The look of every chart: light and dark theme, semantic colors and shared helpers.

Builders draw inside ``themed(theme)``: figure, axes and text pick up the theme's colors when
they are created. Ticks are created lazily at draw time, so ``add_axes`` also stores the tick
colors on the axes.
"""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Literal

import matplotlib as mpl
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.typing import RcKeyType

from iaah.core.analysis.ledger import Period, PeriodKind
from iaah.core.categories import UNKNOWN_COLOR
from iaah.core.text import format_euro

INCOME_COLOR: Final = "#2e7d32"
EXPENSE_COLOR: Final = "#e53935"
NET_COLOR: Final = "#1e88e5"
RATE_COLOR: Final = NET_COLOR  # readable on light and dark backgrounds
INK_ON_PASTEL: Final = "#222222"  # category colors are pastel: dark text in both themes
INK_ON_DARK: Final = "#ffffff"  # for the saturated fixed/variable colors
FIXED_COLOR: Final = "#6d4c41"
VARIABLE_COLOR: Final = "#90a4ae"
PREVIOUS_COLOR: Final = "#bdbdbd"
MERCHANT_COLOR: Final = "#5e35b1"
CALENDAR_COLORMAP: Final = "YlOrRd"

FIGURE_SIZE: Final = (10.0, 6.0)  # inches; the GUI canvas and the report resize it
BASE_FONT: Final = 9
TITLE_FONT: Final = 11
SMALL_FONT: Final = 8
TINY_FONT: Final = 7
LINE_WIDTH: Final = 2.0
THIN_LINE: Final = 0.8
GRID_ALPHA: Final = 0.3
LABEL_ROTATION: Final = 45
FILL_ALPHA: Final = 0.15
CENTER: Final = 0.5  # axes coordinates of the middle
EURO_AXIS: Final = "EUR"
PERCENT: Final = 100

MONTH_ABBREVIATIONS: Final = (
    "Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez",
)  # fmt: skip
MONTH_NAMES: Final = (
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
)  # fmt: skip
ALL_TIME_LABEL: Final = "Gesamter Zeitraum"
LABEL_CHARS: Final = 28  # category and merchant names in legends and on axes
ELLIPSIS: Final = "…"
YEAR_DIGITS: Final = 2  # "Jul 26"


@dataclass(frozen=True, slots=True)
class ChartTheme:
    """Background, text and neutral colors of one theme."""

    name: str
    face: str  # figure background, also the gap between wedges and calendar cells
    axes: str  # plot area
    text: str
    muted: str  # hints, zero lines, grid
    track: str  # empty part of a budget bar

    @property
    def rc(self) -> dict[RcKeyType, Any]:
        """matplotlib settings for building inside ``themed``."""
        return {
            "figure.facecolor": self.face,
            "axes.facecolor": self.axes,
            "axes.edgecolor": self.muted,
            "axes.labelcolor": self.text,
            "axes.titlecolor": self.text,
            "axes.titlesize": TITLE_FONT,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "text.color": self.text,
            "font.size": BASE_FONT,
            "legend.fontsize": SMALL_FONT,
            "legend.frameon": False,
            "legend.labelcolor": self.text,
            # Payees are written by other people: "$" must stay text, never mathtext.
            "text.parse_math": False,
        }


LIGHT: Final = ChartTheme("light", "#ffffff", "#ffffff", "#222222", "#888888", "#eeeeee")
DARK: Final = ChartTheme("dark", "#232629", "#2b2f33", "#e6e6e6", "#a0a0a0", "#3a3f44")


@contextmanager
def themed(theme: ChartTheme) -> Iterator[None]:
    """Build figures with the theme's colors."""
    with mpl.rc_context(theme.rc):
        yield


def new_figure() -> Figure:
    """An empty figure with constrained layout (call inside ``themed``)."""
    return Figure(figsize=FIGURE_SIZE, layout="constrained")


def add_axes(figure: Figure, theme: ChartTheme, *position: int) -> Axes:
    """A subplot whose ticks – created later, at draw time – use the theme's colors."""
    axes = figure.add_subplot(*(position or (1, 1, 1)))
    axes.tick_params(colors=theme.text, labelsize=SMALL_FONT)
    return axes


type GridAxis = Literal["both", "x", "y"]


def grid(axes: Axes, theme: ChartTheme, axis: GridAxis = "both") -> None:
    """Light grid lines behind the data."""
    axes.set_axisbelow(True)
    axes.grid(True, axis=axis, color=theme.muted, alpha=GRID_ALPHA)


def month_axis(axes: Axes, months: Sequence[str]) -> None:
    """Months (``YYYY-MM``) as x tick labels at positions 0, 1, …"""
    axes.set_xticks(range(len(months)), [month_label(month) for month in months])
    axes.tick_params(axis="x", labelrotation=LABEL_ROTATION)


def month_label(month: str) -> str:
    """``"2026-07"`` → ``"Jul 26"``."""
    period = Period.parse(month)
    return f"{MONTH_ABBREVIATIONS[period.month - 1]} {period.year % 10**YEAR_DIGITS:02d}"


def period_label(period: Period) -> str:
    """``"Juli 2026"``, ``"2026"`` or ``"Gesamter Zeitraum"``."""
    if period.kind is PeriodKind.ALL:
        return ALL_TIME_LABEL
    if period.kind is PeriodKind.YEAR:
        return str(period.year)
    return f"{MONTH_NAMES[period.month - 1]} {period.year}"


def euro(amount: Decimal) -> str:
    """German money format for labels."""
    return format_euro(amount)


def percent(ratio: Decimal) -> str:
    """``Decimal("0.253")`` → ``"25 %"``."""
    return f"{ratio * PERCENT:.0f} %"


def short(text: str, limit: int = LABEL_CHARS) -> str:
    """``text`` cut to ``limit`` characters with an ellipsis – long names must not squeeze the
    plot out of the figure."""
    return text if len(text) <= limit else text[: limit - 1] + ELLIPSIS


def color_of(colors: Mapping[str, str], category: str) -> str:
    """A category's color; a neutral grey for names the mapping does not know."""
    return colors.get(category, UNKNOWN_COLOR)


def show_message(axes: Axes, message: str, theme: ChartTheme) -> None:
    """Replace the plot by an explanatory text."""
    axes.axis("off")
    axes.text(CENTER, CENTER, message, ha="center", va="center", color=theme.muted,
              transform=axes.transAxes)  # fmt: skip
