# Portions adapted from budgets (MIT, © 2026 nikluep) – see LICENSES/budgets-MIT.txt
"""Spending and income per category as text or CSV – and merging several CSV summaries.

The CSV layout (``Typ;Kategorie;Betrag (EUR)``) is budgets' own, so summaries written by
either program can be merged. ``render_*``/``parse_*`` are pure; ``write_*``/``read_*`` add the
file and the BOM that Windows editors and Excel need.
"""

import csv
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from io import StringIO
from pathlib import Path
from typing import Final

from iaah.core.analysis.ledger import Entry
from iaah.core.analysis.totals import category_totals
from iaah.core.categories import CategoryKind
from iaah.core.errors import IaahError
from iaah.core.text import (
    COMMA,
    DOT,
    decode_text,
    detect_decimal_style,
    format_euro,
    format_plain_german,
    parse_amount,
)
from iaah.export.files import write_export

EXPENSE: Final = "Ausgabe"
INCOME: Final = "Einnahme"
HEADER: Final = ("Typ", "Kategorie", "Betrag (EUR)")
COLUMNS: Final = len(HEADER)
DELIMITERS: Final = ";,"
SNIFF_CHARS: Final = 2048
ENCODING: Final = "utf-8-sig"
RULE_WIDTH: Final = 46
AMOUNT_WIDTH: Final = 14
MIN_NAME_WIDTH: Final = 18
PERCENT: Final = 100
NONE_LINE: Final = "(keine Buchungen)"
TOTAL: Final = "Gesamt"
NET: Final = "Netto (Einnahmen - Ausgaben)"


class SummaryFileError(IaahError):
    """A CSV summary could not be read."""


@dataclass(frozen=True, slots=True)
class Summary:
    """Net amounts per category, largest first; ignored categories never appear. A category
    whose refunds outweigh its spending shows a negative amount, so the totals equal the
    KPIs of the analysis."""

    expenses: Mapping[str, Decimal] = field(default_factory=dict)
    income: Mapping[str, Decimal] = field(default_factory=dict)

    @property
    def total_expenses(self) -> Decimal:
        """All spending."""
        return sum(self.expenses.values(), Decimal(0))

    @property
    def total_income(self) -> Decimal:
        """All income."""
        return sum(self.income.values(), Decimal(0))

    @property
    def net(self) -> Decimal:
        """Income minus spending; negative is a deficit."""
        return self.total_income - self.total_expenses


def summarize(entries: Iterable[Entry]) -> Summary:
    """Net spending and income per category (a refund lowers its category)."""
    listed = list(entries)
    return Summary(
        category_totals(listed, CategoryKind.EXPENSE), category_totals(listed, CategoryKind.INCOME)
    )


def merge_summaries(summaries: Iterable[Summary]) -> Summary:
    """Add several summaries; a category in more than one is summed."""
    expenses: dict[str, Decimal] = defaultdict(Decimal)
    income: dict[str, Decimal] = defaultdict(Decimal)
    for summary in summaries:
        for name, amount in summary.expenses.items():
            expenses[name] += amount
        for name, amount in summary.income.items():
            income[name] += amount
    return Summary(_descending(expenses), _descending(income))


# -- text -------------------------------------------------------------------------------------


def render_text_summary(summary: Summary) -> str:
    """A plain-text breakdown with shares and the net at the end."""
    width = max([MIN_NAME_WIDTH, *(len(name) for name in [*summary.expenses, *summary.income])])
    rule = "-" * (width + RULE_WIDTH - MIN_NAME_WIDTH)
    sections = (
        _section("Ausgaben nach Kategorie", summary.expenses, summary.total_expenses, width),
        _section("Einnahmen nach Kategorie", summary.income, summary.total_income, width),
    )
    net = f"{NET:<{width}} {format_euro(summary.net):>{AMOUNT_WIDTH}}"
    return "\n\n".join(sections) + f"\n\n{rule}\n{net}"


