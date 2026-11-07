"""Transactions tab: filters, the booking table and the panel that decides categories.

Assigning happens with the colored buttons (or keys 1–9, or the context menu) on the selected
rows – never by editing a table cell. After a manual decision the panel offers keywords with
their effect; nothing is stored until *Übernehmen* is clicked.
"""

import tkinter as tk
from collections.abc import Sequence
from decimal import Decimal
from functools import partial
from tkinter import ttk
from typing import Final

from iaah.core.analysis.ledger import Period
from iaah.core.assignments import AssignmentSource
from iaah.core.suggestions import KeywordPreview
from iaah.core.text import format_euro, parse_amount
from iaah.gui.dialogs.split import SplitDialog
from iaah.gui.host import Host
from iaah.gui.theme import FONT_BOLD, FONT_SMALL, FONT_TITLE, PAD, PAD_LARGE, tint
from iaah.gui.viewmodel import (
    Column,
    Direction,
    Row,
    accounts,
    booking_details,
    decision_text,
    periods,
    view_totals,
)
from iaah.gui.widgets import CategoryButtons, ColumnSpec, ScrolledTree, bind_digits

ALL: Final = "Alle"
ALL_TIME: Final = "Gesamt"
COLUMNS: Final = (
    ColumnSpec(Column.DATE, "Datum", 80),
    ColumnSpec(Column.TYPE, "Buchungsart", 82),
    ColumnSpec(Column.PAYEE, "Empfänger", 130, stretch=True),
    ColumnSpec(Column.PURPOSE, "Verwendungszweck", 140, stretch=True),
    ColumnSpec(Column.AMOUNT, "Betrag", 95, "e"),
    ColumnSpec(Column.CATEGORY, "Kategorie", 140),
)
ARROWS: Final = {False: " ▲", True: " ▼"}
PANEL_WIDTH: Final = 330  # with the columns above the table fits a 1000 px window
WRAP: Final = 310
SUGGESTION_WRAP: Final = 220  # leaves room for the button
FILTER_DELAY_MS: Final = 150  # wait for a pause in typing before filtering
LABEL_GAP: Final = 2
ROW_GAP: Final = 1
SEARCH_WIDTH: Final = 24
AMOUNT_WIDTH: Final = 8
COMBO_WIDTH: Final = 18
DONE: Final = "Alles zugeordnet – keine offene Buchung mehr. 🎉"
EMPTY: Final = "Noch keine Buchungen – Datei ▸ Kontoauszüge importieren (Strg+O)."
NO_SELECTION: Final = "Keine Buchung ausgewählt."


def period_label(period: Period) -> str:
    """Combobox text of a period: ``Gesamt``, ``2026`` or ``2026-07``."""
    return str(period) or ALL_TIME


