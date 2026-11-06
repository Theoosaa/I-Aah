"""Merchant detection behind card and PayPal payments."""

from datetime import date
from decimal import Decimal
from typing import Final

import pytest

from iaah.core.merchants import card_city_words, merchant_key, merchant_label, merchant_text
from iaah.core.models import Transaction

CARD_PURPOSE: Final = "NR XXXX 0010 HANNOVER DE KAUFUMSATZ 29.06"
PAYPAL_NETFLIX: Final = "1/PP.1.PP/. Netflix.com, Ihr Einkauf bei Netflix.com"


def _txn(payee: str, purpose: str = "") -> Transaction:
    return Transaction(date(2026, 7, 1), "Lastschrift", payee, purpose, Decimal("-1"), "x.pdf")


@pytest.mark.parametrize(
    ("txn", "text", "key", "label"),
    [
        (_txn("Vermieter GmbH"), "vermieter gmbh", "vermieter gmbh", "Vermieter GmbH"),
        (_txn("VISA REWE 435 HANNOVER", CARD_PURPOSE), "rewe 435 hannover", "rewe", "REWE"),
        (_txn("VISA DENN S BIOMARKT HANNOV", CARD_PURPOSE), "denn s biomarkt hannov",
         "denn s biomarkt", "DENN S BIOMARKT"),
        (_txn("PayPal Europe S.a.r.l. et Cie S.C.A", PAYPAL_NETFLIX), "netflix.com",
         "netflix com", "Netflix.com"),
        (_txn("Visavis GmbH"), "visavis gmbh", "visavis gmbh", "Visavis GmbH"),
        (_txn("4711"), "4711", "4711", "4711"),  # nothing left after filtering: keep the text
    ],
)  # fmt: skip
def test_merchant_text_key_and_label(txn: Transaction, text: str, key: str, label: str) -> None:
    assert merchant_text(txn) == text
    assert merchant_key(txn) == key
    assert merchant_label(txn) == label


def test_branches_share_one_key() -> None:
    first = _txn("VISA REWE 435 HANNOVER", CARD_PURPOSE)
    second = _txn("VISA REWE 12 HANNOVER", CARD_PURPOSE)
    assert merchant_key(first) == merchant_key(second)


def test_card_city_words() -> None:
    card = _txn("VISA REWE", "NR XXXX 0010 BAD HOMBURG DE KAUFUMSATZ 01.07")
    assert card_city_words(card) == {"bad", "homburg"}
    assert card_city_words(_txn("Vermieter", "Miete Juli")) == frozenset()
