"""Transaction identity and derived fields, statement reconciliation, placements."""

from datetime import date
from decimal import Decimal

from iaah.core.models import Placement, Region, StatementInfo, Transaction
from iaah.core.text import BROKEN_UMLAUT


def _txn(payee: str = "VISA  REWE 435", amount: str = "-11.49") -> Transaction:
    return Transaction(
        booking_date=date(2026, 7, 1),
        booking_type="Lastschrift",
        payee=payee,
        purpose="NR XXXX Kaufumsatz",
        amount=Decimal(amount),
        source="x.pdf",
    )


def test_key_is_pinned() -> None:
    # Manual assignments and the library are stored under this exact string.
    assert _txn().key == "2026-07-01|-11.49|visa rewe 435"


def test_key_ignores_spacing_and_repairs_broken_umlauts() -> None:
    assert _txn("VISA REWE 435").key == _txn("visa   rewe  435").key
    assert _txn(f"M{BROKEN_UMLAUT}ller").key.endswith("|mueller")


def test_key_keeps_two_decimals() -> None:
    assert _txn(amount="-5").key == "2026-07-01|-5.00|visa rewe 435"


def test_search_text_and_month() -> None:
    txn = _txn()
    assert txn.search_text == "visa rewe 435 nr xxxx kaufumsatz"
    assert txn.month == "2026-07"


def test_reconciles() -> None:
    balanced = StatementInfo("x", opening_balance=Decimal(10), closing_balance=Decimal(15))
    assert StatementInfo("x").reconciles is None
    assert StatementInfo("x", opening_balance=Decimal(10)).reconciles is None
    assert balanced.reconciles is False
    assert StatementInfo(
        "x", opening_balance=Decimal(10), closing_balance=Decimal(15), total=Decimal(5)
    ).reconciles


def test_placement_regions_in_reading_order() -> None:
    head = Region(1, (0, 0, 10, 10))
    details = (Region(1, (0, 12, 10, 20)), Region(2, (0, 0, 10, 8)))
    assert Placement(head, details).regions == (head, *details)
