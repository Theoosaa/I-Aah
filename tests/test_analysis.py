"""Analysis on a hand-built three-month ledger; expected values are computed by hand.

May–July 2026: salary 2 000 each month, rent 800 each month, Netflix via PayPal 12.99 each
month, REWE card payments (30 in May; 45.50 + 60 - 10 refund in June), a 200 savings transfer
in an ignored category (June), and in July an Amazon order of 100 split 40 groceries / 60 other.
"""

from datetime import date
from decimal import Decimal
from typing import Final

import pytest

from iaah.core.analysis.ledger import (
    Entry,
    Period,
    PeriodKind,
    build_entries,
    entries_of_category,
    entries_of_merchant,
    in_period,
    month_range,
    next_month,
)
from iaah.core.analysis.recurring import recurring_payments
from iaah.core.analysis.totals import (
    BudgetLevel,
    budget_status,
    category_comparison,
    change,
    expense_by_category,
    kpis,
    money_flow,
    monthly_by_category,
    monthly_cashflow,
    top_merchants,
    totals,
    year_over_year,
)
from iaah.core.assignments import Categorizer, ManualAssignments, SplitPart
from iaah.core.categories import Category, CategoryCatalog, CategoryKind, CategoryRole
from iaah.core.models import Transaction

D = Decimal
NETFLIX_PURPOSE: Final = "1/PP.1.PP/. Netflix.com, Ihr Einkauf bei Netflix.com"
REWE: Final = "VISA REWE 435 HANNOVER"
REWE_PURPOSE: Final = "NR XXXX 0010 HANNOVER DE KAUFUMSATZ"
PAYPAL: Final = "PayPal Europe S.a.r.l. et Cie S.C.A"


def _txn(month: int, day: int, payee: str, amount: str, purpose: str = "") -> Transaction:
    return Transaction(date(2026, month, day), "", payee, purpose, D(amount), "x.pdf")


AMAZON = _txn(7, 12, "Amazon", "-100.00")
LEDGER: Final = [
    _txn(5, 1, "Vermieter", "-800.00", "Miete Mai"),
    _txn(5, 3, PAYPAL, "-12.99", NETFLIX_PURPOSE),
    _txn(5, 10, REWE, "-30.00", REWE_PURPOSE),
    _txn(5, 28, "Arbeitgeber GmbH", "2000.00", "Gehalt"),
    _txn(6, 1, "Vermieter", "-800.00", "Miete Juni"),
    _txn(6, 3, PAYPAL, "-12.99", NETFLIX_PURPOSE),
    _txn(6, 5, REWE, "-45.50", REWE_PURPOSE),
    _txn(6, 6, REWE, "-60.00", REWE_PURPOSE),
    _txn(6, 7, REWE, "10.00", REWE_PURPOSE),
    _txn(6, 15, "Trade Republic", "-200.00", "Sparplan"),
    _txn(6, 28, "Arbeitgeber GmbH", "2000.00", "Gehalt"),
    _txn(7, 1, "Vermieter", "-800.00", "Miete Juli"),
    _txn(7, 3, PAYPAL, "-12.99", NETFLIX_PURPOSE),
    AMAZON,
    _txn(7, 28, "Arbeitgeber GmbH", "2000.00", "Gehalt"),
]


def _categorizer() -> Categorizer:
    catalog = CategoryCatalog(
        [
            Category(
                "Einkommen", "#6fcf99", ("gehalt",), CategoryKind.INCOME,
                role=CategoryRole.INCOME_FALLBACK,
            ),
            Category("Wohnen", "#c9a98b", ("miete",)),
            Category("Lebensmittel", "#92ca7d", ("rewe",)),
            Category("Abos", "#e19bdf", ("netflix",)),
            Category("Umbuchung", "#a0b4c8", ("sparplan",), CategoryKind.IGNORED),
            Category("Sonstiges", "#b8b8b8", role=CategoryRole.EXPENSE_FALLBACK),
        ]
    )  # fmt: skip
    categorizer = Categorizer(catalog, ManualAssignments())
    split = [SplitPart("Lebensmittel", D("-40.00")), SplitPart("Sonstiges", D("-60.00"))]
    categorizer.split(AMAZON, split)
    return categorizer


