"""The library: every imported statement, its bookings and the user's manual decisions.

Importing never adds a booking twice. A file already imported (same SHA-256) is skipped as a
whole; otherwise bookings are de-duplicated as a multiset of ``Transaction.key`` – two
identical coffees on one day stay two, an overlapping CSV export adds nothing twice. A
duplicate that brings a PDF placement replaces a stored booking without one ("enriched"):
that is how bookings migrated from the legacy app gain their position in the PDF and the
clean purpose text of the new parser.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from iaah.core.assignments import ManualAssignments
from iaah.core.models import StatementInfo, Transaction
from iaah.core.parsing.diagnostics import ParsedStatement


@dataclass(frozen=True, slots=True)
class StoredStatement:
    """An imported statement file."""

    info: StatementInfo
    path: str | None = None  # where it was imported from, to reopen the PDF
    sha256: str | None = None  # None for statements migrated from the legacy app


@dataclass(frozen=True, slots=True)
class ImportResult:
    """What importing one file did."""

    added: int
    duplicates: int
    enriched: int
    already_imported: bool = False


@dataclass(slots=True)
class Library:
    """Statements, bookings and manual decisions – everything that is personal data."""

    statements: list[StoredStatement] = field(default_factory=list)
    transactions: list[Transaction] = field(default_factory=list)
    assignments: ManualAssignments = field(default_factory=ManualAssignments)

    def knows(self, sha256: str) -> bool:
        """Whether a file with this hash was imported before."""
        return any(stored.sha256 == sha256 for stored in self.statements)

    def add(
        self, parsed: ParsedStatement, path: str | None = None, sha256: str | None = None
    ) -> ImportResult:
        """Import a parsed statement (see module docstring for de-duplication)."""
        if sha256 is not None and self.knows(sha256):
            return ImportResult(0, len(parsed.transactions), 0, already_imported=True)
        result = self._merge(parsed.transactions)
        self._upsert_statement(StoredStatement(parsed.info, path, sha256))
        return result

    def months(self) -> list[str]:
        """Months with bookings, sorted."""
        return sorted({txn.month for txn in self.transactions})

    def reset(self) -> None:
        """Forget all statements and bookings; manual decisions are kept, so re-importing the
        same statements restores the user's work."""
        self.statements.clear()
        self.transactions.clear()

    def _merge(self, incoming: Iterable[Transaction]) -> ImportResult:
        positions: dict[str, list[int]] = defaultdict(list)
        for index, txn in enumerate(self.transactions):
            positions[txn.key].append(index)
        added = duplicates = enriched = 0
        for txn in incoming:
            match = self._take_match(positions.get(txn.key, []), txn)
            if match is None:
                self.transactions.append(txn)
                added += 1
            elif self.transactions[match].placement is None and txn.placement is not None:
                self.transactions[match] = txn
                enriched += 1
            else:
                duplicates += 1
        return ImportResult(added, duplicates, enriched)

    def _take_match(self, candidates: list[int], txn: Transaction) -> int | None:
        """The first stored booking with the same key on a compatible account – equal, or
        unknown on either side (migrated bookings and CSV exports may lack it)."""
        for position, index in enumerate(candidates):
            stored = self.transactions[index].account
            if not stored or not txn.account or stored == txn.account:
                return candidates.pop(position)
        return None

    def _upsert_statement(self, statement: StoredStatement) -> None:
        """Replace a migrated statement of the same file name; otherwise append."""
        for index, stored in enumerate(self.statements):
            if stored.sha256 is None and stored.info.source == statement.info.source:
                self.statements[index] = statement
                return
        self.statements.append(statement)
