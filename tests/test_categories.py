"""Category catalog: invariants, both lookup directions, matching."""

from decimal import Decimal

import pytest

from iaah.core.categories import (
    PALETTE,
    UNKNOWN_COLOR,
    Category,
    CategoryCatalog,
    CategoryKind,
    CategoryRole,
    KeywordMatch,
    occurs_at_token_start,
)
from iaah.core.errors import (
    CategoryError,
    DuplicateCategoryError,
    FallbackCategoryError,
    KeywordConflictError,
    UnknownCategoryError,
)

INCOME = Category(
    "Einkommen", "#6fcf99", ("gehalt",), CategoryKind.INCOME, role=CategoryRole.INCOME_FALLBACK
)
FOOD = Category("Lebensmittel", "#92ca7d", ("rewe", "denn s biomarkt"))
HEALTH = Category("Gesundheit", "#ffb9b8", ("dm",))
OTHER = Category("Sonstiges", "#b8b8b8", role=CategoryRole.EXPENSE_FALLBACK)


def _catalog(*extra: Category) -> CategoryCatalog:
    return CategoryCatalog([INCOME, FOOD, HEALTH, OTHER, *extra])


def _assert_consistent(catalog: CategoryCatalog) -> None:
    for category in catalog:
        assert catalog.keywords_of(category.name) == category.keywords
        for keyword in category.keywords:
            assert catalog.category_of_keyword(keyword) == category.name


# -- construction ----------------------------------------------------------------------------


def test_keywords_are_normalized_and_deduplicated() -> None:
    catalog = _catalog(Category("Shopping", "#BFCBFF", ("Amazon", "AMAZON ", "Müller")))
    assert catalog.keywords_of("Shopping") == ("amazon", "mueller")
    assert catalog.get("Shopping").color == "#bfcbff"
    _assert_consistent(catalog)


@pytest.mark.parametrize(
    ("extra", "error"),
    [
        (Category("Lebensmittel", "#000000"), DuplicateCategoryError),
        (Category("Shopping", "#000000", ("REWE",)), KeywordConflictError),
        (Category("", "#000000"), CategoryError),
        (Category("Shopping", "red"), CategoryError),
        (Category("Shopping", "#000000", budget=Decimal(-1)), CategoryError),
        (Category("Shopping", "#000000", ("  ",)), CategoryError),
        (Category("Shopping", "#000000", ("/",)), CategoryError),
        (Category("Shopping", "#000000", budget=Decimal("NaN")), CategoryError),
        (Category("Shopping", "#000000", budget=Decimal("Infinity")), CategoryError),
        (Category("Shopping", "#000000", budget=Decimal("10.005")), CategoryError),
        (Category("Shopping", "#000000", budget=Decimal("1E+40")), CategoryError),
    ],
)
def test_invalid_categories_are_rejected(extra: Category, error: type[Exception]) -> None:
    with pytest.raises(error):
        _catalog(extra)


def test_keyword_conflict_names_the_owner() -> None:
    with pytest.raises(KeywordConflictError) as caught:
        _catalog(Category("Shopping", "#000000", ("rewe",)))
    assert (caught.value.keyword, caught.value.owner) == ("rewe", "Lebensmittel")


def test_each_fallback_role_needs_exactly_one_holder() -> None:
    with pytest.raises(FallbackCategoryError):
        CategoryCatalog([INCOME, FOOD])
    second = Category("Rest", "#000000", role=CategoryRole.EXPENSE_FALLBACK)
    with pytest.raises(FallbackCategoryError):
        _catalog(second)


def test_fallback_needs_matching_kind() -> None:
    ignored_fallback = Category(
        "Sonstiges", "#b8b8b8", kind=CategoryKind.IGNORED, role=CategoryRole.EXPENSE_FALLBACK
    )
    with pytest.raises(FallbackCategoryError):
        CategoryCatalog([INCOME, ignored_fallback])


# -- reading ---------------------------------------------------------------------------------


def test_lookups() -> None:
    catalog = _catalog()
    assert catalog.names() == ["Einkommen", "Lebensmittel", "Gesundheit", "Sonstiges"]
    assert "Lebensmittel" in catalog
    assert len(catalog) == 4
    assert catalog.category_of_keyword("REWE") == "Lebensmittel"
    assert catalog.category_of_keyword("aldi") is None
    assert catalog.color_of("Unbekannt") == UNKNOWN_COLOR
    assert catalog.kind_of("Einkommen") is CategoryKind.INCOME
    with pytest.raises(UnknownCategoryError):
        catalog.get("Unbekannt")


def test_fallback_for_sign() -> None:
    catalog = _catalog()
    assert catalog.fallback_for(Decimal("10")).name == "Einkommen"
    assert catalog.fallback_for(Decimal("-10")).name == "Sonstiges"
    assert catalog.fallback_for(Decimal("0")).name == "Sonstiges"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("visa rewe 435 hannover", KeywordMatch("rewe", "Lebensmittel")),
        ("rewe-markt", KeywordMatch("rewe", "Lebensmittel")),
        ("visa denn s biomarkt hannov", KeywordMatch("denn s biomarkt", "Lebensmittel")),
        ("dm drogerie markt", KeywordMatch("dm", "Gesundheit")),
        ("admiral spielhalle", None),
        ("brewery", None),
    ],
)
def test_match_at_token_start(text: str, expected: KeywordMatch | None) -> None:
    assert _catalog().match(text) == expected


