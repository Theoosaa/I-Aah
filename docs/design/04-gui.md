# Step 4 – GUI

The Tkinter application on top of `core`, `charts` and `export`. It keeps every feature of the
legacy app (tabs, analysis, budgets, split, CSV import, password, dark mode) and adds budgets'
PDF review (page view with colored boxes, before/after) and the keyword workflow with preview.

## Principles

* **No business logic in widgets.** Everything that decides something – filters, selection,
  undo, what an assignment does, which keyword previews to show, KPI deltas, before/after –
  lives in `gui/session.py`, which imports no tkinter and is unit-tested. Widgets display rows
  the session prepares and forward events.
* **Every change is saved at once** (`DataStore.save`, atomic, optionally encrypted), as in the
  legacy app. Failures are reported, the session keeps working in memory.
* **One window, one data directory:** `InstanceLock` for the whole lifetime.
* German texts live in the GUI modules; `gui/texts.py` holds the error messages for core
  exceptions (shared with no one else – the CLI has its own).

## Modules

| Module | Contents |
|---|---|
| `gui/app.py` | `main()`: lock, open the store (password, damage, newer version, migration offer), build `App(tk.Tk)` – menu, tabs, status bar – and wire session events to widget refreshes. |
| `gui/session.py` | `Session` (no tkinter): workspace + store, filters, rows, selection, undo/redo, assign/split/clear, keyword suggestions, imports, category editing, period/KPI data, before/after state. |
| `gui/theme.py` | Light/dark palettes (legacy `THEMES`), fonts, paddings, ttk style setup, chart theme per palette, category row tints. |
| `gui/menu.py` | The menu bar (Datei, Bearbeiten, Kategorien, Ansicht, Datenschutz, Hilfe) and key bindings. |
| `gui/importer.py` | Background import: worker thread parses files and hashes them, the main thread polls a queue and applies results; progress dialog; CSV mapping fallback. |
| `gui/tabs/transactions.py` | Filter bar, booking table, detail panel with category buttons (1–9), split/automatic/next-open, inline keyword suggestions. |
| `gui/tabs/review.py` | PDF review (from budgets): statement picker, rendered page with colored boxes, click selects, before/after toggle, booking list, line diagnosis list. |
| `gui/tabs/analysis.py` | Period and chart selectors, KPI cards with deltas, embedded figure (`FigureCanvasTkAgg`), caption, drill-down on click. |
| `gui/tabs/budgets.py` | Budget per expense category with spent/limit/traffic light for the selected period. |
| `gui/tabs/categories.py` | Category list with color swatches; editor: name, color, kind, budget, keywords; add, delete, reorder; load/save category files. |
| `gui/dialogs/*.py` | password, split, CSV mapping, drill-down list, migration report, import summary. |
| `gui/widgets.py` | Small shared widgets: scrolled tree, color swatch, labeled entry. |

## Session (tested without a display)

```python
class Session:
    workspace: Workspace; store: DataStore
    filters: Filters                       # period, category, account, booking type, text, only_open
    def rows(self) -> list[Row]            # filtered, sorted; Row = index, texts, amount, category,
                                           #   color, marker (keyword/fallback/manual/split)
    def select(self, indexes) / selection -> list[int]
    def assign(self, category) -> Change   # all selected; undoable; returns what changed
    def split(self, index, parts) / clear(self, indexes)
    def next_open(self, after: int | None) -> int | None   # next fallback booking in the view
    def suggestions(self, index, category) -> list[KeywordPreview]
    def accept_keyword(self, keyword, category) -> Change  # move_keyword + prune_redundant
    def undo() / redo() -> bool            # snapshots of catalog + manual decisions
    def import_parsed(results) -> ImportSummary
    def kpi_cards(period) -> KpiCards; periods() -> list[Period]; chart_input(period)
    # category editing: add, rename, recolor, set_kind, set_budget, keywords, move, remove
```

