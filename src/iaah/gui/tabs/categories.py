# Portions adapted from budgets (MIT, © 2026 nikluep) – see LICENSES/budgets-MIT.txt
"""Categories tab: the list of categories and an editor for the selected one – name, color,
kind, monthly budget and its keywords (budgets' legend editor, with the legacy settings)."""

import tkinter as tk
from collections.abc import Callable
from tkinter import colorchooser, messagebox, ttk
from typing import Final

from iaah.core.categories import Category, CategoryKind, CategoryRole
from iaah.core.text import format_plain_german
from iaah.gui.host import Host
from iaah.gui.texts import APP_TITLE
from iaah.gui.theme import FONT_TITLE, PAD, PAD_LARGE, tint
from iaah.gui.viewmodel import budget_from_text
from iaah.gui.widgets import ColumnSpec, ScrolledTree

KIND_LABELS: Final[dict[CategoryKind, str]] = {
    CategoryKind.EXPENSE: "Ausgabe",
    CategoryKind.INCOME: "Einnahme",
    CategoryKind.IGNORED: "Ignoriert ⊘",
}
KIND_NAMES: Final[dict[CategoryKind, str]] = {
    CategoryKind.EXPENSE: "Ausgabe",
    CategoryKind.INCOME: "Einnahme",
    CategoryKind.IGNORED: "Ignoriert",
}
ROLE_NOTES: Final[dict[CategoryRole, str]] = {
    CategoryRole.EXPENSE_FALLBACK: "Auffang-Kategorie für Ausgaben ohne passendes Stichwort.",
    CategoryRole.INCOME_FALLBACK: "Auffang-Kategorie für Einnahmen ohne passendes Stichwort.",
}
COLUMNS: Final = (
    ColumnSpec("name", "Kategorie", 200, stretch=True),
    ColumnSpec("kind", "Art", 100),
    ColumnSpec("keywords", "Stichwörter", 90, "e"),
)
HINT: Final = (
    "Ein Stichwort passt, wenn ein Wort in Empfänger oder Verwendungszweck damit beginnt – "
    "„rewe“ passt auf „REWE Markt“, aber nicht auf „Brewery“. Passen mehrere, gewinnt das "
    "längste. Einnahme-Stichwörter gelten nur für Geld, das hereinkommt."
)
ENTRY_WIDTH: Final = 28
SWATCH: Final = 22
LIST_HEIGHT: Final = 12
WRAP: Final = 440


