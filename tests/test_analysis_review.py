"""Regression tests for the step 2c review findings (see docs/review/02c-analysis.md)."""

from datetime import date
from decimal import Decimal
from typing import Final

import pytest

from iaah.core.analysis.ledger import (
    Entry,
    Period,
    PeriodKind,
    build_entries,
    entries_of_day,
    entries_of_merchant,
    transactions_of,
)
from iaah.core.analysis.recurring import recurring_payments
from iaah.core.analysis.timeline import (
    BalancePoint,
    account_balances,
    calendar_grid,
    statements_in_period,
)
from iaah.core.analysis.totals import (
    budget_status,
    category_comparison,
    kpi_changes,
    kpis,
    money_flow,
    monthly_by_category,
    monthly_cashflow,
)
from iaah.core.assignments import Categorizer, ManualAssignments, SplitPart
from iaah.core.categories import Category, CategoryCatalog, CategoryKind, CategoryRole
from iaah.core.merchants import merchant_key, merchant_label
from iaah.core.models import StatementInfo, Transaction

D = Decimal
EXPENSE = CategoryKind.EXPENSE
CARD_PURPOSE: Final = "NR XXXX 0010 HANNOVER DE KAUFUMSATZ 01.07 123456"
PAYPAL: Final = "PayPal Europe S.a.r.l. et Cie S.C.A"


def _txn(day: date, payee: str, amount: str, purpose: str = "", source: str = "x") -> Transaction:
    return Transaction(day, "", payee, purpose, D(amount), source, account="1")


def _entry(txn: Transaction, category: str, kind: CategoryKind = EXPENSE) -> Entry:
    return Entry(txn, category, kind, txn.amount)


def _categorizer() -> Categorizer:
    catalog = CategoryCatalog(
        [
            Category(
                "Einkommen", "#6fcf99", kind=CategoryKind.INCOME, role=CategoryRole.INCOME_FALLBACK
            ),
            Category("Wohnen", "#c9a98b"),
            Category("Nebenkosten", "#f7d06b"),
            Category("Sonstiges", "#b8b8b8", role=CategoryRole.EXPENSE_FALLBACK),
        ]
    )
    return Categorizer(catalog, ManualAssignments())


# -- merchants (findings 1, 2) ---------------------------------------------------------------


def test_glued_legacy_paypal_purpose_yields_the_merchant() -> None:
    glued = "1051374080449/pp.8695.pp/.netflix.com,ihreinkaufbei Netflix.com Mandat:5LXJ"
    txn = _txn(date(2026, 7, 1), PAYPAL, "-12.99", glued)
    assert merchant_key(txn) == "netflix com"
    assert merchant_label(txn) == "Netflix.com"


def test_paypal_without_any_merchant_never_uses_the_raw_purpose() -> None:
    txn = _txn(date(2026, 7, 1), PAYPAL, "-1", "Mandat: 123 Referenz: 456")
    assert "mandat" not in merchant_key(txn)
    assert "Mandat" not in merchant_label(txn)


def test_card_payment_with_odd_payee_keeps_the_payee() -> None:
    first = _txn(date(2026, 7, 1), "VISA R.S.D.E.", "-5", CARD_PURPOSE)
    other = _txn(date(2026, 7, 1), "VISA K.L.M.", "-5", CARD_PURPOSE)
    assert merchant_key(first) != merchant_key(other)
    assert merchant_label(first) == "R.S.D.E."


def test_only_pure_numbers_are_dropped_from_keys() -> None:
    o2 = _txn(date(2026, 7, 1), "O2 GmbH", "-5")
    three_m = _txn(date(2026, 7, 1), "3M GmbH", "-5")
    assert merchant_key(o2) == "o2 gmbh"
    assert merchant_key(o2) != merchant_key(three_m)


# -- recurring (findings 3, 4) ---------------------------------------------------------------


def test_split_rent_is_one_payment_per_month() -> None:
    categorizer = _categorizer()
    rents = [_txn(date(2026, month, 1), "Vermieter", "-800.00") for month in (5, 6, 7)]
    for rent in rents:
        parts = [SplitPart("Wohnen", D("-700.00")), SplitPart("Nebenkosten", D("-100.00"))]
        categorizer.split(rent, parts)
    (payment,) = recurring_payments(build_entries(rents, categorizer)).payments
    assert payment.monthly == D("800.00")