* **Rows** are indexes into `library.transactions` (bookings are frozen values; two identical
  coffees are equal, so identity is the position). Imports only append or replace in place.
* **Undo** stores the catalog and the manual decisions before each change (both are small and
  copy cheaply); a redo stack is cleared by a new change. Imports and resets are not undoable
  (they ask first).
* **Open bookings** are those resolved by the fallback (`AssignmentSource.FALLBACK`) – the
  successor of the legacy "Nicht zugeordnet".
* **Keyword workflow:** after a manual assignment the detail panel lists
  `suggest_keywords(...)` – keyword, "trifft N Buchungen, ändert M", owner if it moves – each
  with an *Übernehmen* button. Nothing is stored without that click.

## Tabs

**Transaktionen** – filter bar (Zeitraum, Kategorie, Konto, Buchungsart, Suche, *nur offene*),
table (Datum, Buchungsart, Empfänger, Verwendungszweck, Betrag, Kategorie; tinted with the
category color; manual decisions marked ✎, splits ⑂), status line with count and sum of the
view. Right: *Ausgewählte Buchung* (full texts, how the category was decided – keyword,
fallback, manual, split), colored category buttons numbered 1–9 (keys 1–9 assign), buttons
*Aufteilen…*, *Automatisch*, *Nächste offene* (F3), keyword suggestions. Multi-selection
assigns all; Ctrl+Z / Ctrl+Y undo/redo. No inline editing in the table (the legacy double-click
combobox bug is gone by design).

**PDF-Prüfung** – statement picker (stored statements with an existing PDF path), page view
rendered with pdfplumber (pypdfium2) and PIL: each booking's regions in its category color;
*Vorher (automatisch)* / *Nachher (aktuell)* toggle; changed bookings outlined; click on a box
selects the booking (session hit test via `core.geometry`), the side list shows the bookings of
the statement and the category buttons; a second list shows the lines the parser did not use
with their reason (`ParseReport`), suspicious ones first. Page navigation, zoom (Ctrl+wheel).

**Auswertung** – period (Gesamt, years, months with data), chart (the 13 `TITLES`), KPI cards
(Einnahmen, Ausgaben, Netto, Sparquote, Ø Ausgaben/Monat) with deltas against the previous
period (green/red by direction), the figure, its caption, a hint when months are missing. Click
on a drill target opens the booking list (Datum, Empfänger, Zweck, Betrag, Kategorie, sum).

**Budgets** – one row per expense category: budget entry (monthly), spent in the selected
period, limit, percent and traffic-light color; *Speichern* validates and stores.

**Kategorien** – left the categories with swatches (order = matching priority irrelevant;
display order), right the editor: name, color (color chooser), kind (Ausgabe / Einnahme /
Ignoriert; fallbacks locked), monthly budget, keywords (add, edit, remove, conflicts named),
*Neue Kategorie*, *Löschen* (tells how many manual decisions go with it), move up/down.

## Menu

* **Datei:** Kontoauszüge importieren… (Ctrl+O, PDF/CSV, several) · Ordner importieren… ·
  CSV mit Spaltenzuordnung… · Exportieren ▸ (Buchungen als CSV… · Buchungen als Excel… ·
  Zusammenfassung als CSV… · Zusammenfassung als Text… · Markiertes Kontoauszug-PDF… · Report
  als PDF…) · Alte I-Aah-Daten übernehmen… · Bibliothek leeren… · Beenden.
  Every export entry names format and content; bookings exports use the current filter.
* **Bearbeiten:** Rückgängig · Wiederholen · Nächste offene Buchung · Automatische
  Zuordnung wiederherstellen (selection) · Überflüssige manuelle Zuordnungen entfernen.
* **Kategorien:** Neue Kategorie… · Kategorien laden… · Kategorien speichern unter…
* **Ansicht:** Dunkles Design · tabs Ctrl+1…5.
* **Datenschutz:** Passwort festlegen/ändern… · Passwort entfernen… · Beschädigte Kopien
  löschen… (only if there are any).
