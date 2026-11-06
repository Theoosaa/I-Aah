"""Chart builders: every kind renders in both themes, explains missing data, can be drilled."""

from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from matplotlib.figure import Figure

from iaah.charts.chart import CAPTIONS, TITLES, Chart, ChartKind, DrillKind
from iaah.charts.flow import MAX_CATEGORY_BANDS, sankey_chart
from iaah.charts.gallery import NO_PREVIOUS, ChartInput, build_chart
from iaah.charts.style import (
    DARK,
    LABEL_CHARS,
    LIGHT,
    ChartTheme,
    month_label,
    percent,
    period_label,
)
from iaah.core.analysis.ledger import Period
from iaah.core.analysis.totals import MoneyFlow, expense_by_category
from iaah.core.category_io import default_catalog
from iaah.core.library import Library
from iaah.core.models import Transaction
from iaah.core.workspace import Workspace

ALL_TIME = Period.all_time()
FEBRUARY = Period.of_month(2026, 2)


def _png(chart: Chart) -> bytes:
    buffer = BytesIO()
    chart.figure.savefig(buffer, format="png")
    return buffer.getvalue()


def _texts(figure: Figure) -> str:
    return "\n".join(text.get_text() for axes in figure.axes for text in axes.texts)


def _targets(chart: Chart, kind: DrillKind) -> list[str]:
    return [target.value for target in chart.targets if target.kind is kind]


@pytest.mark.parametrize("theme", [LIGHT, DARK], ids=lambda theme: theme.name)
@pytest.mark.parametrize("period", [ALL_TIME, FEBRUARY, Period.of_year(2026)], ids=str)
@pytest.mark.parametrize("kind", list(ChartKind))
def test_every_chart_renders(
    workspace: Workspace, kind: ChartKind, period: Period, theme: ChartTheme
) -> None:
    chart = build_chart(kind, ChartInput.of_workspace(workspace, period), theme)
    assert _png(chart).startswith(b"\x89PNG")


@pytest.mark.parametrize("kind", list(ChartKind))
def test_without_data_every_chart_explains_itself(kind: ChartKind) -> None:
    empty = Workspace(default_catalog(), Library())
    chart = build_chart(kind, ChartInput.of_workspace(empty, ALL_TIME), LIGHT)
    assert _texts(chart.figure)
    assert chart.targets == ()
    _png(chart)


def test_every_kind_has_title_and_caption() -> None:
    assert set(TITLES) == set(ChartKind) == set(CAPTIONS)
    assert all(len(caption) > 50 for caption in CAPTIONS.values())


def test_donut_wedges_drill_into_categories(workspace: Workspace) -> None:
    data = ChartInput.of_workspace(workspace, FEBRUARY)
    chart = build_chart(ChartKind.CATEGORIES, data, LIGHT)
    assert _targets(chart, DrillKind.CATEGORY) == list(expense_by_category(data.entries))
    assert "Lebensmittel" in _targets(chart, DrillKind.CATEGORY)  # split part counts there
    assert "Sparen & Anlage" not in _targets(chart, DrillKind.CATEGORY)  # ignored


def test_merchant_and_fixed_cost_bars_drill_into_merchants(workspace: Workspace) -> None:
    data = ChartInput.of_workspace(workspace, ALL_TIME)
    merchants = _targets(build_chart(ChartKind.MERCHANTS, data, LIGHT), DrillKind.MERCHANT)
    assert merchants[-1] == "hausverwaltung nord"  # largest at the top, drawn last
    fixed = _targets(build_chart(ChartKind.FIXED_COSTS, data, LIGHT), DrillKind.MERCHANT)
    assert {"hausverwaltung nord", "netflix com"} <= set(fixed)


def test_calendar_cells_drill_into_days_with_spending(workspace: Workspace) -> None:
    chart = build_chart(ChartKind.CALENDAR, ChartInput.of_workspace(workspace, FEBRUARY), LIGHT)
    days = _targets(chart, DrillKind.DAY)
    assert "2026-02-02" in days  # rent
    assert "2026-02-01" not in days  # salary only: no spending
    assert all(date.fromisoformat(day).month == 2 for day in days)
    labels = [label.get_text() for label in chart.figure.axes[0].get_xticklabels()]
    assert labels == ["Feb 26"]  # the padding cell of 1 March gets no label


def test_budget_and_stacked_bars_drill_into_categories(workspace: Workspace) -> None:
    data = ChartInput.of_workspace(workspace, FEBRUARY)
    budget = _targets(build_chart(ChartKind.BUDGET, data, LIGHT), DrillKind.CATEGORY)
    assert set(budget) == {"Lebensmittel", "Shopping"}
    stacked = _targets(build_chart(ChartKind.STACKED, data, LIGHT), DrillKind.CATEGORY)
    assert "Wohnen" in stacked


def test_sankey_bands_drill_into_categories_but_not_savings(workspace: Workspace) -> None:
    chart = build_chart(ChartKind.FLOW, ChartInput.of_workspace(workspace, FEBRUARY), LIGHT)
    values = _targets(chart, DrillKind.CATEGORY)
    assert "Wohnen" in values
    assert "Gespart" not in values
    assert "Gespart" in _texts(chart.figure)


def test_comparison_needs_a_previous_period(workspace: Workspace) -> None:
    chart = build_chart(ChartKind.COMPARISON, ChartInput.of_workspace(workspace, ALL_TIME), LIGHT)
    assert NO_PREVIOUS in _texts(chart.figure)
    month = build_chart(ChartKind.COMPARISON, ChartInput.of_workspace(workspace, FEBRUARY), LIGHT)
    assert month.figure.axes[0].get_title() == "Kategorien: Februar 2026 vs. Januar 2026"