def test_longest_keyword_wins_and_ties_follow_catalog_order() -> None:
    catalog = _catalog(
        Category("Shopping", "#bfcbff", ("amazon", "visa")),
        Category("Abos", "#e19bdf", ("amazon prime",)),
    )
    assert catalog.match("amazon prime video") == KeywordMatch("amazon prime", "Abos")
    # "rewe" (Lebensmittel) and "visa" (Shopping) are equally long: catalog order decides …
    assert catalog.match("visa rewe 435") == KeywordMatch("rewe", "Lebensmittel")
    # … in both directions (not alphabetical order).
    catalog.move("Shopping", 0)
    assert catalog.match("visa rewe 435") == KeywordMatch("visa", "Shopping")


def test_match_normalizes_its_input() -> None:
    assert _catalog().match("VISA  REWE Markt") == KeywordMatch("rewe", "Lebensmittel")


def test_income_keywords_only_match_money_coming_in() -> None:
    catalog = _catalog()
    assert catalog.match("gehalt juli", Decimal("2000")) == KeywordMatch("gehalt", "Einkommen")
    assert catalog.match("gehaltsabrechnung gebuehr", Decimal("-5")) is None
    assert catalog.match("gehalt juli") == KeywordMatch("gehalt", "Einkommen")  # no amount


def test_occurs_at_token_start_finds_later_occurrences() -> None:
    assert occurs_at_token_start("admin dm", "dm")
    assert not occurs_at_token_start("admin", "dm")


# -- changing --------------------------------------------------------------------------------


def test_mutations_keep_both_directions_consistent() -> None:
    catalog = _catalog()
    catalog.add("Shopping")
    catalog.add_keyword("Shopping", "Amazon")
    catalog.set_keywords("Gesundheit", ["apotheke", "dm drogerie"])
    catalog.remove_keyword("Lebensmittel", "REWE")
    catalog.rename("Lebensmittel", "Essen")
    _assert_consistent(catalog)
    assert catalog.category_of_keyword("rewe") is None
    assert catalog.category_of_keyword("dm") is None
    assert catalog.category_of_keyword("denn s biomarkt") == "Essen"
    assert catalog.names() == ["Einkommen", "Essen", "Gesundheit", "Sonstiges", "Shopping"]


def test_failed_change_leaves_catalog_untouched() -> None:
    catalog = _catalog()
    with pytest.raises(KeywordConflictError):
        catalog.add_keyword("Gesundheit", "rewe")
    with pytest.raises(DuplicateCategoryError):
        catalog.rename("Gesundheit", "Lebensmittel")
    assert catalog.keywords_of("Gesundheit") == ("dm",)
    assert catalog.names() == ["Einkommen", "Lebensmittel", "Gesundheit", "Sonstiges"]
    _assert_consistent(catalog)


def test_add_uses_next_free_palette_color() -> None:
    catalog = _catalog()
    used = {category.color for category in catalog}
    added = catalog.add("Shopping", CategoryKind.EXPENSE)
    assert added.color == next(color for color in PALETTE if color not in used)
    assert catalog.add("Rot", color="#FF0000").color == "#ff0000"


def test_add_keyword_returns_normalized_and_is_idempotent() -> None:
    catalog = _catalog()
    assert catalog.add_keyword("Lebensmittel", " ALDI ") == "aldi"
    assert catalog.add_keyword("Lebensmittel", "aldi") == "aldi"
    assert catalog.keywords_of("Lebensmittel").count("aldi") == 1
    with pytest.raises(CategoryError):
        catalog.add_keyword("Lebensmittel", "   ")


def test_fallbacks_cannot_be_removed_or_rekinded_but_renamed() -> None:
    catalog = _catalog()
    with pytest.raises(FallbackCategoryError):
        catalog.remove("Sonstiges")
    with pytest.raises(FallbackCategoryError):
        catalog.set_kind("Einkommen", CategoryKind.EXPENSE)
    catalog.rename("Sonstiges", "Rest")
    assert catalog.fallback(CategoryRole.EXPENSE_FALLBACK).name == "Rest"


def test_remove_set_kind_color_budget() -> None:
    catalog = _catalog()
    catalog.set_kind("Gesundheit", CategoryKind.IGNORED)
    catalog.set_color("Gesundheit", "#123456")
    catalog.set_budget("Lebensmittel", Decimal("250.00"))
    assert catalog.get("Gesundheit").kind is CategoryKind.IGNORED
    assert catalog.color_of("Gesundheit") == "#123456"
    assert catalog.get("Lebensmittel").budget == Decimal("250.00")
    catalog.set_budget("Lebensmittel", None)
    catalog.remove("Gesundheit")
    assert catalog.get("Lebensmittel").budget is None
    assert catalog.category_of_keyword("dm") is None


def test_move_keyword_is_atomic_and_takes_it_from_the_owner() -> None:
    catalog = _catalog()
    assert catalog.move_keyword("REWE", "Gesundheit") == "rewe"
    assert catalog.category_of_keyword("rewe") == "Gesundheit"
    assert "rewe" not in catalog.keywords_of("Lebensmittel")
    catalog.move_keyword("aldi", "Lebensmittel")  # not owned yet: simply added
    assert catalog.category_of_keyword("aldi") == "Lebensmittel"
    _assert_consistent(catalog)


def test_move_reorders_and_clamps() -> None:
    catalog = _catalog()
    catalog.move("Sonstiges", 0)
    catalog.move("Einkommen", 99)
    assert catalog.names() == ["Sonstiges", "Lebensmittel", "Gesundheit", "Einkommen"]


def test_names_are_looked_up_trimmed() -> None:
    catalog = _catalog()
    assert catalog.get(" Lebensmittel ").name == "Lebensmittel"
    assert " Lebensmittel" in catalog
    assert catalog.rename("Gesundheit", "  Drogerie ") == "Drogerie"


def test_copy_is_independent() -> None:
    original = _catalog()
    copy = original.copy()
    copy.add_keyword("Lebensmittel", "aldi")
    assert original.category_of_keyword("aldi") is None
