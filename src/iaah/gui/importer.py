"""Importing statement files without freezing the window.

A worker thread hashes and parses the files and puts the results on a queue; the main thread
polls the queue, applies results through the session (the library changes only there – Tk and
the session are not thread-safe) and shows a progress window. CSV files whose columns were not
recognised are asked about afterwards, one after another.
"""

import queue
import threading
import tkinter as tk
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from tkinter import ttk
from typing import Final

from iaah.core.errors import CsvMappingError, IaahError, StatementParseError
from iaah.core.parsing.csv_import import CsvTable, import_table, load_table
from iaah.core.parsing.diagnostics import ParsedStatement
from iaah.core.workspace import file_sha256, read_statement_file
from iaah.gui.dialogs.csv_mapping import CsvMappingDialog
from iaah.gui.session import ImportSummary, Session
from iaah.gui.texts import error_message
from iaah.gui.theme import PAD, PAD_LARGE

POLL_MS: Final = 80
PROGRESS_SIZE: Final = "380x100"
BAR_LENGTH: Final = 340


@dataclass(frozen=True, slots=True)
class _Outcome:
    """What the worker found out about one file."""

    path: Path
    sha256: str = ""
    parsed: ParsedStatement | None = None
    needs_mapping: bool = False
    error: IaahError | None = None


class Importer:
    """Runs one import at a time; ``on_done`` receives the summary on the main thread."""

    def __init__(
        self, root: tk.Tk, session: Session, on_done: Callable[[ImportSummary], None]
    ) -> None:
        self._root = root
        self._session = session
        self._on_done = on_done
        self._queue: queue.Queue[_Outcome | None] = queue.Queue()
        self._summary = ImportSummary()
        self._pending_csv: list[_Outcome] = []
        self._total = 0
        self._seen = 0
        self._progress: tk.Toplevel | None = None
        self._label: ttk.Label | None = None
        self._bar: ttk.Progressbar | None = None
        self.busy = False

    def start(self, paths: Sequence[Path]) -> None:
        """Import ``paths`` in the background (ignored while an import runs)."""
        if self.busy or not paths:
            return
        self.busy = True
        self._summary, self._pending_csv, self._total = ImportSummary(), [], len(paths)
        self._summary.files, self._seen = len(paths), 0
        known = {s.sha256 for s in self._session.workspace.library.statements if s.sha256}
        worker = threading.Thread(target=_work, args=(list(paths), known, self._queue), daemon=True)
        worker.start()
        if len(paths) > 1:
            self._open_progress()
        self._root.after(POLL_MS, self._poll)

    def _open_progress(self) -> None:
        window = tk.Toplevel(self._root)
        window.title("Einlesen…")
        window.geometry(PROGRESS_SIZE)
        window.transient(self._root)
        window.protocol("WM_DELETE_WINDOW", lambda: None)  # closes itself when done
        self._label = ttk.Label(window, text="Starte…")
        self._label.pack(anchor="w", padx=PAD_LARGE, pady=PAD)
        self._bar = ttk.Progressbar(window, length=BAR_LENGTH, maximum=self._total)
        self._bar.pack(padx=PAD_LARGE)
        self._progress = window

    def _poll(self) -> None:
        """Apply what the worker delivered; poll again until its end marker arrived – also if
        applying one file failed unexpectedly, so the import always ends."""
        finished = False
        try:
            finished = self._drain()
        finally:
            if not finished:
                self._root.after(POLL_MS, self._poll)

    def _drain(self) -> bool:
        while True:
            try:
                outcome = self._queue.get_nowait()
            except queue.Empty:
                return False
            if outcome is None:
                self._finish()
                return True
            self._apply(outcome)

    def _apply(self, outcome: _Outcome) -> None:
        name = outcome.path.name
        self._seen += 1
        visible = self._progress is not None and self._progress.winfo_exists()
        if visible and self._label is not None and self._bar is not None:
            self._label.configure(text=f"{self._seen}/{self._total}: {name}")
            self._bar.step()
        if outcome.needs_mapping:
            self._pending_csv.append(outcome)
        elif outcome.error is not None:
            self._summary.failed.append((name, error_message(outcome.error)))
        elif outcome.parsed is not None:
            self._import(outcome.path, outcome.parsed, outcome.sha256)
        else:  # the hash was known before the import started
            self._summary.already_imported.append(name)

    def _import(self, path: Path, parsed: ParsedStatement, sha256: str) -> None:
        try:
            result = self._session.import_parsed(parsed, path, sha256)
        except IaahError as error:  # stored in memory, but saving failed
            self._summary.failed.append((path.name, error_message(error)))
            return
        self._summary.record(path.name, parsed, result)

    def _finish(self) -> None:
        """Close the progress window, ask about CSV files, report – and be ready again even if
        one of these steps fails."""
        try:
            if self._progress is not None and self._progress.winfo_exists():
                self._progress.destroy()
            self._progress, self._label, self._bar = None, None, None
            for outcome in self._pending_csv:
                self._ask_mapping(outcome)
            self._summary.missing_months = self._session.missing_months()
        finally:
            self.busy = False
        self._on_done(self._summary)

    def _ask_mapping(self, outcome: _Outcome) -> None:
        try:
            table = load_table(outcome.path)
        except IaahError as error:
            self._summary.failed.append((outcome.path.name, error_message(error)))
            return
        self._map_and_import(outcome, table)

    def _map_and_import(self, outcome: _Outcome, table: CsvTable) -> None:
        choice = CsvMappingDialog(self._root, table, outcome.path.name).show()
        if choice is None:
            self._summary.failed.append((outcome.path.name, "Zuordnung abgebrochen."))
            return
        mapping, header_row = choice
        try:
            parsed = import_table(table, outcome.path.name, mapping, header_row)
        except IaahError as error:
            self._summary.failed.append((outcome.path.name, error_message(error)))
            return
        self._import(outcome.path, parsed, outcome.sha256)


def _work(
    paths: Sequence[Path], known: Collection[str], results: "queue.Queue[_Outcome | None]"
) -> None:
    """Worker thread: hash and parse every file; never touches Tk or the session. The end
    marker always follows, and a file that breaks the parser in an unforeseen way is reported
    as unreadable instead of ending the thread."""
    try:
        for path in paths:
            try:
                results.put(_examine(path, known))
            except Exception as error:  # noqa: BLE001 – thread boundary: report, do not die
                unexpected = StatementParseError(f"unexpected error: {error!r}")
                results.put(_Outcome(path, error=unexpected))
    finally:
        results.put(None)


def _examine(path: Path, known: Collection[str]) -> _Outcome:
    try:
        sha256 = file_sha256(path)
    except IaahError as error:
        return _Outcome(path, error=error)
    if sha256 in known:
        return _Outcome(path, sha256)
    try:
        return _Outcome(path, sha256, parsed=read_statement_file(path))
    except CsvMappingError:
        return _Outcome(path, sha256, needs_mapping=True)
    except IaahError as error:
        return _Outcome(path, sha256, error=error)
