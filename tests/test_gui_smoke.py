"""The real Tk widgets, where a display exists: start-up dialog, the whole window, importer."""

import queue
import tkinter as tk
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from tkinter import filedialog
from typing import Final

import pytest

from iaah.core.storage import DataPaths, DataStore
from iaah.core.workspace import Workspace, file_sha256
from iaah.gui import exports, importer
from iaah.gui.app import App
from iaah.gui.dialogs.simple import PasswordDialog
from iaah.gui.session import Session

DIALOG_DELAY_MS: Final = 100


@pytest.fixture
def root() -> Iterator[tk.Tk]:
    """A Tk root, or a skip on machines without a display."""
    try:
        window = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    yield window
    window.destroy()


def test_dialog_on_a_hidden_window_is_visible(root: tk.Tk) -> None:
    # Start-up asks for the password while the main window is still hidden; a transient
    # dialog would stay hidden with it (review finding).
    root.withdraw()
    dialog = PasswordDialog(root, "Passwort", "Bitte eingeben:")
    dialog.deiconify()
    dialog.update()
    assert dialog.winfo_viewable()
    assert not dialog.wm_transient()
    dialog.destroy()


def test_the_window_builds_every_tab_in_both_themes(
    root: tk.Tk, workspace: Workspace, tmp_path: Path
) -> None:
    app = App(root, DataStore(DataPaths(tmp_path)), workspace)
    for dark in (False, True):
        app._dark.set(dark)
        app.toggle_dark()
        for frame, _label in app._tabs:
            frame.refresh()  # what selecting the tab does
            root.update()
    assert app.session.transactions


def test_worker_always_sends_the_end_marker(
    statement_pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    results: queue.Queue[importer._Outcome | None] = queue.Queue()
    importer._work([statement_pdf, tmp_path / "fehlt.pdf"], set(), results)
    first, second, end = results.get(), results.get(), results.get()
    assert first is not None and first.parsed is not None
    assert second is not None and second.error is not None
    assert end is None

    def broken(path: Path, known: object) -> importer._Outcome:
        raise RuntimeError("parser bug")

    monkeypatch.setattr(importer, "_examine", broken)
    importer._work([statement_pdf], set(), results)
    outcome = results.get()
    assert outcome is not None and outcome.error is not None  # reported, thread not dead
    assert results.get() is None


def test_known_files_are_skipped_without_parsing(statement_pdf: Path) -> None:
    results: queue.Queue[importer._Outcome | None] = queue.Queue()
    known = {file_sha256(statement_pdf)}
    importer._work([statement_pdf], known, results)
    outcome = results.get()
    assert outcome is not None and outcome.parsed is None and outcome.error is None


# -- third review round -----------------------------------------------------------------------


def _app(root: tk.Tk, workspace: Workspace, tmp_path: Path) -> App:
    app = App(root, DataStore(DataPaths(tmp_path)), workspace)
    root.update()
    return app


def test_ctrl_digits_switch_tabs_but_never_assign(
    root: tk.Tk, workspace: Workspace, tmp_path: Path
) -> None:
    app = _app(root, workspace, tmp_path)
    tree = app.transactions.table.tree
    netflix = next(i for i, t in enumerate(app.session.transactions) if t.payee == "NETFLIX.COM")
    tree.selection_set(str(netflix))
    tree.focus_force()  # generated keys go to the focus window, also across earlier tests
    root.update()
    tree.event_generate("<Control-Key-2>")
    root.update()
    shown = str(root.tk.call(str(app.notebook), "select"))  # typeshed leaves select() untyped
    assert shown == str(app.review)  # the tab switched …
    assert not app.session.can_undo  # … and nothing was assigned
    tree.event_generate("<Key-2>")
    root.update()
    assert app.session.resolutions()[netflix].category == app.session.catalog.names()[1]


def test_budget_inputs_survive_a_refresh_but_not_undo(
    root: tk.Tk, workspace: Workspace, tmp_path: Path
) -> None:
    app = _app(root, workspace, tmp_path)
    tab = app.budgets
    tab.refresh()
    tab._entries["Wohnen"].insert(0, "950")
    tab.refresh()  # e.g. another period
    assert tab._entries["Wohnen"].get() == "950"
    tab.save()
    app.undo()
    tab.refresh()
    assert tab._entries["Wohnen"].get() == ""  # the stored state, not the old input
    app.session.set_budgets({"Lebensmittel": Decimal(300)})  # on the categories tab
    tab.refresh()
    assert tab._entries["Lebensmittel"].get() == "300,00"


def test_a_failing_finish_still_reports_and_stops_polling(
    root: tk.Tk, workspace: Workspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = Session(workspace)
    reports: list[object] = []
    scheduled: list[object] = []
    running = importer.Importer(root, session, reports.append)

    def broken() -> list[str]:
        raise RuntimeError("bug")

    monkeypatch.setattr(session, "missing_months", broken)
    monkeypatch.setattr(root, "after", lambda _ms, callback: scheduled.append(callback))
    running.busy = True
    running._queue.put(None)
    with pytest.raises(RuntimeError):
        running._poll()
    assert reports  # the summary still arrives
    assert not running.busy
    assert not scheduled  # and polling stopped


def test_a_dialog_runs_modally_and_returns_its_result(root: tk.Tk) -> None:
    dialog = PasswordDialog(root, "Passwort", "Bitte eingeben:")

    def type_and_accept() -> None:
        assert dialog.grab_status() == "local"  # modal while it runs
        dialog._first.insert(0, "geheim")
        dialog.accept()

    root.after(DIALOG_DELAY_MS, type_and_accept)
    assert dialog.show() == "geheim"


def test_categories_are_never_saved_over_a_statement(
    root: tk.Tk, workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(root, workspace, tmp_path)
    statement = tmp_path / "umsaetze.csv"
    statement.write_text("Datum;Betrag\n", encoding="utf-8")
    monkeypatch.setattr(app.session, "is_statement_file", lambda path: path == statement)
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda **_options: str(statement))
    app.save_categories()
    assert statement.read_text(encoding="utf-8") == "Datum;Betrag\n"
    assert app.status_bar.cget("text") == exports.PROTECTED
