"""GUI state without a display: filters, rows, assigning, keywords, undo, categories, analysis."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from iaah.charts.chart import DrillKind
from iaah.core.analysis.ledger import Period
from iaah.core.analysis.totals import BudgetLevel
from iaah.core.assignments import SplitPart
from iaah.core.categories import CategoryKind
from iaah.core.category_io import default_catalog
from iaah.core.errors import CategoryError, KeywordConflictError, SplitError
from iaah.core.library import ImportResult, Library, StoredStatement
from iaah.core.migration import DroppedItem, DropReason, MigrationReport
from iaah.core.models import StatementInfo, Transaction
from iaah.core.parsing.ing import read_statement
from iaah.core.parsing.layout import LineStatus
from iaah.core.storage import DataPaths, DataStore
from iaah.core.workspace import Workspace
from iaah.gui.session import ImportSummary, Session
from iaah.gui.viewmodel import (
    Column,
    Direction,
    Marker,
    Row,
    Trend,
    accounts,
    booking_at,
    booking_details,
    budget_from_text,
    budget_rows,
    decision_text,
    migration_text,
    periods,
    review_boxes,
    unused_lines,
    view_totals,
)

KIOSK = Transaction(date(2026, 2, 27), "Lastschrift", "Kiosk am Markt", "Zeitung",
                    Decimal("-4.50"), "auszug-2026-02.pdf", "1234567890")  # fmt: skip


@pytest.fixture
def session(workspace: Workspace, tmp_path: Path) -> Session:
    """The synthetic workspace plus one open booking, saving into ``tmp_path``."""
    workspace.library.transactions.append(KIOSK)
    return Session(workspace, DataStore(DataPaths(tmp_path)))


def _index(session: Session, payee: str) -> int:
    return next(i for i, txn in enumerate(session.transactions) if txn.payee == payee)


def _payees(session: Session) -> list[str]:
    return [row.transaction.payee for row in session.rows()]


# -- rows and filters -------------------------------------------------------------------------


def test_rows_show_how_each_category_was_decided(session: Session) -> None:
    rows: dict[str, Row] = {}
    for row in session.rows():  # date order: the first booking per payee
        rows.setdefault(row.transaction.payee, row)
    assert rows["Kiosk am Markt"].marker is Marker.FALLBACK
    assert rows["Kiosk am Markt"].cells[-1] == "? Sonstiges"
    assert rows["Drogerie am Eck"].cells[-1] == "÷ Lebensmittel + Gesundheit"
    assert rows["REWE Markt"].marker is Marker.KEYWORD
    assert rows["REWE Markt"].cells[:2] == ("05.11.2025", "Lastschrift")
    assert rows["REWE Markt"].cells[4] == "-54,30 €"


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"category": "Gesundheit"}, {"Drogerie am Eck"}),  # a split part counts
        ({"text": "zeitung"}, {"Kiosk am Markt"}),
        ({"only_open": True}, {"Kiosk am Markt"}),
        ({"direction": Direction.IN}, {"Arbeitgeber GmbH", "AMAZON EU"}),
        ({"minimum": Decimal(800), "maximum": Decimal(1000)}, {"Hausverwaltung Nord"}),
        ({"account": "fremd"}, set()),
    ],
)
def test_filters(session: Session, change: dict[str, object], expected: set[str]) -> None:
    for name, value in change.items():
        setattr(session.filters, name, value)
    assert set(_payees(session)) == expected


def test_period_filter_and_sorting(session: Session) -> None:
    session.filters.period = Period.of_month(2026, 2)
    assert {row.transaction.month for row in session.rows()} == {"2026-02"}
    session.sort_by(Column.AMOUNT)
    amounts = [row.transaction.amount for row in session.rows()]
    assert amounts == sorted(amounts)
    session.sort_by(Column.AMOUNT)  # again: descending
    assert [row.transaction.amount for row in session.rows()] == sorted(amounts, reverse=True)


def test_view_totals_and_options(session: Session) -> None:
    totals = view_totals(session.rows())
    assert totals.count == len(session.transactions)
    assert totals.open == 1
    assert totals.income == Decimal("10030.00")  # four salaries and a refund
    assert accounts(session.transactions) == ["1234567890"]
    labels = [str(period) for period in periods(session.transactions)]
    assert labels[:4] == ["", "2026", "2025", "2026-02"]


# -- deciding -------------------------------------------------------------------------------


def test_assign_undo_redo_and_saving(session: Session, tmp_path: Path) -> None:
    kiosk = _index(session, "Kiosk am Markt")
    session.select([kiosk])
    assert session.assign("Freizeit") == 1
    assert session.categorizer.resolve(KIOSK).is_manual
    assert (tmp_path / "library.json").exists()
    assert session.undo()
    assert not session.categorizer.resolve(KIOSK).is_manual
    assert session.redo()
    assert session.categorizer.resolve(KIOSK).category == "Freizeit"
    assert not session.can_redo


def test_assigning_the_keyword_category_stores_nothing(session: Session) -> None:
    session.select([_index(session, "Hausverwaltung Nord")])
    session.assign("Wohnen")
    assert len(session.workspace.library.assignments) == 1  # only the fixture's split


def test_multi_select_split_and_clear(session: Session) -> None:
    rewe = [i for i, txn in enumerate(session.transactions) if txn.payee == "REWE Markt"]
    session.select(rewe)
    assert session.assign("Restaurant & Café") == len(rewe)
    session.clear()
    assert all(not session.categorizer.resolve(session.transactions[i]).is_manual for i in rewe)
    kiosk = _index(session, "Kiosk am Markt")
    with pytest.raises(SplitError):
        session.split(kiosk, [SplitPart("Freizeit", Decimal("-1.00"))])
    assert not session.can_redo
    parts = [SplitPart("Freizeit", Decimal("-3.00")), SplitPart("Lebensmittel", Decimal("-1.50"))]
    session.split(kiosk, parts)
    assert session.categorizer.resolve(KIOSK).parts == tuple(parts)


def test_failed_changes_leave_no_undo_step(session: Session) -> None:
    session.select([0])
    with pytest.raises(CategoryError):
        session.assign("Gibt es nicht")
    assert not session.can_undo


def test_next_open_wraps_around(session: Session) -> None:
    kiosk = _index(session, "Kiosk am Markt")
    session.select([kiosk])
    assert session.next_open() == kiosk  # the only open one, found again after wrapping
    session.assign("Freizeit")
    assert session.next_open() is None


def test_keyword_suggestion_accept_and_undo(session: Session) -> None:
    kiosk = _index(session, "Kiosk am Markt")
    session.select([kiosk])
    session.assign("Freizeit")
    previews = session.suggestions(kiosk)
    assert previews[0].keyword == "kiosk"  # "markt" is too generic to be suggested
    assert (previews[0].matches, previews[0].changes) == (1, 0)
    assert session.accept_keyword("kiosk", "Freizeit") == 1  # the decision became redundant
    assert session.catalog.category_of_keyword("kiosk") == "Freizeit"
    assert not session.categorizer.resolve(KIOSK).is_manual
    session.undo()
    assert session.catalog.category_of_keyword("kiosk") is None
    assert session.categorizer.resolve(KIOSK).is_manual


def test_split_bookings_get_no_suggestions(session: Session) -> None:
    assert session.suggestions(_index(session, "Drogerie am Eck")) == []


# -- categories -------------------------------------------------------------------------------


def test_category_edits(session: Session) -> None:
    name = session.add_category("Hobby", "#123456")
    session.select([_index(session, "Kiosk am Markt")])
    session.assign(name)
    assert session.rename_category("Hobby", "Freizeit 2") == "Freizeit 2"
    assert session.categorizer.resolve(KIOSK).category == "Freizeit 2"
    assert session.decisions_using("Freizeit 2") == 1
    session.set_kind("Freizeit 2", CategoryKind.IGNORED)
    session.recolor("Freizeit 2", "#654321")
    session.move_category("Freizeit 2", 0)
    assert session.catalog.names()[0] == "Freizeit 2"
    assert session.remove_category("Freizeit 2") == 1
    assert "Freizeit 2" not in session.catalog


def test_budgets_are_stored_all_or_nothing(session: Session) -> None:
    with pytest.raises(CategoryError):
        session.set_budgets({"Wohnen": Decimal("950.00"), "Shopping": Decimal("-1")})
    assert session.catalog.get("Wohnen").budget is None
    session.set_budgets({"Wohnen": Decimal("950.00"), "Shopping": None})
    assert session.catalog.get("Wohnen").budget == Decimal("950.00")
    assert session.catalog.get("Shopping").budget is None


def test_keyword_conflicts_are_reported(session: Session) -> None:
    with pytest.raises(KeywordConflictError):
        session.set_keywords("Freizeit", ["kino", "rewe"])
    assert "rewe" in session.catalog.keywords_of("Lebensmittel")


def test_replacing_the_catalog_counts_orphaned_decisions(session: Session) -> None:
    catalog = default_catalog()
    catalog.remove("Gesundheit")
    assert session.replace_catalog(catalog) == 1  # the split uses Gesundheit
    session.undo()
    assert "Gesundheit" in session.catalog


# -- library ----------------------------------------------------------------------------------


def test_import_and_reset(session: Session, statement_pdf: Path) -> None:
    parsed = read_statement(statement_pdf)
    result = session.import_parsed(parsed, statement_pdf, "abc")
    assert result.added == 3
    assert session.knows("abc")
    assert session.reviewable()[0].path == str(statement_pdf)
    session.reset_library()
    assert session.transactions == []
    assert len(session.workspace.library.assignments) == 1  # decisions stay


def test_missing_months(session: Session) -> None:
    session.workspace.library.transactions[:] = [
        t for t in session.transactions if t.month != "2025-12"
    ]
    assert session.missing_months() == ["2025-12"]


# -- analysis ---------------------------------------------------------------------------------


def test_kpi_cards_compare_with_the_previous_period(session: Session) -> None:
    view = session.kpis(Period.of_month(2026, 2))
    assert view.figures.months == 1
    assert view.expense is not None  # February cost a little more than January
    assert (view.expense.arrow, view.expense.trend) == ("▲", Trend.BAD)
    assert view.income is not None and view.income.arrow == "▲"
    assert view.savings_rate is not None and view.savings_rate.text.endswith("%-Pkt.")
    assert session.kpis(Period.all_time()).income is None


def test_drill_uses_split_parts(session: Session) -> None:
    entries = session.drill(DrillKind.CATEGORY, "Gesundheit", Period.of_month(2026, 2))
    assert [entry.amount for entry in entries] == [Decimal("-15.00")]
    days = session.drill(DrillKind.DAY, "2026-02-02", Period.all_time())
    assert {entry.transaction.payee for entry in days} == {"Hausverwaltung Nord"}


# -- PDF review -------------------------------------------------------------------------------


def test_review_hit_test_and_boxes(session: Session, statement_pdf: Path) -> None:
    session.import_parsed(read_statement(statement_pdf), statement_pdf, "abc")
    parsed = session.open_statement(session.reviewable()[0])
    head = parsed.transactions[1].placement
    assert head is not None
    x0, top, x1, bottom = head.head.bbox
    scale = 2.0
    point = ((x0 + x1) / 2 * scale, (top + bottom) / 2 * scale)
    assert booking_at(parsed.transactions, 1, point, scale) == 1
    assert booking_at(parsed.transactions, 2, point, scale) is None

    stored = next(i for i, t in enumerate(session.transactions) if t.payee == "REWE Markt"
                  and t.booking_date == date(2026, 7, 2))  # fmt: skip
    session.select([stored])
    session.assign("Restaurant & Café")
    after = review_boxes(parsed.transactions, session.categorizer, before=False)
    before = review_boxes(parsed.transactions, session.categorizer, before=True)
    assert after[1].changed and not after[0].changed
    assert after[1].color == session.catalog.color_of("Restaurant & Café")
    assert before[1].color == session.catalog.color_of("Lebensmittel")


def test_statements_without_file_are_not_reviewable(session: Session, tmp_path: Path) -> None:
    info = StatementInfo("weg.pdf", period="2026-07")
    session.workspace.library.statements.append(StoredStatement(info, str(tmp_path / "weg.pdf")))
    assert session.reviewable() == []


# -- texts and rows of the other tabs ---------------------------------------------------------


def test_decision_texts(session: Session) -> None:
    categorizer = session.categorizer
    rewe = session.transactions[_index(session, "REWE Markt")]
    assert decision_text(categorizer.resolve(rewe)) == "Stichwort „rewe“ → Lebensmittel"
    assert decision_text(categorizer.resolve(KIOSK)).startswith("Kein Stichwort passt")
    split = session.transactions[_index(session, "Drogerie am Eck")]
    assert decision_text(categorizer.resolve(split)) == (
        "Aufgeteilt: Lebensmittel -25,00 € + Gesundheit -15,00 €"
    )
    assert booking_details(KIOSK).splitlines()[:3] == [
        "27.02.2026   -4,50 €",
        "Lastschrift",
        "Kiosk am Markt",
    ]


def test_unused_lines_list_suspicious_ones_first(statement_pdf: Path) -> None:
    report = read_statement(statement_pdf).report
    assert unused_lines(report) == []  # the synthetic statement is clean
    head = report.lines[3]
    flagged = replace(
        report,
        suspicious=(head,),
        lines=(*report.lines, replace(head, status=LineStatus.OUTSIDE_COLUMN)),
    )
    lines = unused_lines(flagged)
    assert [line.suspicious for line in lines] == [True, False]
    assert lines[1].reason == "neben der Buchungsspalte"


def test_budget_rows(session: Session) -> None:
    rows = {
        row.category: row
        for row in budget_rows(session.entries(), session.catalog, Period.of_month(2026, 2))
    }
    assert "Einkommen" not in rows and "Sparen & Anlage" not in rows  # expense categories only
    assert rows["Lebensmittel"].budget == Decimal("100.00")
    assert rows["Lebensmittel"].level is BudgetLevel.OVER  # 140,45 € against 100 €
    assert rows["Wohnen"].level is None
    assert rows["Wohnen"].average == Decimal("900.00")


def test_import_summary_message(statement_pdf: Path) -> None:
    parsed = read_statement(statement_pdf)
    summary = ImportSummary(files=2)
    summary.record("juli.pdf", parsed, ImportResult(3, 0, 0))
    summary.record("juli2.pdf", parsed, ImportResult(0, 3, 0, already_imported=True))
    summary.failed.append(("kaputt.pdf", "Die Datei konnte nicht gelesen werden."))
    summary.missing_months = ["2026-05"]
    message = summary.message()
    assert message.startswith("2 Datei(en) verarbeitet: 3 neue Buchungen")
    assert "Bereits importiert (übersprungen): juli2.pdf" in message
    assert "Fehlende Monate in der Reihe: 2026-05" in message
    assert "Nicht lesbar: kaputt.pdf" in message


def test_migration_report_text() -> None:
    report = MigrationReport(
        categories=3,
        keywords=5,
        assignments=1,
        transactions=10,
        statements=2,
        dropped=[DroppedItem("^ALDI.*", "Lebensmittel", DropReason.REGEX)],
    )
    text = migration_text(report)
    assert "3 Kategorien mit 5 Stichwörtern" in text
    assert "^ALDI.* → Lebensmittel: regulärer Ausdruck" in text


def test_adopt_replaces_the_state(session: Session) -> None:
    session.select([0])
    session.assign("Freizeit")
    session.adopt(default_catalog(), Library())
    assert session.transactions == []
    assert not session.can_undo
    assert session.selection == []


# -- second review round ----------------------------------------------------------------------


def test_legacy_data_only_goes_into_a_pristine_state(workspace: Workspace) -> None:
    session = Session(Workspace(default_catalog(), Library()))
    assert session.is_pristine()
    session.add_category("Haustier")
    assert not session.is_pristine()  # own categories would be replaced
    decided = Session(
        Workspace(default_catalog(), Library(assignments=workspace.library.assignments))
    )
    assert not decided.is_pristine()  # so would decisions


def test_changes_without_effect_leave_no_undo_step(session: Session) -> None:
    first = session.catalog.names()[0]
    session.move_category(first, 0)
    session.recolor(first, session.catalog.color_of(first))
    assert not session.can_undo


def test_category_filter_follows_rename_and_removal(session: Session) -> None:
    session.filters.category = "Shopping"
    session.rename_category("Shopping", "Einkauf")
    assert session.filters.category == "Einkauf"
    assert session.rows()
    session.remove_category("Einkauf")
    assert session.filters.category == ""


def test_suggestions_only_after_a_manual_decision(session: Session) -> None:
    kiosk = _index(session, "Kiosk am Markt")
    assert session.suggestions(kiosk) == []  # open: a keyword would only route to Sonstiges
    session.select([kiosk])
    session.assign("Freizeit")
    assert session.suggestions(kiosk)


def test_status_counts_split_parts_under_a_category_filter(session: Session) -> None:
    session.filters.category = "Gesundheit"
    totals = view_totals(session.rows(), "Gesundheit")
    assert totals.expense == Decimal("-15.00")


def test_cached_categories_follow_every_change(session: Session) -> None:
    kiosk = _index(session, "Kiosk am Markt")
    before = session.resolutions()[kiosk].category
    session.select([kiosk])
    session.assign("Freizeit")
    assert (before, session.resolutions()[kiosk].category) == ("Sonstiges", "Freizeit")
    session.undo()
    assert session.resolutions()[kiosk].category == "Sonstiges"


def test_budget_text() -> None:
    assert budget_from_text(" 120,50 ") == Decimal("120.50")
    assert budget_from_text("") is None
    assert budget_from_text("0") is None
    for invalid in ("viel", "-5"):
        with pytest.raises(ValueError, match="budget"):
            budget_from_text(invalid)


def test_exports_never_target_a_statement(session: Session, statement_pdf: Path) -> None:
    session.import_parsed(read_statement(statement_pdf), statement_pdf, "abc")
    assert session.is_statement_file(statement_pdf)
    assert not session.is_statement_file(statement_pdf.with_name("report.pdf"))


def test_session_without_store_does_not_save(workspace: Workspace) -> None:
    session = Session(Workspace(workspace.catalog, Library()))
    session.add_category("Neu")
    assert "Neu" in session.catalog
