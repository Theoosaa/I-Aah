"""The main window: tabs, menus, key bindings and start-up (``main``).

``App`` implements ``Host`` for the tabs: it runs user actions with German error messages,
refreshes the visible tab after every change (the others when they are shown next) and keeps
the instance lock for the lifetime of the window.
"""

import logging
import tkinter as tk
import webbrowser
from collections.abc import Callable
from functools import partial
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Final

from iaah.core.category_io import load_catalog, save_catalog
from iaah.core.errors import IaahError, StorageError, WrongPasswordError
from iaah.core.parsing.csv_import import import_table, load_table
from iaah.core.storage import DataPaths, DataStore, InstanceLock
from iaah.core.workspace import Workspace, file_sha256
from iaah.gui import exports, theme
from iaah.gui.dialogs.csv_mapping import CsvMappingDialog
from iaah.gui.dialogs.simple import NewCategoryDialog, PasswordDialog
from iaah.gui.importer import Importer
from iaah.gui.session import ImportSummary, Session
from iaah.gui.startup import choose_and_migrate, offer_migration, open_workspace
from iaah.gui.tabs.analysis import AnalysisTab
from iaah.gui.tabs.budgets import BudgetsTab
from iaah.gui.tabs.categories import CategoriesTab
from iaah.gui.tabs.review import ReviewTab
from iaah.gui.tabs.transactions import TransactionsTab
from iaah.gui.texts import APP_TITLE, error_message
from iaah.gui.theme import DARK, LIGHT, PAD, PAD_SMALL, PALETTES, Palette

TITLE: Final = "I-Aah – Kontoanalyse"
SIZE: Final = "1250x780"
MIN_SIZE: Final = (1000, 640)
TAB_PAD: Final = "  "
STATEMENTS: Final = [("Kontoauszüge", "*.pdf *.csv"), ("PDF", "*.pdf"), ("CSV", "*.csv")]
CATEGORY_FILES: Final = [("Kategorien (JSON)", "*.json"), ("Kategorien (CSV)", "*.csv")]
TEXT_FIELDS: Final = (tk.Entry, ttk.Entry, tk.Text, tk.Spinbox, ttk.Spinbox)
BREAK: Final = "break"  # Tk: the event is handled
ZOOMED: Final = "zoomed"  # Tk window state "maximized" (Windows); stored instead of a size
PDF_PATTERN: Final = "*.pdf"
UI_GEOMETRY: Final = "geometry"
UI_THEME: Final = "theme"
UI_TAB: Final = "tab"
UI_PERIOD: Final = "period"
UI_CHART: Final = "chart"
ABOUT: Final = (
    "I-Aah liest Kontoauszüge (ING-PDF, CSV), ordnet Buchungen über Stichwörter Kategorien zu "
    "und wertet sie aus.\n\nMIT-Lizenz. Enthält Code aus „budgets“ (MIT, © 2026 nikluep)."
)
PASSWORD_WARNING: Final = (
    "Neues Passwort für die I-Aah-Daten. Ohne dieses Passwort kommst du nicht mehr an deine "
    "Daten – es gibt keine Wiederherstellung."
)


type TabWidget = TransactionsTab | ReviewTab | AnalysisTab | BudgetsTab | CategoriesTab