def test_insufficient_data_gives_a_message(workspace: Workspace) -> None:
    month = ChartInput.of_workspace(workspace, FEBRUARY)
    assert "zwei Monate" in _texts(build_chart(ChartKind.FIXED_COSTS, month, LIGHT).figure)
    assert "Zu wenige Monate" in _texts(build_chart(ChartKind.TREND, month, LIGHT).figure)
    only_2026 = Workspace(workspace.catalog, Library(transactions=[
        txn for txn in workspace.library.transactions if txn.booking_date.year == 2026
    ]))  # fmt: skip
    years = build_chart(ChartKind.YEARS, ChartInput.of_workspace(only_2026, ALL_TIME), LIGHT)
    assert "zwei Jahren" in _texts(years.figure)


def test_dark_theme_reaches_lazily_created_ticks(workspace: Workspace) -> None:
    chart = build_chart(ChartKind.OVERVIEW, ChartInput.of_workspace(workspace, ALL_TIME), DARK)
    chart.figure.canvas.draw()
    axes = chart.figure.axes[0]
    assert {label.get_color() for label in axes.get_xticklabels()} == {DARK.text}
    assert axes.get_facecolor()[:3] != (1.0, 1.0, 1.0)


def test_building_does_not_change_the_input(workspace: Workspace) -> None:
    data = ChartInput.of_workspace(workspace, ALL_TIME)
    before = list(data.all_entries)
    for kind in ChartKind:
        build_chart(kind, data, LIGHT)
    assert list(data.all_entries) == before


# -- review findings --------------------------------------------------------------------------


def _with_payee(workspace: Workspace, payee: str) -> Workspace:
    """The workspace plus one large booking to ``payee`` in February 2026."""
    txn = Transaction(date(2026, 2, 25), "Lastschrift", payee, "", Decimal("-5000.00"), "x.pdf")
    library = Library(workspace.library.statements, [*workspace.library.transactions, txn])
    return Workspace(workspace.catalog, library)


def test_dollar_signs_stay_text(workspace: Workspace) -> None:
    data = ChartInput.of_workspace(_with_payee(workspace, r"Shop $\foo$ Berlin"), FEBRUARY)
    chart = build_chart(ChartKind.MERCHANTS, data, LIGHT)
    _png(chart)  # mathtext would raise while drawing
    labels = [label.get_text() for label in chart.figure.axes[0].get_yticklabels()]
    assert r"Shop $\foo$ Berlin" in labels


def test_long_names_are_shortened(workspace: Workspace) -> None:
    data = ChartInput.of_workspace(_with_payee(workspace, "X" * 200), FEBRUARY)
    chart = build_chart(ChartKind.MERCHANTS, data, LIGHT)
    labels = [label.get_text() for label in chart.figure.axes[0].get_yticklabels()]
    assert max(len(label) for label in labels) == LABEL_CHARS
    assert labels[-1].endswith("…")


def test_donut_names_a_refund_surplus(workspace: Workspace) -> None:
    refund = Transaction(date(2026, 2, 26), "Gutschrift", "Zalando", "Retoure",
                         Decimal("500.00"), "x.pdf")  # fmt: skip
    library = Library(transactions=[*workspace.library.transactions, refund])
    data = ChartInput.of_workspace(Workspace(workspace.catalog, library), FEBRUARY)
    chart = build_chart(ChartKind.CATEGORIES, data, LIGHT)
    assert "Shopping" not in _targets(chart, DrillKind.CATEGORY)
    note = chart.figure.axes[0].get_xlabel()
    assert note.startswith("Mehr erstattet als ausgegeben: Shopping")


def test_budget_title_matches_its_limits(workspace: Workspace) -> None:
    empty_month = ChartInput.of_workspace(workspace, Period.of_month(2026, 5))
    chart = build_chart(ChartKind.BUDGET, empty_month, LIGHT)
    assert "(1 Monat(e) im Zeitraum)" in chart.figure.axes[0].get_title()


def test_calendar_first_label_uses_the_first_day_in_range(workspace: Workspace) -> None:
    sunday = Transaction(date(2026, 8, 2), "", "Kiosk", "", Decimal("-3.00"), "x.pdf")
    later = Transaction(date(2026, 8, 20), "", "Kiosk", "", Decimal("-4.00"), "x.pdf")
    data = ChartInput.of_workspace(
        Workspace(workspace.catalog, Library(transactions=[sunday, later])), ALL_TIME
    )
    chart = build_chart(ChartKind.CALENDAR, data, LIGHT)
    labels = [label.get_text() for label in chart.figure.axes[0].get_xticklabels()]
    assert labels == ["Aug 26"]  # the Monday of that week lies in July


def test_sankey_groups_many_small_categories() -> None:
    outflows = tuple((f"Kategorie {n}", Decimal(100 - n)) for n in range(60))
    chart = sankey_chart(MoneyFlow(Decimal(10_000), outflows, Decimal(4_000)), {}, LIGHT)
    assert len(chart.targets) == MAX_CATEGORY_BANDS - 1
    assert "Übrige Kategorien (49)" in _texts(chart.figure)
    _png(chart)


def test_labels() -> None:
    assert month_label("2026-07") == "Jul 26"
    assert month_label("2025-03") == "Mär 25"
    assert period_label(Period.of_month(2026, 3)) == "März 2026"
    assert period_label(Period.of_year(2026)) == "2026"
    assert period_label(ALL_TIME) == "Gesamter Zeitraum"
    assert percent(Decimal("0.253")) == "25 %"