class CategoriesTab(ttk.Frame):
    """Category list left, editor right."""

    def __init__(self, parent: tk.Misc, host: Host) -> None:
        super().__init__(parent, padding=PAD)
        self.host = host
        self._current: str | None = None
        self._build_list()
        self._build_editor()
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

    # -- building ---------------------------------------------------------------------------

    def _build_list(self) -> None:
        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="nsew")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.table = ScrolledTree(left, COLUMNS, selectmode="browse")
        self.table.grid(row=0, column=0, sticky="nsew")
        self.table.tree.bind("<<TreeviewSelect>>", lambda _event: self._on_select())
        buttons = ttk.Frame(left)
        buttons.grid(row=1, column=0, sticky="w", pady=PAD)
        ttk.Button(buttons, text="Neu…", command=self._new).pack(side="left")
        ttk.Button(buttons, text="Löschen", command=self._delete).pack(side="left", padx=PAD)
        ttk.Button(buttons, text="▲", style="Small.TButton", command=lambda: self._move(-1)).pack(
            side="left"
        )
        ttk.Button(buttons, text="▼", style="Small.TButton", command=lambda: self._move(1)).pack(
            side="left"
        )

    def _build_editor(self) -> None:
        editor = ttk.Frame(self, padding=(PAD_LARGE, 0, 0, 0))
        editor.grid(row=0, column=1, sticky="nsew")
        ttk.Label(editor, text="Kategorie bearbeiten", font=FONT_TITLE).grid(
            row=0, column=0, columnspan=3, sticky="w"
        )
        self.name = self._labeled_entry(editor, 1, "Name:", "Umbenennen", self._rename)
        ttk.Label(editor, text="Farbe:").grid(row=2, column=0, sticky="w", pady=PAD)
        self.swatch = tk.Frame(editor, width=SWATCH, height=SWATCH)
        self.swatch.grid(row=2, column=1, sticky="w")
        ttk.Button(editor, text="Farbe…", command=self._recolor).grid(row=2, column=2, sticky="w")
        self._build_kind(editor)
        self.budget = self._labeled_entry(
            editor, 4, "Budget €/Monat:", "Übernehmen", self._set_budget
        )
        self.note = ttk.Label(editor, text="", style="Muted.TLabel", wraplength=WRAP)
        self.note.grid(row=5, column=0, columnspan=3, sticky="w", pady=PAD)
        self._build_keywords(editor)

    def _labeled_entry(
        self, parent: ttk.Frame, row: int, label: str, button: str, command: Callable[[], object]
    ) -> ttk.Entry:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=PAD)
        entry = ttk.Entry(parent, width=ENTRY_WIDTH)
        entry.grid(row=row, column=1, sticky="w")
        ttk.Button(parent, text=button, command=command).grid(
            row=row, column=2, sticky="w", padx=PAD
        )
        return entry

    def _build_kind(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Art:").grid(row=3, column=0, sticky="w")
        frame = ttk.Frame(parent)
        frame.grid(row=3, column=1, columnspan=2, sticky="w")
        self.kind = tk.StringVar()
        self._kind_buttons = [
            ttk.Radiobutton(
                frame, text=name, value=kind.value, variable=self.kind, command=self._set_kind
            )
            for kind, name in KIND_NAMES.items()
        ]
        for button in self._kind_buttons:
            button.pack(side="left", padx=(0, PAD))

    def _build_keywords(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Stichwörter", font=FONT_TITLE).grid(row=6, column=0, sticky="w")
        self.keywords = tk.Listbox(parent, height=LIST_HEIGHT, exportselection=False)
        self.keywords.grid(row=7, column=0, columnspan=3, sticky="ew")
        self.keywords.bind("<<ListboxSelect>>", lambda _event: self._pick_keyword())
        self.keyword = ttk.Entry(parent, width=ENTRY_WIDTH)
        self.keyword.grid(row=8, column=0, columnspan=2, sticky="ew", pady=PAD)
        self.keyword.bind("<Return>", lambda _event: self._add_keyword())
        buttons = ttk.Frame(parent)
        buttons.grid(row=9, column=0, columnspan=3, sticky="w")
        ttk.Button(buttons, text="Hinzufügen", command=self._add_keyword).pack(side="left")
        ttk.Button(buttons, text="Ändern", command=self._edit_keyword).pack(side="left", padx=PAD)
        ttk.Button(buttons, text="Entfernen", command=self._remove_keyword).pack(side="left")
        ttk.Label(parent, text=HINT, style="Muted.TLabel", wraplength=WRAP).grid(
            row=10, column=0, columnspan=3, sticky="w", pady=PAD
        )

    # -- showing ------------------------------------------------------------------------------

    def refresh(self) -> None:
        """List and editor from the catalog."""
        catalog = self.host.session.catalog
        for category in catalog:
            self.table.tree.tag_configure(
                category.color, background=tint(category.color, self.host.palette)
            )
        self.table.fill(
            (c.name, (c.name, KIND_LABELS[c.kind], str(len(c.keywords))), (c.color,))
            for c in catalog
        )
        if self._current not in catalog:
            self._current = catalog.names()[0] if len(catalog) else None
        if self._current is not None:
            self.table.show([self._current])
        self._show_editor()

    def _on_select(self) -> None:
        selected = self.table.selected()
        if selected:
            self._current = selected[0]
            self._show_editor()

    def _category(self) -> Category | None:
        catalog = self.host.session.catalog
        if self._current is None or self._current not in catalog:
            return None
        return catalog.get(self._current)

    def _show_editor(self) -> None:
        category = self._category()
        if category is None:
            return
        _replace(self.name, category.name)
        _replace(self.budget, format_plain_german(category.budget) if category.budget else "")
        self.swatch.configure(bg=category.color)
        self.kind.set(category.kind.value)
        state = "disabled" if category.role else "normal"
        for button in self._kind_buttons:
            button.configure(state=state)
        uses = self.host.session.decisions_using(category.name)
        role = ROLE_NOTES[category.role] if category.role else ""
        self.note.configure(text=f"{role} {uses} manuelle Zuordnung(en) nutzen diese Kategorie.")
        self.keywords.delete(0, "end")
        for keyword in category.keywords:
            self.keywords.insert("end", keyword)

    # -- actions ------------------------------------------------------------------------------

    def _new(self) -> None:
        name = self.host.new_category()
        if name is not None:
            self._current = name
            self.refresh()

    def _delete(self) -> None:
        category = self._category()
        if category is None:
            return
        uses = self.host.session.decisions_using(category.name)
        question = (
            f"„{category.name}“ löschen? {uses} manuelle Zuordnung(en), die "
            "Stichwörter und das Budget gehen mit."
        )
        if messagebox.askyesno(APP_TITLE, question, parent=self):
            self.host.run(lambda: self.host.session.remove_category(category.name))

    def _move(self, step: int) -> None:
        names = self.host.session.catalog.names()
        if self._current in names:
            position = min(max(names.index(self._current) + step, 0), len(names) - 1)
            current = self._current
            self.host.run(lambda: self.host.session.move_category(current, position))

    def _rename(self) -> None:
        old, new = self._current, self.name.get().strip()
        if old is None or not new or new == old:
            return

        def rename() -> None:
            self._current = self.host.session.rename_category(old, new)

        self.host.run(rename)

    def _recolor(self) -> None:
        category = self._category()
        if category is None:
            return
        _, chosen = colorchooser.askcolor(
            category.color, parent=self, title=f"Farbe für {category.name}"
        )
        if chosen:
            self.host.run(lambda: self.host.session.recolor(category.name, chosen.lower()))

    def _set_kind(self) -> None:
        category = self._category()
        if category is not None:
            kind = CategoryKind(self.kind.get())
            self.host.run(lambda: self.host.session.set_kind(category.name, kind))

    def _set_budget(self) -> None:
        category = self._category()
        if category is None:
            return
        try:
            amount = budget_from_text(self.budget.get())
        except ValueError:
            messagebox.showerror(APP_TITLE, "Das Budget ist kein gültiger Betrag.", parent=self)
            return
        self.host.run(lambda: self.host.session.set_budgets({category.name: amount}))

    def _pick_keyword(self) -> None:
        selection = self.keywords.curselection()
        if selection:
            _replace(self.keyword, self.keywords.get(selection[0]))

    def _keyword_list(self) -> list[str]:
        return list(self.keywords.get(0, "end"))

    def _store_keywords(self, keywords: list[str]) -> None:
        if self._current is not None:
            name = self._current
            if self.host.run(lambda: self.host.session.set_keywords(name, keywords)):
                self.keyword.delete(0, "end")

    def _add_keyword(self) -> None:
        text = self.keyword.get().strip()
        if text:
            self._store_keywords([*self._keyword_list(), text])

    def _edit_keyword(self) -> None:
        selection, text = self.keywords.curselection(), self.keyword.get().strip()
        if selection and text:
            keywords = self._keyword_list()
            keywords[selection[0]] = text
            self._store_keywords(keywords)

    def _remove_keyword(self) -> None:
        selection = self.keywords.curselection()
        if selection:
            keywords = self._keyword_list()
            del keywords[selection[0]]
            self._store_keywords(keywords)


def _replace(entry: ttk.Entry, text: str) -> None:
    entry.delete(0, "end")
    entry.insert(0, text)
