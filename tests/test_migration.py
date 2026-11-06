"""Migration of the legacy settings.json / data.json – one test per row of the design table."""

import base64
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet

from iaah.core.categories import CategoryKind, CategoryRole
from iaah.core.category_io import default_catalog
from iaah.core.crypto import LEGACY_ITERATIONS, MAGIC_LEGACY, Cipher
from iaah.core.errors import PasswordRequiredError, StorageError
from iaah.core.migration import (
    DropReason,
    LegacyData,
    Migration,
    has_legacy_files,
    migrate,
    read_legacy,
)

SETTINGS: dict[str, Any] = {
    "version": 2,
    "categories": [
        {"name": "Einkommen", "color": "#2e7d32"},  # legacy default color -> new pastel
        {"name": "Lebensmittel", "color": "#123456"},  # picked by the user -> kept
        {"name": "Versicherung", "color": "#8e24aa"},
        {"name": "Umbuchung", "color": "#00897b", "exclude": True},
        {"name": "Sonstiges", "color": "#546e7a"},
        {"name": "Nicht zugeordnet", "color": "#bdbdbd"},
    ],
    "rules": [
        {"keyword": "REWE", "category": "Lebensmittel"},
        {"keyword": "rewe ", "category": "Versicherung"},  # same keyword again: conflict
        {"keyword": "VERS", "category": "Versicherung"},
        {"keyword": "^ALDI.*", "category": "Lebensmittel", "regex": True},
        {"keyword": "LIDL", "category": "Lebensmittel", "regex": True},  # literal regex
        {"keyword": "MIETE", "category": "Wohnen"},  # unknown category
        {"keyword": "TABAK", "category": "Nicht zugeordnet"},
        {"keyword": "BAHN", "category": "Lebensmittel", "min": 10},
        {"keyword": "   ", "category": "Lebensmittel"},
    ],
    "budgets": {"Lebensmittel": 250.0},
    "overrides": {
        "2026-07-02|-40.00|Fritz Mueller": "Versicherung",
        "2026-07-03|-9.99|/Dauerauftrag Verein": "Lebensmittel",
        "2026-07-04|-20.00|Unbekannt": "Nicht zugeordnet",
        "2026-07-05|-20.00|Splitter": [
            {"category": "Lebensmittel", "betrag": -15.0},
            {"category": "Versicherung", "betrag": -5.0},
        ],
        "2026-07-06|-1.00|Nirgends": "Gibt es nicht",
        "2026-07-07|-3.00|Ohne  Buchung": "Lebensmittel",
    },
}


def _legacy(day: str, kind: str, payee: str, amount: float, purpose: str) -> dict[str, Any]:
    """A booking as the legacy data.json stored it."""
    return {
        "datum": day, "buchungsart": kind, "empfaenger": payee, "zweck": purpose,
        "betrag": amount, "monat": day[:7], "quelle": "juli.pdf", "konto": "123",
    }  # fmt: skip


DATA: dict[str, Any] = {
    "version": 2,
    "files": ["juli.pdf"],
    "statements": [
        {"quelle": "juli.pdf", "konto": "123", "iban": "DE00", "monat": "2026-07",
         "alter_saldo": 1000.0, "neuer_saldo": 905.01},
    ],
    "transactions": [
        _legacy("2026-07-01", "Lastschrift", "LEBENSVERS.VON 1871", -20.0, "Beitrag"),
        _legacy("2026-07-02", "Lastschrift", "Fritz Mueller", -40.0, ""),
        _legacy("2026-07-03", "Gutschrift", "/Dauerauftrag Verein", -9.99, ""),
        _legacy("2026-07-05", "Lastschrift", "Splitter", -20.0, ""),
        _legacy("2026-07-08", "", "ARBEITGEBER", 0.0, "Lohn"),
        _legacy("2026-07-09", "Lastschrift", "VISA BACKSTUBE", -5.0, ""),
        _legacy("2026-07-10", "Lastschrift", "HUK COBURG", -100.0, ""),
        _legacy("2026-07-11", "Lastschrift", "DEUTSCHEBAHN", -20.0, ""),
    ],
}  # fmt: skip


@pytest.fixture(scope="module")
def migration() -> Migration:
    return migrate(LegacyData(SETTINGS, DATA), default_catalog())


def _dropped(migration: Migration, reason: DropReason) -> list[str]:
    return [item.what for item in migration.report.dropped if item.reason is reason]


def test_categories(migration: Migration) -> None:
    catalog = migration.catalog
    assert "Nicht zugeordnet" not in catalog
    assert catalog.fallback(CategoryRole.INCOME_FALLBACK).name == "Einkommen"
    assert catalog.fallback(CategoryRole.EXPENSE_FALLBACK).name == "Sonstiges"
    assert catalog.kind_of("Umbuchung") is CategoryKind.IGNORED
    assert "Ignoriert" not in catalog  # an ignored category exists already
    assert catalog.get("Lebensmittel").budget == Decimal("250.00")


