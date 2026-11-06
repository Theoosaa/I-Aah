# Portions adapted from budgets (MIT, © 2026 nikluep) – see LICENSES/budgets-MIT.txt
"""Reading and writing category catalogs (JSON, CSV) and the bundled default catalog.

The codecs (``catalog_to_*`` / ``catalog_from_*``) work on strings; ``load_catalog`` and
``save_catalog`` are the thin file wrappers. Besides its own formats, the reader accepts the
category files of *budgets* – JSON (a list of ``{name, keywords, excluded}``, tolerating the
trailing commas of hand-edited files) and CSV (``name,keywords,excluded`` with ``;`` between
keywords) – and adds the fallback categories such files lack. Every problem surfaces as a
``CategoryFileError``.
"""

import csv
import io
import json
import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from importlib import resources
from pathlib import Path
from typing import Any, Final

from iaah.core.categories import (
    FALLBACK_KINDS,
    PALETTE,
    Category,
    CategoryCatalog,
    CategoryKind,
    CategoryRole,
    normalize_keyword,
)
from iaah.core.errors import CategoryError, CategoryFileError
from iaah.core.text import (
    DecimalStyle,
    decode_text,
    format_plain_german,
    normalize_text,
    parse_amount,
)

logger: Final = logging.getLogger(__name__)

FORMAT_VERSION: Final = 1
DEFAULT_RESOURCE: Final = "data/default_categories.json"
JSON_SUFFIX: Final = ".json"
CSV_SUFFIX: Final = ".csv"
# Field names of the JSON and CSV formats ("excluded" only in budgets files).
FIELD_VERSION: Final = "version"
FIELD_CATEGORIES: Final = "categories"
FIELD_NAME: Final = "name"
FIELD_COLOR: Final = "color"
FIELD_KIND: Final = "kind"
FIELD_ROLE: Final = "role"
FIELD_BUDGET: Final = "budget"
FIELD_KEYWORDS: Final = "keywords"
FIELD_EXCLUDED: Final = "excluded"
CSV_COLUMNS: Final = (FIELD_NAME, FIELD_COLOR, FIELD_KIND, FIELD_ROLE, FIELD_BUDGET, FIELD_KEYWORDS)
TRUE_WORDS: Final = frozenset({"true", "1", "yes", "ja"})
QUOTE: Final = '"'
# A JSON string literal (kept as is) or a trailing comma before "]" / "}" (dropped).
_STRING_OR_TRAILING_COMMA: Final = re.compile(r'("(?:[^"\\]|\\.)*")|,(\s*[\]}])')

CSV_DELIMITERS: Final = (";", ",")
OWN_KEYWORD_SEPARATOR: Final = "|"
BUDGETS_KEYWORD_SEPARATOR: Final = ";"
BUDGETS_DELIMITER: Final = ","
# Columns only this program writes; budgets files have name, keywords, excluded.
OWN_COLUMNS: Final = frozenset({FIELD_COLOR, FIELD_KIND, FIELD_ROLE, FIELD_BUDGET})


@dataclass(frozen=True, slots=True)
class _CsvFormat:
    delimiter: str
    budgets: bool  # budgets layout: "excluded" column, ";" between keywords

    @property
    def keyword_separator(self) -> str:
        return BUDGETS_KEYWORD_SEPARATOR if self.budgets else OWN_KEYWORD_SEPARATOR


def default_catalog() -> CategoryCatalog:
    """The catalog shipped with I-Aah."""
    resource = resources.files("iaah").joinpath(DEFAULT_RESOURCE)
    return catalog_from_json(resource.read_text(encoding="utf-8"))


def with_fallbacks(categories: Iterable[Category], defaults: CategoryCatalog) -> list[Category]:
    """Give every fallback role a holder.

    A category named like the default fallback takes the role (and its kind); otherwise the
    default fallback is appended, without keywords another category already owns.
    """
    result = list(categories)
    for role in CategoryRole:
        if any(category.role is role for category in result):
            continue
        default = defaults.fallback(role)
        names = [category.name for category in result]
        if default.name not in names:
            result.append(_without_taken_keywords(default, result))
            continue
        index = names.index(default.name)
        if result[index].kind is not FALLBACK_KINDS[role]:
            kind = FALLBACK_KINDS[role]
            logger.warning("%r becomes the %s and now counts as %s", default.name, role, kind)
        result[index] = replace(result[index], role=role, kind=FALLBACK_KINDS[role])
    return result


# -- JSON -------------------------------------------------------------------------------------


def catalog_to_json(catalog: CategoryCatalog) -> str:
    """Serialize a catalog to this program's JSON format."""
    return json.dumps(catalog_to_data(catalog), ensure_ascii=False, indent=2)


def catalog_from_json(text: str) -> CategoryCatalog:
    """Parse this program's JSON format or a budgets category file."""
    data = _load_json(text)
    if isinstance(data, list):
        return _from_budgets(data)
    return catalog_from_data(data)


