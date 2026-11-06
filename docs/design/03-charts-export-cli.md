# Step 3 – Charts, exports and `iaah-cli`

Everything above `core` that does not need Tk: the 13 charts of the legacy app as pure figure
builders, the file exports (marked statement PDF, bookings as CSV/Excel, category summary,
PDF report) and the command line. The GUI (step 4) only wires these up.

## Layering

```
cli ──► export ──► charts ──► core
  └────────────► core   export ──► core
```

`charts` and `export` never import tkinter; `tests/test_architecture.py` already enforces it.
German text (titles, captions, column headers, report and CLI output) lives in these layers.

## Charts (`src/iaah/charts/`)

| Module | Contents |
|---|---|
| `style.py` | `ChartTheme` (`LIGHT`, `DARK`), semantic colors (income, expense, net, fixed, variable, budget levels), `new_figure(theme, size)`, `month_label("2026-07") → "Jul 26"`, `empty_chart(message, theme)`. |
| `chart.py` | `ChartKind` (13 kinds), `TITLES`, `CAPTIONS`, `Chart(figure, targets)`, `DrillTarget(artist, kind, value)`, `DrillKind` (category, merchant, day). |
| `cashflow.py` | cash flow per month with savings rate, cumulative flow, real account balances, year over year. |
| `categories.py` | donut by category, comparison with the previous period, top-5 trend, stacked months, budget traffic light. |
| `flow.py` | Sankey: income → categories and savings. |
| `spending.py` | fixed vs. variable costs with the detected payments, top merchants, spending calendar. |
| `gallery.py` | `ChartInput` + `build_chart(kind, data, theme) -> Chart`: runs the `core.analysis` function a kind needs and calls its builder. GUI and report use only this. |

**Builders** take prepared data (results of `core.analysis`, category colors as
`Mapping[str, str]`) plus a `ChartTheme` and return a `Chart`. They never see the catalog, the
library or the GUI. Each one draws an explanatory text instead of an empty axis when its data is
insufficient (no spending, fewer than two months, no budgets, …).

**Figures without pyplot.** Builders create `matplotlib.figure.Figure` directly: no global
figure registry, no backend selection, so the same figure is embedded by the GUI
(`FigureCanvasTkAgg`) and saved by the report. The theme is applied by building inside
`matplotlib.rc_context(theme.rc)` – every artist picks up face, text, tick, spine and grid colors
at creation, replacing the legacy app's after-the-fact recoloring. Layout is constrained.

**Drill-down.** `Chart.targets` lists the clickable artists (donut wedges, stacked and budget
bars → category; merchant bars → merchant key; calendar cells → ISO date). The GUI hit-tests
with `artist.contains(event)` and calls `core.analysis.ledger.entries_of_*`.

**Money** stays `Decimal` up to the builder, which converts to `float` for matplotlib only. No
numpy: the calendar is one `Rectangle` per day (≤ 371), colored through a matplotlib colormap.

**Captions** say what a chart shows and over which period (AGENTS.md). Texts follow the
legacy captions, adjusted to the new semantics (refunds lower a category, ignored categories
never count, fixed costs grouped by merchant).

`ChartInput` (frozen):

| Field | Used by |
|---|---|
| `period: Period`, `entries` (of the period) | most charts |
| `previous: Period | None`, `previous_entries` | comparison |
| `all_entries` | year over year |
| `statements`, `transactions` (all, see `account_balances`) | real balance |
| `colors: Mapping[str, str]`, `budgets: Mapping[str, Decimal]` | category charts, budget |

Months of the period for the budget limit: the number of months the period spans that have
bookings, at least one – as in the legacy app.

## Exports (`src/iaah/export/`)