def test_colors(migration: Migration) -> None:
    catalog = migration.catalog
    assert catalog.color_of("Lebensmittel") == "#123456"  # the user's choice
    assert catalog.color_of("Einkommen") == default_catalog().color_of("Einkommen")


def test_rules_become_keywords(migration: Migration) -> None:
    catalog = migration.catalog
    assert catalog.category_of_keyword("rewe") == "Lebensmittel"
    assert catalog.category_of_keyword("lidl") == "Lebensmittel"
    assert catalog.category_of_keyword("bahn") == "Lebensmittel"  # kept, bounds dropped
    assert catalog.category_of_keyword("vers") == "Versicherung"


def test_dropped_rules_are_reported(migration: Migration) -> None:
    assert _dropped(migration, DropReason.CONFLICT) == ["rewe "]
    assert _dropped(migration, DropReason.REGEX) == ["^ALDI.*"]
    assert "MIETE" in _dropped(migration, DropReason.UNKNOWN_CATEGORY)
    assert "TABAK" in _dropped(migration, DropReason.UNASSIGNED)
    assert _dropped(migration, DropReason.AMOUNT_BOUNDS) == ["BAHN"]
    assert _dropped(migration, DropReason.EMPTY) == ["   "]


def test_default_keywords_close_substring_gaps(migration: Migration) -> None:
    # "VERS" used to match inside "LEBENSVERS.VON"; token starts do not – the default
    # keyword "lebensvers" of the same-named category takes over.
    assert migration.catalog.category_of_keyword("lebensvers") == "Versicherung"
    insurance = migration.library.transactions[0]
    assert insurance not in [change.transaction for change in migration.report.changed]


def test_overrides_become_decisions_with_new_keys(migration: Migration) -> None:
    manual = migration.library.assignments
    by_payee = {txn.payee: txn for txn in migration.library.transactions}
    assert manual.get(by_payee["Fritz Mueller"].key) == "Versicherung"
    assert manual.get(by_payee["Verein"].key) == "Lebensmittel"  # payee re-split
    split = manual.get(by_payee["Splitter"].key)
    assert isinstance(split, tuple)
    assert [part.amount for part in split] == [Decimal("-15.00"), Decimal("-5.00")]
    assert manual.get("2026-07-07|-3.00|ohne buchung") == "Lebensmittel"  # rebuilt key
    assert "2026-07-04|-20.00|Unbekannt" in _dropped(migration, DropReason.UNASSIGNED)
    assert "2026-07-06|-1.00|Nirgends" in _dropped(migration, DropReason.UNKNOWN_CATEGORY)
    assert migration.report.assignments == 4


def test_library(migration: Migration) -> None:
    library = migration.library
    verein = next(txn for txn in library.transactions if txn.payee == "Verein")
    assert verein.booking_type == "Gutschrift/Dauerauftrag"
    (statement,) = library.statements
    assert statement.sha256 is None
    assert statement.info.opening_balance == Decimal("1000.00")
    assert statement.info.total == Decimal("-214.99")
    assert (migration.report.transactions, migration.report.statements) == (8, 1)


def test_changed_automatic_categories_are_reported(migration: Migration) -> None:
    changed = {c.transaction.payee: (c.before, c.after) for c in migration.report.changed}
    assert changed == {
        # default keyword "huk" of the same-named category now catches it
        "HUK COBURG": ("Nicht zugeordnet", "Versicherung"),
        # legacy "BAHN" matched inside "DEUTSCHEBAHN"; token starts do not
        "DEUTSCHEBAHN": ("Lebensmittel", "Sonstiges"),
    }


def test_files(tmp_path: Path) -> None:
    assert not has_legacy_files(tmp_path)
    (tmp_path / "settings.json").write_text(json.dumps(SETTINGS), encoding="utf-8")
    assert has_legacy_files(tmp_path)
    legacy = read_legacy(tmp_path)
    assert legacy.data is None
    assert legacy.settings is not None


def test_encrypted_legacy_data_needs_the_password(tmp_path: Path) -> None:
    salt = b"0123456789abcdef"
    key = Cipher.derive("geheim", salt, LEGACY_ITERATIONS).key
    token = Fernet(key).encrypt(json.dumps(DATA).encode())
    (tmp_path / "data.json").write_bytes(MAGIC_LEGACY + base64.b64encode(salt) + b"\n" + token)
    with pytest.raises(PasswordRequiredError):
        read_legacy(tmp_path)
    legacy = read_legacy(tmp_path, "geheim")
    assert legacy.data is not None
    assert legacy.cipher is not None


