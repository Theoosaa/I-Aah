"""Fixed costs: payments to the same merchant that come back every month at a stable amount.

The rule is the legacy app's, with its numbers named: a merchant counts as fixed cost if it
appears in at least ``min(3, months)`` months, has at most 1.6 bookings per month (more means
everyday shopping) and amounts whose coefficient of variation stays below 0.35. Grouping is by
merchant, so subscriptions paid through PayPal or a card are recognised too.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final

from iaah.core.analysis.ledger import MONTHS_PER_YEAR, Entry, months_of, next_month
from iaah.core.categories import CategoryKind
from iaah.core.merchants import merchant_key, merchant_label

ZERO: Final = Decimal(0)
MIN_MONTHS_FOR_DETECTION: Final = 2
REQUIRED_MONTHS_CAP: Final = 3
MAX_BOOKINGS_PER_MONTH: Final = Decimal("1.6")
MAX_VARIATION: Final = Decimal("0.35")


@dataclass(frozen=True, slots=True)
class RecurringPayment:
    """A detected fixed cost."""

    merchant: str  # grouping key, for drill-down
    label: str
    monthly: Decimal
    next_month: str  # expected next booking, "YYYY-MM"

    @property
    def yearly(self) -> Decimal:
        """Monthly amount times twelve."""
        return self.monthly * MONTHS_PER_YEAR


@dataclass(frozen=True, slots=True)
class RecurringReport:
    """Fixed vs. variable spending of a set of entries."""

    months: int
    fixed: Decimal  # total over the period
    variable: Decimal
    payments: tuple[RecurringPayment, ...]  # largest monthly amount first

    @property
    def detectable(self) -> bool:
        """Detection needs at least two months of bookings."""
        return self.months >= MIN_MONTHS_FOR_DETECTION

    @property
    def monthly_fixed(self) -> Decimal:
        """Fixed costs per month."""
        return self.fixed / self.months if self.months else ZERO


@dataclass(slots=True)
class _Group:
    label: str
    amounts: list[Decimal] = field(default_factory=list)
    months: set[str] = field(default_factory=set)

    @property
    def total(self) -> Decimal:
        return sum(self.amounts, ZERO)


def recurring_payments(entries: Sequence[Entry]) -> RecurringReport:
    """Split spending into fixed costs and the rest, and list the fixed costs."""
    months = len(months_of(entries))
    groups = _spending_by_merchant(entries)
    recurring = {key: group for key, group in groups.items() if _is_recurring(group, months)}
    payments = sorted(
        (_payment(key, group) for key, group in recurring.items()),
        key=lambda payment: payment.monthly,
        reverse=True,
    )
    fixed = sum((group.total for group in recurring.values()), ZERO)
    variable = sum((g.total for key, g in groups.items() if key not in recurring), ZERO)
    return RecurringReport(months, fixed, variable, tuple(payments))


def _spending_by_merchant(entries: Sequence[Entry]) -> dict[str, _Group]:
    groups: dict[str, _Group] = {}
    for entry in entries:
        if entry.kind is not CategoryKind.EXPENSE or entry.amount >= 0:
            continue
        key = merchant_key(entry.transaction)
        group = groups.setdefault(key, _Group(merchant_label(entry.transaction)))
        group.amounts.append(-entry.amount)
        group.months.add(entry.month)
    return groups


def _is_recurring(group: _Group, months: int) -> bool:
    if months < MIN_MONTHS_FOR_DETECTION:
        return False
    if len(group.months) < min(REQUIRED_MONTHS_CAP, months):
        return False
    if len(group.amounts) > len(group.months) * MAX_BOOKINGS_PER_MONTH:
        return False
    return _variation(group.amounts) < MAX_VARIATION


def _variation(amounts: Sequence[Decimal]) -> Decimal:
    """Coefficient of variation: standard deviation relative to the mean."""
    mean = sum(amounts, ZERO) / len(amounts)
    variance = sum(((amount - mean) ** 2 for amount in amounts), ZERO) / len(amounts)
    return variance.sqrt() / mean


def _payment(key: str, group: _Group) -> RecurringPayment:
    monthly = group.total / len(group.months)
    return RecurringPayment(key, group.label, monthly, next_month(max(group.months)))
