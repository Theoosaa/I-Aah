"""Category files: JSON and CSV round trips, budgets import, default catalog, errors."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from iaah.core.categories import Category, CategoryCatalog, CategoryKind, CategoryRole
from iaah.core.category_io import (
    catalog_from_csv,
    catalog_from_json,
    catalog_to_csv,
    catalog_to_json,
    default_catalog,
    load_catalog,
    save_catalog,
)
from iaah.core.errors import CategoryFileError


def _sample() -> CategoryCatalog:
    return CategoryCatalog(
        [
            Category(
                "Einkommen", "#6fcf99", ("gehalt",), CategoryKind.INCOME,
                role=CategoryRole.INCOME_FALLBACK,
            ),
            Category("Lebensmittel", "#92ca7d", ("rewe", "denn s"), budget=Decimal("250.5")),
            Category("Umbuchung", "#a0b4c8", ("sparplan",), CategoryKind.IGNORED),
            Category("Sonstiges", "#b8b8b8", role=CategoryRole.EXPENSE_FALLBACK),
        ]
    )  # fmt: skip


def test_json_round_trip() -> None:
    catalog = _sample()
    assert list(catalog_from_json(catalog_to_json(catalog))) == list(catalog)


def test_json_uses_real_types() -> None:
    data = json.loads(catalog_to_json(_sample()))
    food = data["categories"][1]
    assert data["version"] == 1
    assert food == {
        "name": "Lebensmittel",
        "color": "#92ca7d",
        "kind": "expense",
        "budget": "250.5",
        "keywords": ["rewe", "denn s"],
    }


def test_csv_round_trip() -> None:
    catalog = _sample()
    text = catalog_to_csv(catalog)
    assert "250,50" in text
    assert list(catalog_from_csv(text)) == list(catalog)


def test_budgets_format_is_imported() -> None:
    budgets = [
        {"name": "Einkaufen", "keywords": ["rewe", "REWE", "lidl"]},
        {"name": "Ignoriert", "keywords": ["vodafone"], "excluded": "true"},
        {"name": "Andere", "keywords": ["lidl", "kino"], "excluded": True},
        {"name": "Sonstiges", "keywords": []},
    ]
    catalog = catalog_from_json(json.dumps(budgets))
    assert catalog.keywords_of("Einkaufen") == ("rewe", "lidl")
    assert catalog.keywords_of("Andere") == ("kino",)  # "lidl" was claimed first
    assert catalog.kind_of("Ignoriert") is CategoryKind.IGNORED
    assert catalog.kind_of("Andere") is CategoryKind.IGNORED
    assert catalog.fallback(CategoryRole.EXPENSE_FALLBACK).name == "Sonstiges"
    income = catalog.fallback(CategoryRole.INCOME_FALLBACK)
    assert (income.name, income.kind) == ("Einkommen", CategoryKind.INCOME)
    assert len({category.color for category in catalog}) == len(catalog)


def test_budgets_json_with_trailing_commas_is_imported() -> None:
    # Same shape as budgets' data/categories.json, which is hand-edited and not strict JSON.
    text = """[
      {"name": "Einkaufen", "keywords": ["rewe", "lidl",]},
      {"name": "Ignoriert", "keywords": ["vodafone", "ewe",], "excluded": "true"},
      {"name": "Sonstiges", "keywords": []},
    ]"""
    catalog = catalog_from_json(text)
    assert catalog.keywords_of("Ignoriert") == ("vodafone", "ewe")
    assert catalog.kind_of("Ignoriert") is CategoryKind.IGNORED


def test_budgets_csv_is_imported() -> None:
    text = "name,keywords,excluded\nEinkaufen,rewe;lidl,False\nIgnoriert,vodafone,True\n"
    catalog = catalog_from_csv(text)
    assert catalog.keywords_of("Einkaufen") == ("rewe", "lidl")
    assert catalog.kind_of("Ignoriert") is CategoryKind.IGNORED
    assert catalog.fallback(CategoryRole.EXPENSE_FALLBACK).name == "Sonstiges"


def test_budgets_csv_is_lenient_like_budgets_json() -> None:
    text = "name,keywords,excluded\nA,rewe;-,False\nB,rewe;lidl,False\n"
    catalog = catalog_from_csv(text)
    assert catalog.keywords_of("A") == ("rewe",)  # "-" skipped
    assert catalog.keywords_of("B") == ("lidl",)  # "rewe" claimed by A first


def test_own_csv_resaved_with_commas_keeps_its_keyword_separator() -> None:
    text = "name,color,kind,keywords\nEssen,#92ca7d,expense,rewe|edeka\n"
    assert catalog_from_csv(text).keywords_of("Essen") == ("rewe", "edeka")


def test_trailing_comma_repair_leaves_strings_alone() -> None:
    text = '[{"name": "A,]", "keywords": ["x,}",],},]'
    catalog = catalog_from_json(text)
    assert "A,]" in catalog
    assert catalog.keywords_of("A,]") == ("x,}",)


def test_excluded_budgets_fallback_is_switched_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    catalog = catalog_from_json('[{"name": "Sonstiges", "keywords": [], "excluded": true}]')
    assert catalog.kind_of("Sonstiges") is CategoryKind.EXPENSE
    assert "becomes the expense_fallback and now counts as expense" in caplog.text


def test_default_catalog_is_valid() -> None:
    catalog = default_catalog()
    assert catalog.fallback(CategoryRole.EXPENSE_FALLBACK).name == "Sonstiges"
    assert catalog.fallback(CategoryRole.INCOME_FALLBACK).name == "Einkommen"
    assert catalog.kind_of("Ignoriert") is CategoryKind.IGNORED
    assert catalog.category_of_keyword("rewe") == "Lebensmittel"


@pytest.mark.parametrize(
    "text",
    [
        "{not json",
        '{"categories": []}',
        '{"version": 1, "categories": [{"name": "X"}]}',
        '{"version": 1, "categories": ["X"]}',
        '{"version": 1, "categories": [{"name": "X", "color": "#000000", "kind": "neu"}]}',
        '[{"keywords": []}]',
        # valid entries, but no fallback categories
        '{"version": 1, "categories": [{"name": "X", "color": "#000000"}]}',
        # malformed field types
        '{"version": 1, "categories": 5}',
        '[{"name": "X", "keywords": "rewe"}]',
        '[{"name": "X", "keywords": [null]}]',
    ],
)
def test_invalid_json_raises(text: str) -> None:
    with pytest.raises(CategoryFileError):
        catalog_from_json(text)


@pytest.mark.parametrize("budget", ["NaN", "Infinity", "-1", "10.005", "viel"])
def test_invalid_budget_in_an_otherwise_valid_file(budget: str) -> None:
    data = json.loads(catalog_to_json(_sample()))
    data["categories"][1]["budget"] = budget
    with pytest.raises(CategoryFileError, match=r"budget|invalid category entry"):
        catalog_from_json(json.dumps(data))


@pytest.mark.parametrize(
    "text",
    ["farbe;x\nrot;y\n", "name;budget\nEssen;viel\n", "name;kind\nEssen;neu\n"],
)
def test_invalid_csv_raises(text: str) -> None:
    with pytest.raises(CategoryFileError):
        catalog_from_csv(text)


def test_minimal_csv_gets_colors_and_fallbacks() -> None:
    catalog = catalog_from_csv("name;keywords\nEssen;rewe|aldi\n")
    assert catalog.keywords_of("Essen") == ("rewe", "aldi")
    assert catalog.fallback(CategoryRole.EXPENSE_FALLBACK).name == "Sonstiges"


def test_csv_budget_accepts_english_format_too() -> None:
    catalog = catalog_from_csv("name;budget\nEssen;250.50\nKino;1.250\n")
    assert catalog.get("Essen").budget == Decimal("250.50")
    assert catalog.get("Kino").budget == Decimal("1250")  # German thousands first


def test_csv_export_rejects_keywords_containing_the_separator() -> None:
    catalog = _sample()
    catalog.add_keyword("Lebensmittel", "a|b")
    with pytest.raises(CategoryFileError):
        catalog_to_csv(catalog)


def test_cp1252_csv_from_excel_is_read(tmp_path: Path) -> None:
    path = tmp_path / "kategorien.csv"
    path.write_bytes("name;keywords\nBäckerei;bäcker\n".encode("cp1252"))
    assert load_catalog(path).keywords_of("Bäckerei") == ("baecker",)


@pytest.mark.parametrize("suffix", [".json", ".csv"])
def test_file_round_trip(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / f"kategorien{suffix}"
    save_catalog(_sample(), path)
    assert list(load_catalog(path)) == list(_sample())


def test_file_errors(tmp_path: Path) -> None:
    with pytest.raises(CategoryFileError):
        load_catalog(tmp_path / "fehlt.json")
    with pytest.raises(CategoryFileError):
        save_catalog(_sample(), tmp_path / "kategorien.txt")