def test_damaged_legacy_files_raise(tmp_path: Path) -> None:
    (tmp_path / "settings.json").write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(StorageError):
        read_legacy(tmp_path)
    with pytest.raises(StorageError):
        migrate(LegacyData({"categories": [{"color": "#000000"}]}, None), default_catalog())


# -- review findings -------------------------------------------------------------------------


def _alias_settings() -> dict[str, Any]:
    return {
        "categories": [
            {"name": "Einkommen", "color": "#2e7d32"},
            {"name": "Miete & Wohnen", "color": "#6d4c41"},
            {"name": "Restaurant/Cafe", "color": "#fb8c00"},
            {"name": "Eigene", "color": "#00acc1"},  # untouched default of a removed default
            {"name": "Andere", "color": "rot"},  # invalid colour: a free one instead of a crash
            {"name": "Sonstiges", "color": "#546e7a"},
        ],
        "rules": [],
    }


def test_untouched_categories_get_distinct_colors_and_alias_keywords() -> None:
    catalog = migrate(LegacyData(_alias_settings(), None), default_catalog()).catalog
    colors = [category.color for category in catalog]
    assert len(set(colors)) == len(colors)
    defaults = default_catalog()
    assert catalog.color_of("Miete & Wohnen") == defaults.color_of("Wohnen")
    assert catalog.category_of_keyword("miete") == "Miete & Wohnen"
    assert catalog.category_of_keyword("lieferando") == "Restaurant/Cafe"


def test_split_rounding_is_absorbed_against_the_booking_amount() -> None:
    settings = {
        "categories": [{"name": "A", "color": "#111111"}, {"name": "B", "color": "#222222"},
                       {"name": "Sonstiges", "color": "#546e7a"}],
        "overrides": {
            "2026-07-01|-20.00|X": [
                {"category": "A", "betrag": -6.665},
                {"category": "B", "betrag": -6.665},
                {"category": "Nicht zugeordnet", "betrag": -6.67},
            ]
        },
    }  # fmt: skip
    migration = migrate(LegacyData(settings, None), default_catalog())
    split = migration.library.assignments.get("2026-07-01|-20.00|x")
    assert isinstance(split, tuple)
    assert sum(part.amount for part in split) == Decimal("-20.00")
    assert {part.category for part in split} == {"A", "B", "Sonstiges"}  # unassigned -> fallback


def test_legacy_matcher_uses_the_legacy_payee_text() -> None:
    settings = {
        "categories": [{"name": "Verein", "color": "#111111"},
                       {"name": "Sonstiges", "color": "#546e7a"}],
        "rules": [{"keyword": "DAUERAUFTRAG", "category": "Verein"},
                  {"keyword": "ZINS", "category": "Nicht zugeordnet"}],
    }  # fmt: skip
    data = {
        "transactions": [
            _legacy("2026-07-03", "Gutschrift", "/Dauerauftrag Verein", -9.99, ""),
            _legacy("2026-07-04", "", "ZINSGUTSCHRIFT", 1.0, ""),
        ]
    }
    changed = migrate(LegacyData(settings, data), default_catalog()).report.changed
    assert {(c.transaction.payee, c.before, c.after) for c in changed} == {
        # the rule matched the legacy payee; the re-split payee no longer contains the word
        ("Verein", "Verein", "Sonstiges"),
        # legacy showed "Nicht zugeordnet" for this money in; now it is income
        ("ZINSGUTSCHRIFT", "Nicht zugeordnet", "Einkommen"),
    }


def test_legacy_data_never_shows_in_repr() -> None:
    assert "LEBENSVERS" not in repr(LegacyData(SETTINGS, DATA))


# -- second review round ---------------------------------------------------------------------


def test_bookings_without_account_take_their_statements_account() -> None:
    booking = _legacy("2026-07-01", "Lastschrift", "Kiosk", -2.0, "")
    del booking["konto"]
    other = {**_legacy("2026-07-01", "Lastschrift", "Kiosk", -2.0, ""), "quelle": "fremd.csv"}
    del other["konto"]
    data = {"statements": DATA["statements"], "transactions": [booking, other]}
    library = migrate(LegacyData(None, data), default_catalog()).library
    assert [txn.account for txn in library.transactions] == ["123", ""]  # no statement: unknown


def test_decisions_without_booking_get_the_unglued_payee() -> None:
    settings = {
        "categories": [{"name": "Verein", "color": "#111111"},
                       {"name": "Sonstiges", "color": "#546e7a"}],
        "overrides": {"2026-08-03|-9.99|/Dauerauftrag Verein": "Verein",
                      "2026-08-04|-5.00|/Rente": "Verein"},  # nothing after the glue: kept
    }  # fmt: skip
    manual = migrate(LegacyData(settings, None), default_catalog()).library.assignments
    assert manual.get("2026-08-03|-9.99|verein") == "Verein"  # what a PDF import will produce
    assert manual.get("2026-08-04|-5.00|/rente") == "Verein"
