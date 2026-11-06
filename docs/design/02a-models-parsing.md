# Step 2a – Models, text helpers and parsing

Step 2 ("core") is split into four sub-steps, each with its own design/implement/review/revise
cycle, so reviews stay focused: **2a** models + parsing, **2b** categories + assignments,
**2c** analysis, **2d** library, storage + migration.

## Modules

| Module | Responsibility |
|---|---|
| `core/errors.py` | Exception hierarchy (`IaahError` and subclasses). |
| `core/models.py` | Immutable domain data: `Placement`, `Transaction`, `StatementInfo`, `ParsedStatement`. |
| `core/text.py` | `normalize_text`, `clean_display`, `format_euro`, German amount/date parsing. |
| `core/parsing/layout.py` | Bank-agnostic geometry: pdfplumber words → `Line`s → `Block`s with bounding boxes. |
| `core/parsing/diagnostics.py` | `LineStatus`, `LineDiagnosis`, `ParseReport`. |
| `core/parsing/ing.py` | ING-DiBa semantics on top of the layout: heads, booking types, metadata, reconciliation. |
| `core/parsing/csv_import.py` | Generic CSV export import (sniffing, header detection, column mapping). |

## Data model

```python
type BBox = tuple[float, float, float, float]      # x0, top, x1, bottom; PDF points, top-left origin

@dataclass(frozen=True, slots=True)
class Placement:            # where a booking sits in its PDF
    page: int               # 1-based
    head: BBox              # primary line (date, text, amount)
    details: BBox | None    # union of continuation lines

@dataclass(frozen=True, slots=True)
class Transaction:
    booking_date: date
    booking_type: str       # "Lastschrift", "Gutschrift", … ("" if unknown)
    payee: str
    purpose: str            # continuation lines joined with spaces
    amount: Decimal         # negative = money out
    source: str             # file name of the statement
    account: str = ""
    placement: Placement | None = None
    month -> "YYYY-MM";  key -> "date|amount|normalized payee";  search_text -> normalized payee + purpose

@dataclass(frozen=True, slots=True)
class StatementInfo:
    source: str; account: str; iban: str; period: str          # period "YYYY-MM" or ""
    opening_balance: Decimal | None; closing_balance: Decimal | None; total: Decimal
    reconciles -> bool | None

@dataclass(frozen=True, slots=True)
class ParsedStatement:
    info: StatementInfo; transactions: tuple[Transaction, ...]; report: ParseReport
```

`Transaction` deliberately carries **no category**: categorization is derived (step 2b), so a
transaction never holds stale state. Money is `Decimal` throughout.

## Parsing pipeline

```
pdfplumber page.extract_words(x_tolerance_ratio=0.15)      # I/O, only in ing.read_statement
  → layout.group_words_into_lines(words, page)              # pure; drops rotated words
  → layout.group_lines_into_blocks(lines, is_head, is_noise) # pure; diagnoses every line
  → ing: block → Transaction, lines → metadata              # pure
```

* **`x_tolerance_ratio=0.15`**: measured on a real ING statement – the default tolerance glues
  the purpose lines together (`NRXXXX0010HANNOVERDEKAUFUMSATZ`), the font-relative ratio restores
  the spaces while head lines stay identical. The legacy text parser had the same glued text.
* **Line grouping** (from budgets): cluster by vertical position only; rotated/mirrored words
  (e.g. the vertical `T_…` margin code next to bookings) are dropped and counted.
* **Block grouping** (from budgets): a line continues the open booking only if it is not a head,
  not noise, lies inside the head's column span (± `COLUMN_TOLERANCE`) and within `MAX_LINE_GAP`
  of the previous accepted line, and the booking has fewer than `MAX_DETAIL_LINES` details.
  The predicates `is_head`/`is_noise` are injected, so `layout.py` stays bank-agnostic.
* **ING semantics** (from legacy `parser.py`): head pattern `DD.MM.YYYY <text> <amount>`,
  booking-type prefixes, noise prefixes (page header/footer), leading valuta date stripped from
  detail lines, metadata (period, opening/closing balance, IBAN, account number) searched in
  every line's text.

## Diagnostics

Every line gets exactly one `LineStatus`: `HEAD`, `DETAIL`, `NOISE`, `NO_OPEN_BOOKING`,
`OUTSIDE_COLUMN`, `GAP_TOO_LARGE`, `DETAIL_LIMIT`, `BAD_HEAD` (looks like a head but date/amount
invalid). `ParseReport.suspicious` lists lines that contain both a date and an amount but did not
become a head – the most likely missed bookings. This replaces the budgets `--debug` log with
data the GUI and CLI can show.

## CSV import

`sniff_table(raw: bytes) -> CsvTable` (encoding + delimiter), `find_header(rows)`,
`guess_mapping(header) -> ColumnMapping` (`CsvField` → column index), and
`parse_rows(rows, mapping, source) -> ParsedStatement`. `read_csv(path)` is the thin I/O wrapper.
Missing date/amount column → `CsvMappingError`.

## Exceptions (`core/errors.py`)

`IaahError` → `StatementParseError`, `CsvMappingError`, `CategoryError` (2b), `StorageError` (2d).

## Tests

* `test_text.py`: normalization (umlauts → ae/oe/ue, ß, accents, whitespace), amounts
  (`-1.234,56`, `1.234,56 €`, English format in CSV), dates, euro formatting.
* `test_layout.py`: ported budgets cases (vertical clustering, rotated words, column
  containment, gap, detail limit, lines before the first booking) – each now also asserting the
  diagnosed `LineStatus`.
* `test_ing.py`: synthetic pages → transactions, booking-type split, valuta stripping, metadata,
  reconciliation, noise lines, suspicious-line detection.
* `test_csv_import.py`: German/English amounts, header detection, auto mapping, mapping errors.
* `test_sample_statement.py` (skipped unless `IAAH_SAMPLE_PDF` is set): 48 bookings,
  sum 1 288,32 €, reconciles, every booking has a placement, no suspicious lines.