def catalog_to_data(catalog: CategoryCatalog) -> dict[str, Any]:
    """The catalog as JSON-ready data (also embedded in the app's data file)."""
    return {FIELD_VERSION: FORMAT_VERSION, FIELD_CATEGORIES: [_to_dict(c) for c in catalog]}


def catalog_from_data(data: object) -> CategoryCatalog:
    """Inverse of ``catalog_to_data``; ``CategoryFileError`` for anything malformed."""
    if not isinstance(data, dict) or data.get(FIELD_VERSION) != FORMAT_VERSION:
        raise CategoryFileError("unknown category file format")
    entries = data.get(FIELD_CATEGORIES)
    if not isinstance(entries, list):
        raise CategoryFileError("'categories' must be a list")
    return _build(_from_dict(entry) for entry in entries)


def _load_json(text: str) -> object:
    """Strict JSON; on failure retry without trailing commas (hand-edited budgets files)."""
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        try:
            return json.loads(_strip_trailing_commas(text))
        except json.JSONDecodeError:
            raise CategoryFileError(f"invalid JSON: {error}") from error


def _strip_trailing_commas(text: str) -> str:
    """Drop commas before ``]``/``}`` outside of string literals."""
    return _STRING_OR_TRAILING_COMMA.sub(lambda match: match[1] or match[2], text)


def _to_dict(category: Category) -> dict[str, Any]:
    data: dict[str, Any] = {
        FIELD_NAME: category.name,
        FIELD_COLOR: category.color,
        FIELD_KIND: category.kind,
    }
    if category.role is not None:
        data[FIELD_ROLE] = category.role
    if category.budget is not None:
        data[FIELD_BUDGET] = str(category.budget)
    data[FIELD_KEYWORDS] = list(category.keywords)
    return data


def _from_dict(entry: object) -> Category:
    if not isinstance(entry, Mapping):
        raise CategoryFileError(f"category entry is not an object: {entry!r}")
    try:
        budget = entry.get(FIELD_BUDGET)
        role = entry.get(FIELD_ROLE)
        return Category(
            name=str(entry[FIELD_NAME]),
            color=str(entry[FIELD_COLOR]),
            keywords=_keyword_list(entry.get(FIELD_KEYWORDS)),
            kind=CategoryKind(entry.get(FIELD_KIND, CategoryKind.EXPENSE)),
            budget=Decimal(str(budget)) if budget is not None else None,
            role=CategoryRole(role) if role else None,
        )
    except (KeyError, TypeError, ValueError, InvalidOperation) as error:
        raise CategoryFileError(f"invalid category entry: {entry!r}") from error


def _from_budgets(entries: list[object]) -> CategoryCatalog:
    taken: set[str] = set()
    categories = [_from_budgets_entry(entry, index, taken) for index, entry in enumerate(entries)]
    return _build(with_fallbacks(categories, default_catalog()))


def _from_budgets_entry(entry: object, index: int, taken: set[str]) -> Category:
    if not isinstance(entry, Mapping) or FIELD_NAME not in entry:
        raise CategoryFileError(f"invalid budgets category entry: {entry!r}")
    name = str(entry[FIELD_NAME])
    return Category(
        name=name,
        color=PALETTE[index % len(PALETTE)],
        keywords=_unclaimed(_keyword_list(entry.get(FIELD_KEYWORDS)), taken, name),
        kind=_kind_from_excluded(entry.get(FIELD_EXCLUDED)),
    )


def _keyword_list(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(keyword, str) for keyword in value):
        raise CategoryFileError(f"keywords must be a list of strings, got {value!r}")
    return tuple(value)


def _kind_from_excluded(value: object) -> CategoryKind:
    excluded = str(value).strip().lower() in TRUE_WORDS
    return CategoryKind.IGNORED if excluded else CategoryKind.EXPENSE


# -- CSV --------------------------------------------------------------------------------------