def test_stopped_payment_is_inactive_without_next_month() -> None:
    old_subscription = [_txn(date(2026, m, 3), "Zeitung", "-9.99") for m in (1, 2, 3)]
    still_going = [_txn(date(2026, m, 1), "Miete", "-800") for m in (1, 2, 3, 4, 5, 6)]
    report = recurring_payments([_entry(t, "X") for t in [*old_subscription, *still_going]])
    rent, newspaper = report.payments
    assert (rent.active, rent.next_month) == (True, "2026-07")
    assert (newspaper.active, newspaper.next_month, newspaper.last_month) == (
        False,
        None,
        "2026-03",
    )
    assert report.last_month == "2026-06"


def test_too_many_bookings_per_month_is_everyday_shopping() -> None:
    shopping = [_txn(date(2026, m, d), "Bäcker", "-3.00") for m in (5, 6, 7) for d in (1, 15)]
    assert recurring_payments([_entry(t, "X") for t in shopping]).payments == ()


def test_detection_over_two_months() -> None:
    rent = [_txn(date(2026, m, 1), "Miete", "-800") for m in (6, 7)]
    assert len(recurring_payments([_entry(t, "X") for t in rent]).payments) == 1


@pytest.mark.parametrize(("spread", "recurring"), [("0.34", True), ("0.35", False)])
def test_variation_limit(spread: str, recurring: bool) -> None:
    # amounts 100·(1 ± spread): mean 100, standard deviation 100·spread -> variation = spread
    low, high = D(100) * (1 - D(spread)), D(100) * (1 + D(spread))
    bookings = [
        _txn(date(2026, m, 1), "Strom", str(-amount)) for m, amount in ((5, low), (6, high))
    ]
    report = recurring_payments([_entry(t, "X") for t in bookings])
    assert bool(report.payments) is recurring


# -- totals (findings 5, 6, 7, 8, 10) --------------------------------------------------------


def test_category_comparison_ties_are_deterministic() -> None:
    day = date(2026, 6, 1)
    previous = [_entry(_txn(day, "x", "-10"), name) for name in ("Epsilon", "Alpha", "Gamma")]
    rows = category_comparison([], previous, limit=3)
    assert [row.category for row in rows] == ["Alpha", "Epsilon", "Gamma"]


def test_kpi_changes() -> None:
    july = [
        _entry(_txn(date(2026, 7, 1), "a", "1000"), "E", CategoryKind.INCOME),
        _entry(_txn(date(2026, 7, 2), "b", "-600"), "X"),
    ]
    june = [_entry(_txn(date(2026, 6, 1), "a", "1000"), "E", CategoryKind.INCOME),
            _entry(_txn(date(2026, 6, 2), "b", "-800"), "X")]  # fmt: skip
    changes = kpi_changes(kpis(july), kpis(june))
    assert changes is not None
    assert (changes.expense.difference, changes.expense.ratio) == (D("-200"), D("-0.25"))
    assert changes.savings_rate_points == D("0.2")  # 40 % vs. 20 %
    assert kpi_changes(kpis(july), kpis([])) is None
    no_income = kpi_changes(kpis(july), kpis(june[1:]))
    assert no_income is not None
    assert no_income.savings_rate_points is None


def test_money_flow_parts_add_up_to_income() -> None:
    day = date(2026, 7, 1)
    entries = [
        _entry(_txn(day, "job", "100"), "E", CategoryKind.INCOME),
        _entry(_txn(day, "a", "-60"), "A"),
        _entry(_txn(day, "b", "20"), "B"),  # refund only: not an outflow
    ]
    flow = money_flow(entries)
    assert flow.outflows == (("A", D("60")),)
    assert flow.saved == D("40")


def test_stacked_months_never_go_below_zero() -> None:
    entries = [
        _entry(_txn(date(2026, 5, 1), "a", "-30"), "A"),
        _entry(_txn(date(2026, 6, 1), "a", "10"), "A"),
    ]
    assert monthly_by_category(entries).series == {"A": (D("30"), D("0"))}