* **Hilfe:** Datenordner öffnen · Über I-Aah.

## Start-up

1. `InstanceLock` – a second instance shows a message and exits.
2. `DataStore` – password dialog while `needs_password()` (wrong → again; cancel → exit);
   `UnsupportedVersionError` → message, exit; `StorageError` without backup → offer to set
   the unreadable file aside and start empty (`DataStore.start_over()`, new in core: moves data
   file and backup to damaged copies) or exit; `recovered_from_backup` → info with the path of
   the damaged copy.
3. No data yet → offer *Alte I-Aah-Daten übernehmen* (legacy folder chooser; the working
   directory is preselected when it holds legacy files); encrypted legacy data asks for its
   password; the migration report is shown once.

## Import

`importer.py`: a worker thread runs `read_statement_file` + `file_sha256` per file and puts
results (or the error) on a queue; the main thread polls every 100 ms, updates a progress
dialog and applies results through the session (library changes only on the main thread).
Files already imported are recognised by hash before parsing. A CSV whose columns cannot be
detected opens the mapping dialog (header row, date/amount/payee/purpose columns, preview).
The summary names added, duplicates, enriched, already imported, files that do not reconcile,
files with suspicious lines, and months now missing in the library.

## Parity with the legacy app

A complete inventory of `kontoanalyse.py` was taken before implementing. Kept, with their
legacy texts where sensible:

* Window "I-Aah – Kontoanalyse", 1250×780, minimum 1000×640, ttk theme *clam*, Segoe UI 9,
  rows 24 px high.
* **Filters:** Zeitraum (was Monat), Kategorie, Suche (payee, purpose, booking type; live),
  Konto, Typ (Alle / Nur Ausgaben / Nur Einnahmen), Betrag von … bis … (absolute, live),
  *Filter zurücksetzen*, *Nächste offene ▶* (wraps around, "alles zugeordnet" when done).
* Column sorting by clicking a heading (now with ▲/▼); row tint with the category color (82 %
  towards white, 72 % towards the background in dark mode); status line "N Buchungen |
  Einnahmen X | Ausgaben Y | K offen" – for the *filtered* view (legacy: always all).
* Context menu: *Kategorie zuweisen ▸* (all + *Neue Kategorie…*), *Aufteilen…*, *Automatisch
  zuordnen*, *Stichwort vorschlagen…*. Keys 1–9 assign the n-th category (table focused),
  Ctrl+Z everywhere. *Neue Kategorie* from the transactions tab creates and assigns it.
* KPI cards as before: value colors (income green, expense red, net by sign), "Basis: N
  Monat(e)", deltas "▲/▼ N % ggü. Vorperiode" (savings rate in %-Pkt.), green when the change
  is good, none for *Gesamt*. Empty state text, caption with the drill hint, matplotlib
  navigation toolbar (save image, zoom).
* Drill-down window "Buchungen – {Auswahl} ({Zeitraum})" with Datum, Empfänger, Zweck, Betrag,
  Kategorie and "N Buchungen Summe: X" – sums now use the split *part* (legacy bug).
* Budgets: rows for expense categories, monthly budget entry (empty or 0 removes it), Ø actual
  per month, *Budgets speichern*.
* Categories: new (name + next free color, inline errors), color, delete (confirmation, names
  what goes with it), ignored on/off (now the kind), keywords instead of rules.
* Split dialog with live "Summe X / Buchung Y ✓ passt" or "⚠ Differenz Z", *Zeile +*; rows can
  now also be removed; validation from `validate_split`.
* CSV mapping dialog (Datum *, Betrag *, Empfänger, Verwendungszweck, preview); the header row
  can now be chosen.
* Folder import takes the folder's PDFs; several files run in the background with a progress
  window ("i/n: Datei"); one summary message after the import.
