"""Keyword candidates and previews."""

from datetime import date
from decimal import Decimal

import pytest

from iaah.core.assignments import Categorizer, ManualAssignments
from iaah.core.categories import (
    Category,
    CategoryCatalog,
    CategoryKind,
    CategoryRole,
    occurs_at_token_start,
)
from iaah.core.models import Transaction
from iaah.core.suggestions import keyword_candidates, preview_keyword, suggest_keywords


def _txn(payee: str, purpose: str = "", amount: str = "-10.00") -> Transaction:
    return Transaction(date(2026, 7, 1), "Lastschrift", payee, purpose, Decimal(amount), "x.pdf")


PAYPAL_PATREON = _txn(
    "PayPal Europe S.a.r.l. et Cie S.C.A",
    "1051374080449/PP.8695.PP/. Patreon Ireland Limited, Ihr Einkauf bei Patreon Ireland Limited",
)
CANDIDATE_CASES = [
    (_txn("VISA REWE 435 HANNOVER"), ["rewe", "hannover"]),
    (
        _txn("VISA DENN S BIOMARKT HANNOV"),
        ["denn s biomarkt hannov", "denn s biomarkt", "denn", "biomarkt", "hannov"],
    ),
    (PAYPAL_PATREON, ["patreon ireland", "patreon", "ireland"]),
    (_txn("Visavis GmbH"), ["visavis"]),
    (_txn("RSG Group GmbH"), ["rsg"]),
    (_txn("VISA SØSTRENE GRENE"), ["søstrene grene", "søstrene", "grene"]),
    # Card payment: the city from the purpose is never suggested, also not cut short.
    (
        _txn("VISA DENN S BIOMARKT HANNOV", "NR XXXX 0010 HANNOVER DE KAUFUMSATZ 29.06"),
        ["denn s biomarkt", "denn", "biomarkt"],
    ),
    # PayPal with an empty first copy: the merchant comes from "… bei <merchant> Mandat:".
    (
        _txn(
            "PayPal Europe S.a.r.l. et Cie S.C.A", "123/PP.1.PP/. , Ihr Einkauf bei Steam Mandat: X"
        ),
        ["steam"],
    ),
]


@pytest.mark.parametrize(("txn", "expected"), CANDIDATE_CASES)
def test_keyword_candidates(txn: Transaction, expected: list[str]) -> None:
    assert keyword_candidates(txn) == expected


@pytest.mark.parametrize(("txn", "expected"), CANDIDATE_CASES)
def test_every_candidate_matches_its_own_booking(txn: Transaction, expected: list[str]) -> None:
    assert all(occurs_at_token_start(txn.search_text, kw) for kw in keyword_candidates(txn))


def _categorizer() -> Categorizer:
    catalog = CategoryCatalog(
        [
            Category(
                "Einkommen", "#6fcf99", (), CategoryKind.INCOME, role=CategoryRole.INCOME_FALLBACK
            ),
            Category("Lebensmittel", "#92ca7d", ("rewe",)),
            Category("Shopping", "#bfcbff"),
            Category("Sonstiges", "#b8b8b8", role=CategoryRole.EXPENSE_FALLBACK),
        ]
    )
    return Categorizer(catalog, ManualAssignments())


REWE_1 = _txn("VISA REWE 435")
REWE_2 = _txn("VISA REWE 12")
BIOMARKT = _txn("VISA BIOMARKT HANNOVER")
BIOMARKT_MANUAL = _txn("VISA BIOMARKT LINDEN", amount="-3.00")
LEDGER = [REWE_1, REWE_2, BIOMARKT, BIOMARKT_MANUAL]


def test_preview_counts_matches_and_changes_but_ignores_manual() -> None:
    categorizer = _categorizer()
    categorizer.assign(BIOMARKT_MANUAL, "Shopping")
    preview = preview_keyword(categorizer, "Biomarkt", "Lebensmittel", LEDGER)
    assert (preview.keyword, preview.owner, preview.matches, preview.changes) == (
        "biomarkt",
        None,
        2,
        1,
    )
    assert categorizer.catalog.category_of_keyword("biomarkt") is None  # nothing stored


def test_preview_of_an_income_keyword_counts_money_in_only() -> None:
    ledger = [_txn("Arbeitgeber", "Lohn Juli", "2500.00"), _txn("Finanzamt", "Lohnsteuer", "-300")]
    preview = preview_keyword(_categorizer(), "lohn", "Einkommen", ledger)
    assert (preview.matches, preview.changes) == (1, 0)  # the salary is income already


def test_preview_of_an_owned_keyword_simulates_moving_it() -> None:
    preview = preview_keyword(_categorizer(), "rewe", "Shopping", LEDGER)
    assert (preview.owner, preview.matches, preview.changes) == ("Lebensmittel", 2, 2)


def test_suggestions_put_owned_keywords_last_and_skip_own_ones() -> None:
    categorizer = _categorizer()
    categorizer.catalog.add_keyword("Shopping", "hannover")
    suggestions = suggest_keywords(
        categorizer, _txn("VISA REWE BIOMARKT HANNOVER"), "Lebensmittel", LEDGER
    )
    keywords = [preview.keyword for preview in suggestions]
    assert "rewe" not in keywords  # Lebensmittel already has it
    assert keywords[-1] == "hannover"
    assert suggestions[-1].owner == "Shopping"
