"""Dividing one booking over several categories, with a live check of the sum."""

import tkinter as tk
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from tkinter import ttk
from typing import Final

from iaah.core.assignments import SplitPart, validate_split
from iaah.core.errors import SplitError
from iaah.core.models import Transaction
from iaah.core.text import clean_display, format_euro, format_plain_german, parse_amount
from iaah.gui.dialogs.base import Dialog
from iaah.gui.texts import error_message
from iaah.gui.theme import FONT_BOLD, PAD

COMBO_WIDTH: Final = 24
AMOUNT_WIDTH: Final = 12
REMOVE: Final = "✕"
REMOVE_WIDTH: Final = 2
LINE_GAP: Final = 1
HINT: Final = "Beträge ohne Vorzeichen eingeben – sie bekommen das der Buchung."


@dataclass(slots=True)
class _Line:
    frame: ttk.Frame
    category: ttk.Combobox
    amount: ttk.Entry


class SplitDialog(Dialog[list[SplitPart]]):
    """Rows of category and amount; *Zeile +* adds one, ✕ removes one."""

    def __init__(
        self,
        parent: tk.Misc,
        txn: Transaction,
        categories: Sequence[str],
        current: Sequence[SplitPart],
    ) -> None:
        super().__init__(parent, "Buchung aufteilen", "Speichern")
        self._txn = txn
        self._categories = list(categories)
        heading = f"{clean_display(txn.payee)}   {format_euro(txn.amount)}"
        ttk.Label(self.body, text=heading, font=FONT_BOLD).pack(anchor="w")
        ttk.Label(self.body, text=HINT, style="Muted.TLabel").pack(anchor="w", pady=(0, PAD))
        self._lines_frame = ttk.Frame(self.body)
        self._lines_frame.pack(fill="x")
        self._lines: list[_Line] = []
        for part in self._initial(current):
            self._add_line(part.category, part.amount)
        ttk.Button(self.body, text="Zeile +", command=lambda: self._add_line("", None)).pack(
            anchor="w", pady=PAD
        )
        self._sum = ttk.Label(self.body, text="")
        self._sum.pack(anchor="w")
        self._update_sum()

    def _initial(self, current: Sequence[SplitPart]) -> list[SplitPart]:
        """The existing split, else the current category with the whole amount plus an empty
        second row."""
        if len(current) > 1:
            return list(current)
        first = current[0].category if current else self._categories[0]
        return [SplitPart(first, self._txn.amount), SplitPart("", Decimal(0))]

    def _add_line(self, category: str, amount: Decimal | None) -> None:
        frame = ttk.Frame(self._lines_frame)
        frame.pack(fill="x", pady=LINE_GAP)
        combo = ttk.Combobox(frame, values=self._categories, state="readonly", width=COMBO_WIDTH)
        combo.set(category)
        combo.pack(side="left")
        entry = ttk.Entry(frame, width=AMOUNT_WIDTH, justify="right")
        if amount:
            entry.insert(0, format_plain_german(abs(amount)))
        entry.pack(side="left", padx=PAD)
        line = _Line(frame, combo, entry)
        ttk.Button(frame, text=REMOVE, width=REMOVE_WIDTH, command=lambda: self._remove(line)).pack(
            side="left"
        )
        combo.bind("<<ComboboxSelected>>", lambda _event: self._update_sum())
        entry.bind("<KeyRelease>", lambda _event: self._update_sum())
        self._lines.append(line)

    def _remove(self, line: _Line) -> None:
        line.frame.destroy()
        self._lines.remove(line)
        self._update_sum()

    def _parts(self) -> list[SplitPart] | None:
        """The filled rows as parts with the booking's sign; ``None`` if an amount is invalid."""
        parts: list[SplitPart] = []
        for line in self._lines:
            text = line.amount.get().strip()
            if not text and not line.category.get():
                continue
            amount = parse_amount(text)
            if amount is None:
                return None
            parts.append(SplitPart(line.category.get(), abs(amount).copy_sign(self._txn.amount)))
        return parts

    def _update_sum(self) -> None:
        parts = self._parts()
        if parts is None:
            self._sum.configure(text="⚠ Ungültiger Betrag", style="Bad.TLabel")
            return
        total = sum((part.amount for part in parts), Decimal(0))
        difference = self._txn.amount - total
        shown = f"Summe {format_euro(total)} / Buchung {format_euro(self._txn.amount)}"
        if difference:
            self._sum.configure(
                text=f"{shown}   ⚠ Differenz {format_euro(difference)}", style="Bad.TLabel"
            )
        else:
            self._sum.configure(text=f"{shown}   ✓ passt", style="Good.TLabel")

    def result_or_none(self) -> list[SplitPart] | None:
        parts = self._parts()
        if parts is None or any(not part.category for part in parts):
            self.show_error("Jede Zeile braucht eine Kategorie und einen gültigen Betrag.")
            return None
        try:
            return list(validate_split(self._txn.amount, parts))
        except SplitError as error:
            self.show_error(error_message(error))
            return None