def test_monthly_cashflow_includes_income() -> None:
    entries = [_entry(_txn(date(2026, 5, 1), "job", "100"), "E", CategoryKind.INCOME)]
    assert monthly_cashflow(entries)[0].totals.income == D("100")


def test_budget_without_months_counts_one_month() -> None:
    entries = [_entry(_txn(date(2026, 5, 1), "a", "-50"), "A")]
    (status,) = budget_status(entries, {"A": D("40")}, months=0)
    assert (status.limit, status.ratio) == (D("40"), D("1.25"))


# -- ledger / timeline (findings 6, 9, 11) ---------------------------------------------------


def test_transactions_of_keeps_identical_bookings_apart() -> None:
    day = date(2026, 7, 1)
    twins = [_txn(day, "Kaffee", "-3"), _txn(day, "Kaffee", "-3")]
    assert len(transactions_of([_entry(t, "X") for t in twins])) == 2


def test_merchant_drill_down_only_lists_expenses() -> None:
    day = date(2026, 7, 1)
    entries = [
        _entry(_txn(day, "Shop", "-10"), "X"),
        _entry(_txn(day, "Shop", "-5"), "U", CategoryKind.IGNORED),
    ]
    assert len(entries_of_merchant(entries, "shop")) == 1
    assert len(entries_of_day(entries, day)) == 2


def test_calendar_follows_the_period_and_crosses_years() -> None:
    bounds = (date(2025, 12, 29), date(2026, 1, 4))
    grid = calendar_grid({date(2026, 1, 2): D("7")}, bounds)
    assert grid is not None
    assert (grid.start, grid.weeks) == (date(2025, 12, 29), 1)
    assert grid.cells[0] == (D(0),)  # Monday 29 Dec 2025: inside, no spending
    assert grid.day_at(4, 0) == date(2026, 1, 2)
    assert grid.cells[4] == (D("7"),)
    month = calendar_grid({}, Period.parse("2026-02").bounds())
    assert month is not None
    # Feb 2026 starts on a Sunday (end of the first column) and ends on a Saturday: 5 columns.
    assert month.weeks == 5
    assert month.cells[6][0] == D(0)
    assert month.cells[0][0] is None


def test_balances_keep_statement_order_and_accounts_apart() -> None:
    first = StatementInfo("a.pdf", account="1", period="2026-07", opening_balance=D("100"))
    second = StatementInfo("b.pdf", account="1", period="2026-07", opening_balance=D("150"))
    other = StatementInfo("c.pdf", account="2", period="2026-07", opening_balance=D("5"))
    empty = StatementInfo("d.pdf", account="1", period="2026-08", opening_balance=D("1"))
    bookings = [
        _txn(date(2026, 6, 30), "early", "50", source="a.pdf"),  # before its period
        _txn(date(2026, 7, 10), "x", "-1", source="b.pdf"),
        _txn(date(2026, 7, 2), "y", "-2", source="c.pdf"),
    ]
    balances = account_balances([second, other, empty, first], bookings)
    assert balances["1"] == [
        BalancePoint(date(2026, 6, 30), D("100")),
        BalancePoint(date(2026, 6, 30), D("150")),
        BalancePoint(date(2026, 7, 1), D("150")),
        BalancePoint(date(2026, 7, 10), D("149")),
    ]
    assert balances["2"][-1] == BalancePoint(date(2026, 7, 2), D("3"))


def test_statements_in_period() -> None:
    july = StatementInfo("a", period="2026-07")
    unknown = StatementInfo("b")
    assert statements_in_period([july, unknown], Period.parse("2026")) == [july]
    assert statements_in_period([july, unknown], Period.parse("2026-06")) == []
    assert statements_in_period([july, unknown], Period.all_time()) == [july, unknown]


@pytest.mark.parametrize(
    ("kind", "year", "month"),
    [(PeriodKind.MONTH, 2026, 13), (PeriodKind.YEAR, 2026, 7), (PeriodKind.ALL, 2026, 0)],
)
def test_period_validates_direct_construction(kind: PeriodKind, year: int, month: int) -> None:
    with pytest.raises(ValueError, match=r"month|year"):
        Period(kind, year, month)


def test_period_parse_accepts_ascii_digits_only() -> None:
    with pytest.raises(ValueError, match="period"):
        Period.parse("٢٠٢٦")
