# Portions adapted from budgets (MIT, © 2026 nikluep) – see LICENSES/budgets-MIT.txt
"""Category catalog: categories, their keyword lists, and matching text against them.

The catalog is the single source of truth for both lookup directions – category → keywords and
keyword → category. Categories are immutable; every change builds the complete new state,
validates it and only then swaps it in. A failed change leaves the catalog untouched, and the
keyword index can never drift from the categories.
"""

import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum
from typing import Final, Self

from iaah.core.errors import (
    CategoryError,
    DuplicateCategoryError,
    FallbackCategoryError,
    KeywordConflictError,
    UnknownCategoryError,
)
from iaah.core.text import is_whole_cents, normalize_text

# Pastel colors from budgets, extended to 16: distinct, with black text readable on top.
PALETTE: Final = (
    "#ffb6cb", "#92ca7d", "#bfcbff", "#f4a16c", "#83e1db", "#e19bdf", "#d6d28c", "#6dc0fe",
    "#ffb9b8", "#6fcf99", "#d1c4ff", "#e6ab5a", "#f7d06b", "#a0b4c8", "#c9a98b", "#b8e0a0",
)  # fmt: skip
UNKNOWN_COLOR: Final = "#dddddd"
_HEX_COLOR: Final = re.compile(r"#[0-9a-f]{6}")


class CategoryKind(StrEnum):
    """How a category's bookings count in the analysis."""

    EXPENSE = "expense"
    INCOME = "income"
    IGNORED = "ignored"  # never counted: transfers between own accounts, corrections


class CategoryRole(StrEnum):
    """Catches bookings that no keyword matches; exactly one category holds each role."""

    EXPENSE_FALLBACK = "expense_fallback"
    INCOME_FALLBACK = "income_fallback"


FALLBACK_KINDS: Final[dict[CategoryRole, CategoryKind]] = {
    CategoryRole.EXPENSE_FALLBACK: CategoryKind.EXPENSE,
    CategoryRole.INCOME_FALLBACK: CategoryKind.INCOME,
}


@dataclass(frozen=True, slots=True)
class Category:
    """A category and the keywords that route bookings to it."""

    name: str
    color: str  # "#rrggbb"
    keywords: tuple[str, ...] = ()  # normalized, unique across the catalog
    kind: CategoryKind = CategoryKind.EXPENSE
    budget: Decimal | None = None  # per month, whole cents
    role: CategoryRole | None = None


@dataclass(frozen=True, slots=True)
class KeywordMatch:
    """The keyword that decided a booking's category."""

    keyword: str
    category: str


def normalize_keyword(keyword: str) -> str:
    """Fold a keyword like booking text; it must keep at least one letter or digit."""
    normalized = normalize_text(keyword)
    if not any(char.isalnum() for char in normalized):
        raise CategoryError(f"keyword needs a letter or digit: {keyword!r}")
    return normalized


def occurs_at_token_start(text: str, keyword: str) -> bool:
    """Whether ``keyword`` occurs in ``text`` at the start of a token.

    ``"dm"`` occurs in ``"dm drogerie"`` but not in ``"admiral"``; ``"rewe"`` occurs in
    ``"visa rewe 435"`` and ``"rewe-markt"``. A token is a run of letters or digits in the
    Unicode sense (``str.isalnum``).
    """
    start = text.find(keyword)
    while start >= 0:
        if start == 0 or not text[start - 1].isalnum():
            return True
        start = text.find(keyword, start + 1)
    return False


