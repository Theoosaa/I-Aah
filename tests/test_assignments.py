"""Manual assignments, splits and resolving bookings (manual > keyword > fallback)."""

from datetime import date
from decimal import Decimal

import pytest

from iaah.core.assignments import (
    AssignmentSource,
    Categorizer,
    ManualAssignments,
    SplitPart,
    validate_split,
)
from iaah.core.categories import Category, CategoryCatalog, CategoryKind, CategoryRole
from iaah.core.errors import SplitError, UnknownCategoryError
from iaah.core.models import Transaction


def _catalog() -> CategoryCatalog:
    return CategoryCatalog(
        [
            Category(
                "Einkommen", "#6fcf99", ("gehalt",), CategoryKind.INCOME,
                role=CategoryRole.INCOME_FALLBACK,
            ),
            Category("Lebensmittel", "#92ca7d", ("rewe",)),
            Category("Haushalt", "#c9a98b"),
            Category("Sonstiges", "#b8b8b8", role=CategoryRole.EXPENSE_FALLBACK),
        ]
    )  # fmt: skip


def _txn(payee: str, amount: str = "-20.00", purpose: str = "") -> Transaction:
    return Transaction(date(2026, 7, 1), "Lastschrift", payee, purpose, Decimal(amount), "x.pdf")


@pytest.fixture
def categorizer() -> Categorizer:
    return Categorizer(_catalog(), ManualAssignments())


REWE = _txn("VISA REWE 435")
UNKNOWN_SHOP = _txn("Laden am Eck")
REFUND = _txn("Unbekannt GmbH", "15.00")


def test_auto_by_keyword_and_fallback(categorizer: Categorizer) -> None:
    by_keyword = categorizer.auto(REWE)
    assert (by_keyword.category, by_keyword.source, by_keyword.keyword) == (
        "Lebensmittel",
        AssignmentSource.KEYWORD,
        "rewe",
    )
    assert categorizer.auto(UNKNOWN_SHOP).category == "Sonstiges"
    assert categorizer.auto(UNKNOWN_SHOP).source is AssignmentSource.FALLBACK
    assert categorizer.auto(REFUND).category == "Einkommen"


def test_manual_beats_keyword(categorizer: Categorizer) -> None:
    categorizer.assign(REWE, "Haushalt")
    resolution = categorizer.resolve(REWE)
    assert (resolution.category, resolution.source) == ("Haushalt", AssignmentSource.MANUAL)
    assert resolution.auto_category == "Lebensmittel"
    assert resolution.is_manual
    assert resolution.differs_from_auto
    assert resolution.parts == (SplitPart("Haushalt", Decimal("-20.00")),)


def test_assigning_the_keyword_category_removes_the_decision(categorizer: Categorizer) -> None:
    categorizer.assign(REWE, "Haushalt")
    categorizer.assign(REWE, "Lebensmittel")
    assert REWE.key not in categorizer.manual
    assert categorizer.resolve(REWE).source is AssignmentSource.KEYWORD


def test_confirming_the_fallback_is_remembered_as_reviewed(categorizer: Categorizer) -> None:
    categorizer.assign(UNKNOWN_SHOP, "Sonstiges")
    resolution = categorizer.resolve(UNKNOWN_SHOP)
    assert (resolution.category, resolution.source) == ("Sonstiges", AssignmentSource.MANUAL)
    assert not resolution.differs_from_auto


def test_assign_unknown_category_raises(categorizer: Categorizer) -> None:
    with pytest.raises(UnknownCategoryError):
        categorizer.assign(REWE, "Gibt es nicht")
    with pytest.raises(UnknownCategoryError):
        categorizer.split(REWE, [SplitPart("Gibt es nicht", Decimal("-20.00"))])


def test_split_resolution(categorizer: Categorizer) -> None:
    parts = [SplitPart("Lebensmittel", Decimal("-5.00")), SplitPart("Haushalt", Decimal("-15.00"))]
    categorizer.split(REWE, parts)
    resolution = categorizer.resolve(REWE)
    assert resolution.source is AssignmentSource.SPLIT
    assert resolution.category == "Haushalt"  # the largest part
    assert resolution.parts == tuple(parts)
    assert resolution.differs_from_auto
    categorizer.clear(REWE)
    assert categorizer.resolve(REWE).source is AssignmentSource.KEYWORD


@pytest.mark.parametrize(
    ("parts", "message"),
    [
        ([("A", "-20.00")], "at least"),
        ([("A", "-10.00"), ("A", "-10.00")], "only once"),
        ([("A", "-25.00"), ("B", "5.00")], "sign"),
        ([("A", "-20.00"), ("B", "0")], "sign"),
        ([("A", "-10.00"), ("B", "-9.99")], "add up"),
    ],
)
def test_invalid_splits(parts: list[tuple[str, str]], message: str) -> None:
    split = [SplitPart(category, Decimal(amount)) for category, amount in parts]
    with pytest.raises(SplitError, match=message):
        validate_split(Decimal("-20.00"), split)


