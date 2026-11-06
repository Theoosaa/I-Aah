"""Immutable domain data shared by all layers.

A ``Transaction`` deliberately carries no category: categorization is derived from the
catalog and the manual assignments, so a transaction can never hold stale state.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from iaah.core.text import normalize_text

type BBox = tuple[float, float, float, float]
"""``(x0, top, x1, bottom)`` in PDF points with the origin at the top left of the page."""


@dataclass(frozen=True, slots=True)
class Region:
    """A rectangle on one page of a PDF."""

    page: int  # 1-based
    bbox: BBox


@dataclass(frozen=True, slots=True)
class Placement:
    """Where a booking sits in its source PDF.

    ``details`` holds one region per page, because purpose lines may continue on the next page.
    """

    head: Region  # primary line: date, text, amount
    details: tuple[Region, ...] = ()

    @property
    def regions(self) -> tuple[Region, ...]:
        """Head and detail regions, in reading order."""
        return (self.head, *self.details)


@dataclass(frozen=True, slots=True)
class Transaction:
    """One booking of a statement. Negative amounts are money going out."""

    booking_date: date
    booking_type: str
    payee: str
    purpose: str
    amount: Decimal
    source: str
    account: str = ""
    placement: Placement | None = None

    @property
    def month(self) -> str:
        """Booking month as ``YYYY-MM``."""
        return f"{self.booking_date:%Y-%m}"

    @property
    def key(self) -> str:
        """Stable identity for manual assignments and de-duplication."""
        return f"{self.booking_date.isoformat()}|{self.amount:.2f}|{normalize_text(self.payee)}"

    @property
    def search_text(self) -> str:
        """Normalized payee and purpose, the text keywords are matched against."""
        return normalize_text(f"{self.payee} {self.purpose}")


@dataclass(frozen=True, slots=True)
class StatementInfo:
    """Metadata of one imported statement file."""

    source: str
    account: str = ""
    iban: str = ""
    period: str = ""  # "YYYY-MM", empty if the statement does not state it
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    total: Decimal = Decimal(0)

    @property
    def reconciles(self) -> bool | None:
        """Whether opening balance plus all bookings equals the closing balance.

        ``None`` if the statement does not state both balances (e.g. CSV exports).
        """
        if self.opening_balance is None or self.closing_balance is None:
            return None
        return self.opening_balance + self.total == self.closing_balance