class App:
    """The main window around one session."""

    def __init__(self, root: tk.Tk, store: DataStore, workspace: Workspace) -> None:
        self.root = root
        self._session = Session(workspace, store)
        self._store = store
        ui = store.load_ui_state()
        self._palette = PALETTES.get(str(ui.get(UI_THEME)), LIGHT)
        self._dark = tk.BooleanVar(value=self._palette is DARK)
        theme.apply(root, self._palette)
        root.title(TITLE)
        root.minsize(*MIN_SIZE)
        geometry = str(ui.get(UI_GEOMETRY) or SIZE)
        root.geometry(SIZE if geometry == ZOOMED else geometry)
        if geometry == ZOOMED:
            root.state(ZOOMED)
        self._build_tabs()
        self.status_bar = ttk.Label(root, text="", anchor="w", padding=(PAD, PAD_SMALL))
        self.status_bar.pack(side="bottom", fill="x")
        self.notebook.pack(side="top", fill="both", expand=True)
        self._build_menu()
        self._bind_keys()
        self.importer = Importer(root, self._session, self._import_done)
        self._restore(ui)
        root.protocol("WM_DELETE_WINDOW", self.quit)
        self.changed()

    # -- Host -------------------------------------------------------------------------------

    @property
    def session(self) -> Session:
        """The running session."""
        return self._session

    @property
    def palette(self) -> Palette:
        """The current theme."""
        return self._palette

    def run(self, action: Callable[[], object]) -> bool:
        """Run a user action; German message on error, refresh after success."""
        try:
            action()
        except IaahError as error:
            messagebox.showerror(APP_TITLE, error_message(error), parent=self.root)
            self.changed()  # the change may have happened in memory although saving failed
            return False
        self.changed()
        return True

    def new_category(self) -> str | None:
        """Ask for a new category and create it."""
        answer = NewCategoryDialog(self.root, self._session.catalog).show()
        if answer is None:
            return None
        name, color = answer
        created: list[str] = []
        self.run(lambda: created.append(self._session.add_category(name, color)))
        return created[0] if created else None

    def show_in_review(self, index: int) -> None:
        """Switch to the PDF review at the booking ``transactions[index]``."""
        self.notebook.select(self.review)
        if not self.review.show_booking(self._session.transactions[index]):
            self.status(
                "Für diese Buchung gibt es kein PDF (CSV-Import, oder die Datei wurde verschoben)."
            )

    def status(self, text: str) -> None:
        """A note in the status bar."""
        self.status_bar.configure(text=text)

    # -- building ---------------------------------------------------------------------------

    def _build_tabs(self) -> None:
        self.notebook = ttk.Notebook(self.root)
        self.transactions = TransactionsTab(self.notebook, self)
        self.review = ReviewTab(self.notebook, self)
        self.analysis = AnalysisTab(self.notebook, self)
        self.budgets = BudgetsTab(self.notebook, self)
        self.categories = CategoriesTab(self.notebook, self)
        self._tabs: list[tuple[TabWidget, str]] = [
            (self.transactions, "Transaktionen"),
            (self.review, "PDF-Prüfung"),
            (self.analysis, "Auswertung"),
            (self.budgets, "Budgets"),
            (self.categories, "Kategorien"),
        ]
        for frame, label in self._tabs:
            self.notebook.add(frame, text=f"{TAB_PAD}{label}{TAB_PAD}")
        self._by_name: dict[str, TabWidget] = {str(frame): frame for frame, _ in self._tabs}
        self._stale: set[str] = set()
        self.notebook.bind("<<NotebookTabChanged>>", lambda _event: self._refresh_visible())

    def _build_menu(self) -> None:
        bar = tk.Menu(self.root)
        for label, build in (
            ("Datei", self._menu_file),
            ("Bearbeiten", self._menu_edit),
            ("Kategorien", self._menu_categories),
            ("Ansicht", self._menu_view),
            ("Datenschutz", self._menu_privacy),
            ("Hilfe", self._menu_help),
        ):
            menu = tk.Menu(bar, tearoff=False)
            build(menu)
            bar.add_cascade(label=label, menu=menu)
        self.root.configure(menu=bar)

    def _menu_file(self, menu: tk.Menu) -> None:
        menu.add_command(
            label="Kontoauszüge importieren (PDF, CSV)…",
            accelerator="Strg+O",
            command=self.import_files,
        )
        menu.add_command(label="Alle PDFs eines Ordners importieren…", command=self.import_folder)
        menu.add_command(label="CSV mit eigener Spaltenzuordnung…", command=self.import_mapped_csv)
        export = tk.Menu(menu, tearoff=False)
        self._menu_export(export)
        menu.add_cascade(label="Exportieren", menu=export)
        menu.add_separator()
        menu.add_command(label="Alte I-Aah-Daten übernehmen…", command=self.migrate)
        menu.add_command(label="Bibliothek leeren…", command=self.reset_library)
        menu.add_separator()
        menu.add_command(label="Beenden", command=self.quit)

    def _menu_export(self, menu: tk.Menu) -> None:
        """Every entry names content and format; bookings and summaries use the filter."""
        root = self.root
        for label, command in (
            ("Buchungen (gefiltert) als CSV…", lambda: exports.bookings(root, self, excel=False)),
            ("Buchungen (gefiltert) als Excel…", lambda: exports.bookings(root, self, excel=True)),
            ("Zusammenfassung je Kategorie als CSV…",
             lambda: exports.summary(root, self, text=False)),
            ("Zusammenfassung je Kategorie als Text…",
             lambda: exports.summary(root, self, text=True)),
        ):  # fmt: skip
            menu.add_command(label=label, command=command)
        menu.add_separator()
        menu.add_command(label="Markiertes Kontoauszug-PDF…",
                         command=lambda: exports.marked_pdf(root, self))  # fmt: skip
        menu.add_command(label="Report des Auswertungs-Zeitraums als PDF…",
                         command=lambda: exports.report(root, self,
                                                        self.analysis.selected_period))  # fmt: skip

    def _menu_edit(self, menu: tk.Menu) -> None:
        menu.add_command(label="Rückgängig", accelerator="Strg+Z", command=self.undo)
        menu.add_command(label="Wiederholen", accelerator="Strg+Y", command=self.redo)
        menu.add_separator()
        menu.add_command(label="Nächste offene Buchung", accelerator="F3", command=self.next_open)
        menu.add_command(label="Auswahl automatisch zuordnen", command=self.transactions.clear)
        menu.add_command(label="Überflüssige manuelle Zuordnungen entfernen", command=self.prune)

    def _menu_categories(self, menu: tk.Menu) -> None:
        menu.add_command(label="Neue Kategorie…", command=self.new_category)
        menu.add_command(label="Kategorien aus Datei laden…", command=self.load_categories)
        menu.add_command(label="Kategorien speichern unter…", command=self.save_categories)

    def _menu_view(self, menu: tk.Menu) -> None:
        menu.add_checkbutton(label="Dunkles Design", variable=self._dark, command=self.toggle_dark)
        menu.add_separator()
        for number, (frame, label) in enumerate(self._tabs, start=1):
            menu.add_command(
                label=label,
                accelerator=f"Strg+{number}",
                command=partial(self.notebook.select, frame),
            )

    def _menu_privacy(self, menu: tk.Menu) -> None:
        menu.add_command(label="Passwort festlegen oder ändern…", command=self.set_password)
        menu.add_command(label="Passwort entfernen…", command=self.remove_password)
        menu.add_command(label="Beschädigte Kopien löschen…", command=self.delete_damaged_copies)

    def _menu_help(self, menu: tk.Menu) -> None:
        menu.add_command(label="Datenordner öffnen", command=self.open_data_folder)
        menu.add_command(
            label="Über I-Aah",
            command=lambda: messagebox.showinfo(APP_TITLE, ABOUT, parent=self.root),
        )

    def _bind_keys(self) -> None:
        root = self.root
        root.bind_all("<Control-z>", self._shortcut(self.undo, in_text_fields=False))
        root.bind_all("<Control-y>", self._shortcut(self.redo, in_text_fields=False))
        root.bind_all("<Control-o>", self._shortcut(self.import_files))
        root.bind_all("<F3>", self._shortcut(self.next_open))
        for number, (frame, _label) in enumerate(self._tabs, start=1):
            show = partial(self.notebook.select, frame)
            root.bind_all(f"<Control-Key-{number}>", self._shortcut(show))

    def _shortcut(
        self, action: Callable[[], object], in_text_fields: bool = True
    ) -> Callable[["tk.Event[tk.Misc]"], str | None]:
        """A key handler that acts only in the main window – never behind a modal dialog – and,
        for undo/redo, not while the user types in a field."""

        def handler(event: "tk.Event[tk.Misc]") -> str | None:
            widget = event.widget
            if not isinstance(widget, tk.Misc) or widget.winfo_toplevel() is not self.root:
                return None
            if not in_text_fields and isinstance(widget, TEXT_FIELDS):
                return None
            action()
            return BREAK

        return handler

    def _restore(self, ui: dict[str, object]) -> None:
        tab = ui.get(UI_TAB)
        if isinstance(tab, int) and 0 <= tab < len(self._tabs):
            self.notebook.select(self._tabs[tab][0])
        self.analysis.choose(str(ui.get(UI_PERIOD, "")), str(ui.get(UI_CHART, "")))

    # -- refreshing ---------------------------------------------------------------------------

    def changed(self) -> None:
        """Data changed: refresh the visible tab now, the others when they are shown."""
        self._stale = {str(frame) for frame, _ in self._tabs}
        self._refresh_visible()

    def _refresh_visible(self) -> None:
        selected = self.notebook.select()
        if selected not in self._stale:
            return
        self._stale.discard(selected)
        self._by_name[selected].refresh()

    # -- actions ------------------------------------------------------------------------------

    def import_files(self) -> None:
        """Pick statement files and import them in the background."""
        chosen = filedialog.askopenfilenames(
            parent=self.root, title="Kontoauszüge importieren", filetypes=STATEMENTS
        )
        self.importer.start([Path(name) for name in chosen])

    def import_folder(self) -> None:
        """Import every PDF of a folder."""
        chosen = filedialog.askdirectory(parent=self.root, title="Ordner mit Kontoauszügen")
        if not chosen:
            return
        pdfs = sorted(Path(chosen).glob(PDF_PATTERN))
        if not pdfs:
            messagebox.showinfo(
                APP_TITLE, "In diesem Ordner liegen keine PDF-Dateien.", parent=self.root
            )
            return
        self.importer.start(pdfs)

    def import_mapped_csv(self) -> None:
        """Import a CSV export choosing header row and columns by hand."""
        chosen = filedialog.askopenfilename(
            parent=self.root, title="CSV-Export wählen", filetypes=[("CSV", "*.csv")]
        )
        if not chosen:
            return
        path = Path(chosen)

        def run_import() -> None:
            table = load_table(path)
            choice = CsvMappingDialog(self.root, table, path.name).show()
            if choice is None:
                return
            parsed = import_table(table, path.name, *choice)
            summary = ImportSummary(files=1)
            summary.record(
                path.name, parsed, self._session.import_parsed(parsed, path, file_sha256(path))
            )
            self._import_done(summary)

        self.run(run_import)

    def _import_done(self, summary: ImportSummary) -> None:
        self.changed()
        message = summary.message()
        if summary.failed or summary.not_reconciling or summary.with_problems:
            messagebox.showwarning(APP_TITLE, message, parent=self.root)
        else:
            messagebox.showinfo(APP_TITLE, message, parent=self.root)

    def migrate(self) -> None:
        """Take over the legacy app's files."""
        choose_and_migrate(self.root, self._session)
        self.changed()

    def reset_library(self) -> None:
        """Forget all statements and bookings after asking."""
        question = (
            "Alle importierten Auszüge und Buchungen aus I-Aah entfernen? Kategorien, "
            "Stichwörter und deine Zuordnungen bleiben; ein erneuter Import stellt "
            "alles wieder her."
        )
        if messagebox.askyesno(APP_TITLE, question, parent=self.root):
            self.run(self._session.reset_library)

    def undo(self) -> None:
        """Undo the last change of categories or decisions."""
        if not self._session.can_undo:
            self.status("Nichts rückgängig zu machen.")
        elif self.run(self._session.undo):
            self.status("Rückgängig gemacht.")

    def redo(self) -> None:
        """Redo the last undone change."""
        if not self._session.can_redo:
            self.status("Nichts zu wiederholen.")
        elif self.run(self._session.redo):
            self.status("Wiederholt.")

    def next_open(self) -> None:
        """Jump to the next open booking on the transactions tab."""
        self.notebook.select(self.transactions)
        self.transactions.next_open()

    def prune(self) -> None:
        """Drop manual decisions that keywords make anyway."""
        dropped: list[int] = []
        if self.run(lambda: dropped.append(self._session.prune_all())):
            self.status(f"{dropped[0]} überflüssige manuelle Zuordnungen entfernt.")

    def load_categories(self) -> None:
        """Replace the catalog by a category file (JSON or CSV)."""
        chosen = filedialog.askopenfilename(
            parent=self.root, title="Kategorien laden", filetypes=CATEGORY_FILES
        )
        if not chosen:
            return
        question = (
            "Die aktuellen Kategorien und Stichwörter durch die Datei ersetzen? "
            "Rückgängig ist danach möglich."
        )
        if not messagebox.askyesno(APP_TITLE, question, parent=self.root):
            return
        orphaned: list[int] = []
        if (
            self.run(
                lambda: orphaned.append(self._session.replace_catalog(load_catalog(Path(chosen))))
            )
            and orphaned[0]
        ):
            self.status(
                f"{orphaned[0]} manuelle Zuordnungen nennen Kategorien, die die Datei "
                "nicht hat – sie gelten wieder, sobald es die Kategorie gibt."
            )

    def save_categories(self) -> None:
        """Write the catalog to a JSON or CSV file."""
        chosen = filedialog.asksaveasfilename(
            parent=self.root,
            title="Kategorien speichern",
            defaultextension=".json",
            filetypes=CATEGORY_FILES,
        )
        if chosen and self.run(lambda: save_catalog(self._session.catalog, Path(chosen))):
            self.status(f"Kategorien gespeichert: {chosen}")

    def toggle_dark(self) -> None:
        """Switch between the light and the dark theme."""
        self._palette = DARK if self._dark.get() else LIGHT
        theme.apply(self.root, self._palette)
        self.changed()

    def set_password(self) -> None:
        """Encrypt the data (or change the password). Damaged copies are asked about only
        after the new password was entered, and the status says if some stay unencrypted."""
        if self._session.encrypted and not self._confirm_current_password():
            return
        password = PasswordDialog(
            self.root, "Passwort festlegen", PASSWORD_WARNING, confirm=True
        ).show()
        if password is None or not self.delete_damaged_copies(asking_first=True):
            return
        if not self.run(lambda: self._session.enable_encryption(password)):
            return
        kept = len(self._store.damaged_copies())
        note = (
            f" Achtung: {kept} beschädigte Kopie(n) liegen noch unverschlüsselt im Datenordner."
            if kept
            else ""
        )
        self.status(f"Passwortschutz ist aktiv; die Daten liegen verschlüsselt vor.{note}")

    def remove_password(self) -> None:
        """Store the data unencrypted again."""
        if not self._session.encrypted:
            self.status("Die Daten sind nicht verschlüsselt.")
            return
        if self._confirm_current_password() and self.run(self._session.disable_encryption):
            self.status("Passwortschutz entfernt.")

    def _confirm_current_password(self) -> bool:
        password = PasswordDialog(
            self.root, "Aktuelles Passwort", "Bitte das aktuelle Passwort eingeben:"
        ).show()
        if password is None:
            return False
        try:
            self._session.verify_password(password)
        except WrongPasswordError as error:
            messagebox.showerror(APP_TITLE, error_message(error), parent=self.root)
            return False
        except StorageError as error:
            messagebox.showerror(APP_TITLE, error_message(error), parent=self.root)
            return False
        return True

    def delete_damaged_copies(self, asking_first: bool = False) -> bool:
        """Offer to delete damaged copies (they may hold unencrypted data); ``False`` when the
        user cancels."""
        copies = self._store.damaged_copies()
        if not copies:
            if not asking_first:
                self.status("Es gibt keine beschädigten Kopien.")
            return True
        listing = "\n".join(str(path) for path in copies)
        answer = messagebox.askyesnocancel(
            APP_TITLE,
            "Diese beschädigten Kopien können "
            f"unverschlüsselte Daten enthalten:\n{listing}\n\n"
            "Endgültig löschen?",
            parent=self.root,
        )
        if answer is None:
            return False
        if answer:
            self._remove(copies)
        return True

    def _remove(self, paths: list[Path]) -> None:
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                self.status(f"{path} konnte nicht gelöscht werden.")
                return
        self.status(f"{len(paths)} beschädigte Kopie(n) gelöscht.")

    def open_data_folder(self) -> None:
        """Show the data directory in the file manager."""
        webbrowser.open(self._store.paths.root.as_uri())

    def quit(self) -> None:
        """Remember window and view, then close."""
        zoomed = self.root.state() == ZOOMED
        state = {
            UI_GEOMETRY: ZOOMED if zoomed else self.root.geometry(),
            UI_THEME: self._palette.name,
            UI_TAB: self.notebook.index(self.notebook.select()),
            UI_PERIOD: str(self.analysis.selected_period),
            UI_CHART: self.analysis.selected_kind.value,
        }
        try:
            self._store.save_ui_state(state)
        except (StorageError, ValueError):
            logging.getLogger(__name__).warning("could not save the window state")
        self.root.destroy()


def main() -> None:
    """Start the GUI: lock the data directory, open the data, run the window."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    root = tk.Tk()
    root.withdraw()
    theme.apply(root, LIGHT)
    paths = DataPaths.default()
    lock = InstanceLock(paths.lock)
    try:
        lock.acquire()
    except StorageError as error:
        messagebox.showerror(APP_TITLE, error_message(error), parent=root)
        root.destroy()
        return
    try:
        _run(root, DataStore(paths))
    finally:
        lock.release()


def _run(root: tk.Tk, store: DataStore) -> None:
    workspace = open_workspace(root, store)
    if workspace is None:
        root.destroy()
        return
    app = App(root, store, workspace)
    root.deiconify()
    offer_migration(root, app.session, Path.cwd())
    app.changed()
    root.mainloop()