class CategoryCatalog:
    """Ordered set of categories with a keyword → category index."""

    def __init__(self, categories: Iterable[Category]) -> None:
        self._categories: dict[str, Category] = {}
        self._index: dict[str, str] = {}
        self._longest_first: tuple[str, ...] = ()
        self._commit(categories)

    # -- reading ----------------------------------------------------------------------------

    def __iter__(self) -> Iterator[Category]:
        return iter(self._categories.values())

    def __len__(self) -> int:
        return len(self._categories)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name.strip() in self._categories

    def names(self) -> list[str]:
        """Category names in catalog order."""
        return list(self._categories)

    def get(self, name: str) -> Category:
        """The category called ``name``; ``UnknownCategoryError`` if there is none."""
        try:
            return self._categories[name.strip()]
        except KeyError:
            raise UnknownCategoryError(name) from None

    def keywords_of(self, name: str) -> tuple[str, ...]:
        """Category → keywords."""
        return self.get(name).keywords

    def category_of_keyword(self, keyword: str) -> str | None:
        """Keyword → category (the keyword is normalized first)."""
        return self._index.get(normalize_text(keyword))

    def fallback(self, role: CategoryRole) -> Category:
        """The category holding ``role``."""
        return next(category for category in self if category.role is role)

    def fallback_for(self, amount: Decimal) -> Category:
        """Where an unmatched booking goes: income fallback for money in, else expense."""
        role = CategoryRole.INCOME_FALLBACK if amount > 0 else CategoryRole.EXPENSE_FALLBACK
        return self.fallback(role)

    def color_of(self, name: str) -> str:
        """The category's color, or a neutral grey for unknown names."""
        category = self._categories.get(name.strip())
        return category.color if category else UNKNOWN_COLOR

    def kind_of(self, name: str) -> CategoryKind:
        """How bookings of this category count."""
        return self.get(name).kind

    def match(self, text: str, amount: Decimal | None = None) -> KeywordMatch | None:
        """The longest keyword occurring at a token start of ``text`` (normalized here).

        Equally long keywords are tried in catalog order. With ``amount``, keywords of income
        categories only match money coming in – "lohn" must not claim an outgoing
        "Lohnsteuer" payment.
        """
        normalized = normalize_text(text)
        money_out = amount is not None and amount <= 0
        for keyword in self._longest_first:
            category = self._index[keyword]
            if money_out and self._categories[category].kind is CategoryKind.INCOME:
                continue
            if occurs_at_token_start(normalized, keyword):
                return KeywordMatch(keyword, category)
        return None

    def next_color(self) -> str:
        """The first palette color no category uses yet."""
        used = {category.color for category in self}
        unused = (color for color in PALETTE if color not in used)
        return next(unused, PALETTE[len(self) % len(PALETTE)])

    def copy(self) -> Self:
        """An independent catalog with the same categories (categories are immutable)."""
        return type(self)(self)

    # -- changing ---------------------------------------------------------------------------

    def add(
        self, name: str, kind: CategoryKind = CategoryKind.EXPENSE, color: str | None = None
    ) -> Category:
        """Append a new category; the next free palette color unless ``color`` is given."""
        category = Category(name=name, color=color or self.next_color(), kind=kind)
        self._commit([*self, category])
        return self.get(name)

    def remove(self, name: str) -> None:
        """Delete a category. Fallback categories cannot be deleted."""
        target = self.get(name)
        if target.role is not None:
            raise FallbackCategoryError(f"fallback category cannot be removed: {name!r}")
        self._commit(category for category in self if category is not target)

    def move(self, name: str, position: int) -> None:
        """Move a category to ``position`` (clamped) – the order breaks keyword ties and sets
        the order of the assignment buttons."""
        target = self.get(name)
        others = [category for category in self if category is not target]
        index = max(0, min(position, len(others)))
        self._commit([*others[:index], target, *others[index:]])

    def rename(self, old: str, new: str) -> str:
        """Rename a category, keeping position, keywords and role; returns the stored name."""
        self._update(old, lambda category: replace(category, name=new))
        return new.strip()

    def set_color(self, name: str, color: str) -> None:
        """Change a category's color."""
        self._update(name, lambda category: replace(category, color=color))

    def set_kind(self, name: str, kind: CategoryKind) -> None:
        """Change how a category counts; fallback categories keep their kind."""
        self._update(name, lambda category: replace(category, kind=kind))

    def set_budget(self, name: str, budget: Decimal | None) -> None:
        """Set or clear (``None``) a monthly budget."""
        self._update(name, lambda category: replace(category, budget=budget))

    def add_keyword(self, name: str, keyword: str) -> str:
        """Add a keyword to a category and return it normalized.

        Raises ``KeywordConflictError`` if another category already owns it.
        """
        normalized = normalize_keyword(keyword)
        keywords = self.keywords_of(name)
        if normalized not in keywords:
            self.set_keywords(name, (*keywords, normalized))
        return normalized

    def move_keyword(self, keyword: str, to: str) -> str:
        """Give a keyword to category ``to``, taking it from its current owner – atomically."""
        normalized = normalize_keyword(keyword)
        target = self.get(to)

        def change(category: Category) -> Category:
            kept = tuple(kw for kw in category.keywords if kw != normalized)
            return replace(category, keywords=(*kept, normalized) if category is target else kept)

        self._commit(change(category) for category in self)
        return normalized

    def remove_keyword(self, name: str, keyword: str) -> None:
        """Remove a keyword from a category (no-op if it does not have it)."""
        normalized = normalize_keyword(keyword)
        self.set_keywords(name, [kw for kw in self.keywords_of(name) if kw != normalized])

    def set_keywords(self, name: str, keywords: Iterable[str]) -> None:
        """Replace a category's keyword list."""
        new_keywords = tuple(keywords)
        self._update(name, lambda category: replace(category, keywords=new_keywords))

    # -- internals --------------------------------------------------------------------------

    def _update(self, name: str, change: Callable[[Category], Category]) -> None:
        current = self.get(name)
        self._commit(change(category) if category is current else category for category in self)

    def _commit(self, categories: Iterable[Category]) -> None:
        validated = _validated([_normalized(category) for category in categories])
        self._categories = {category.name: category for category in validated}
        self._index = {kw: category.name for category in validated for kw in category.keywords}
        self._longest_first = tuple(sorted(self._index, key=len, reverse=True))


def _normalized(category: Category) -> Category:
    keywords = dict.fromkeys(normalize_keyword(keyword) for keyword in category.keywords)
    return replace(
        category,
        name=category.name.strip(),
        color=category.color.strip().lower(),
        keywords=tuple(keywords),
    )


def _validated(categories: list[Category]) -> list[Category]:
    names: set[str] = set()
    owners: dict[str, str] = {}
    for category in categories:
        _check_fields(category)
        if category.name in names:
            raise DuplicateCategoryError(category.name)
        names.add(category.name)
        for keyword in category.keywords:
            if keyword in owners:
                raise KeywordConflictError(keyword, owners[keyword])
            owners[keyword] = category.name
    _check_roles(categories)
    return categories


def _check_fields(category: Category) -> None:
    if not category.name:
        raise CategoryError("category name must not be empty")
    if not _HEX_COLOR.fullmatch(category.color):
        raise CategoryError(f"invalid color for {category.name!r}: {category.color!r}")
    if category.budget is not None:
        _check_budget(category.name, category.budget)
    if category.role is not None and category.kind is not FALLBACK_KINDS[category.role]:
        raise FallbackCategoryError(f"{category.name!r} must stay {FALLBACK_KINDS[category.role]}")


def _check_budget(name: str, budget: Decimal) -> None:
    if not is_whole_cents(budget) or budget < 0:
        raise CategoryError(f"budget of {name!r} must be a non-negative amount in whole cents")


def _check_roles(categories: list[Category]) -> None:
    for role in CategoryRole:
        holders = [category.name for category in categories if category.role is role]
        if len(holders) != 1:
            raise FallbackCategoryError(f"exactly one category needs role {role}, got {holders}")
