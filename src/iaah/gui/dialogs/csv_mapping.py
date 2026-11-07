"""Choosing header row and columns of a CSV export whose layout was not recognised."""

import tkinter as tk
from tkinter import ttk
from typing import Final

from iaah.core.parsing.csv_import import CsvField, CsvTable, find_header, guess_mapping
from iaah.gui.dialogs.base import Dialog
from iaah.gui.theme import FONT_BOLD, PAD
from iaah.gui.widgets import ColumnSpec, ScrolledTree

NONE: Final = "(keine)"
NO_HEADER: Final = 0  # spinbox value: the file has no header row
PREVIEW_ROWS: Final = 5
PREVIEW_COLUMNS: Final = 8
PREVIEW_WIDTH: Final = 110
CELL_CHARS: Final = 30
COMBO_WIDTH: Final = 30
SPIN_WIDTH: Final = 5
ROW_GAP: Final = 1
FIRST_FIELD_ROW: Final = 2  # below file name and header row
FIELD_LABELS: Final[dict[CsvField, str]] = {
    CsvField.DATE: "Datum *",
    CsvField.AMOUNT: "Betrag *",
    CsvField.PAYEE: "Empfänger",
    CsvField.PURPOSE: "Verwendungszweck",
}
REQUIRED: Final = (CsvField.DATE, CsvField.AMOUNT)
PREVIEW_ROW: Final = FIRST_FIELD_ROW + len(FIELD_LABELS)

type Mapping = tuple[dict[CsvField, int], int | None]  # columns, header row index


class CsvMappingDialog(Dialog[Mapping]):
    """Header row (0 = none), the four columns, and a preview of the first bookings."""

    def __init__(self, parent: tk.Misc, table: CsvTable, filename: str) -> None:
        super().__init__(parent, "CSV-Spalten zuordnen", "Importieren")
        self._table = table
        ttk.Label(self.body, text=filename, font=FONT_BOLD).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(self.body, text="Kopfzeile (0 = keine):").grid(row=1, column=0, sticky="w")
        detected = find_header(table.rows)
        self._header = tk.IntVar(value=NO_HEADER if detected is None else detected + 1)
        ttk.Spinbox(
            self.body,
            from_=NO_HEADER,
            to=len(table.rows),
            width=SPIN_WIDTH,
            textvariable=self._header,
            command=self._refresh,
        ).grid(row=1, column=1, sticky="w", pady=PAD)
        self._combos = {
            field: self._combo(row, field)
            for row, field in enumerate(FIELD_LABELS, start=FIRST_FIELD_ROW)
        }
        self._preview = ScrolledTree(self.body, self._preview_columns(), selectmode="none")
        self._preview.grid(row=PREVIEW_ROW, column=0, columnspan=2, sticky="nsew", pady=PAD)
        self._refresh()

    def _combo(self, row: int, field: CsvField) -> ttk.Combobox:
        ttk.Label(self.body, text=FIELD_LABELS[field]).grid(row=row, column=0, sticky="w")
        combo = ttk.Combobox(self.body, state="readonly", width=COMBO_WIDTH)
        combo.grid(row=row, column=1, sticky="w", pady=ROW_GAP)
        return combo

    def _preview_columns(self) -> list[ColumnSpec]:
        widest = min(max((len(row) for row in self._table.rows), default=0), PREVIEW_COLUMNS)
        return [ColumnSpec(f"c{n}", f"Spalte {n + 1}", PREVIEW_WIDTH) for n in range(widest)]

    def _header_index(self) -> int | None:
        try:
            value = self._header.get()
        except tk.TclError:  # the spinbox holds no number while being edited
            return None
        return value - 1 if NO_HEADER < value <= len(self._table.rows) else None

    def _refresh(self) -> None:
        """Column choices from the header row, the automatic guess, and the preview."""
        index = self._header_index()
        header = self._table.rows[index] if index is not None else ()
        width = max((len(row) for row in self._table.rows), default=0)
        choices = [NONE, *(self._column_name(n, header) for n in range(width))]
        guess = guess_mapping(header) if header else {}
        for field, combo in self._combos.items():
            combo.configure(values=choices)
            combo.set(choices[guess[field] + 1] if field in guess else NONE)
        start = 0 if index is None else index + 1
        rows = self._table.rows[start : start + PREVIEW_ROWS]
        self._preview.fill(
            (str(n), [c[:CELL_CHARS] for c in row[:PREVIEW_COLUMNS]], ())
            for n, row in enumerate(rows)
        )

    @staticmethod
    def _column_name(number: int, header: tuple[str, ...]) -> str:
        name = header[number] if number < len(header) else ""
        return f"{number + 1}: {name}" if name else f"Spalte {number + 1}"

    def result_or_none(self) -> Mapping | None:
        mapping = {
            field: combo.current() - 1
            for field, combo in self._combos.items()
            if combo.current() > 0
        }
        if not all(field in mapping for field in REQUIRED):
            self.show_error("Datum und Betrag müssen einer Spalte zugeordnet sein.")
            return None
        return mapping, self._header_index()
