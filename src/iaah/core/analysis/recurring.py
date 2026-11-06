"""Fixed costs: payments to the same merchant that come back every month at a stable amount.

The rule is the legacy app's, with its numbers named: a merchant counts as fixed cost if it
appears in at least ``min(3, months)`` months, has at most 1.6 bookings per month (more means
everyday shopping) and amounts whose coefficient of variation stays below 0.35. Like the legacy
app it counts *bookings* – a split rent is still one payment per month. Grouping is by
merchant, so subscriptions paid through PayPal or a card are recognised too.

Amounts are gross outgoing payments (refunds are not subtracted), so ``fixed + variable`` can
exceed the net expense of the KPI tiles by the refunds of the period.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final

from iaah.core.analysis.ledger import (
    MONTHS_PER_YEAR,
    ZERO,
    Entry,
    bookings,
    months_of,
    next_month,
)
from iaah.core.categories import CategoryKind
from iaah.core.merchants import merchant_key, merchant_label

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
    last_month: str  # last month with a booking, "YYYY-MM"
    active: bool  # booked in the last or second-to-last month of the data

    @property
    def yearly(self) -> Decimal:
        """Monthly amount times twelve."""
        return self.monthly * MONTHS_PER_YEAR

    @property
    def next_month(self) -> str | None:
        """Expected next booking; ``None`` once the payment has stopped."""
        return next_month(self.last_month) if self.active else None


@dataclass(frozen=True, slots=True)
class RecurringReport:
    """Fixed vs. variable spending of a set of entries."""

    months: int
    last_month: str  # last month of the data ("" without data)
    fixed: Decimal  # gross total over the period, stopped payments included
    variable: Decimal
    payments: tuple[RecurringPayment, ...]  # active first, then by monthly amount

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
    months = months_of(entries)
    last = months[-1] if months else ""
    groups = _spending_by_merchant(entries)
    recurring = {key: group for key, group in groups.items() if _is_recurring(group, len(months))}
    payments = sorted(
        (_payment(key, group, last) for key, group in recurring.items()),
        key=lambda payment: (not payment.active, -payment.monthly, payment.label),
    )
    fixed = sum((group.total for group in recurring.values()), ZERO)
    variable = sum((g.total for key, g in groups.items() if key not in recurring), ZERO)
    return RecurringReport(len(months), last, fixed, variable, tuple(payments))


def _spending_by_merchant(entries: Sequence[Entry]) -> dict[str, _Group]:
    """Gross outgoing amount per booking (its expense parts added up), grouped by merchant."""
    groups: dict[str, _Group] = {}
    for txn, parts in bookings(entries):
        outgoing = -sum((p.amount for p in parts if p.kind is CategoryKind.EXPENSE), ZERO)
        if outgoing <= 0:
            continue
        group = groups.setdefault(merchant_key(txn), _Group(merchant_label(txn)))
        group.amounts.append(outgoing)
        group.months.add(txn.month)
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


def _payment(key: str, group: _Group, last_month_of_data: str) -> RecurringPayment:
    last = max(group.months)
    # Still running if the next expected booking is not before the data's last month.
    active = next_month(last) >= last_month_of_data
    monthly = group.total / len(group.months)
    return RecurringPayment(key, group.label, monthly, last, active)