def test_stale_decisions_fall_back_to_automatic(categorizer: Categorizer) -> None:
    categorizer.assign(REWE, "Haushalt")
    categorizer.catalog.remove("Haushalt")
    assert categorizer.resolve(REWE).source is AssignmentSource.KEYWORD


def test_rename_and_forget_category() -> None:
    manual = ManualAssignments()
    manual.set_category(REWE, "Alt")
    manual.set_split(
        UNKNOWN_SHOP, [SplitPart("Alt", Decimal("-1")), SplitPart("B", Decimal("-19"))]
    )
    manual.set_category(REFUND, "B")
    manual.rename_category("Alt", "Neu")
    assert manual.get(REWE.key) == "Neu"
    assert manual.uses("Neu")
    assert not manual.uses("Alt")
    assert manual.forget_category("Neu") == 2
    assert dict(manual.items()) == {REFUND.key: "B"}


def test_income_keyword_does_not_claim_outgoing_payments(categorizer: Categorizer) -> None:
    tax = _txn("Finanzamt", "-300.00", "Gehaltsabrechnung Lohnsteuer")
    salary = _txn("Arbeitgeber", "2500.00", "Gehalt Juli")
    assert categorizer.auto(tax).category == "Sonstiges"
    assert categorizer.auto(salary).source is AssignmentSource.KEYWORD


def test_categorizer_rename_keeps_decisions(categorizer: Categorizer) -> None:
    categorizer.assign(REWE, "Haushalt")
    assert categorizer.rename_category("Haushalt", "  Zuhause ") == "Zuhause"
    resolution = categorizer.resolve(REWE)
    assert (resolution.category, resolution.source) == ("Zuhause", AssignmentSource.MANUAL)


def test_categorizer_remove_drops_decisions(categorizer: Categorizer) -> None:
    categorizer.assign(REWE, "Haushalt")
    assert categorizer.remove_category("Haushalt") == 1
    assert "Haushalt" not in categorizer.catalog
    assert REWE.key not in categorizer.manual


def test_renaming_into_a_split_partner_merges_the_parts() -> None:
    manual = ManualAssignments()
    parts = [
        SplitPart("A", Decimal("-5")),
        SplitPart("B", Decimal("-10")),
        SplitPart("C", Decimal("-5")),
    ]
    manual.set_split(REWE, parts)
    manual.rename_category("A", "B")
    assert manual.get(REWE.key) == (SplitPart("B", Decimal("-15")), SplitPart("C", Decimal("-5")))
    manual.rename_category("C", "B")
    assert manual.get(REWE.key) == "B"  # collapsed into one category


def test_prune_redundant_returns_what_it_dropped_for_undo(categorizer: Categorizer) -> None:
    categorizer.assign(UNKNOWN_SHOP, "Haushalt")
    categorizer.assign(REWE, "Haushalt")
    categorizer.catalog.add_keyword("Haushalt", "laden am eck")
    dropped = categorizer.prune_redundant([UNKNOWN_SHOP, REWE], keyword="Laden am Eck")
    assert dropped == {UNKNOWN_SHOP.key: "Haushalt"}
    assert UNKNOWN_SHOP.key not in categorizer.manual
    assert REWE.key in categorizer.manual  # still differs from its keyword category
    categorizer.manual.restore(dropped)
    assert categorizer.manual.get(UNKNOWN_SHOP.key) == "Haushalt"


def test_prune_with_keyword_only_checks_bookings_containing_it(categorizer: Categorizer) -> None:
    categorizer.assign(UNKNOWN_SHOP, "Haushalt")
    categorizer.catalog.add_keyword("Haushalt", "laden am eck")
    assert categorizer.prune_redundant([UNKNOWN_SHOP], keyword="kiosk") == {}


def test_names_are_stored_as_in_the_catalog(categorizer: Categorizer) -> None:
    categorizer.assign(UNKNOWN_SHOP, " Haushalt ")
    assert categorizer.manual.get(UNKNOWN_SHOP.key) == "Haushalt"
    categorizer.rename_category("Haushalt", "Zuhause")
    assert categorizer.resolve(UNKNOWN_SHOP).category == "Zuhause"
    categorizer.assign(REWE, " Lebensmittel ")  # the keyword's own category: no decision
    assert REWE.key not in categorizer.manual
    parts = [SplitPart(" Zuhause", Decimal("-5")), SplitPart("Lebensmittel ", Decimal("-15"))]
    categorizer.split(REWE, parts)
    assert [part.category for part in categorizer.resolve(REWE).parts] == [
        "Zuhause",
        "Lebensmittel",
    ]


@pytest.mark.parametrize("amount", ["-10.005", "NaN", "-1E+40"])
def test_split_parts_must_be_finite_whole_cents(amount: str) -> None:
    parts = [SplitPart("A", Decimal(amount)), SplitPart("B", Decimal("-10.00"))]
    with pytest.raises(SplitError, match="cents"):
        validate_split(Decimal("-20.00"), parts)


def test_copy_is_independent() -> None:
    manual = ManualAssignments({REWE.key: "Haushalt"})
    copy = manual.copy()
    copy.clear(REWE)
    assert len(manual) == 1
    assert len(copy) == 0
