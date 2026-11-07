"""Opening the data directory with the user: password, damaged or newer data, and taking over
the legacy app's files.

Every path that cannot load the data ends without saving anything: the store refuses to
overwrite data the session has not loaded (unlike the legacy app, which could replace an
encrypted file after a cancelled password prompt).
"""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Final

from iaah.core.category_io import default_catalog
from iaah.core.errors import (
    DataUnreadableError,
    IaahError,
    PasswordRequiredError,
    StorageError,
    UnsupportedVersionError,
    WrongPasswordError,
)
from iaah.core.library import Library
from iaah.core.migration import LegacyData, has_legacy_files, migrate, read_legacy
from iaah.core.storage import DataStore
from iaah.core.workspace import Workspace
from iaah.gui.dialogs.simple import PasswordDialog, show_text
from iaah.gui.session import Session
from iaah.gui.texts import APP_TITLE, error_message
from iaah.gui.viewmodel import migration_text

NOT_EMPTY: Final = (
    "Alte Daten lassen sich nur übernehmen, solange keine Kontoauszüge importiert sind."
)
DAMAGED: Final = (
    "Die I-Aah-Daten sind beschädigt und es gibt keine lesbare Sicherungskopie.\n\n"
    "Sollen die beschädigten Dateien beiseitegelegt (nicht gelöscht) werden, damit I-Aah leer "
    "starten kann? „Nein“ beendet I-Aah."
)


def open_workspace(root: tk.Misc, store: DataStore) -> Workspace | None:
    """Load the data with the user's help; ``None`` means: quit without touching anything."""
    while True:
        try:
            if store.needs_password() and not _unlock(root, store):
                return None
            catalog, library = store.load()
        except PasswordRequiredError:  # a damaged plain file left only an encrypted backup
            if not _unlock(root, store):
                return None
            continue
        except (UnsupportedVersionError, DataUnreadableError) as error:
            # Not damage: a newer version, or a file that is locked right now. Never set aside.
            messagebox.showerror(APP_TITLE, error_message(error), parent=root)
            return None
        except StorageError:
            return _start_over(root, store)
        _report_recovery(root, store)
        return Workspace(catalog, library)


def _unlock(root: tk.Misc, store: DataStore) -> bool:
    """Ask until the password fits or the user cancels."""
    prompt = "Die I-Aah-Daten sind verschlüsselt. Bitte das Passwort eingeben:"
    while True:
        password = PasswordDialog(root, "Passwort", prompt).show()
        if password is None:
            return False
        try:
            store.unlock(password)
        except WrongPasswordError as error:
            messagebox.showerror(APP_TITLE, error_message(error), parent=root)
            continue
        except StorageError as error:
            messagebox.showerror(APP_TITLE, error_message(error), parent=root)
            return False
        return True


def _start_over(root: tk.Misc, store: DataStore) -> Workspace | None:
    if not messagebox.askyesno(APP_TITLE, DAMAGED, parent=root):
        return None
    try:
        moved = store.start_over()
    except StorageError as error:
        messagebox.showerror(APP_TITLE, error_message(error), parent=root)
        return None
    places = "\n".join(str(path) for path in moved)
    messagebox.showinfo(APP_TITLE, f"Beiseitegelegt:\n{places}", parent=root)
    return Workspace(default_catalog(), Library())


def _report_recovery(root: tk.Misc, store: DataStore) -> None:
    if not store.recovered_from_backup:
        return
    if store.damaged_copy is None:
        text = "Die Datendatei fehlte; I-Aah hat die Sicherungskopie geladen."
    else:
        text = (
            "Die Datendatei war beschädigt; I-Aah hat die Sicherungskopie geladen.\n\n"
            f"Die beschädigte Datei liegt hier: {store.damaged_copy}"
        )
    messagebox.showwarning(APP_TITLE, text, parent=root)


# -- legacy data ------------------------------------------------------------------------------


def offer_migration(root: tk.Misc, session: Session, folder: Path) -> bool:
    """On a first start – nothing of the user's yet – take over the legacy app's files if
    ``folder`` holds them. ``True`` if they were adopted."""
    if not session.is_pristine() or not has_legacy_files(folder):
        return False
    question = (
        f"Im Ordner {folder} liegen Daten der alten I-Aah-Version (Kategorien, Regeln, "
        "Buchungen, Zuordnungen). Jetzt übernehmen? Die alten Dateien bleiben "
        "unverändert."
    )
    if not messagebox.askyesno(APP_TITLE, question, parent=root):
        return False
    return migrate_from(root, session, folder)


def choose_and_migrate(root: tk.Misc, session: Session) -> None:
    """Menu action: pick the legacy folder and take its files over – into an empty library
    only, and over own categories or decisions only after an explicit warning."""
    if not session.workspace.is_empty():
        messagebox.showinfo(APP_TITLE, NOT_EMPTY, parent=root)
        return
    if not session.is_pristine() and not _replace_confirmed(root, session):
        return
    chosen = filedialog.askdirectory(parent=root, title="Ordner der alten I-Aah-Version")
    if not chosen:
        return
    folder = Path(chosen)
    if not has_legacy_files(folder):
        messagebox.showinfo(
            APP_TITLE,
            "In diesem Ordner liegen keine settings.json oder data.json der alten Version.",
            parent=root,
        )
        return
    migrate_from(root, session, folder)


def _replace_confirmed(root: tk.Misc, session: Session) -> bool:
    categories = len(session.catalog)
    decisions = len(session.workspace.library.assignments)
    question = (
        f"Die Übernahme ersetzt deine {categories} Kategorien mit ihren Stichwörtern und deine "
        f"{decisions} manuellen Zuordnungen – das lässt sich nicht rückgängig machen.\n\n"
        "Tipp: vorher Kategorien ▸ Kategorien speichern unter… \n\nTrotzdem übernehmen?"
    )
    return messagebox.askyesno(APP_TITLE, question, icon="warning", default="no", parent=root)


def migrate_from(root: tk.Misc, session: Session, folder: Path) -> bool:
    """Read, migrate and adopt the legacy files; show the report. ``True`` if adopted."""
    try:
        legacy = read_legacy(folder)
    except PasswordRequiredError:
        password = PasswordDialog(
            root, "Passwort der alten Daten", "Die alte data.json ist verschlüsselt:"
        ).show()
        if password is None:
            return False
        try:
            legacy = read_legacy(folder, password)
        except IaahError as error:
            messagebox.showerror(APP_TITLE, error_message(error), parent=root)
            return False
    except IaahError as error:
        messagebox.showerror(APP_TITLE, error_message(error), parent=root)
        return False
    return _adopt(root, session, legacy)


def _adopt(root: tk.Misc, session: Session, legacy: LegacyData) -> bool:
    try:
        migration = migrate(legacy, default_catalog())
        session.adopt(migration.catalog, migration.library)
    except IaahError as error:
        messagebox.showerror(APP_TITLE, error_message(error), parent=root)
        return False
    show_text(root, "Übernahme der alten Daten", migration_text(migration.report))
    return True
