"""The user's working state – category catalog plus library – and the operations that need
both: importing statement files and building the analysis entries.

Renaming or removing categories together with their manual decisions is done through
``Workspace.categorizer`` (``Categorizer.rename_category`` / ``remove_category``).
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Self

from iaah.core.analysis.ledger import Entry, build_entries
from iaah.core.assignments import Categorizer
from iaah.core.categories import CategoryCatalog
from iaah.core.errors import StatementParseError
from iaah.core.library import ImportResult, Library
from iaah.core.parsing.csv_import import read_csv
from iaah.core.parsing.diagnostics import ParsedStatement
from iaah.core.parsing.ing import read_statement
from iaah.core.storage import DataStore

PDF_SUFFIX: Final = ".pdf"
CSV_SUFFIX: Final = ".csv"
HASH_ALGORITHM: Final = "sha256"


@dataclass(slots=True)
class Workspace:
    """Catalog and library of one user."""

    catalog: CategoryCatalog
    library: Library

    @classmethod
    def load(cls, store: DataStore) -> Self:
        """Read catalog and library (defaults on first start)."""
        catalog, library = store.load()
        return cls(catalog, library)

    def save(self, store: DataStore) -> None:
        """Write catalog and library together."""
        store.save(self.catalog, self.library)

    @property
    def categorizer(self) -> Categorizer:
        """Resolves bookings with the catalog and the library's manual decisions."""
        return Categorizer(self.catalog, self.library.assignments)

    def is_empty(self) -> bool:
        """No statements and no bookings yet (e.g. before migrating legacy data)."""
        return not self.library.statements and not self.library.transactions

    def import_file(self, path: Path) -> ImportResult:
        """Read a statement file (PDF or CSV, by suffix) and add it to the library.

        A file imported before is recognised by its hash without being parsed again; only its
        new location is remembered. Raises ``StatementParseError`` / ``CsvMappingError``; for a
        CSV whose columns cannot be detected the GUI asks for the mapping and calls
        ``import_parsed``.
        """
        digest = file_sha256(path)
        if self.library.knows(digest):
            relocated = self.library.relocate(digest, str(path))
            return ImportResult(0, 0, 0, already_imported=True, relocated=relocated)
        return self.library.add(read_statement_file(path), str(path), digest)

    def import_parsed(self, parsed: ParsedStatement, path: Path) -> ImportResult:
        """Add an already parsed statement of ``path`` to the library."""
        return self.library.add(parsed, str(path), file_sha256(path))

    def entries(self) -> list[Entry]:
        """All bookings, categorized once, as input for the analysis."""
        return build_entries(self.library.transactions, self.categorizer)


def read_statement_file(path: Path) -> ParsedStatement:
    """Parse a statement with the reader its suffix calls for."""
    suffix = path.suffix.lower()
    if suffix == PDF_SUFFIX:
        return read_statement(path)
    if suffix == CSV_SUFFIX:
        return read_csv(path)
    raise StatementParseError(f"unsupported statement file type: {suffix!r}")


def file_sha256(path: Path) -> str:
    """Hex SHA-256 of a file, to recognise a statement that was imported before."""
    try:
        with path.open("rb") as handle:
            return hashlib.file_digest(handle, HASH_ALGORITHM).hexdigest()
    except OSError as error:
        raise StatementParseError(f"cannot read {path}") from error
