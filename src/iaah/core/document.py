"""The app's data document: category catalog and library in one JSON file.

One file, written atomically, means catalog and manual decisions can never be saved half –
renaming a category touches both, and an interrupted password change cannot leave two files
under two different keys. Money is stored as decimal strings, dates as ISO strings, bounding
boxes as ``[page, x0, top, x1, bottom]``.
"""

import json
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any, Final

from iaah.core.assignments import Assignment, ManualAssignments, SplitPart
from iaah.core.categories import CategoryCatalog
from iaah.core.category_io import catalog_from_data, catalog_to_data
from iaah.core.errors import CategoryFileError, StorageError, UnsupportedVersionError
from iaah.core.library import Library, StoredStatement
from iaah.core.models import BBox, Placement, Region, StatementInfo, Transaction
from iaah.core.text import is_whole_cents

DOCUMENT_VERSION: Final = 1
# document
KEY_VERSION: Final = "version"
KEY_CATALOG: Final = "catalog"
KEY_STATEMENTS: Final = "statements"
KEY_TRANSACTIONS: Final = "transactions"
KEY_ASSIGNMENTS: Final = "assignments"
# statement
KEY_SOURCE: Final = "source"
KEY_PATH: Final = "path"
KEY_SHA256: Final = "sha256"
KEY_ACCOUNT: Final = "account"
KEY_IBAN: Final = "iban"
KEY_PERIOD: Final = "period"
KEY_OPENING: Final = "opening_balance"
KEY_CLOSING: Final = "closing_balance"
KEY_TOTAL: Final = "total"
# transaction
KEY_DATE: Final = "date"
KEY_TYPE: Final = "type"
KEY_PAYEE: Final = "payee"
KEY_PURPOSE: Final = "purpose"
KEY_AMOUNT: Final = "amount"
KEY_PLACEMENT: Final = "placement"
KEY_HEAD: Final = "head"
KEY_DETAILS: Final = "details"
# split part
KEY_CATEGORY: Final = "category"


def document_to_json(catalog: CategoryCatalog, library: Library) -> str:
    """Serialize catalog and library into one document."""
    data = {
        KEY_VERSION: DOCUMENT_VERSION,
        KEY_CATALOG: catalog_to_data(catalog),
        KEY_STATEMENTS: [_statement_to_data(s) for s in library.statements],
        KEY_TRANSACTIONS: [_transaction_to_data(t) for t in library.transactions],
        KEY_ASSIGNMENTS: {k: _assignment_to_data(e) for k, e in library.assignments.items()},
    }
    return json.dumps(data, ensure_ascii=False, indent=1)


def document_from_json(text: str) -> tuple[CategoryCatalog, Library]:
    """Parse a document; ``StorageError`` for anything malformed – never partial data.

    A document from a newer program version raises ``UnsupportedVersionError``, so it is never
    mistaken for damage (and never "recovered" by an older version).
    """
    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as error:  # incl. absurdly long numbers, deep nesting
        raise StorageError(f"damaged data file: {error}") from error
    version = data.get(KEY_VERSION) if isinstance(data, dict) else None
    if isinstance(version, int) and version > DOCUMENT_VERSION:
        raise UnsupportedVersionError(f"data file version {version} is newer than this program")
    try:
        _require(isinstance(data, dict), "document is not an object")
        _require(version == DOCUMENT_VERSION, "unsupported document version")
        assignments = data[KEY_ASSIGNMENTS]
        _require(isinstance(assignments, dict), "assignments must be an object")
        library = Library(
            statements=[_statement_from_data(entry) for entry in data[KEY_STATEMENTS]],
            transactions=[_transaction_from_data(entry) for entry in data[KEY_TRANSACTIONS]],
            assignments=ManualAssignments(
                {str(key): _assignment_from_data(value) for key, value in assignments.items()}
            ),
        )
        return catalog_from_data(data[KEY_CATALOG]), library
    except (KeyError, TypeError, ValueError, ArithmeticError) as error:  # Decimal, int(inf)
        raise StorageError(f"damaged data file: {error}") from error
    except CategoryFileError as error:
        raise StorageError(f"damaged categories in data file: {error}") from error


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _statement_to_data(stored: StoredStatement) -> dict[str, Any]:
    info = stored.info
    return {
        KEY_SOURCE: info.source,
        KEY_PATH: stored.path,
        KEY_SHA256: stored.sha256,
        KEY_ACCOUNT: info.account,
        KEY_IBAN: info.iban,
        KEY_PERIOD: info.period,
        KEY_OPENING: _money_or_none(info.opening_balance),
        KEY_CLOSING: _money_or_none(info.closing_balance),
        KEY_TOTAL: str(info.total),
    }