* Reset keeps categories and decisions and asks first. Password on/off as before (twice when
  setting; the current one when removing). UI state: geometry, theme, tab, period, chart
  (filters on accounts or categories are not stored – the UI state is unencrypted).

Changed on purpose: no inline combobox in the table (the double-click bug); double-click opens
the booking in the PDF review instead. No "Als Regel merken" with the whole payee – keyword
suggestions with preview replace it. Regex rules are gone (they crashed in the legacy app,
`re` was never imported). Cancelling the start-up password exits instead of running unlocked
with empty data (legacy could then overwrite the encrypted file).

## Changes during implementation

* The display-free part is two modules: `gui/session.py` (state, actions, undo, saving) and
  `gui/viewmodel.py` (pure functions: filters, rows, sorting, KPI cards, budget rows, review
  boxes and hit test, unused lines, decision and migration texts). The architecture test
  checks both for tkinter imports.
* `gui/host.py` – the `Host` protocol the tabs use (session, palette, run, new category, show
  in review, status) – so tabs never import the app.
* Menus and key bindings are builder methods of `App` (`gui/app.py`); `gui/menu.py` was not
  needed. Start-up dialogs and the legacy migration live in `gui/startup.py`, the export
  actions in `gui/exports.py`, German error texts in `gui/texts.py`.
* `DataStore.start_over()` (core) moves an unreadable data file and backup aside as damaged
  copies, so the app can start empty without deleting anything.
* The review tab assigns parsed bookings directly (`Session.assign_to`): decisions are stored
  by booking key, so a statement parsed again needs no mapping to library positions.
* Classic Tk widgets take the theme from the option database (so the matplotlib toolbar
  recolors its icons in dark mode); existing lists, texts and canvases are restyled when the
  theme changes.
* mypy: `disallow_untyped_calls` is off for `iaah.gui.*` only – typeshed leaves a few tkinter
  methods and matplotlib's Tk backend untyped.
* Split marker is `÷` (the planned `⑂` is missing in Segoe UI); found on the screenshots, as
  were column widths, button widths and dark-mode details.

## Revisions after review

Details in `docs/review/04-gui.md`. Changes to this note:

* **Start-up:** read errors are `DataUnreadableError` (core) → message and exit, nothing is set
  aside; only damage offers `start_over()`. The legacy offer appears only while
  `Session.is_pristine()`; the menu entry needs an empty library and confirms what it replaces.
  Dialogs are transient only for a visible owner (the password prompt comes before the window).
* **Import:** polling every 80 ms (legacy value); the progress window cannot be closed; the
  worker always sends its end marker, so an import always finishes.
* **Shortcuts** act only in the main window; Ctrl+Z/Ctrl+Y keep their own meaning in entry
  fields. Keys 1–9 also work on the PDF review.
* **Context menu:** *In der PDF-Prüfung zeigen* instead of *Stichwort vorschlagen…* – the
  suggestions are always visible in the side panel, for manual decisions only.
* **Datenschutz:** *Beschädigte Kopien löschen…* is always in the menu and says when there are
  none.
* No-op changes create no undo step; the category filter follows rename and removal; the
  status line counts split parts under a category filter; exports never overwrite an imported
  statement.

## Tests

`tests/test_gui_session.py`: filters, rows and markers, selection after refresh, assign (keyword
category clears, fallback confirmation stored), multi-assign, split, clear, next open, undo/redo
across assign and keyword acceptance, suggestions and acceptance with prune, KPI cards and
deltas, periods, category edits incl. rename/remove with decisions, import summaries, hit test
of the review page, saving after each change (into `tmp_path`). `test_architecture.py` gains:
`gui/session.py` imports no tkinter. The widgets are verified by running the app (screenshots of
every tab in light and dark, with the synthetic workspace) and by `tests/test_gui_smoke.py`
(real Tk, skipped without a display): start-up dialog on a hidden window, every tab in both
themes, importer worker.