def _section(title: str, amounts: Mapping[str, Decimal], total: Decimal, width: int) -> str:
    rule = "-" * (width + RULE_WIDTH - MIN_NAME_WIDTH)
    lines = [title, rule]
    if not amounts:
        lines.append(NONE_LINE)
    for name, amount in amounts.items():
        share = amount / total * PERCENT if total else Decimal(0)
        percent = f"{share:5.1f}".replace(DOT, COMMA)  # German: 57,6 %
        lines.append(f"{name:<{width}} {format_euro(amount):>{AMOUNT_WIDTH}}  ({percent} %)")
    lines += [rule, f"{TOTAL:<{width}} {format_euro(total):>{AMOUNT_WIDTH}}"]
    return "\n".join(lines)


def write_text_summary(summary: Summary, path: Path) -> None:
    """Save the text summary (with BOM for old Windows editors)."""
    write_export(path, (render_text_summary(summary) + "\n").encode(ENCODING))


# -- CSV --------------------------------------------------------------------------------------


def render_csv_summary(summary: Summary) -> str:
    """One row per category; amounts as plain numbers with decimal comma, so spreadsheets read
    them as numbers."""
    buffer = StringIO()
    writer = csv.writer(buffer, delimiter=DELIMITERS[0])
    writer.writerow(HEADER)
    for kind, amounts in ((EXPENSE, summary.expenses), (INCOME, summary.income)):
        writer.writerows([kind, name, format_plain_german(a)] for name, a in amounts.items())
    return buffer.getvalue()


def parse_csv_summary(text: str) -> Summary:
    """Read a CSV summary (``;`` or ``,``, decimal comma or point); rows of the same category
    are added up."""
    rows = [row for row in csv.reader(StringIO(text), _dialect(text)) if any(map(str.strip, row))]
    if not rows or tuple(cell.strip() for cell in rows[0]) != HEADER:
        raise SummaryFileError(f"not a category summary: header must be {';'.join(HEADER)}")
    cells = [_cells(row, number) for number, row in enumerate(rows[1:], start=2)]
    style = detect_decimal_style(raw for _, _, raw in cells)
    sides: dict[str, dict[str, Decimal]] = {
        EXPENSE: defaultdict(Decimal),
        INCOME: defaultdict(Decimal),
    }
    for number, (kind, name, raw) in enumerate(cells, start=2):
        amount = parse_amount(raw, style)
        if amount is None:
            raise SummaryFileError(f"line {number}: invalid amount {raw!r}")
        sides[kind][name] += amount
    return Summary(_descending(sides[EXPENSE]), _descending(sides[INCOME]))


def _dialect(text: str) -> type[csv.Dialect]:
    try:
        return csv.Sniffer().sniff(text[:SNIFF_CHARS], delimiters=DELIMITERS)
    except csv.Error:
        return csv.excel


def _cells(row: Sequence[str], number: int) -> tuple[str, str, str]:
    if len(row) != COLUMNS:
        raise SummaryFileError(f"line {number}: expected {COLUMNS} columns")
    kind, name, raw = (cell.strip() for cell in row)
    if kind not in (EXPENSE, INCOME):
        raise SummaryFileError(f"line {number}: unknown type {kind!r}")
    return kind, name, raw


def write_csv_summary(summary: Summary, path: Path) -> None:
    """Save the CSV summary with BOM (Excel shows umlauts and € correctly)."""
    write_export(path, render_csv_summary(summary).encode(ENCODING))


def read_csv_summary(path: Path) -> Summary:
    """Read a CSV summary written by I-Aah or budgets."""
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise SummaryFileError(f"cannot read {path}") from error
    return parse_csv_summary(decode_text(raw)[0])


def _descending(amounts: Mapping[str, Decimal]) -> dict[str, Decimal]:
    return dict(sorted(amounts.items(), key=lambda item: item[1], reverse=True))