def _statement_from_data(entry: Mapping[str, Any]) -> StoredStatement:
    info = StatementInfo(
        source=str(entry[KEY_SOURCE]),
        account=str(entry[KEY_ACCOUNT]),
        iban=str(entry[KEY_IBAN]),
        period=str(entry[KEY_PERIOD]),
        opening_balance=_decimal_or_none(entry[KEY_OPENING]),
        closing_balance=_decimal_or_none(entry[KEY_CLOSING]),
        total=_decimal(entry[KEY_TOTAL]),
    )
    return StoredStatement(info, _str_or_none(entry[KEY_PATH]), _str_or_none(entry[KEY_SHA256]))


def _transaction_to_data(txn: Transaction) -> dict[str, Any]:
    return {
        KEY_DATE: txn.booking_date.isoformat(),
        KEY_TYPE: txn.booking_type,
        KEY_PAYEE: txn.payee,
        KEY_PURPOSE: txn.purpose,
        KEY_AMOUNT: str(txn.amount),
        KEY_SOURCE: txn.source,
        KEY_ACCOUNT: txn.account,
        KEY_PLACEMENT: _placement_to_data(txn.placement),
    }


def _transaction_from_data(entry: Mapping[str, Any]) -> Transaction:
    return Transaction(
        booking_date=date.fromisoformat(entry[KEY_DATE]),
        booking_type=str(entry[KEY_TYPE]),
        payee=str(entry[KEY_PAYEE]),
        purpose=str(entry[KEY_PURPOSE]),
        amount=_decimal(entry[KEY_AMOUNT]),
        source=str(entry[KEY_SOURCE]),
        account=str(entry[KEY_ACCOUNT]),
        placement=_placement_from_data(entry[KEY_PLACEMENT]),
    )


def _placement_to_data(placement: Placement | None) -> dict[str, Any] | None:
    if placement is None:
        return None
    return {
        KEY_HEAD: _region_to_data(placement.head),
        KEY_DETAILS: [_region_to_data(region) for region in placement.details],
    }


def _placement_from_data(value: Mapping[str, Any] | None) -> Placement | None:
    if value is None:
        return None
    details = tuple(_region_from_data(region) for region in value[KEY_DETAILS])
    return Placement(_region_from_data(value[KEY_HEAD]), details)


def _region_to_data(region: Region) -> list[float]:
    return [region.page, *region.bbox]


def _region_from_data(value: list[float]) -> Region:
    page, x0, top, x1, bottom = value
    bbox: BBox = (float(x0), float(top), float(x1), float(bottom))
    return Region(int(page), bbox)


def _assignment_to_data(entry: Assignment) -> str | list[dict[str, str]]:
    if isinstance(entry, str):
        return entry
    return [{KEY_CATEGORY: part.category, KEY_AMOUNT: str(part.amount)} for part in entry]


def _assignment_from_data(value: object) -> Assignment:
    if isinstance(value, str):
        return value
    if not isinstance(value, list):
        raise ValueError("assignment must be a name or a list of parts")
    return tuple(SplitPart(str(part[KEY_CATEGORY]), _decimal(part[KEY_AMOUNT])) for part in value)


def _decimal(value: object) -> Decimal:
    """An amount in whole cents; NaN, infinity and fractions of a cent are rejected."""
    amount = Decimal(str(value))
    _require(is_whole_cents(amount), f"invalid amount {value!r}")
    return amount


def _decimal_or_none(value: object) -> Decimal | None:
    return None if value is None else _decimal(value)


def _money_or_none(amount: Decimal | None) -> str | None:
    return None if amount is None else str(amount)


def _str_or_none(value: object) -> str | None:
    return None if value is None else str(value)
