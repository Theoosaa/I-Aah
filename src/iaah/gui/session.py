"""The GUI's state and actions, without tkinter – the part of the GUI worth testing.

A ``Session`` owns the workspace and the store. Every change of the catalog or the manual
decisions runs through ``_change``: it snapshots both for undo, applies the change and saves at
once (atomic, optionally encrypted). Imports change only the library and are not undoable – the
GUI asks before destructive library actions.
"""

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Final

from iaah.charts.chart import DrillKind
from iaah.charts.gallery import ChartInput
from iaah.core.analysis.ledger import (
    Entry,
    Period,
    entries_of_category,
    entries_of_day,
    entries_of_merchant,
    in_period,
)
from iaah.core.analysis.timeline import missing_months
from iaah.core.assignments import (
    AssignmentSource,
    Categorizer,
    ManualAssignments,
    Resolution,
    SplitPart,
)
from iaah.core.categories import CategoryCatalog, CategoryKind
from iaah.core.category_io import default_catalog
from iaah.core.library import ImportResult, Library, StoredStatement
from iaah.core.models import Transaction
from iaah.core.parsing.diagnostics import ParsedStatement
from iaah.core.parsing.ing import read_statement
from iaah.core.storage import DataStore
from iaah.core.suggestions import KeywordPreview, suggest_keywords
from iaah.core.workspace import Workspace
from iaah.gui.viewmodel import (
    Column,
    Filters,
    KpiView,
    Row,
    build_rows,
    kpi_view,
    next_open,
    sort_rows,
)

UNDO_LIMIT: Final = 50
PDF_SUFFIX: Final = ".pdf"


@dataclass(frozen=True, slots=True)
class _State:
    """What undo restores: the catalog and the manual decisions."""

    catalog: CategoryCatalog
    manual: ManualAssignments


@dataclass(slots=True)
class ImportSummary:
    """What a batch of files did, for the message after an import."""

    files: int = 0
    added: int = 0
    duplicates: int = 0
    enriched: int = 0
    already_imported: list[str] = field(default_factory=list)
    without_bookings: list[str] = field(default_factory=list)
    not_reconciling: list[str] = field(default_factory=list)
    with_problems: list[str] = field(default_factory=list)  # suspicious or unreadable lines
    failed: list[tuple[str, str]] = field(default_factory=list)  # file, German reason
    missing_months: list[str] = field(default_factory=list)

    def record(self, name: str, parsed: ParsedStatement, result: ImportResult) -> None:
        """Count one imported file and note what deserves a look (``files`` is set by the
        importer to the number of files handed in)."""
        if result.already_imported:
            self.already_imported.append(name)
            return
        self.added += result.added
        self.duplicates += result.duplicates
        self.enriched += result.enriched
        if not parsed.transactions:
            self.without_bookings.append(name)
        if parsed.info.reconciles is False:
            self.not_reconciling.append(name)
        if parsed.report.has_problems:
            self.with_problems.append(name)

    def message(self) -> str:
        """The German summary shown after an import."""
        lines = [
            f"{self.files} Datei(en) verarbeitet: {self.added} neue Buchungen, "
            f"{self.duplicates} schon vorhanden, {self.enriched} um ihre PDF-Position "
            "ergänzt."
        ]
        notes = (
            ("Bereits importiert (übersprungen)", self.already_imported),
            ("Keine Buchungen erkannt", self.without_bookings),
            ("Saldo stimmt nicht – bitte in der PDF-Prüfung ansehen", self.not_reconciling),
            ("Auffällige Zeilen – bitte in der PDF-Prüfung ansehen", self.with_problems),
            ("Fehlende Monate in der Reihe", self.missing_months),
        )
        lines += [f"{title}: {', '.join(items)}" for title, items in notes if items]
        lines += [f"Nicht lesbar: {name} – {reason}" for name, reason in self.failed]
        return "\n\n".join(lines)


