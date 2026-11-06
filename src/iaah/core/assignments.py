"""Manual assignments (including splits) and resolving a booking to its category.

Priority: a manual assignment or split beats a keyword, a keyword beats the fallback.
``Resolution.auto_category`` always states what keywords and fallback alone would give – the
"before" of the review tab's before/after view.
"""

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Final, Self

from iaah.core.categories import CategoryCatalog, normalize_keyword, occurs_at_token_start
from iaah.core.errors import SplitError
from iaah.core.models import Transaction
from iaah.core.text import is_whole_cents

MIN_SPLIT_PARTS: Final = 2


class AssignmentSource(StrEnum):
    """Why a booking has its category."""

    MANUAL = "manual"  # the user chose it
    SPLIT = "split"  # the user divided the booking over several categories
    KEYWORD = "keyword"  # a keyword of the catalog matched
    FALLBACK = "fallback"  # nothing matched; the fallback category caught it


MANUAL_SOURCES: Final = frozenset({AssignmentSource.MANUAL, AssignmentSource.SPLIT})


@dataclass(frozen=True, slots=True)
class SplitPart:
    """One share of a split booking; signed like the booking."""

    category: str
    amount: Decimal


type Assignment = str | tuple[SplitPart, ...]
"""A category name, or the parts of a split."""


@dataclass(frozen=True, slots=True)
class Resolution:
    """The category of a booking, how it was decided, and how it divides."""

    category: str  # primary category; for splits the largest part
    source: AssignmentSource
    parts: tuple[SplitPart, ...]  # a single part unless split
    auto_category: str  # what keywords and fallback alone would give
    keyword: str | None = None  # the deciding keyword for KEYWORD resolutions

    @property
    def is_manual(self) -> bool:
        """Whether the user decided this booking."""
        return self.source in MANUAL_SOURCES

    @property
    def differs_from_auto(self) -> bool:
        """Whether the user's decision differs from the automatic one (before/after view)."""
        return self.source is AssignmentSource.SPLIT or self.category != self.auto_category


def validate_split(amount: Decimal, parts: Sequence[SplitPart]) -> tuple[SplitPart, ...]:
    """Check that ``parts`` divide ``amount`` exactly; raise ``SplitError`` otherwise."""
    if len(parts) < MIN_SPLIT_PARTS:
        raise SplitError(f"a split needs at least {MIN_SPLIT_PARTS} parts")
    if len({part.category for part in parts}) != len(parts):
        raise SplitError("each category may appear only once in a split")
    if not all(is_whole_cents(part.amount) for part in parts):
        raise SplitError("every part must be a finite amount in whole cents")
    if any(part.amount == 0 or (part.amount > 0) != (amount > 0) for part in parts):
        raise SplitError("every part needs a non-zero amount with the booking's sign")
    if sum((part.amount for part in parts), Decimal(0)) != amount:
        raise SplitError("the parts must add up to the booking amount")
    return tuple(parts)


class ManualAssignments:
    """Manual decisions by ``Transaction.key``. Knows nothing about the catalog."""

    def __init__(self, entries: Mapping[str, Assignment] | None = None) -> None:
        self._entries: dict[str, Assignment] = dict(entries or {})

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, key: object) -> bool:
        return key in self._entries

    def get(self, key: str) -> Assignment | None:
        """The stored decision for a booking key."""
        return self._entries.get(key)

    def items(self) -> Iterator[tuple[str, Assignment]]:
        """All decisions, for storage."""
        return iter(self._entries.items())

    def copy(self) -> Self:
        """An independent copy (entries are immutable)."""
        return type(self)(self._entries)

    def set_category(self, txn: Transaction, category: str) -> None:
        """Remember a single category for a booking."""
        self._entries[txn.key] = category

    def set_split(self, txn: Transaction, parts: Sequence[SplitPart]) -> None:
        """Remember a split; raises ``SplitError`` if it does not divide the booking."""
        self._entries[txn.key] = validate_split(txn.amount, parts)

    def clear(self, txn: Transaction) -> None:
        """Forget the decision for a booking (no-op if there is none)."""
        self._entries.pop(txn.key, None)

    def restore(self, entries: Mapping[str, Assignment]) -> None:
        """Put decisions back by key (undo of a prune or a bulk change)."""
        self._entries.update(entries)

    def discard(self, keys: Iterable[str]) -> None:
        """Forget the decisions for these booking keys."""
        for key in keys:
            self._entries.pop(key, None)

    def uses(self, name: str) -> bool:
        """Whether any decision refers to category ``name``."""
        return any(_uses(entry, name) for entry in self._entries.values())

    def rename_category(self, old: str, new: str) -> None:
        """Follow a category rename. Split parts that end up in the same category merge."""
        self._entries = {key: _renamed(entry, old, new) for key, entry in self._entries.items()}

    def forget_category(self, name: str) -> int:
        """Drop every decision that uses ``name``, splits included; return how many."""
        kept = {key: entry for key, entry in self._entries.items() if not _uses(entry, name)}
        dropped = len(self._entries) - len(kept)
        self._entries = kept
        return dropped


