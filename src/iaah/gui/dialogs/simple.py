"""Password and new-category dialogs, and the windows that list bookings or show a report."""

import tkinter as tk
from collections.abc import Sequence
from tkinter import colorchooser, ttk
from typing import Final

from iaah.core.analysis.ledger import ZERO, Entry
from iaah.core.categories import CategoryCatalog
from iaah.core.text import clean_display, format_euro
from iaah.gui.dialogs.base import Dialog
from iaah.gui.theme import FONT_BOLD, FONT_MONO, PAD, PAD_LARGE
from iaah.gui.viewmodel import day_label
from iaah.gui.widgets import ColumnSpec, ScrolledTree

MASK: Final = "•"
ENTRY_WIDTH: Final = 32
PROMPT_WRAP: Final = 320  # pixels
SWATCH_SIZE: Final = 24
PURPOSE_CHARS: Final = 60
LIST_SIZE: Final = "760x440"
TEXT_SIZE: Final = "720x480"
TEXT_WIDTH: Final = 90
ENTRY_COLUMNS: Final = (
    ColumnSpec("day", "Datum", 80),
    ColumnSpec("payee", "Empfänger", 200, stretch=True),
    ColumnSpec("purpose", "Zweck", 240, stretch=True),
    ColumnSpec("amount", "Betrag", 100, "e"),
    ColumnSpec("category", "Kategorie", 120),
)


class PasswordDialog(Dialog[str]):
    """Asks for a password; with ``confirm`` twice (when setting one)."""

    def __init__(self, parent: tk.Misc, title: str, prompt: str, confirm: bool = False) -> None:
        super().__init__(parent, title, "OK")
        ttk.Label(self.body, text=prompt, wraplength=PROMPT_WRAP).pack(anchor="w")
        self._first = ttk.Entry(self.body, show=MASK, width=ENTRY_WIDTH)
        self._first.pack(fill="x", pady=PAD)
        self._second: ttk.Entry | None = None
        if confirm:
            ttk.Label(self.body, text="Noch einmal:").pack(anchor="w")
            self._second = ttk.Entry(self.body, show=MASK, width=ENTRY_WIDTH)
            self._second.pack(fill="x", pady=PAD)
        self.initial_focus = self._first

    def result_or_none(self) -> str | None:
        password = self._first.get()
        if not password:
            self.show_error("Bitte ein Passwort eingeben.")
            return None
        if self._second is not None and self._second.get() != password:
            self.show_error("Die beiden Passwörter stimmen nicht überein.")
            return None
        return password


class NewCategoryDialog(Dialog[tuple[str, str]]):
    """Name and color of a new category; the color defaults to the next free one."""

    def __init__(self, parent: tk.Misc, catalog: CategoryCatalog) -> None:
        super().__init__(parent, "Neue Kategorie", "Anlegen")
        self._catalog = catalog
        self._color = catalog.next_color()
        ttk.Label(self.body, text="Name:").grid(row=0, column=0, sticky="w")
        self._name = ttk.Entry(self.body, width=ENTRY_WIDTH)
        self._name.grid(row=0, column=1, sticky="ew", padx=PAD)
        ttk.Label(self.body, text="Farbe:").grid(row=1, column=0, sticky="w", pady=PAD)
        self._swatch = tk.Frame(self.body, width=SWATCH_SIZE, height=SWATCH_SIZE, bg=self._color)
        self._swatch.grid(row=1, column=1, sticky="w", padx=PAD)
        ttk.Button(self.body, text="Ändern…", command=self._pick).grid(row=1, column=2)
        self.initial_focus = self._name

    def _pick(self) -> None:
        _, chosen = colorchooser.askcolor(self._color, parent=self, title="Farbe wählen")
        if chosen:
            self._color = chosen.lower()
            self._swatch.configure(bg=self._color)

    def result_or_none(self) -> tuple[str, str] | None:
        name = self._name.get().strip()
        if not name:
            self.show_error("Bitte einen Namen eingeben.")
            return None
        if name in self._catalog:
            self.show_error(f"„{name}“ gibt es schon.")
            return None
        return name, self._color


def show_entries(parent: tk.Misc, title: str, entries: Sequence[Entry]) -> None:
    """A window listing bookings (split parts with their part amount) and their sum."""
    window = tk.Toplevel(parent)
    window.title(title)
    window.geometry(LIST_SIZE)
    table = ScrolledTree(window, ENTRY_COLUMNS, selectmode="browse")
    table.pack(fill="both", expand=True, padx=PAD, pady=PAD)
    ordered = sorted(entries, key=lambda entry: entry.day)
    table.fill((str(n), _entry_cells(entry), ()) for n, entry in enumerate(ordered))
    total = sum((entry.amount for entry in entries), ZERO)
    summary = f"{len(entries)} Buchungen   Summe: {format_euro(total)}"
    ttk.Label(window, text=summary, font=FONT_BOLD).pack(anchor="e", padx=PAD_LARGE, pady=PAD)


def _entry_cells(entry: Entry) -> tuple[str, ...]:
    return (
        day_label(entry.day),
        clean_display(entry.transaction.payee),
        clean_display(entry.transaction.purpose)[:PURPOSE_CHARS],
        format_euro(entry.amount),
        entry.category,
    )


def show_text(parent: tk.Misc, title: str, text: str) -> None:
    """A window with a longer, selectable text (migration report, import details)."""
    window = tk.Toplevel(parent)
    window.title(title)
    window.geometry(TEXT_SIZE)
    box = tk.Text(window, wrap="word", font=FONT_MONO, width=TEXT_WIDTH)
    box.insert("1.0", text)
    box.configure(state="disabled")
    box.pack(fill="both", expand=True, padx=PAD, pady=PAD)
    ttk.Button(window, text="Schließen", command=window.destroy).pack(pady=PAD)