@pytest.fixture(scope="module")
def entries() -> list[Entry]:
    return build_entries(LEDGER, _categorizer())


def _period(text: str, entries: list[Entry]) -> list[Entry]:
    return in_period(entries, Period.parse(text))


# -- ledger ----------------------------------------------------------------------------------


def test_build_entries_expands_splits(entries: list[Entry]) -> None:
    assert len(entries) == len(LEDGER) + 1
    amazon = [entry for entry in entries if entry.transaction is AMAZON]
    assert [(e.category, e.amount) for e in amazon] == [
        ("Lebensmittel", D("-40.00")),
        ("Sonstiges", D("-60.00")),
    ]
    assert not next(e for e in entries if e.category == "Umbuchung").counted


@pytest.mark.parametrize(
    ("text", "kind", "previous"),
    [
        ("", PeriodKind.ALL, None),
        ("2026", PeriodKind.YEAR, "2025"),
        ("2026-01", PeriodKind.MONTH, "2025-12"),
    ],
)
def test_period_parse_and_previous(text: str, kind: PeriodKind, previous: str | None) -> None:
    period = Period.parse(text)
    assert period.kind is kind
    assert str(period) == text
    assert (str(period.previous()) if period.previous() else None) == previous


@pytest.mark.parametrize("text", ["2026-13", "26", "Juli", "2026-7"])
def test_period_parse_rejects(text: str) -> None:
    with pytest.raises(ValueError, match=r"period|month"):
        Period.parse(text)


def test_period_contains() -> None:
    assert Period.parse("2026-07").contains(date(2026, 7, 31))
    assert not Period.parse("2026-07").contains(date(2026, 8, 1))
    assert Period.parse("2026").contains(date(2026, 1, 1))
    assert Period.all_time().contains(date(1999, 1, 1))


def test_month_arithmetic() -> None:
    assert next_month("2026-12") == "2027-01"
    assert month_range("2026-11", "2027-02") == ["2026-11", "2026-12", "2027-01", "2027-02"]
    assert month_range("2026-05", "2026-04") == []


def test_drill_down(entries: list[Entry]) -> None:
    assert len(entries_of_category(entries, "Wohnen")) == 3
    assert len(entries_of_merchant(entries, "netflix com")) == 3


# -- totals ----------------------------------------------------------------------------------


def test_totals_ignore_transfers_and_net_refunds(entries: list[Entry]) -> None:
    overall = totals(entries)
    assert overall.income == D("6000.00")
    assert overall.expense == D("2664.47")  # 2400 rent + 38.97 Netflix + 165.50 food + 60 other
    assert overall.net == D("3335.53")
    assert overall.savings_rate == D("3335.53") / D("6000.00")


def test_kpis_and_change(entries: list[Entry]) -> None:
    july = kpis(_period("2026-07", entries))
    assert (july.totals.expense, july.months) == (D("912.99"), 1)
    assert kpis(entries).average_monthly_expense == D("2664.47") / 3
    assert change(D("110"), D("100")).difference == D("10")
    assert change(D("110"), D("100")).ratio == D("0.1")
    assert change(D("90"), D("-100")).ratio == D("1.9")  # relative to the magnitude
    assert change(D("5"), D("0")).ratio is None


def test_savings_rate_without_income() -> None:
    assert totals([]).savings_rate is None


def test_monthly_cashflow(entries: list[Entry]) -> None:
    flows = monthly_cashflow(entries)
    assert [flow.month for flow in flows] == ["2026-05", "2026-06", "2026-07"]
    assert [flow.totals.expense for flow in flows] == [D("842.99"), D("908.49"), D("912.99")]


def test_expense_by_category(entries: list[Entry]) -> None:
    assert expense_by_category(entries) == {
        "Wohnen": D("2400.00"),
        "Lebensmittel": D("165.50"),
        "Sonstiges": D("60.00"),
        "Abos": D("38.97"),
    }