class Categorizer:
    """Resolves bookings with a catalog and the manual decisions."""

    def __init__(self, catalog: CategoryCatalog, manual: ManualAssignments) -> None:
        self.catalog = catalog
        self.manual = manual

    def auto(self, txn: Transaction) -> Resolution:
        """The category from keywords alone, else the fallback for the booking's sign."""
        match = self.catalog.match(txn.search_text, txn.amount)
        if match is not None:
            return _single(
                txn, match.category, AssignmentSource.KEYWORD, match.category, match.keyword
            )
        fallback = self.catalog.fallback_for(txn.amount).name
        return _single(txn, fallback, AssignmentSource.FALLBACK, fallback)

    def resolve(self, txn: Transaction) -> Resolution:
        """The effective category. Decisions naming an unknown category are ignored."""
        auto = self.auto(txn)
        entry = self.manual.get(txn.key)
        if isinstance(entry, str) and entry in self.catalog:
            category = self.catalog.get(entry).name
            return _single(txn, category, AssignmentSource.MANUAL, auto.category)
        if isinstance(entry, tuple) and all(part.category in self.catalog for part in entry):
            primary = max(entry, key=lambda part: abs(part.amount)).category
            return Resolution(primary, AssignmentSource.SPLIT, entry, auto.category)
        return auto

    def assign(self, txn: Transaction, category: str) -> None:
        """Assign a category by hand.

        Re-assigning the keyword's own category removes the decision (nothing to remember).
        Confirming the *fallback* category is stored: the booking counts as reviewed.
        """
        stored = self.catalog.get(category).name  # raises UnknownCategoryError
        auto = self.auto(txn)
        if auto.source is AssignmentSource.KEYWORD and auto.category == stored:
            self.manual.clear(txn)
            return
        self.manual.set_category(txn, stored)

    def split(self, txn: Transaction, parts: Sequence[SplitPart]) -> None:
        """Divide a booking over several categories (names as stored in the catalog)."""
        stored = [SplitPart(self.catalog.get(p.category).name, p.amount) for p in parts]
        self.manual.set_split(txn, stored)

    def clear(self, txn: Transaction) -> None:
        """Return a booking to automatic categorization."""
        self.manual.clear(txn)

    def rename_category(self, old: str, new: str) -> str:
        """Rename in catalog and decisions together; returns the stored name."""
        old_name = self.catalog.get(old).name
        new_name = self.catalog.rename(old_name, new)
        self.manual.rename_category(old_name, new_name)
        return new_name

    def remove_category(self, name: str) -> int:
        """Delete a category and every decision using it; returns how many were dropped."""
        stored = self.catalog.get(name).name
        self.catalog.remove(stored)
        return self.manual.forget_category(stored)

    def prune_redundant(
        self, transactions: Iterable[Transaction], keyword: str | None = None
    ) -> dict[str, Assignment]:
        """Drop decisions that a keyword now makes anyway and return them (for undo).

        Called after adding ``keyword``, so that moving the keyword later takes these bookings
        along instead of leaving them pinned by a stale decision. With ``keyword`` only the
        bookings containing it are checked.
        """
        needle = normalize_keyword(keyword) if keyword is not None else None
        dropped: dict[str, Assignment] = {}
        for txn in transactions:
            if needle is not None and not occurs_at_token_start(txn.search_text, needle):
                continue
            auto = self.auto(txn)
            if (
                auto.source is AssignmentSource.KEYWORD
                and self.manual.get(txn.key) == auto.category
            ):
                dropped[txn.key] = auto.category
        self.manual.discard(dropped)
        return dropped


def _single(
    txn: Transaction,
    category: str,
    source: AssignmentSource,
    auto_category: str,
    keyword: str | None = None,
) -> Resolution:
    parts = (SplitPart(category, txn.amount),)
    return Resolution(category, source, parts, auto_category, keyword)


def _uses(entry: Assignment, name: str) -> bool:
    if isinstance(entry, str):
        return entry == name
    return any(part.category == name for part in entry)


def _renamed(entry: Assignment, old: str, new: str) -> Assignment:
    if isinstance(entry, str):
        return new if entry == old else entry
    merged: dict[str, Decimal] = {}
    for part in entry:
        category = new if part.category == old else part.category
        merged[category] = merged.get(category, Decimal(0)) + part.amount
    if len(merged) == 1:
        return next(iter(merged))  # the split collapsed into a single category
    return tuple(SplitPart(category, amount) for category, amount in merged.items())
