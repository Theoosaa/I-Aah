"""Balances over time, the spending calendar and missing months."""

from datetime import date
from decimal import Decimal

from iaah.core.analysis.ledger import Entry
from iaah.core.analysis.timeline import (
    BalancePoint,
    account_balances,
    calendar_grid,
    cumulative_flow,
    daily_spending,
    missing_months,
)
from iaah.core.categories import CategoryKind
from iaah.core.models import StatementInfo, Transaction

D = Decimal


def _txn(day: date, amount: str, source: str = "mai.pdf") -> Transaction:
    return Transaction(day, "", "x", "", D(amount), source, account="123")


def test_cumulative_flow_has_one_point_per_day() -> None:
    bookings = [
        _txn(date(2026, 5, 2), "-10"),
        _txn(date(2026, 5, 1), "100"),
        _txn(date(2026, 5, 2), "-5"),
    ]
    assert cumulative_flow(bookings) == [
        BalancePoint(date(2026, 5, 1), D("100")),
        BalancePoint(date(2026, 5, 2), D("85")),
    ]


def test_account_balances_start_from_each_statement() -> None:
    may = StatementInfo("mai.pdf", account="123", period="2026-05", opening_balance=D("1000"))
    june = StatementInfo("juni.pdf", account="123", period="2026-06", opening_balance=D("990"))
    csv_export = StatementInfo("umsatz.csv", account="123")  # no balance: skipped
    bookings = [
        _txn(date(2026, 5, 10), "-10"),
        _txn(date(2026, 6, 3), "50", "juni.pdf"),
        _txn(date(2026, 6, 4), "-1", "umsatz.csv"),
    ]
    assert account_balances([june, csv_export, may], bookings) == {
        "123": [
            BalancePoint(date(2026, 5, 1), D("1000")),
            BalancePoint(date(2026, 5, 10), D("990")),
            BalancePoint(date(2026, 6, 1), D("990")),
            BalancePoint(date(2026, 6, 3), D("1040")),
        ]
    }


def test_daily_spending_is_gross_and_expense_only() -> None:
    day = date(2026, 5, 4)
    entries = [
        Entry(_txn(day, "-20"), "Essen", CategoryKind.EXPENSE, D("-20")),
        Entry(_txn(day, "5"), "Essen", CategoryKind.EXPENSE, D("5")),  # refund: not subtracted
        Entry(_txn(day, "-200"), "Umbuchung", CategoryKind.IGNORED, D("-200")),
        Entry(_txn(day, "900"), "Gehalt", CategoryKind.INCOME, D("900")),
    ]
    assert daily_spending(entries) == {day: D("20")}


def test_calendar_grid_lays_out_weeks() -> None:
    wednesday, next_tuesday = date(2026, 7, 1), date(2026, 7, 7)
    grid = calendar_grid({wednesday: D("10"), next_tuesday: D("3")})
    assert grid is not None
    assert grid.start == date(2026, 6, 29)  # Monday
    assert grid.weeks == 2
    monday_row, tuesday_row, wednesday_row = grid.cells[0], grid.cells[1], grid.cells[2]
    assert monday_row == (None, D(0))  # before the range / inside without spending
    assert tuesday_row == (None, D("3"))
    assert wednesday_row == (D("10"), None)
    assert grid.week_start(1) == date(2026, 7, 6)


def test_calendar_grid_empty() -> None:
    assert calendar_grid({}) is None


def test_missing_months() -> None:
    assert missing_months(["2026-08", "2025-11", "2026-01"]) == [
        "2025-12",
        "2026-02",
        "2026-03",
        "2026-04",
        "2026-05",
        "2026-06",
        "2026-07",
    ]
    assert missing_months([]) == []