def test_fully_refunded_category_is_left_out() -> None:
    catalog = _categorizer()
    refund_only = build_entries([_txn(6, 7, REWE, "10.00", REWE_PURPOSE)], catalog)
    assert expense_by_category(refund_only) == {}


def test_category_comparison(entries: list[Entry]) -> None:
    rows = category_comparison(_period("2026-07", entries), _period("2026-06", entries), 3)
    assert [(r.category, r.current, r.previous) for r in rows] == [
        ("Wohnen", D("800.00"), D("800.00")),
        ("Sonstiges", D("60.00"), D("0")),
        ("Lebensmittel", D("40.00"), D("95.50")),
    ]


def test_monthly_by_category(entries: list[Entry]) -> None:
    series = monthly_by_category(entries, top=2)
    assert series.months == ("2026-05", "2026-06", "2026-07")
    assert series.series == {
        "Wohnen": (D("800.00"), D("800.00"), D("800.00")),
        "Lebensmittel": (D("30.00"), D("95.50"), D("40.00")),
    }


def test_top_merchants_see_through_card_and_paypal(entries: list[Entry]) -> None:
    ranked = top_merchants(entries, limit=4)
    assert [(m.label, m.amount) for m in ranked] == [
        ("Vermieter", D("2400.00")),
        ("REWE", D("125.50")),
        ("Amazon", D("100.00")),
        ("Netflix.com", D("38.97")),
    ]


def test_money_flow(entries: list[Entry]) -> None:
    flow = money_flow(entries)
    assert flow.income == D("6000.00")
    assert flow.saved == D("3335.53")
    assert flow.outflows[0] == ("Wohnen", D("2400.00"))
    assert money_flow([e for e in entries if e.kind is CategoryKind.EXPENSE]).saved == 0


def test_year_over_year(entries: list[Entry]) -> None:
    months = year_over_year(entries)[2026]
    assert months[4:7] == (D("842.99"), D("908.49"), D("912.99"))
    assert months[:4] == (None,) * 4
    assert months[7:] == (None,) * 5


@pytest.mark.parametrize(
    ("spent", "level"),
    [("80.00", BudgetLevel.OK), ("90.00", BudgetLevel.WARNING), ("100.00", BudgetLevel.WARNING),
     ("100.01", BudgetLevel.OVER)],
)  # fmt: skip
def test_budget_levels_at_the_thresholds(spent: str, level: BudgetLevel) -> None:
    entries = build_entries([_txn(7, 1, REWE, f"-{spent}")], _categorizer())
    (status,) = budget_status(entries, {"Lebensmittel": D("100.00")}, months=1)
    assert (status.spent, status.limit, status.level) == (D(spent), D("100.00"), level)


def test_budget_limit_scales_with_months(entries: list[Entry]) -> None:
    (status,) = budget_status(entries, {"Lebensmittel": D("50.00"), "Abos": D(0)}, months=3)
    assert (status.limit, status.spent) == (D("150.00"), D("165.50"))
    assert status.level is BudgetLevel.OVER


# -- recurring -------------------------------------------------------------------------------


def test_recurring_payments(entries: list[Entry]) -> None:
    report = recurring_payments(entries)
    assert report.detectable
    assert [(p.label, p.monthly, p.next_month) for p in report.payments] == [
        ("Vermieter", D("800.00"), "2026-08"),
        ("Netflix.com", D("12.99"), "2026-08"),
    ]
    assert report.payments[0].yearly == D("9600.00")
    assert report.fixed == D("2438.97")
    assert report.variable == D("235.50")  # REWE 135.50 gross (2 months only) + Amazon 100


def test_recurring_needs_two_months(entries: list[Entry]) -> None:
    report = recurring_payments(_period("2026-07", entries))
    assert not report.detectable
    assert report.payments == ()


def test_unstable_amounts_are_not_fixed_costs() -> None:
    ledger = [
        _txn(month, 1, "Stadtwerke", amount)
        for month, amount in ((5, "-20"), (6, "-90"), (7, "-30"))
    ]
    report = recurring_payments(build_entries(ledger, _categorizer()))
    assert report.payments == ()