| Module | Contents |
|---|---|
| `marked_pdf.py` | Copy of a statement PDF with every booking underlaid in its category color, plus a legend page (ported from budgets' `highlighting.py`, legacy `highlight.py` retired in step 5). |
| `tables.py` | Bookings as CSV (`;`, decimal comma, UTF-8 with BOM – opens correctly in Excel) and as Excel workbook (real dates and numbers, euro format, frozen header, filter). |
| `summary.py` | Category summary (ported from budgets' `summary.py`, now `Decimal`): text and CSV, reading CSV summaries back, merging several. |
| `report.py` | PDF report: cover page with period, KPIs and missing months, then the report charts on A4 landscape pages. |

Every module follows the pure/thin-I/O split: `render_*`/`mark_*` return `str`/`bytes`/a
workbook; `write_*` add the file. Writes go to the path the user chose (no atomic write: these
are user exports, not the data file).

**Marked PDF.**

* `Mark(placement, stripes)`: one per booking with a placement. `Stripe(color, share)`; a
  normal booking has one stripe, a **split booking one per part**, proportional to the part
  amounts – the PDF shows the split instead of only its largest part.
* `marks_for(transactions, categorizer)` and `legend_for(...)` (category, color, number of
  bookings, sum) build them; `mark_pdf(pdf_bytes, marks, legend) -> bytes` draws them with
  reportlab under the original text (`merge_page(over=False)`, 40 % opacity) and appends the
  legend page(s). `write_marked_pdf(source, target, transactions, categorizer) -> MarkResult`.
* Box geometry (PDF points, top-left origin → reportlab's bottom-left) moves to
  `core/geometry.py` (`to_target_box`, ported from budgets' `transform_bbox`), so the PDF review
  tab of step 4 uses the same math.
* Regions on pages the PDF does not have are skipped and counted, never an error.

**Bookings table.** One row per `Entry` (a split booking yields one row per part):
Datum, Konto, Buchungsart, Empfänger, Verwendungszweck, Betrag, Kategorie, Art (Ausgabe,
Einnahme, Ignoriert). Text cells go through `clean_display`.

**Summary.** `Summary(expenses, income)` per category (net, positive, largest first; ignored
categories never count). Needs `income_by_category`, which joins `expense_by_category` in
`core.analysis.totals`. CSV columns as in budgets (`Typ;Kategorie;Betrag (EUR)`) so their files
merge with ours.

**Report.** `REPORT_CHARTS`: cash flow, categories, fixed costs, top merchants, real balance,
budget (only when budgets exist). `render_report(data: ChartInput) -> bytes` through
`PdfPages` on a `BytesIO`; always the light theme.

## Command line (`src/iaah/cli.py`, `iaah-cli`)

Stateless by default: files in, outputs out. German help and output, English option names.

| Command | Does |
|---|---|
| `check PDF…` | Per file: bookings, sum, balance check (ok / difference / not checkable), lines per status, every suspicious or unreadable line with page. `--lines` prints every line with its status. Exit code 1 if a file does not reconcile or has problems. |
| `summary FILE… [--period P] [--format text csv chart report] [--output-dir D]` | Reads PDFs and CSVs into one `Library` (de-duplicated like the app), categorizes, prints/writes the summary (`zusammenfassung.csv`, `ausgaben.png`, `report.pdf`). |
| `highlight PDF [-o OUT]` | Marked PDF, default `<name>_markiert.pdf` beside the source. |
| `merge CSV… [--format text csv chart] [--output-dir D]` | Merges summary CSVs (budgets' `merge`). |

Categories: `--categories FILE` (JSON/CSV, `category_io.load_catalog`) or `--library`, which
reads the app's data directory **read-only** (catalog *and* manual decisions; asks for the
password with `getpass` if the data is encrypted; never saves). `summary --library` without
files uses the stored bookings. Default: the bundled default catalog.

`main(argv: Sequence[str] | None = None) -> int` returns the exit code (0 ok, 1 problems found,
2 bad input). Core errors are caught as `IaahError` and printed in German. The console is
switched to UTF-8 where possible (budgets' `ensure_utf8_console`).

## Changes during implementation

* `ChartInput` holds only `period` and `all_entries` (plus statements, transactions, colors,
  budgets); the period's entries and the previous period are derived, so the GUI cannot pass
  inconsistent pairs. `ChartInput.of_workspace(workspace, period)` builds it.
* The fixed-cost bars are clickable too (merchant), and so are the Sankey bands (category).
* The calendar labels only months that begin inside the shown range.
* Pastel category colors always get dark labels, the saturated fixed/variable colors white
  ones – in both themes (found by rendering every chart light and dark).
* The bookings export defuses text that a spreadsheet would run as a formula (`=`, `+`, `-`,
  `@`): payee and purpose are written by the sender of a transfer.
* Summary CSVs are read with automatic decimal style, so budgets' `,`/`.` files merge too.
* matplotlib's stubs lack date support: `cashflow._dates` returns `Any` and `DateFormatter` is
  called with a narrow `type: ignore` – the only two exceptions to strict typing.
* The synthetic statement PDF is built in `tests/conftest.py` (fixtures `statement_pdf`,
  `build_statement_pdf`); `tests/fixtures/` was not needed.

## Revisions after review (see `docs/review/03-charts-export-cli.md`)

* `DataStore(read_only=True)` for `iaah-cli --library`: no lock (writes are atomic renames),
  nothing moved, tidied or saved. The CLI no longer takes the instance lock and works while
  the app runs.
* `export/files.py`: `ExportError`, `write_export`, `ensure_folder`, `figure_png` – every
  export writes through them, so GUI and CLI report write failures in German.
* `core.analysis.totals.category_totals(entries, kind)`: net per category including refund
  surpluses (negative); the summary uses it, so its totals equal the KPIs. The donut takes the
  same mapping and names refund surpluses below the ring.
* Charts never parse mathtext (`text.parse_math: False`) and cut long names (`style.short`);
  the Sankey chart shows at most 12 bands.
* Marked PDF: no media-box offset (pdfplumber coordinates are absolute), rotated pages are
  skipped, legend names made printable for the standard PDF font.
* CLI: German errors with file name, details with `-v`; a pattern without match and a PDF
  without bookings are errors.

## Tests

* `tests/conftest.py`: builds a synthetic ING-like statement PDF with reportlab
  (two pages, a booking whose purpose continues on page 2, opening/closing balance). Used by
  parser, marked-PDF and CLI tests – a real end-to-end path without personal data.
* `test_geometry.py`: box transform in both coordinate systems (from budgets).
* `test_charts.py`: every `ChartKind` builds from a synthetic `ChartInput` in both themes and
  saves as PNG; empty and insufficient data give a message chart; drill targets carry the
  expected values; every kind has title and caption; no builder mutates its input.
* `test_export_marked_pdf.py`: page count = source + legend; stripes per split part; legend
  lists categories with counts; bookings without placement or on missing pages are skipped.
* `test_export_tables.py`, `test_export_summary.py`, `test_export_report.py`: exact CSV text,
  workbook cells and formats, summary round trip and merge, report page count.
* `test_cli.py`: `main([...])` with the synthetic PDF and CSV files in `tmp_path`, checking
  output, exit codes and written files; `--library` against a temporary `IAAH_HOME`.
