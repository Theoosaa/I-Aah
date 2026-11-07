"""Budgets tab: a monthly budget per expense category, with the actual spending of a period."""

import tkinter as tk
from decimal import Decimal
from tkinter import messagebox, ttk
from typing import Final

from iaah.core.analysis.ledger import Period
from iaah.core.analysis.totals import BudgetLevel
from iaah.core.text import format_euro, format_plain_german
from iaah.gui.host import Host
from iaah.gui.tabs.transactions import period_label
from iaah.gui.texts import APP_TITLE
from iaah.gui.theme import FONT_BOLD, PAD, PAD_LARGE, Palette
from iaah.gui.viewmodel import BudgetRow, budget_from_text, budget_rows, periods

INTRO: Final = (
    "Monatsbudget je Ausgabe-Kategorie. Leer oder 0 entfernt ein Budget. Daneben steht, was im "
    "gewählten Zeitraum im Schnitt pro Monat ausgegeben wurde, und wie voll das Budget ist."
)
HEADINGS: Final = ("", "Kategorie", "Budget €/Monat", "Ø Ist €/Monat", "Stand")
LEVEL_TEXTS: Final[dict[BudgetLevel, str]] = {
    BudgetLevel.OK: "im Rahmen",
    BudgetLevel.WARNING: "fast erreicht",
    BudgetLevel.OVER: "überzogen",
}
PERCENT: Final = 100
ENTRY_WIDTH: Final = 12
SWATCH: Final = 14
WRAP: Final = 700
FIRST_ROW: Final = 1  # below the headings


class BudgetsTab(ttk.Frame):
    """Intro, period choice, one row per expense category, save button."""

    def __init__(self, parent: tk.Misc, host: Host) -> None:
        super().__init__(parent, padding=PAD_LARGE)
        self.host = host
        self._periods: list[Period] = [Period.all_time()]
        self._entries: dict[str, ttk.Entry] = {}
        ttk.Label(self, text=INTRO, wraplength=WRAP, justify="left").pack(anchor="w")
        bar = ttk.Frame(self)
        bar.pack(anchor="w", pady=PAD)
        ttk.Label(bar, text="Zeitraum:").pack(side="left")
        self.period = ttk.Combobox(bar, state="readonly", width=ENTRY_WIDTH)
        self.period.pack(side="left", padx=PAD)
        self.period.bind("<<ComboboxSelected>>", lambda _event: self.refresh())
        self.grid_frame = ttk.Frame(self)
        self.grid_frame.pack(anchor="w", pady=PAD)
        ttk.Button(self, text="Budgets speichern", command=self.save).pack(anchor="w", pady=PAD)

    def refresh(self) -> None:
        """Rows for the catalog's expense categories and the chosen period."""
        position = self.period.current()
        chosen = self._periods[position] if 0 <= position < len(self._periods) else None
        self._periods = periods(self.host.session.transactions)
        self.period.configure(values=[period_label(p) for p in self._periods])
        self.period.current(self._periods.index(chosen) if chosen in self._periods else 0)
        session = self.host.session
        rows = budget_rows(session.entries(), session.catalog, self._periods[self.period.current()])
        typed = self._typed(rows)
        for child in self.grid_frame.winfo_children():
            child.destroy()
        for column, heading in enumerate(HEADINGS):
            ttk.Label(self.grid_frame, text=heading, font=FONT_BOLD).grid(
                row=0, column=column, sticky="w", padx=PAD
            )
        self._entries = {
            row.category: self._row(line, row) for line, row in enumerate(rows, start=FIRST_ROW)
        }
        for name, text in typed.items():
            if name in self._entries:
                _replace(self._entries[name], text)

    def _typed(self, rows: list[BudgetRow]) -> dict[str, str]:
        """Entries the user changed but did not save yet – they survive a refresh."""
        stored = {row.category: _budget_text(row.budget) for row in rows}
        return {
            name: entry.get()
            for name, entry in self._entries.items()
            if entry.winfo_exists() and entry.get().strip() != stored.get(name, "")
        }

    def _row(self, line: int, row: BudgetRow) -> ttk.Entry:
        tk.Frame(self.grid_frame, width=SWATCH, height=SWATCH, bg=row.color).grid(
            row=line, column=0, padx=PAD
        )
        ttk.Label(self.grid_frame, text=row.category).grid(row=line, column=1, sticky="w", padx=PAD)
        entry = ttk.Entry(self.grid_frame, width=ENTRY_WIDTH, justify="right")
        entry.insert(0, _budget_text(row.budget))
        entry.grid(row=line, column=2, padx=PAD)
        ttk.Label(self.grid_frame, text=format_euro(row.average), style="Muted.TLabel").grid(
            row=line, column=3, sticky="e", padx=PAD
        )
        text, color = _state(row, self.host.palette)
        ttk.Label(self.grid_frame, text=text, foreground=color).grid(
            row=line, column=4, sticky="w", padx=PAD
        )
        return entry

    def save(self) -> None:
        """Validate every entry, then store all budgets at once."""
        budgets: dict[str, Decimal | None] = {}
        for name, entry in self._entries.items():
            try:
                budgets[name] = budget_from_text(entry.get())
            except ValueError:
                messagebox.showerror(
                    APP_TITLE, f"Das Budget für „{name}“ ist kein gültiger Betrag.", parent=self
                )
                return
        if self.host.run(lambda: self.host.session.set_budgets(budgets)):
            self.host.status("Budgets gespeichert.")


def _budget_text(budget: Decimal | None) -> str:
    return format_plain_german(budget) if budget is not None else ""


def _replace(entry: ttk.Entry, text: str) -> None:
    entry.delete(0, "end")
    entry.insert(0, text)


def _state(row: BudgetRow, palette: Palette) -> tuple[str, str]:
    if row.level is None or row.ratio is None:
        return "", palette.muted
    colors = {
        BudgetLevel.OK: palette.good,
        BudgetLevel.WARNING: palette.warn,
        BudgetLevel.OVER: palette.bad,
    }
    color = colors[row.level]
    return f"{row.ratio * PERCENT:.0f} % – {LEVEL_TEXTS[row.level]}", color
