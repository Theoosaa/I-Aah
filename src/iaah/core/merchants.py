"""Who a booking actually went to.

Card and PayPal payments name the payment service as payee – "VISA REWE 435 HANNOVER",
"PayPal Europe S.a.r.l. …" with the merchant hidden in the purpose ("… Ihr Einkauf bei
Patreon …"). Keyword suggestions and the analysis (top merchants, fixed costs) both need the
merchant, so the logic lives here once.

Purposes come in two shapes: with spaces (new parser) and glued together (bookings migrated
from the legacy app: "…/.netflix.com,ihreinkaufbei Netflix.com mandat:…"). The PayPal patterns
accept both.
"""

import re
import string
from typing import Final

from iaah.core.models import Transaction
from iaah.core.text import clean_display, normalize_text

# Payment services that put themselves in front of the actual merchant.
INTERMEDIARIES: Final = ("paypal", "visa", "mastercard", "klarna", "google pay", "apple pay")
# PayPal names the merchant twice: "…/pp.1234.pp/. Shop Name, ihr einkauf bei Shop Name …".
# Either copy may have spaces inside words (PDF glyph spacing) or none at all (legacy text).
PAYPAL_PATTERNS: Final = (
    re.compile(r"/\.\s*(?P<merchant>[^,]*?)\s*,\s*ihr"),
    re.compile(r"ihr\s*einkauf\s*bei\s*(?P<merchant>.+?)(?:\s*mandat:|$)"),
    re.compile(r"\bbei\s+(?P<merchant>.+?)(?:\s+mandat:|$)"),
)
# Card payments name the city: "nr xxxx 0010 hannover de kaufumsatz …".
CARD_CITY: Final = re.compile(r"\bnr x+ \d+ (?P<city>.+?) [a-z]{2} kaufumsatz\b")

# Words that never identify a merchant on their own: legal forms, fillers, banking terms.
GENERIC_WORDS: Final = frozenset(
    {
        "gmbh", "mbh", "ohg", "inc", "ltd", "llc", "limited", "sarl", "sca", "plc", "corp",
        "cie", "company", "group", "handels", "europe", "deutschland", "germany", "und", "and",
        "the", "der", "die", "das", "fuer", "von", "bei", "mit", "eine", "marke", "ihr", "ihre",
        "einkauf", "kaufumsatz", "umsatz", "zahlung", "payment", "payments", "bank",
        "lastschrift", "gutschrift", "ueberweisung", "dauerauftrag", "mandat", "referenz",
        "kartenzahlung", "online", "shop", "store", "www", "com", "net", "org", "xxxx", "pay",
        "google", "apple", "visa", "paypal", "sagt", "danke", "markt", "filiale",
    }
)  # fmt: skip

MIN_LETTERS: Final = 3
# Letters and digits in the Unicode sense – the same notion of "token" as
# ``categories.occurs_at_token_start`` (``str.isalnum``).
TOKEN: Final = re.compile(r"[^\W_]+")
NO_WORDS: Final = frozenset[str]()


def is_meaningful_word(word: str) -> bool:
    """A word that could name a merchant: letters only, long enough, not generic."""
    return word.isalpha() and len(word) >= MIN_LETTERS and word not in GENERIC_WORDS


def is_city_word(word: str, city: frozenset[str]) -> bool:
    """Whether ``word`` is (a cut-short form of) a city word – payees cut cities short,
    "hannov" for "hannover"."""
    return len(word) >= MIN_LETTERS and any(city_word.startswith(word) for city_word in city)


def merchant_text(txn: Transaction) -> str:
    """The normalized part of the booking that names the merchant.

    For a payment service the payee rest ("visa rewe 435") if it names someone, else the
    merchant PayPal writes into the purpose, else the payee rest as it is. The raw purpose is
    never used – it carries mandate and reference numbers.
    """
    payee = normalize_text(txn.payee)
    intermediary = _intermediary(payee)
    if intermediary is None:
        return payee
    remainder = payee[len(intermediary) :].strip()
    if _has_meaningful_word(remainder):
        return remainder
    return _merchant_from_purpose(normalize_text(txn.purpose)) or remainder or payee


def merchant_key(txn: Transaction) -> str:
    """Grouping key for analysis: the merchant text without branch numbers and card-payment
    city, so "rewe 435 hannover" and "rewe 12 hannover" are both "rewe"."""
    text = merchant_text(txn)
    city = card_city_words(txn)
    words = [word for word in TOKEN.findall(text) if not _is_noise(word, city)]
    return " ".join(words) or text


def merchant_label(txn: Transaction) -> str:
    """The merchant for display: the same words as ``merchant_key``, in the booking's own
    spelling where the payee names the merchant."""
    payee = clean_display(txn.payee).strip()
    words = payee.split()
    intermediary = _intermediary(normalize_text(payee))
    if intermediary is not None:
        words = words[len(intermediary.split()) :]
        if not _has_meaningful_word(normalize_text(" ".join(words))):
            purpose_merchant = _merchant_from_purpose(normalize_text(txn.purpose))
            if purpose_merchant:
                # capwords, not title(): "netflix.com" -> "Netflix.com", not "Netflix.Com"
                return string.capwords(purpose_merchant)
    city = card_city_words(txn)
    kept = [word for word in words if not _is_noise(normalize_text(word), city)]
    return " ".join(kept) or payee


def card_city_words(txn: Transaction) -> frozenset[str]:
    """Words of the city a card payment names in its purpose (empty for other bookings)."""
    found = CARD_CITY.search(normalize_text(txn.purpose))
    return frozenset(TOKEN.findall(found["city"])) if found else NO_WORDS


def _intermediary(normalized_payee: str) -> str | None:
    """``"visa rewe"`` starts with the word ``"visa"``, ``"visavis gmbh"`` does not."""
    for name in INTERMEDIARIES:
        if normalized_payee == name or normalized_payee.startswith(f"{name} "):
            return name
    return None


def _merchant_from_purpose(purpose: str) -> str | None:
    for pattern in PAYPAL_PATTERNS:
        found = pattern.search(purpose)
        if found and _has_meaningful_word(found["merchant"]):
            return str(found["merchant"]).strip()
    return None


def _has_meaningful_word(text: str) -> bool:
    return any(is_meaningful_word(word) for word in TOKEN.findall(text))


def _is_noise(word: str, city: frozenset[str]) -> bool:
    """Branch numbers ("435") and the card-payment city – but not words with digits ("o2")."""
    return word.isdigit() or is_city_word(word, city)