class Session:
    """Workspace, filters, selection and undo of one running app."""

    def __init__(self, workspace: Workspace, store: DataStore | None = None) -> None:
        self.workspace = workspace
        self.store = store
        self.filters = Filters()
        self.sort: tuple[Column, bool] = (Column.DATE, False)
        self.selection: list[int] = []
        self._undo: list[_State] = []
        self._redo: list[_State] = []
        self._resolutions: list[Resolution] | None = None  # cache until anything changes

    # -- basics -----------------------------------------------------------------------------

    def resolutions(self) -> list[Resolution]:
        """The category of every booking, in library order – computed once per change, so
        typing in a filter does not resolve thousands of bookings per key."""
        if self._resolutions is None:
            categorizer = self.categorizer
            self._resolutions = [categorizer.resolve(txn) for txn in self.transactions]
        return self._resolutions

    def is_pristine(self) -> bool:
        """Nothing of the user's yet: no bookings, no decisions, the default categories – the
        only state legacy data may be taken over into."""
        library = self.workspace.library
        untouched = list(self.catalog) == list(default_catalog())
        return untouched and self.workspace.is_empty() and not len(library.assignments)

    def _changed(self) -> None:
        """Forget cached categories and drop a category filter that no longer exists."""
        self._resolutions = None
        if self.filters.category and self.filters.category not in self.catalog:
            self.filters.category = ""

    @property
    def categorizer(self) -> Categorizer:
        """Resolves bookings with the current catalog and decisions."""
        return self.workspace.categorizer

    @property
    def catalog(self) -> CategoryCatalog:
        """The category catalog."""
        return self.workspace.catalog

    @property
    def transactions(self) -> list[Transaction]:
        """All bookings; a row's index points into this list."""
        return self.workspace.library.transactions

    def save(self) -> None:
        """Write catalog and library (``StorageError`` if that fails; the session goes on)."""
        if self.store is not None:
            self.workspace.save(self.store)

    # -- the table --------------------------------------------------------------------------

    def rows(self) -> list[Row]:
        """The filtered, sorted bookings."""
        rows = build_rows(self.transactions, self.resolutions(), self.catalog, self.filters)
        return sort_rows(rows, *self.sort)

    def sort_by(self, column: Column) -> None:
        """Sort by ``column``; the same column again reverses the order."""
        current, descending = self.sort
        self.sort = (column, not descending if column is current else False)

    def select(self, indexes: Iterable[int]) -> None:
        """Remember the selected bookings (indexes into ``transactions``)."""
        self.selection = [index for index in indexes if 0 <= index < len(self.transactions)]

    def selected(self) -> list[Transaction]:
        """The selected bookings."""
        return [self.transactions[index] for index in self.selection]

    def next_open(self) -> int | None:
        """The next booking a fallback caught, after the last selected one in the view."""
        return next_open(self.rows(), self.selection[-1] if self.selection else None)

    # -- deciding categories ------------------------------------------------------------------

    def assign(self, category: str) -> int:
        """Give every selected booking ``category``; returns how many were selected."""
        return self.assign_to(self.selected(), category)

    def assign_to(self, bookings: Sequence[Transaction], category: str) -> int:
        """Give ``bookings`` ``category`` – also bookings parsed again for the PDF review
        (decisions are stored by booking key)."""

        def apply() -> None:
            categorizer = self.categorizer
            for txn in bookings:
                categorizer.assign(txn, category)

        self._change(apply)
        return len(bookings)

    def split(self, index: int, parts: Sequence[SplitPart]) -> None:
        """Divide one booking (``SplitError`` if the parts do not add up)."""
        txn = self.transactions[index]
        self._change(lambda: self.categorizer.split(txn, parts))

    def clear(self) -> None:
        """Return the selected bookings to automatic categorization."""
        bookings = self.selected()

        def apply() -> None:
            for txn in bookings:
                self.workspace.library.assignments.clear(txn)

        self._change(apply)

    def suggestions(self, index: int) -> list[KeywordPreview]:
        """Keyword candidates after a manual decision, with their effect. Nothing for other
        bookings: a keyword for an open booking would only route it to the fallback, and a
        split has several categories."""
        txn = self.transactions[index]
        resolution = self.categorizer.resolve(txn)
        if resolution.source is not AssignmentSource.MANUAL:
            return []
        return suggest_keywords(self.categorizer, txn, resolution.category, self.transactions)

    def accept_keyword(self, keyword: str, category: str) -> int:
        """Add (or move) ``keyword`` to ``category`` and drop the decisions it makes
        unnecessary; returns how many were dropped."""

        def apply() -> int:
            stored = self.catalog.move_keyword(keyword, category)
            return len(self.categorizer.prune_redundant(self.transactions, stored))

        return self._change(apply)

    def prune_all(self) -> int:
        """Drop every manual decision that a keyword makes anyway."""
        return self._change(lambda: len(self.categorizer.prune_redundant(self.transactions)))

    # -- categories ---------------------------------------------------------------------------

    def add_category(
        self, name: str, color: str | None = None, kind: CategoryKind = CategoryKind.EXPENSE
    ) -> str:
        """Append a category; returns its stored name."""
        return self._change(lambda: self.catalog.add(name, kind, color).name)

    def rename_category(self, old: str, new: str) -> str:
        """Rename in catalog and decisions (and in the category filter); returns the stored
        name."""
        filtered = self.filters.category == old
        stored = self._change(lambda: self.categorizer.rename_category(old, new))
        if filtered:
            self.filters.category = stored
        return stored

    def recolor(self, name: str, color: str) -> None:
        """Change a category's color."""
        self._change(lambda: self.catalog.set_color(name, color))

    def set_kind(self, name: str, kind: CategoryKind) -> None:
        """Expense, income or ignored."""
        self._change(lambda: self.catalog.set_kind(name, kind))

    def set_budgets(self, budgets: Mapping[str, Decimal | None]) -> None:
        """Monthly budgets; ``None`` removes one. All or none are stored: the catalog is
        replaced only when every value is valid."""

        def apply() -> None:
            trial = self.catalog.copy()
            for name, budget in budgets.items():
                trial.set_budget(name, budget)
            self.workspace.catalog = trial

        self._change(apply)

    def set_keywords(self, name: str, keywords: Iterable[str]) -> None:
        """Replace a category's keyword list (``KeywordConflictError`` names a taken one)."""
        listed = list(keywords)
        self._change(lambda: self.catalog.set_keywords(name, listed))

    def move_category(self, name: str, position: int) -> None:
        """Change the display order (keys 1–9 follow it)."""
        self._change(lambda: self.catalog.move(name, position))

    def remove_category(self, name: str) -> int:
        """Delete a category; returns how many manual decisions went with it."""
        return self._change(lambda: self.categorizer.remove_category(name))

    def decisions_using(self, name: str) -> int:
        """How many manual decisions refer to category ``name``."""
        return sum(name in _names(entry) for _, entry in self.workspace.library.assignments.items())

    def replace_catalog(self, catalog: CategoryCatalog) -> int:
        """Use a loaded category file; returns how many decisions name a category it lacks
        (they are kept, but ignored until such a category exists again)."""

        def apply() -> None:
            self.workspace.catalog = catalog

        self._change(apply)
        entries = self.workspace.library.assignments.items()
        return sum(any(name not in catalog for name in _names(entry)) for _, entry in entries)

    # -- undo ---------------------------------------------------------------------------------

    @property
    def can_undo(self) -> bool:
        """Whether there is a change to undo."""
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        """Whether there is an undone change to redo."""
        return bool(self._redo)

    def undo(self) -> bool:
        """Restore the state before the last change."""
        return self._swap(self._undo, self._redo)

    def redo(self) -> bool:
        """Apply the last undone change again."""
        return self._swap(self._redo, self._undo)

    def _swap(self, source: list[_State], target: list[_State]) -> bool:
        if not source:
            return False
        target.append(self._snapshot())
        state = source.pop()
        self.workspace.catalog = state.catalog
        self.workspace.library.assignments = state.manual
        self._changed()
        self.save()
        return True

    def _snapshot(self) -> _State:
        return _State(self.catalog.copy(), self.workspace.library.assignments.copy())

    def _unchanged_since(self, state: _State) -> bool:
        same_catalog = list(state.catalog) == list(self.catalog)
        manual = self.workspace.library.assignments
        return same_catalog and dict(state.manual.items()) == dict(manual.items())

    def _change[T](self, action: Callable[[], T]) -> T:
        """Apply ``action`` with an undo snapshot, then save. If it raises, nothing changed
        (catalog and decisions validate before they commit); if it changed nothing (the same
        color again, the top category moved up), no undo step and no save."""
        before = self._snapshot()
        result = action()
        if self._unchanged_since(before):
            return result
        self._undo.append(before)
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()
        self._changed()
        self.save()
        return result

    # -- library ------------------------------------------------------------------------------

    def import_parsed(self, parsed: ParsedStatement, path: Path, sha256: str) -> ImportResult:
        """Add a parsed file to the library and save."""
        result = self.workspace.library.add(parsed, str(path), sha256)
        self._changed()
        self.save()
        return result

    def knows(self, sha256: str) -> bool:
        """Whether a file with this hash was imported before."""
        return self.workspace.library.knows(sha256)

    def adopt(self, catalog: CategoryCatalog, library: Library) -> None:
        """Take over migrated data as the new state; undo starts afresh. Only call it while
        ``is_pristine`` – or after the user confirmed replacing what is there."""
        self.workspace = Workspace(catalog, library)
        self.selection, self._undo, self._redo = [], [], []
        self.filters = Filters()
        self._changed()
        self.save()

    # -- password -----------------------------------------------------------------------------

    @property
    def encrypted(self) -> bool:
        """Whether the data is stored encrypted."""
        return self.store is not None and self.store.encrypted

    def verify_password(self, password: str) -> None:
        """``WrongPasswordError`` unless ``password`` opens the stored data."""
        if self.store is not None:
            self.store.unlock(password)

    def enable_encryption(self, password: str) -> None:
        """Encrypt the data (also to change the password)."""
        if self.store is not None:
            self.store.enable_encryption(password, self.catalog, self.workspace.library)

    def disable_encryption(self) -> None:
        """Store the data unencrypted."""
        if self.store is not None:
            self.store.disable_encryption(self.catalog, self.workspace.library)

    def reset_library(self) -> None:
        """Forget statements and bookings; categories and decisions stay."""
        self.workspace.library.reset()
        self.selection = []
        self._changed()
        self.save()

    def missing_months(self) -> list[str]:
        """Months without bookings between the first and the last imported one."""
        return missing_months(txn.month for txn in self.transactions)

    def reviewable(self) -> list[StoredStatement]:
        """Imported PDF statements whose file still exists, newest period first."""
        paths = [
            (stored, Path(stored.path))
            for stored in self.workspace.library.statements
            if stored.path
        ]
        statements = [
            stored for stored, path in paths if path.suffix.lower() == PDF_SUFFIX and path.exists()
        ]
        return sorted(statements, key=lambda stored: stored.info.period, reverse=True)

    @staticmethod
    def open_statement(stored: StoredStatement) -> ParsedStatement:
        """Parse a stored statement again – placements and line report for the review tab."""
        return read_statement(Path(stored.path or ""))

    def statement_of(self, txn: Transaction) -> StoredStatement | None:
        """The reviewable statement a booking came from, if its PDF still exists."""
        return next((s for s in self.reviewable() if s.info.source == txn.source), None)

    def is_statement_file(self, path: Path) -> bool:
        """Whether ``path`` is an imported statement – exports must never overwrite one."""
        target = path.resolve()
        stored = (Path(s.path).resolve() for s in self.workspace.library.statements if s.path)
        return any(candidate == target for candidate in stored)

    # -- analysis -----------------------------------------------------------------------------

    def entries(self) -> list[Entry]:
        """All bookings, categorized."""
        return self.workspace.entries()

    def chart_input(self, period: Period) -> ChartInput:
        """What the charts of ``period`` read."""
        return ChartInput.of_workspace(self.workspace, period)

    def kpis(self, period: Period) -> KpiView:
        """KPI cards of ``period``."""
        return kpi_view(self.entries(), period)

    def drill(self, kind: DrillKind, value: str, period: Period) -> list[Entry]:
        """The entries behind a clicked chart element (split parts with their own amount)."""
        entries = in_period(self.entries(), period)
        if kind is DrillKind.CATEGORY:
            return entries_of_category(entries, value)
        if kind is DrillKind.MERCHANT:
            return entries_of_merchant(entries, value)
        return entries_of_day(entries, date.fromisoformat(value))


def _names(entry: str | tuple[SplitPart, ...]) -> list[str]:
    return [entry] if isinstance(entry, str) else [part.category for part in entry]
