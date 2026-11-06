"""Keyword suggestions with a preview of their effect – instead of silent auto-rules.

Both predecessors created rules automatically and got them wrong easily (budgets' learning
step was never finished). Here, after a manual assignment the GUI offers keywords taken from
the booking, each with how many bookings it would match and how many automatic categories it
would change. Nothing is stored until the user confirms; then the GUI calls
``CategoryCatalog.move_keyword`` and ``Categorizer.prune_redundant``.
"""

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Final

from iaah.core.assignments import Categorizer
from iaah.core.categories import CategoryKind, normalize_keyword, occurs_at_token_start
from iaah.core.merchants import (
    TOKEN,
    card_city_words,
    is_city_word,
    is_meaningful_word,
    merchant_text,
)
from iaah.core.models import Transaction

MAX_CONNECTOR_LETTERS: Final = 2  # short words allowed inside a phrase ("denn s biomarkt")
MAX_PHRASE_WORDS: Final = 3
MIN_PHRASE_WORDS: Final = 2
MAX_CANDIDATES: Final = 6


@dataclass(frozen=True, slots=True)
class KeywordPreview:
    """What adding a keyword to a category would do."""

    keyword: str
    owner: str | None  # category that owns the keyword today, if any
    matches: int  # bookings the keyword applies to (income keywords: money coming in only)
    changes: int  # bookings without manual decision whose category would change


type _Ledger = Sequence[tuple[Transaction, str]]  # bookings with their search text


def keyword_candidates(txn: Transaction) -> list[str]:
    """Keyword candidates for a booking, most specific first.

    Every candidate is a contiguous piece of the booking's normalized merchant text starting
    at a token (``merchants.TOKEN`` shares the token notion of ``occurs_at_token_start``), so
    it is guaranteed to match the booking it came from. Card-payment cities are left out –
    they would route every shop in town to one category.
    """
    text = merchant_text(txn)
    city = card_city_words(txn)
    tokens = list(TOKEN.finditer(text))
    phrases = _phrases(text, tokens, city)
    words = (token.group() for token in tokens if _is_candidate_word(token.group(), city))
    return list(dict.fromkeys([*phrases, *words]))[:MAX_CANDIDATES]


def preview_keyword(
    categorizer: Categorizer, keyword: str, category: str, transactions: Sequence[Transaction]
) -> KeywordPreview:
    """Simulate adding ``keyword`` to ``category`` on a copy of the catalog.

    A keyword owned by another category is simulated as moved, since keywords are unique.
    """
    return _preview(categorizer, keyword, category, _with_texts(transactions))


def suggest_keywords(
    categorizer: Categorizer, txn: Transaction, category: str, transactions: Sequence[Transaction]
) -> list[KeywordPreview]:
    """Previews for the booking's candidates; keywords owned by another category come last,
    keywords the category already has are left out."""
    ledger = _with_texts(transactions)
    previews = [
        _preview(categorizer, candidate, category, ledger)
        for candidate in keyword_candidates(txn)
        if categorizer.catalog.category_of_keyword(candidate) != category
    ]
    return sorted(previews, key=lambda preview: preview.owner is not None)


def _with_texts(transactions: Sequence[Transaction]) -> list[tuple[Transaction, str]]:
    return [(txn, txn.search_text) for txn in transactions]


def _preview(
    categorizer: Categorizer, keyword: str, category: str, ledger: _Ledger
) -> KeywordPreview:
    normalized = normalize_keyword(keyword)
    owner = categorizer.catalog.category_of_keyword(normalized)
    trial = categorizer.catalog.copy()
    trial.move_keyword(normalized, category)
    after = Categorizer(trial, categorizer.manual)

    # Only bookings containing the keyword can change – also when it moves between categories.
    # Income keywords never apply to money going out, so those are no matches either.
    income_only = trial.kind_of(category) is CategoryKind.INCOME
    hits = [
        txn
        for txn, text in ledger
        if occurs_at_token_start(text, normalized) and (txn.amount > 0 or not income_only)
    ]
    automatic = [txn for txn in hits if not categorizer.resolve(txn).is_manual]
    changes = sum(categorizer.auto(t).category != after.auto(t).category for t in automatic)
    return KeywordPreview(normalized, owner, len(hits), changes)


def _phrases(text: str, tokens: Sequence[re.Match[str]], city: frozenset[str]) -> Iterator[str]:
    """The first run of candidate words (short connectors allowed inside) as a phrase, plus its
    two-word prefix – only if the run has at least two candidate words."""
    run = _first_run(tokens, city)
    good = [token for token in run if _is_candidate_word(token.group(), city)][:MAX_PHRASE_WORDS]
    if len(good) < MIN_PHRASE_WORDS:
        return
    yield text[good[0].start() : good[-1].end()]
    yield text[good[0].start() : good[MIN_PHRASE_WORDS - 1].end()]


def _first_run(tokens: Sequence[re.Match[str]], city: frozenset[str]) -> list[re.Match[str]]:
    run: list[re.Match[str]] = []
    for token in tokens:
        word = token.group()
        if _is_candidate_word(word, city) or (run and _is_connector(word)):
            run.append(token)
        elif run:
            break
    return run


def _is_candidate_word(word: str, city: frozenset[str]) -> bool:
    return is_meaningful_word(word) and not is_city_word(word, city)


def _is_connector(word: str) -> bool:
    return word.isalpha() and len(word) <= MAX_CONNECTOR_LETTERS
