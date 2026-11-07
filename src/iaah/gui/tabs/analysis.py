"""Analysis tab: period and chart choice, KPI cards with deltas, the chart, its caption, and a
booking list for a clicked chart element."""

import tkinter as tk
from tkinter import ttk
from typing import Final

from matplotlib.backend_bases import Event, MouseEvent

# The toolbar is defined in _backend_tk; backend_tkagg re-exports it without declaring it.
from matplotlib.backends._backend_tk import NavigationToolbar2Tk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from iaah.charts.chart import CAPTIONS, TITLES, Chart, ChartKind, DrillKind
from iaah.charts.gallery import build_chart
from iaah.charts.style import percent, period_label
from iaah.core.analysis.ledger import Period
from iaah.core.merchants import merchant_label
from iaah.core.text import format_euro
from iaah.gui.dialogs.simple import show_entries
from iaah.gui.host import Host
from iaah.gui.tabs.transactions import period_label as combo_label
from iaah.gui.theme import PAD, Palette
from iaah.gui.viewmodel import Delta, KpiView, Trend, periods
from iaah.gui.widgets import KpiCard

CARDS: Final = ("Einnahmen", "Ausgaben", "Netto gespart", "Sparquote", "Ø Ausgaben / Monat")
NO_RATE: Final = "–"
VERSUS: Final = "ggü. Vorperiode"
DRILL_HINT: Final = "   (Tipp: Klick auf ein Element zeigt die Buchungen.)"
CAPTION_MARGIN: Final = 24  # pixels between caption and window edge
CHART_WIDTH: Final = 42
PERIOD_WIDTH: Final = 12


