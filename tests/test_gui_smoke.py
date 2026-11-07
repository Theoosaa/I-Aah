"""The real Tk widgets, where a display exists: start-up dialog, the whole window, importer."""

import queue
import tkinter as tk
from collections.abc import Iterator
from pathlib import Path

import pytest

from iaah.core.storage import DataPaths, DataStore
from iaah.core.workspace import Workspace, file_sha256
from iaah.gui import importer
from iaah.gui.app import App
from iaah.gui.dialogs.simple import PasswordDialog


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
