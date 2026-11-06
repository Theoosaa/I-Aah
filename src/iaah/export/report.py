"""A PDF report of a period: cover page with the key figures, then one chart per page.

Built from the same ``ChartInput`` as the analysis tab, always in the light theme (printed
paper is white). Each chart page carries its caption, so the report explains itself.
"""

import textwrap
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Final

from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure

from iaah.charts.chart import CAPTIONS, ChartKind
from iaah.charts.gallery import ChartInput, build_chart
from iaah.charts.style import LIGHT, SMALL_FONT, month_label, percent, period_label
from iaah.core.analysis.ledger import months_of
from iaah.core.analysis.timeline import missing_months
from iaah.core.analysis.totals import Kpis, kpis
from iaah.core.text import format_euro
from iaah.export.files import write_export

REPORT_CHARTS: Final = (
    ChartKind.OVERVIEW,
    ChartKind.CATEGORIES,
    ChartKind.FIXED_COSTS,
    ChartKind.MERCHANTS,
    ChartKind.BALANCE,
)
A4_PORTRAIT: Final = (8.27, 11.69)  # inches
A4_LANDSCAPE: Final = (11.69, 8.27)
COVER_LEFT: Final = 0.08
COVER_TOP: Final = 0.92  # figure coordinates
BODY_TOP: Final = 0.84
TITLE_SIZE: Final = 20
COVER_TEXT_SIZE: Final = 12
CAPTION_CHARS: Final = 150  # per line at A4 landscape
DATE_FORMAT: Final = "%d.%m.%Y"
TITLE: Final = "I-Aah – Auswertung"
CREATOR: Final = "I-Aah"
NO_DATA: Final = "–"
LABEL_WIDTH: Final = 22


def render_report(data: ChartInput, created: date | None = None) -> bytes:
    """The report as PDF bytes; ``created`` defaults to today."""
    buffer = BytesIO()
    with PdfPages(buffer, metadata={"Creator": CREATOR, "Title": TITLE}) as pdf:
        pdf.savefig(_cover(data, created or date.today()))
        for kind in report_charts(data):
            figure = build_chart(kind, data, LIGHT).figure
            figure.set_size_inches(A4_LANDSCAPE)
            figure.supxlabel(textwrap.fill(CAPTIONS[kind], CAPTION_CHARS), fontsize=SMALL_FONT,
                             color=LIGHT.muted)  # fmt: skip
            pdf.savefig(figure)
    return buffer.getvalue()


def write_report(data: ChartInput, path: Path, created: date | None = None) -> None:
    """Save the report as PDF."""
    write_export(path, render_report(data, created))


def report_charts(data: ChartInput) -> list[ChartKind]:
    """The report's charts; the budget page only when budgets are set."""
    kinds = list(REPORT_CHARTS)
    if data.budgets:
        kinds.insert(kinds.index(ChartKind.FIXED_COSTS), ChartKind.BUDGET)
    return kinds


def cover_lines(data: ChartInput, created: date) -> list[str]:
    """The text of the cover page: period, key figures, gaps in the imported months."""
    entries = data.entries
    figures = kpis(entries)
    missing = missing_months(months_of(entries))
    lines = [f"Zeitraum: {period_label(data.period)}", "", *_kpi_lines(figures), ""]
    if missing:  # derived from bookings: a statement may exist, but it has no booking
        lines.append(f"Monate ohne Buchungen: {', '.join(map(month_label, missing))}")
    lines.append(f"Erstellt am {created.strftime(DATE_FORMAT)}")
    return lines


def _kpi_lines(figures: Kpis) -> list[str]:
    totals = figures.totals
    rate = totals.savings_rate
    rows = (
        ("Einnahmen", format_euro(totals.income)),
        ("Ausgaben", format_euro(totals.expense)),
        ("Netto gespart", format_euro(totals.net)),
        ("Sparquote", percent(rate) if rate is not None else NO_DATA),
        ("Ø Ausgaben je Monat", format_euro(figures.average_monthly_expense)),
        ("Monate mit Buchungen", str(figures.months)),
    )
    return [f"{label + ':':<{LABEL_WIDTH}}{value}" for label, value in rows]


def _cover(data: ChartInput, created: date) -> Figure:
    figure = Figure(figsize=A4_PORTRAIT)
    figure.text(COVER_LEFT, COVER_TOP, TITLE, fontsize=TITLE_SIZE, fontweight="bold", va="top")
    body = "\n".join(cover_lines(data, created))
    figure.text(COVER_LEFT, BODY_TOP, body, fontsize=COVER_TEXT_SIZE, va="top",
                family="monospace")  # fmt: skip
    return figure
