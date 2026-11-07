"""A modal dialog with OK/Cancel, an inline error line and a typed result."""

import tkinter as tk
from tkinter import ttk
from typing import Final

from iaah.gui.theme import PAD, PAD_LARGE

CANCEL: Final = "Abbrechen"
ERROR_WRAP: Final = 360  # pixels


class Dialog[T](tk.Toplevel):
    """Subclasses fill ``self.body`` and implement ``result_or_none``; ``show`` returns the
    result, or ``None`` when cancelled."""

    def __init__(self, parent: tk.Misc, title: str, ok_text: str) -> None:
        super().__init__(parent)
        self.title(title)
        owner = parent.winfo_toplevel()
        # A transient dialog shares its owner's visibility: during start-up the main window is
        # still hidden, so the password dialog must stand on its own there.
        if owner.winfo_viewable():
            self.transient(owner)
        self.resizable(False, False)
        self.result: T | None = None
        self.initial_focus: tk.Misc | None = None  # set by subclasses
        self.body = ttk.Frame(self, padding=PAD_LARGE)
        self.body.pack(fill="both", expand=True)
        self._error = ttk.Label(self, text="", style="Bad.TLabel", wraplength=ERROR_WRAP)
        self._error.pack(fill="x", padx=PAD_LARGE)
        self._buttons(ok_text)
        self.bind("<Escape>", lambda _event: self.destroy())
        self.bind("<Return>", lambda _event: self.accept())

    def _buttons(self, ok_text: str) -> None:
        row = ttk.Frame(self, padding=PAD_LARGE)
        row.pack(fill="x")
        ttk.Button(row, text=CANCEL, command=self.destroy).pack(side="right")
        ttk.Button(row, text=ok_text, command=self.accept).pack(side="right", padx=PAD)

    def show(self) -> T | None:
        """Run modally until closed."""
        self.deiconify()
        self.lift()
        self.wait_visibility()
        self.grab_set()
        self.focus_force()
        if self.initial_focus is not None:
            self.initial_focus.focus_set()
        self.wait_window()
        return self.result

    def accept(self) -> None:
        """Take the result if the input is valid, else show why not."""
        result = self.result_or_none()
        if result is not None:
            self.result = result
            self.destroy()

    def result_or_none(self) -> T | None:
        """The result of valid input; call ``show_error`` and return ``None`` otherwise."""
        raise NotImplementedError

    def show_error(self, message: str) -> None:
        """An inline error below the inputs (cleared by the next valid attempt)."""
        self._error.configure(text=message)
