"""The data document: catalog and library in one file."""

import json
from datetime import date
from decimal import Decimal

import pytest

from iaah.core.assignments import SplitPart
from iaah.core.category_io import default_catalog
from iaah.core.document import document_from_json, document_to_json
from iaah.core.errors import StorageError, UnsupportedVersionError
from iaah.core.library import Library, StoredStatement
from iaah.core.models import Placement, Region, StatementInfo, Transaction


def _library() -> Library:
    placement = Placement(
        Region(1, (70.0, 375.0, 552.6, 386.0)), (Region(2, (70.0, 10.0, 300.0, 20.0)),)
    )
    placed = Transaction(
        date(2026, 7, 1), "Lastschrift", "REWE", "Einkauf", Decimal("-11.49"), "juli.pdf", "123",
        placement,
    )  # fmt: skip
    plain = Transaction(date(2026, 7, 2), "", "Arbeitgeber", "", Decimal("2500"), "x.csv")
    info = StatementInfo(
        "juli.pdf", "123", "DE89", "2026-07", Decimal("100"), None, Decimal("-11.49")
    )
    library = Library([StoredStatement(info, "C:/juli.pdf", "abc")], [placed, plain])
    library.assignments.set_category(plain, "Einkommen")
    parts = [SplitPart("A", Decimal("-10.00")), SplitPart("B", Decimal("-1.49"))]
    library.assignments.set_split(placed, parts)
    return library


def test_round_trip_is_exact() -> None:
    library = _library()
    catalog, again = document_from_json(document_to_json(default_catalog(), library))
    assert list(catalog) == list(default_catalog())
    assert again.statements == library.statements
    assert again.transactions == library.transactions
    assert dict(again.assignments.items()) == dict(library.assignments.items())


def test_money_is_stored_as_decimal_strings() -> None:
    data = json.loads(document_to_json(default_catalog(), _library()))
    assert data["transactions"][0]["amount"] == "-11.49"
    assert data["statements"][0]["closing_balance"] is None


def _with(field: str, value: object) -> str:
    data = json.loads(document_to_json(default_catalog(), _library()))
    data[field] = value
    return json.dumps(data)


@pytest.mark.parametrize(
    "text",
    [
        "{",
        "[]",
        '{"version": 0}',
        '{"version": "2"}',
        _with("assignments", []),
        _with("assignments", {"k": 5}),
        _with("transactions", [{"date": "x"}]),
        _with("catalog", {"version": 1, "categories": []}),
        '{"version": 1, "x": ' + "9" * 5000 + "}",  # beyond int's digit limit
        "[" * 100_000 + "]" * 100_000,  # nesting beyond the recursion limit
    ],
)
def test_damaged_documents_raise_storage_error(text: str) -> None:
    with pytest.raises(StorageError) as caught:
        document_from_json(text)
    assert not isinstance(caught.value, UnsupportedVersionError)


def test_a_newer_version_is_not_damage() -> None:
    with pytest.raises(UnsupportedVersionError):
        document_from_json(_with("version", 2))


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "1.005"])
def test_invalid_amounts_are_rejected(amount: str) -> None:
    data = json.loads(document_to_json(default_catalog(), _library()))
    data["transactions"][0]["amount"] = amount
    with pytest.raises(StorageError):
        document_from_json(json.dumps(data))


def test_infinite_page_number_is_damage() -> None:
    data = json.loads(document_to_json(default_catalog(), _library()))
    data["transactions"][0]["placement"]["head"][0] = float("inf")
    with pytest.raises(StorageError):
        document_from_json(json.dumps(data))
