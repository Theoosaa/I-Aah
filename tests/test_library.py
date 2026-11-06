"""Library import: hash skip, multiset de-duplication, enrichment, legacy statement upgrade."""

from datetime import date
from decimal import Decimal

from iaah.core.library import Library, StoredStatement
from iaah.core.models import Placement, Region, StatementInfo, Transaction
from iaah.core.parsing.diagnostics import ParsedStatement

PLACED = Placement(Region(1, (0, 0, 1, 1)))


def _txn(payee: str, amount: str = "-3.00", placement: Placement | None = None) -> Transaction:
    return Transaction(
        date(2026, 7, 1), "", payee, "", Decimal(amount), "juli.pdf", placement=placement
    )


def _parsed(*transactions: Transaction, source: str = "juli.pdf") -> ParsedStatement:
    return ParsedStatement(StatementInfo(source, period="2026-07"), transactions)


def test_identical_bookings_in_one_statement_stay_two() -> None:
    library = Library()
    result = library.add(_parsed(_txn("Kaffee"), _txn("Kaffee")), sha256="a")
    assert (result.added, result.duplicates) == (2, 0)
    assert len(library.transactions) == 2


def test_same_file_is_skipped_as_a_whole() -> None:
    library = Library()
    library.add(_parsed(_txn("Kaffee")), sha256="a")
    result = library.add(_parsed(_txn("Kaffee")), sha256="a")
    assert result.already_imported
    assert len(library.statements) == 1


def test_overlapping_export_adds_only_what_is_new() -> None:
    library = Library()
    library.add(_parsed(_txn("Kaffee"), _txn("Kaffee")), sha256="pdf")
    result = library.add(
        _parsed(_txn("Kaffee"), _txn("Kaffee"), _txn("Brot"), source="x.csv"), sha256="csv"
    )
    assert (result.added, result.duplicates) == (1, 2)
    assert len(library.transactions) == 3


def test_placement_enriches_a_migrated_booking() -> None:
    library = Library(transactions=[_txn("Kaffee")])
    result = library.add(_parsed(_txn("Kaffee", placement=PLACED)), sha256="a")
    assert (result.added, result.duplicates, result.enriched) == (0, 0, 1)
    assert library.transactions[0].placement == PLACED


def test_migrated_statement_is_upgraded_in_place() -> None:
    legacy = StoredStatement(StatementInfo("juli.pdf", period="2026-07"))
    library = Library(statements=[legacy])
    library.add(_parsed(_txn("Kaffee")), path="C:/x/juli.pdf", sha256="a")
    (stored,) = library.statements
    assert (stored.path, stored.sha256) == ("C:/x/juli.pdf", "a")


def test_months_and_reset_keep_manual_decisions() -> None:
    library = Library()
    library.add(_parsed(_txn("Kaffee")), sha256="a")
    library.assignments.set_category(library.transactions[0], "Café")
    assert library.months() == ["2026-07"]
    library.reset()
    assert (library.statements, library.transactions) == ([], [])
    assert len(library.assignments) == 1


def test_same_booking_on_two_accounts_stays_two() -> None:
    library = Library()
    first = Transaction(date(2026, 7, 31), "", "Gebühr", "", Decimal("-4.90"), "a.pdf", "111")
    second = Transaction(date(2026, 7, 31), "", "Gebühr", "", Decimal("-4.90"), "b.pdf", "222")
    library.add(_parsed(first, source="a.pdf"), sha256="a")
    result = library.add(_parsed(second, source="b.pdf"), sha256="b")
    assert result.added == 1
    assert len(library.transactions) == 2


def test_unknown_account_still_deduplicates() -> None:
    library = Library(transactions=[_txn("Kaffee")])  # migrated: no account
    with_account = Transaction(date(2026, 7, 1), "", "Kaffee", "", Decimal("-3.00"), "j.pdf", "111")
    assert library.add(_parsed(with_account), sha256="a").duplicates == 1


def test_enrichment_keeps_manual_decisions() -> None:
    migrated = _txn("Kaffee")
    library = Library(transactions=[migrated])
    library.assignments.set_category(migrated, "Café")
    library.add(_parsed(_txn("Kaffee", placement=PLACED)), sha256="a")
    assert library.assignments.get(library.transactions[0].key) == "Café"
    assert library.knows("a")
