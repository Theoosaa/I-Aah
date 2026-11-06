"""PDF report: cover page plus one page per report chart."""

from datetime import date
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

from iaah.charts.chart import ChartKind
from iaah.charts.gallery import ChartInput
from iaah.core.analysis.ledger import Period
from iaah.core.library import Library
from iaah.core.workspace import Workspace
from iaah.export.report import (
    REPORT_CHARTS,
    cover_lines,
    render_report,
    report_charts,
    write_report,
)

CREATED = date(2026, 3, 1)


def test_report_has_a_cover_and_one_page_per_chart(workspace: Workspace) -> None:
    data = ChartInput.of_workspace(workspace, Period.all_time())
    kinds = report_charts(data)
    assert ChartKind.BUDGET in kinds  # the workspace has budgets
    reader = PdfReader(BytesIO(render_report(data, CREATED)))
    assert len(reader.pages) == 1 + len(kinds)
    cover = reader.pages[0].extract_text()
    assert "I-Aah – Auswertung" in cover
    assert "Erstellt am 01.03.2026" in cover


def test_without_budgets_there_is_no_budget_page(workspace: Workspace) -> None:
    plain = Workspace(workspace.catalog.copy(), workspace.library)
    for name in ("Lebensmittel", "Shopping"):
        plain.catalog.set_budget(name, None)
    data = ChartInput.of_workspace(plain, Period.all_time())
    assert report_charts(data) == list(REPORT_CHARTS)


def test_cover_lines(workspace: Workspace) -> None:
    lines = cover_lines(ChartInput.of_workspace(workspace, Period.of_month(2026, 2)), CREATED)
    assert lines[0] == "Zeitraum: Februar 2026"
    assert any(line.startswith("Einnahmen:") and line.endswith("2.500,00 €") for line in lines)
    assert any(line.startswith("Sparquote:") for line in lines)
    assert not any(line.startswith("Monate ohne Buchungen") for line in lines)


def test_cover_names_missing_months(workspace: Workspace) -> None:
    gap = [t for t in workspace.library.transactions if t.month != "2025-12"]
    data = ChartInput.of_workspace(Workspace(workspace.catalog, Library(transactions=gap)),
                                   Period.all_time())  # fmt: skip
    assert "Monate ohne Buchungen: Dez 25" in cover_lines(data, CREATED)


def test_empty_report_still_renders(workspace: Workspace, tmp_path: Path) -> None:
    data = ChartInput.of_workspace(Workspace(workspace.catalog, Library()), Period.all_time())
    path = tmp_path / "report.pdf"
    write_report(data, path, CREATED)
    assert len(PdfReader(path).pages) == 1 + len(report_charts(data))
    rate = next(line for line in cover_lines(data, CREATED) if line.startswith("Sparquote:"))
    assert rate.endswith("–")  # no income, no rate