class TransactionsTab(ttk.Frame):
    """Filter bar on top, table left, decision panel right, status line below."""

    def __init__(self, parent: tk.Misc, host: Host) -> None:
        super().__init__(parent, padding=PAD)
        self.host = host
        self._periods: list[Period] = []
        self._pending: str | None = None  # scheduled filter run while typing
        self._menu: tk.Menu | None = None  # the context menu last shown
        self._build_filters()
        self._build_table()
        self._build_panel()
        self.status = ttk.Label(self, text="", style="Status.TLabel")
        self.status.grid(row=3, column=0, columnspan=2, sticky="e", pady=(PAD, 0))
        self.rowconfigure(2, weight=1)
        self.columnconfigure(0, weight=1)

    # -- building ---------------------------------------------------------------------------

    def _build_filters(self) -> None:
        first, second = ttk.Frame(self), ttk.Frame(self)
        first.grid(row=0, column=0, columnspan=2, sticky="ew")
        second.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(PAD, PAD))
        self.period = self._combo(first, "Zeitraum:")
        self.category = self._combo(first, "Kategorie:")
        self.search = self._entry(first, "Suche:", SEARCH_WIDTH)
        self.account = self._combo(second, "Konto:")
        self.direction = self._combo(second, "Typ:", [d.value for d in Direction])
        self.minimum = self._entry(second, "Betrag von", AMOUNT_WIDTH)
        self.maximum = self._entry(second, "bis", AMOUNT_WIDTH)
        ttk.Button(second, text="Filter zurücksetzen", command=self.reset_filters).pack(
            side="left", padx=PAD
        )
        ttk.Button(second, text="Nächste offene ▶", command=self.next_open).pack(side="right")
        self.only_open = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            second, text="nur offene", variable=self.only_open, command=self._apply_filters
        ).pack(side="right", padx=PAD)

    def _combo(self, parent: ttk.Frame, label: str, values: Sequence[str] = ()) -> ttk.Combobox:
        ttk.Label(parent, text=label).pack(side="left", padx=(PAD, LABEL_GAP))
        combo = ttk.Combobox(parent, state="readonly", width=COMBO_WIDTH, values=list(values))
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", lambda _event: self._apply_filters())
        if values:
            combo.set(values[0])
        return combo

    def _entry(self, parent: ttk.Frame, label: str, width: int) -> ttk.Entry:
        ttk.Label(parent, text=label).pack(side="left", padx=(PAD, LABEL_GAP))
        entry = ttk.Entry(parent, width=width)
        entry.pack(side="left")
        entry.bind("<KeyRelease>", lambda _event: self._schedule_filters())
        return entry

    def _build_table(self) -> None:
        self.table = ScrolledTree(self, COLUMNS)
        self.table.grid(row=2, column=0, sticky="nsew")
        tree = self.table.tree
        for column in Column:
            tree.heading(column.value, command=partial(self._sort, column))
        tree.bind("<<TreeviewSelect>>", lambda _event: self._on_select())
        tree.bind("<Double-1>", lambda _event: self._open_in_review())
        tree.bind("<Button-3>", self._context_menu)
        bind_digits(tree, self._assign_number)

    def _build_panel(self) -> None:
        panel = ttk.Frame(self, width=PANEL_WIDTH, padding=(PAD_LARGE, 0, 0, 0))
        panel.grid(row=2, column=1, sticky="ns")
        panel.grid_propagate(False)
        ttk.Label(panel, text="Ausgewählte Buchung", font=FONT_TITLE).pack(anchor="w")
        self.details = ttk.Label(panel, text=NO_SELECTION, wraplength=WRAP, justify="left")
        self.details.pack(anchor="w", pady=PAD)
        self.decision = ttk.Label(panel, text="", wraplength=WRAP, style="Muted.TLabel")
        self.decision.pack(anchor="w")
        ttk.Label(panel, text="Kategorie zuweisen (Tasten 1–9):", font=FONT_BOLD).pack(
            anchor="w", pady=(PAD_LARGE, PAD)
        )
        self.buttons = CategoryButtons(panel, self.assign)
        self.buttons.pack(anchor="w")
        actions = ttk.Frame(panel)
        actions.pack(anchor="w", pady=PAD)
        ttk.Button(actions, text="Aufteilen…", command=self.split).pack(side="left")
        ttk.Button(actions, text="Automatisch", command=self.clear).pack(side="left", padx=PAD)
        ttk.Button(actions, text="+ Neue Kategorie", command=self._new_category).pack(side="left")
        ttk.Label(panel, text="Stichwort vorschlagen", font=FONT_BOLD).pack(
            anchor="w", pady=(PAD_LARGE, 0)
        )
        self.suggestions = ttk.Frame(panel)
        self.suggestions.pack(fill="x")

    # -- refreshing ---------------------------------------------------------------------------

    def refresh(self) -> None:
        """Options, buttons, table, status and panel from the session."""
        self._refresh_options()
        self.buttons.set_categories([(c.name, c.color) for c in self.host.session.catalog])
        self._refresh_table()

    def _refresh_table(self) -> None:
        """Table, status and panel only – what a filter or sort change touches."""
        session = self.host.session
        rows = session.rows()
        self._fill(rows)
        self.status.configure(text=self._status_text(rows) if session.transactions else EMPTY)
        self.table.show([str(index) for index in session.selection])
        self._show_panel()

    def _status_text(self, rows: Sequence[Row]) -> str:
        totals = view_totals(rows, self.host.session.filters.category)
        open_part = f" | {totals.open} offen" if totals.open else ""
        return (
            f"{totals.count} Buchungen | Einnahmen {format_euro(totals.income)} | "
            f"Ausgaben {format_euro(totals.expense)}{open_part}"
        )

    def _refresh_options(self) -> None:
        session = self.host.session
        self._periods = periods(session.transactions)
        self.period.configure(values=[period_label(p) for p in self._periods])
        self.category.configure(values=[ALL, *session.catalog.names()])
        self.account.configure(values=[ALL, *accounts(session.transactions)])
        filters = session.filters
        self.period.set(period_label(filters.period))
        self.category.set(filters.category or ALL)
        self.account.set(filters.account or ALL)
        self.direction.set(filters.direction.value)

    def _fill(self, rows: Sequence[Row]) -> None:
        palette = self.host.palette
        for color in {row.color for row in rows}:
            self.table.tree.tag_configure(color, background=tint(color, palette))
        self.table.fill((str(row.index), row.cells, (row.color,)) for row in rows)
        column, descending = self.host.session.sort
        for spec in COLUMNS:
            arrow = ARROWS[descending] if spec.key == column else ""
            self.table.tree.heading(spec.key, text=spec.heading + arrow)

    def _show_panel(self) -> None:
        session = self.host.session
        selected = session.selected()
        self.buttons.set_enabled(bool(selected))
        self._clear_suggestions()
        if len(selected) != 1:
            total = sum((txn.amount for txn in selected), Decimal(0))
            text = f"{len(selected)} Buchungen ausgewählt, Summe {format_euro(total)}"
            self.details.configure(text=text if selected else NO_SELECTION)
            self.decision.configure(text="")
            return
        resolution = session.categorizer.resolve(selected[0])
        self.details.configure(text=booking_details(selected[0]))
        self.decision.configure(text=decision_text(resolution))
        if resolution.source is AssignmentSource.MANUAL:
            self._show_suggestions(session.suggestions(session.selection[0]))

    def _clear_suggestions(self) -> None:
        for child in self.suggestions.winfo_children():
            child.destroy()

    def _show_suggestions(self, previews: Sequence[KeywordPreview]) -> None:
        category = self.host.session.categorizer.resolve(self.host.session.selected()[0]).category
        if not previews:
            ttk.Label(
                self.suggestions, text="Kein passendes Stichwort gefunden.", style="Muted.TLabel"
            ).pack(anchor="w")
            return
        for preview in previews:
            self._suggestion_row(preview, category)

    def _suggestion_row(self, preview: KeywordPreview, category: str) -> None:
        row = ttk.Frame(self.suggestions)
        row.pack(fill="x", pady=ROW_GAP)
        moved = f", gehört bisher zu {preview.owner}" if preview.owner else ""
        text = (
            f"„{preview.keyword}“ → {category}\ntrifft {preview.matches}, ändert "
            f"{preview.changes}{moved}"
        )
        ttk.Label(row, text=text, font=FONT_SMALL, wraplength=SUGGESTION_WRAP).pack(side="left")
        ttk.Button(
            row, text="Übernehmen", command=lambda: self._accept(preview.keyword, category)
        ).pack(side="right")

    # -- actions ------------------------------------------------------------------------------

    def _schedule_filters(self) -> None:
        if self._pending is not None:
            self.after_cancel(self._pending)
        self._pending = self.after(FILTER_DELAY_MS, self._apply_filters)

    def _apply_filters(self) -> None:
        self._pending = None
        filters = self.host.session.filters
        position = self.period.current()
        filters.period = self._periods[position] if position >= 0 else Period.all_time()
        filters.category = "" if self.category.get() in ("", ALL) else self.category.get()
        filters.account = "" if self.account.get() in ("", ALL) else self.account.get()
        filters.direction = Direction(self.direction.get() or Direction.ALL)
        filters.text = self.search.get()
        filters.minimum = parse_amount(self.minimum.get()) if self.minimum.get() else None
        filters.maximum = parse_amount(self.maximum.get()) if self.maximum.get() else None
        filters.only_open = self.only_open.get()
        self._refresh_table()

    def reset_filters(self) -> None:
        """Back to everything."""
        for entry in (self.search, self.minimum, self.maximum):
            entry.delete(0, "end")
        self.only_open.set(False)
        self.host.session.filters = type(self.host.session.filters)()
        self.refresh()

    def _sort(self, column: Column) -> None:
        self.host.session.sort_by(column)
        self._refresh_table()

    def _on_select(self) -> None:
        self.host.session.select(int(iid) for iid in self.table.selected())
        self._show_panel()

    def assign(self, category: str) -> None:
        """Give the selected bookings ``category``."""
        if self.host.session.selection:
            self.host.run(lambda: self.host.session.assign(category))

    def _assign_number(self, number: int) -> None:
        names = self.host.session.catalog.names()
        if number <= len(names):
            self.assign(names[number - 1])

    def _accept(self, keyword: str, category: str) -> None:
        def accept() -> None:
            pruned = self.host.session.accept_keyword(keyword, category)
            note = f" ({pruned} manuelle Zuordnungen sind jetzt überflüssig)" if pruned else ""
            self.host.status(f"Stichwort „{keyword}“ gehört jetzt zu {category}{note}.")

        self.host.run(accept)

    def split(self) -> None:
        """Divide the one selected booking."""
        session = self.host.session
        if len(session.selection) != 1:
            self.host.status("Zum Aufteilen genau eine Buchung auswählen.")
            return
        index = session.selection[0]
        txn = session.transactions[index]
        current = session.categorizer.resolve(txn).parts
        parts = SplitDialog(self, txn, session.catalog.names(), current).show()
        if parts is not None:
            self.host.run(lambda: session.split(index, parts))

    def clear(self) -> None:
        """Return the selection to automatic categorization."""
        if self.host.session.selection:
            self.host.run(self.host.session.clear)

    def _new_category(self) -> None:
        name = self.host.new_category()
        if name is not None:
            self.assign(name)

    def next_open(self) -> None:
        """Select the next open booking in the view (wrapping around)."""
        index = self.host.session.next_open()
        if index is None:
            self.host.status(DONE if self.host.session.transactions else EMPTY)
            return
        self.host.session.select([index])
        self.table.show([str(index)])
        self.table.tree.focus(str(index))
        self.table.tree.focus_set()

    def _open_in_review(self) -> None:
        if len(self.host.session.selection) == 1:
            self.host.show_in_review(self.host.session.selection[0])

    def _context_menu(self, event: "tk.Event[tk.Misc]") -> None:
        iid = self.table.tree.identify_row(event.y)
        if iid and iid not in self.table.selected():
            self.table.tree.selection_set(iid)
            self._on_select()
        if self._menu is not None:
            self._menu.destroy()  # one menu at a time – built afresh for the current categories
        menu = self._menu = tk.Menu(self, tearoff=False)
        categories = tk.Menu(menu, tearoff=False)
        for name in self.host.session.catalog.names():
            categories.add_command(label=name, command=partial(self.assign, name))
        categories.add_separator()
        categories.add_command(label="Neue Kategorie…", command=self._new_category)
        menu.add_cascade(label="Kategorie zuweisen", menu=categories)
        menu.add_command(label="Aufteilen…", command=self.split)
        menu.add_command(label="Automatisch zuordnen", command=self.clear)
        menu.add_command(label="In der PDF-Prüfung zeigen", command=self._open_in_review)
        menu.tk_popup(event.x_root, event.y_root)