class AnalysisTab(ttk.Frame):
    """Controls on top, KPI cards, the chart and its caption below."""

    def __init__(self, parent: tk.Misc, host: Host) -> None:
        super().__init__(parent, padding=PAD)
        self.host = host
        self._periods: list[Period] = [Period.all_time()]
        self._kinds = list(ChartKind)
        self._chart: Chart | None = None
        self._canvas: FigureCanvasTkAgg | None = None
        self._toolbar: NavigationToolbar2Tk | None = None
        self._pending_period = ""
        self._build_controls()
        self._build_cards()
        self.figure_frame = ttk.Frame(self)
        self.figure_frame.grid(row=2, column=0, sticky="nsew", pady=PAD)
        self.caption = ttk.Label(self, text="", style="Muted.TLabel")
        self.bind("<Configure>", lambda event: self.caption.configure(
            wraplength=max(event.width - CAPTION_MARGIN, CAPTION_MARGIN)))  # fmt: skip
        self.caption.grid(row=3, column=0, sticky="w")
        self.rowconfigure(2, weight=1)
        self.columnconfigure(0, weight=1)

    def _build_controls(self) -> None:
        bar = ttk.Frame(self)
        bar.grid(row=0, column=0, sticky="ew")
        ttk.Label(bar, text="Zeitraum:").pack(side="left")
        self.period = ttk.Combobox(bar, state="readonly", width=PERIOD_WIDTH)
        self.period.pack(side="left", padx=PAD)
        ttk.Label(bar, text="Diagramm:").pack(side="left", padx=(PAD, 0))
        self.kind = ttk.Combobox(
            bar, state="readonly", width=CHART_WIDTH, values=[TITLES[kind] for kind in self._kinds]
        )
        self.kind.current(0)
        self.kind.pack(side="left", padx=PAD)
        for combo in (self.period, self.kind):
            combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh())
        self.gaps = ttk.Label(bar, text="", style="Bad.TLabel")
        self.gaps.pack(side="right")

    def _build_cards(self) -> None:
        row = ttk.Frame(self)
        row.grid(row=1, column=0, sticky="ew", pady=(PAD, 0))
        self.cards = [KpiCard(row, title) for title in CARDS]
        for column, card in enumerate(self.cards):
            card.grid(row=0, column=column, sticky="ew", padx=(0, PAD))
            row.columnconfigure(column, weight=1)

    # -- state for the UI file ----------------------------------------------------------------

    @property
    def selected_period(self) -> Period:
        """The chosen period."""
        position = self.period.current()
        return self._periods[position] if 0 <= position < len(self._periods) else Period.all_time()

    @property
    def selected_kind(self) -> ChartKind:
        """The chosen chart."""
        return self._kinds[max(self.kind.current(), 0)]

    def choose(self, period: str, kind: str) -> None:
        """Restore a period (``"2026-07"``) and a chart kind (``"overview"``) saved earlier;
        applied at the next refresh, when the periods are known."""
        self._pending_period = period
        if kind in {k.value for k in self._kinds}:
            self.kind.current(self._kinds.index(ChartKind(kind)))

    # -- drawing ------------------------------------------------------------------------------

    def refresh(self) -> None:
        """Rebuild period list, KPI cards and chart."""
        chosen = self.selected_period
        self._periods = periods(self.host.session.transactions)
        labels = [str(p) for p in self._periods]
        if self._pending_period in labels:
            chosen, self._pending_period = self._periods[labels.index(self._pending_period)], ""
        self.period.configure(values=[combo_label(p) for p in self._periods])
        self.period.current(self._periods.index(chosen) if chosen in self._periods else 0)
        period = self.selected_period
        self._show_cards(self.host.session.kpis(period))
        missing = self.host.session.missing_months()
        self.gaps.configure(text=f"Fehlende Monate: {', '.join(missing)}" if missing else "")
        self._show_chart(period)

    def _show_cards(self, view: KpiView) -> None:
        palette, totals = self.host.palette, view.figures.totals
        net_color = palette.good if totals.net >= 0 else palette.bad
        rate = totals.savings_rate
        values = (
            (format_euro(totals.income), palette.good, view.income),
            (format_euro(totals.expense), palette.bad, view.expense),
            (format_euro(totals.net), net_color, view.net),
            (percent(rate) if rate is not None else NO_RATE, palette.fg, view.savings_rate),
        )
        for card, (value, color, delta) in zip(self.cards, values, strict=False):
            card.show(value, color, *self._delta(delta, palette))
        basis = f"Basis: {view.figures.months} Monat(e)"
        average = format_euro(view.figures.average_monthly_expense)
        self.cards[-1].show(average, palette.fg, basis, palette.muted)

    @staticmethod
    def _delta(delta: Delta | None, palette: Palette) -> tuple[str, str]:
        if delta is None:
            return "", palette.muted
        colors = {Trend.GOOD: palette.good, Trend.BAD: palette.bad, Trend.NEUTRAL: palette.muted}
        return f"{delta.arrow} {delta.text} {VERSUS}", colors[delta.trend]

    def _show_chart(self, period: Period) -> None:
        kind = self.selected_kind
        data = self.host.session.chart_input(period)
        self._chart = build_chart(kind, data, self.host.palette.chart)
        if self._canvas is not None:
            self._canvas.get_tk_widget().destroy()
        if self._toolbar is not None:
            self._toolbar.destroy()
        self._canvas = FigureCanvasTkAgg(self._chart.figure, master=self.figure_frame)
        self._toolbar = NavigationToolbar2Tk(self._canvas, self.figure_frame, pack_toolbar=False)
        self._toolbar.pack(side="bottom", fill="x")
        self._canvas.get_tk_widget().pack(fill="both", expand=True)
        self._canvas.mpl_connect("button_press_event", self._click)
        self._canvas.draw_idle()  # one draw when Tk is idle, not one per call
        hint = DRILL_HINT if self._chart.targets else ""
        self.caption.configure(text=f"ⓘ  {CAPTIONS[kind]}{hint}")

    def _click(self, event: Event) -> None:
        if self._chart is None or not isinstance(event, MouseEvent):
            return
        for target in self._chart.targets:
            hit, _ = target.artist.contains(event)
            if hit:
                self._drill(target.kind, target.value)
                return

    def _drill(self, kind: DrillKind, value: str) -> None:
        period = self.selected_period
        entries = self.host.session.drill(kind, value, period)
        if not entries:
            return
        label = merchant_label(entries[0].transaction) if kind is DrillKind.MERCHANT else value
        show_entries(self, f"Buchungen – {label} ({period_label(period)})", entries)
