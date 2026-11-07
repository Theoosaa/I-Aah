"""Category summary: text, CSV, reading back and merging (compatible with budgets)."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from iaah.core.analysis.ledger import Period, in_period
from iaah.core.analysis.totals import totals
from iaah.core.library import Library
from iaah.core.models import Transaction
from iaah.core.workspace import Workspace
from iaah.export.summary import (
    Summary,
    SummaryFileError,
    merge_summaries,
    parse_csv_summary,
    read_csv_summary,
    render_csv_summary,
    render_text_summary,
    summarize,
    write_csv_summary,
)

FEBRUARY = Period.of_month(2026, 2)


def _february(workspace: Workspace) -> Summary:
    return summarize(in_period(workspace.entries(), FEBRUARY))


def test_summarize_follows_the_analysis_rules(workspace: Workspace) -> None:
    summary = _february(workspace)
    assert "Sparen & Anlage" not in summary.expenses  # ignored
    assert summary.expenses["Shopping"] == Decimal("59.99")  # 89.99 minus the 30.00 refund
    assert summary.expenses["Lebensmittel"] == Decimal("140.45")  # incl. the split part
    assert summary.income == {"Einkommen": Decimal("2500.00")}
    assert list(summary.expenses) == sorted(summary.expenses, key=summary.expenses.__getitem__,
                                            reverse=True)  # fmt: skip
    entries = in_period(workspace.entries(), FEBRUARY)
    assert summary.net == totals(entries).net


def test_net_equals_the_kpis_even_with_a_refund_surplus(workspace: Workspace) -> None:
    refund = Transaction(date(2026, 2, 26), "Gutschrift", "Zalando", "Retoure",
                         Decimal("500.00"), "x.pdf")  # fmt: skip
    library = Library(transactions=[*workspace.library.transactions, refund])
    entries = in_period(Workspace(workspace.catalog, library).entries(), FEBRUARY)
    summary = summarize(entries)
    assert summary.expenses["Shopping"] == Decimal("-440.01")  # refunds outweigh spending
    assert list(summary.expenses)[-1] == "Shopping"
    assert (summary.total_expenses, summary.net) == (totals(entries).expense, totals(entries).net)
    assert parse_csv_summary(render_csv_summary(summary)) == summary


def test_text_summary(workspace: Workspace) -> None:
    text = render_text_summary(_february(workspace))
    assert text.startswith("Ausgaben nach Kategorie\n")
    assert "Restaurant" not in text
    assert "Einnahmen nach Kategorie" in text
    assert "Wohnen" in text
    assert text.splitlines()[-1].startswith("Netto (Einnahmen - Ausgaben)")
    assert text.splitlines()[-1].endswith("1.371,57 €")
    shares = [line[line.rindex("(") :] for line in text.splitlines() if line.endswith(" %)")]
    assert shares
    assert all("," in share and "." not in share for share in shares)  # German: (57,6 %)
    assert "(keine Buchungen)" in render_text_summary(Summary())


def test_csv_round_trip(workspace: Workspace) -> None:
    summary = _february(workspace)
    text = render_csv_summary(summary)
    assert text.splitlines()[0] == "Typ;Kategorie;Betrag (EUR)"
    assert "Ausgabe;Shopping;59,99" in text
    assert parse_csv_summary(text) == summary


def test_budgets_style_files_are_read() -> None:
    text = (
        '"Typ","Kategorie","Betrag (EUR)"\n'
        '"Ausgabe","Lebensmittel","1234.50"\n'
        '"Ausgabe","Lebensmittel","0.50"\n'
        '"Einnahme","Gehalt","2500.00"\n\n'
    )
    summary = parse_csv_summary(text)
    assert summary.expenses == {"Lebensmittel": Decimal("1235.00")}
    assert summary.income == {"Gehalt": Decimal("2500.00")}


def test_merge_adds_categories() -> None:
    first = Summary({"A": Decimal(10), "B": Decimal(5)}, {"Lohn": Decimal(100)})
    second = Summary({"B": Decimal(20)}, {})
    merged = merge_summaries([first, second])
    assert merged.expenses == {"B": Decimal(25), "A": Decimal(10)}
    assert list(merged.expenses) == ["B", "A"]
    assert merged.income == {"Lohn": Decimal(100)}


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Datum;Betrag\n01.01.2026;1,00\n",
        "Typ;Kategorie;Betrag (EUR)\nAusgabe;A\n",
        "Typ;Kategorie;Betrag (EUR)\nUmbuchung;A;1,00\n",
        "Typ;Kategorie;Betrag (EUR)\nAusgabe;A;viel\n",
    ],
)
def test_invalid_summaries_raise(text: str) -> None:
    with pytest.raises(SummaryFileError):
        parse_csv_summary(text)


def test_files(workspace: Workspace, tmp_path: Path) -> None:
    path = tmp_path / "zusammenfassung.csv"
    write_csv_summary(_february(workspace), path)
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert read_csv_summary(path) == _february(workspace)
    with pytest.raises(SummaryFileError):
        read_csv_summary(tmp_path / "fehlt.csv")
