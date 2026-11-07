"""Small widgets shared by several tabs: a scrolled table, the colored category buttons and
the KPI card."""

import tkinter as tk
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from tkinter import ttk
from typing import Final, Literal

from iaah.gui.theme import FONT_KPI, FONT_SMALL, PAD, PAD_SMALL, text_on

type Anchor = Literal["w", "e", "center"]

BUTTON_COLUMNS: Final = 3
NUMBERED_CATEGORIES: Final = 9  # keys 1–9
BUTTON_WIDTH: Final = 18
BUTTON_RELIEF: Final = "raised"


@dataclass(frozen=True, slots=True)
class ColumnSpec:
    """One table column."""

    key: str
    heading: str
    width: int
    anchor: Anchor = "w"
    stretch: bool = False


class ScrolledTree(ttk.Frame):
    """A headings-only ``ttk.Treeview`` with a vertical scrollbar."""

    def __init__(
        self,
        parent: tk.Misc,
        columns: Sequence[ColumnSpec],
        selectmode: Literal["extended", "browse", "none"] = "extended",
    ) -> None:
        super().__init__(parent)
        self.tree = ttk.Treeview(
            self, columns=[c.key for c in columns], show="headings", selectmode=selectmode
        )
        for column in columns:
            self.tree.heading(column.key, text=column.heading)
            self.tree.column(
                column.key, width=column.width, anchor=column.anchor, stretch=column.stretch
            )
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        across = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scrollbar.set, xscrollcommand=across.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        across.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

    def fill(self, rows: Iterable[tuple[str, Sequence[str], Sequence[str]]]) -> None:
        """Replace all rows; each is ``(iid, values, tags)``."""
        self.tree.delete(*self.tree.get_children())
        for iid, values, tags in rows:
            self.tree.insert("", "end", iid=iid, values=list(values), tags=list(tags))

    def selected(self) -> list[str]:
        """The iids of the selected rows."""
        return list(self.tree.selection())

    def show(self, iids: Sequence[str]) -> None:
        """Select ``iids`` (those still present) and scroll the first into view."""
        present = [iid for iid in iids if self.tree.exists(iid)]
        self.tree.selection_set(present)
        if present:
            self.tree.see(present[0])


class CategoryButtons(ttk.Frame):
    """One colored button per category; the first nine are numbered for the keys 1–9."""

    def __init__(self, parent: tk.Misc, on_choose: Callable[[str], None]) -> None:
        super().__init__(parent)
        self._on_choose = on_choose
        self._buttons: list[tk.Button] = []

    def set_categories(self, categories: Sequence[tuple[str, str]]) -> None:
        """Rebuild the buttons for ``(name, color)`` pairs in display order."""
        for button in self._buttons:
            button.destroy()
        self._buttons = [
            self._button(position, name, color) for position, (name, color) in enumerate(categories)
        ]

    def set_enabled(self, enabled: bool) -> None:
        """Enable the buttons only while something is selected."""
        for button in self._buttons:
            button.configure(state="normal" if enabled else "disabled")

    def _button(self, position: int, name: str, color: str) -> tk.Button:
        number = f"{position + 1}  " if position < NUMBERED_CATEGORIES else ""
        button = tk.Button(
            self,
            text=f"{number}{name}",
            bg=color,
            fg=text_on(color),
            activebackground=color,
            relief=BUTTON_RELIEF,
            anchor="w",
            width=BUTTON_WIDTH,
            command=lambda: self._on_choose(name),
        )
        row, column = divmod(position, BUTTON_COLUMNS)
        button.grid(row=row, column=column, sticky="ew", padx=PAD_SMALL, pady=PAD_SMALL)
        return button


class KpiCard(ttk.Frame):
    """A KPI tile: title, big value, a small line below (delta or basis)."""

    def __init__(self, parent: tk.Misc, title: str) -> None:
        super().__init__(parent, style="Card.TFrame", padding=PAD)
        ttk.Label(self, text=title, style="Card.TLabel", font=FONT_SMALL).pack(anchor="w")
        self.value = ttk.Label(self, text="–", style="Card.TLabel", font=FONT_KPI)
        self.value.pack(anchor="w")
        self.note = ttk.Label(self, text="", style="Card.TLabel", font=FONT_SMALL)
        self.note.pack(anchor="w")

    def show(self, value: str, value_color: str, note: str, note_color: str) -> None:
        """Set the texts and their colors."""
        self.value.configure(text=value, foreground=value_color)
        self.note.configure(text=note, foreground=note_color)
