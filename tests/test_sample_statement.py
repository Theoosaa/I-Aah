"""Optional regression against a real ING statement.

Set ``IAAH_SAMPLE_PDF`` to the path of the reference statement (July 2026) to run it. The file
itself never enters the repository.
"""

import os
from decimal import Decimal
from pathlib import Path
from typing import Final

import pytest

from iaah.core.parsing.diagnostics import ParsedStatement
from iaah.core.parsing.ing import read_statement
from iaah.core.parsing.layout import LineStatus

SAMPLE_ENV: Final = "IAAH_SAMPLE_PDF"
EXPECTED_BOOKINGS: Final = 48
EXPECTED_TOTAL: Final = Decimal("1288.32")

pytestmark = pytest.mark.skipif(not os.environ.get(SAMPLE_ENV), reason=f"{SAMPLE_ENV} not set")


@pytest.fixture(scope="module")
def statement() -> ParsedStatement:
    return read_statement(Path(os.environ[SAMPLE_ENV]))


def test_all_bookings_found(statement: ParsedStatement) -> None:
    assert len(statement.transactions) == EXPECTED_BOOKINGS
    assert statement.info.total == EXPECTED_TOTAL


def test_statement_reconciles(statement: ParsedStatement) -> None:
    assert statement.info.reconciles is True
    assert statement.info.period == "2026-07"


def test_every_booking_is_placed_on_a_single_page(statement: ParsedStatement) -> None:
    # No booking of the reference statement crosses a page break; text after the closing
    # balance once leaked into the last booking.
    for txn in statement.transactions:
        assert txn.placement is not None
        assert {region.page for region in txn.placement.regions} == {txn.placement.head.page}


def test_no_suspicious_lines(statement: ParsedStatement) -> None:
    assert statement.report.suspicious == ()
    assert statement.report.with_status(LineStatus.DETAIL_LIMIT) == ()
