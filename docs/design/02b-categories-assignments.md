# Step 2b – Categories, keyword matching and assignments

## Modules

| Module | Responsibility |
|---|---|
| `core/categories.py` | `Category`, `CategoryKind`, `CategoryRole`, `CategoryCatalog` (both lookup directions), keyword matching, keyword candidates, palette. |
| `core/category_io.py` | Catalog codecs (JSON, CSV), legacy budgets JSON import, bundled default catalog. |
| `core/assignments.py` | Manual assignments and splits, `Categorizer` (auto vs. resolved category), keyword preview/suggestions. |
| `iaah/data/default_categories.json` | Default catalog (German names are *data*, not UI text). |

## Category model

```python
class CategoryKind(StrEnum):  EXPENSE, INCOME, IGNORED      # IGNORED never counts (transfers, "Ignoriert")
class CategoryRole(StrEnum):  EXPENSE_FALLBACK, INCOME_FALLBACK

@dataclass(slots=True)
class Category:
    name: str
    color: str                       # "#rrggbb"
    keywords: list[str]              # normalized, unique across the whole catalog
    kind: CategoryKind = EXPENSE
    budget: Decimal | None = None    # monthly budget
    role: CategoryRole | None = None
```

* `kind` replaces both the legacy `exclude` flag and the hard-coded `"Einkommen"` checks:
  several income categories and several ignored categories are possible.
* Fallback roles are fixed to exactly one category each (defaults: *Sonstiges*, *Einkommen*);
  they cannot be deleted. *Ignoriert* ships as a default `IGNORED` category.
  "Nicht zugeordnet" disappears – unmatched bookings land in the fallback and are recognisable
  by their assignment source (`FALLBACK`).

## CategoryCatalog – both directions

```python
catalog.names() -> list[str]                    catalog.get(name) -> Category
catalog.keywords_of(name) -> tuple[str, ...]    catalog.category_of_keyword(kw) -> str | None
catalog.fallback(role) -> Category              catalog.color_of(name) -> str
catalog.match(text) -> KeywordMatch | None      # longest keyword wins, ties: catalog order
catalog.add(name, color=None) / remove / rename / set_color / set_kind / set_budget
catalog.add_keyword(name, kw) / remove_keyword(name, kw) / set_keywords(name, kws)
catalog.copy() -> CategoryCatalog
```

The keyword → category index is rebuilt by every mutating method, so both directions are always
consistent. A keyword already owned by another category raises `KeywordConflictError(keyword,
owner)` – never a silent overwrite.

**Matching rule:** text and keywords are normalized (`text.normalize_text`); a keyword matches
when it occurs at a **token start** (start of text or after a non-alphanumeric character).
`"dm"` matches `"dm drogerie"` but not `"admiral"`; `"rewe"` matches `"visa rewe 435"` and
`"rewe-markt"`. Pure substring matching (both legacy tools) produced false hits for short keywords.

## Assignments

```python
class AssignmentSource(StrEnum): MANUAL, SPLIT, KEYWORD, FALLBACK

@dataclass(frozen=True, slots=True) class SplitPart:  category: str; amount: Decimal
@dataclass(frozen=True, slots=True) class Resolution:
    category: str; source: AssignmentSource; keyword: str | None
    parts: tuple[SplitPart, ...]      # one part unless split
    auto_category: str                # what keywords/fallback alone would give (before/after view)

ManualAssignments: assign(txn, cat) / split(txn, parts) / clear(txn) / get(key)
                   rename_category(old, new) / forget_category(name) / items()
Categorizer(catalog, manual): auto(txn) -> Resolution; resolve(txn) -> Resolution
```

* Assignments are keyed by `Transaction.key`; identical bookings (same day, amount, payee) share
  one assignment – acceptable, they are the same kind of booking.
* A split needs ≥ 2 parts with non-zero amounts that sum exactly to the booking amount
  (`SplitError` otherwise). Its primary `category` is the largest part.

## Keyword suggestions (replaces the missing budgets `refine_categories` and legacy auto-rules)

```python
keyword_candidates(txn) -> list[str]
preview_keyword(categorizer, keyword, category, transactions) -> KeywordPreview
suggest_keywords(categorizer, txn, category, transactions) -> list[KeywordPreview]

@dataclass(frozen=True, slots=True)
class KeywordPreview: keyword: str; owner: str | None; matches: int; changes: int
```

* Candidates: normalized payee tokens and the first two-token phrase; when the payee is a
  payment intermediary (PayPal, VISA, Klarna, Google/Apple Pay …) the purpose text is used
  instead. Generic tokens (booking types, legal forms, `ihr`, `einkauf`, …) and tokens with
  digits or fewer than 3 letters are dropped.
* `preview_keyword` adds the keyword to a **copy** of the catalog and counts bookings that
  would match (`matches`) and whose automatic category would change (`changes`), ignoring
  manually assigned bookings. Nothing is saved – the GUI asks for confirmation first.

## Category files

JSON (`version`, `categories: [{name, color, kind, role?, budget?, keywords}]`, real booleans and
decimal strings) and CSV (`name;color;kind;budget;keywords` with `|`-separated keywords). Import
also accepts the budgets format (list of `{name, keywords, excluded}`), assigns palette colors,
maps `excluded` to `IGNORED` and adds missing fallback categories.

## Tests

`test_categories.py` (both lookup directions stay consistent after every mutation, conflicts,
token-start matching, longest match, fallbacks undeletable, rename keeps keywords),
`test_category_io.py` (round trips, budgets import, invalid files), `test_assignments.py`
(manual > keyword > fallback, splits validation, rename/forget, before/after via
`auto_category`, keyword preview counts, candidate extraction incl. PayPal case).