def catalog_to_csv(catalog: CategoryCatalog) -> str:
    """Serialize a catalog as ``;``-separated CSV (keywords joined with ``|``)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=CSV_DELIMITERS[0])
    writer.writerow(CSV_COLUMNS)
    for category in catalog:
        writer.writerow(_to_row(category))
    return buffer.getvalue()


def catalog_from_csv(text: str) -> CategoryCatalog:
    """Parse this program's CSV (any of ``;``/``,``) or a budgets CSV
    (``name,keywords,excluded``). Budgets files are read leniently like budgets JSON."""
    layout = _csv_format(text)
    reader = csv.DictReader(io.StringIO(text), delimiter=layout.delimiter)
    taken: set[str] = set()
    categories = [_from_row(row, index, layout, taken) for index, row in enumerate(reader)]
    return _build(with_fallbacks(categories, default_catalog()))


def _to_row(category: Category) -> list[str]:
    if any(OWN_KEYWORD_SEPARATOR in keyword for keyword in category.keywords):
        raise CategoryFileError(
            f"a keyword of {category.name!r} contains {OWN_KEYWORD_SEPARATOR!r}"
        )
    budget = format_plain_german(category.budget) if category.budget is not None else ""
    role = category.role or ""
    keywords = OWN_KEYWORD_SEPARATOR.join(category.keywords)
    return [category.name, category.color, category.kind, role, budget, keywords]


def _csv_format(text: str) -> _CsvFormat:
    """Delimiter from the header; the layout from its columns, not from the delimiter – our own
    file re-saved by a spreadsheet with commas must still split keywords at ``|``."""
    lines = text.splitlines()
    header = lines[0] if lines else ""
    for delimiter in CSV_DELIMITERS:
        columns = {cell.strip().strip(QUOTE).lower() for cell in header.split(delimiter)}
        if FIELD_NAME not in columns:
            continue
        budgets = FIELD_EXCLUDED in columns or (
            delimiter == BUDGETS_DELIMITER and not columns & OWN_COLUMNS
        )
        return _CsvFormat(delimiter, budgets)
    raise CategoryFileError("CSV needs a 'name' column")


def _from_row(
    row: Mapping[str, str | None], index: int, layout: _CsvFormat, taken: set[str]
) -> Category:
    def cell(column: str) -> str:
        return (row.get(column) or "").strip()

    raw_keywords = [kw for kw in cell(FIELD_KEYWORDS).split(layout.keyword_separator) if kw.strip()]
    name = cell(FIELD_NAME)
    # budgets files: skip unusable keywords, first claim wins (as for budgets JSON)
    keywords = _unclaimed(raw_keywords, taken, name) if layout.budgets else tuple(raw_keywords)
    try:
        # Own files state the kind; budgets files only say whether a category is excluded.
        kind_text = cell(FIELD_KIND)
        kind = CategoryKind(kind_text) if kind_text else _kind_from_excluded(cell(FIELD_EXCLUDED))
        return Category(
            name=name,
            color=cell(FIELD_COLOR) or PALETTE[index % len(PALETTE)],
            keywords=keywords,
            kind=kind,
            budget=_csv_budget(cell(FIELD_BUDGET)),
            role=CategoryRole(cell(FIELD_ROLE)) if cell(FIELD_ROLE) else None,
        )
    except ValueError as error:
        raise CategoryFileError(f"invalid category row {index + 1}: {error}") from error


def _csv_budget(raw: str) -> Decimal | None:
    """German format first (as written by ``catalog_to_csv``), English as a fallback."""
    if not raw:
        return None
    for style in DecimalStyle:
        budget = parse_amount(raw, style)
        if budget is not None:
            return budget
    raise ValueError(f"invalid budget {raw!r}")


# -- files ------------------------------------------------------------------------------------


def load_catalog(path: Path) -> CategoryCatalog:
    """Read a ``.json`` or ``.csv`` category file in any common encoding."""
    suffix = _checked_suffix(path)
    try:
        text, _ = decode_text(path.read_bytes())
    except OSError as error:
        raise CategoryFileError(f"cannot read {path}") from error
    return catalog_from_json(text) if suffix == JSON_SUFFIX else catalog_from_csv(text)


def save_catalog(catalog: CategoryCatalog, path: Path) -> None:
    """Write a ``.json`` or ``.csv`` category file (CSV with BOM, so Excel shows umlauts)."""
    suffix = _checked_suffix(path)
    try:
        if suffix == JSON_SUFFIX:
            path.write_text(catalog_to_json(catalog), encoding="utf-8")
        else:
            path.write_text(catalog_to_csv(catalog), encoding="utf-8-sig", newline="")
    except OSError as error:
        raise CategoryFileError(f"cannot write {path}") from error


# -- helpers ----------------------------------------------------------------------------------


def _build(categories: Iterable[Category]) -> CategoryCatalog:
    try:
        return CategoryCatalog(categories)
    except CategoryError as error:
        raise CategoryFileError(str(error)) from error


def _checked_suffix(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix not in (JSON_SUFFIX, CSV_SUFFIX):
        raise CategoryFileError(f"unsupported category file type: {suffix!r}")
    return suffix


def _unclaimed(raw_keywords: Iterable[str], taken: set[str], owner: str) -> tuple[str, ...]:
    """Normalized keywords that no earlier category claimed; the first claim wins."""
    keywords: list[str] = []
    for raw in raw_keywords:
        try:
            keyword = normalize_keyword(raw)
        except CategoryError:
            continue  # empty or punctuation-only keyword
        if keyword in taken:
            logger.warning("keyword %r of %r already used by an earlier category", keyword, owner)
            continue
        taken.add(keyword)
        keywords.append(keyword)
    return tuple(keywords)


def _without_taken_keywords(category: Category, others: Iterable[Category]) -> Category:
    taken = {normalize_text(keyword) for other in others for keyword in other.keywords}
    free = tuple(kw for kw in category.keywords if normalize_text(kw) not in taken)
    return replace(category, keywords=free)
