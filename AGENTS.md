# AGENTS.md – I-Aah

Guide for coding agents **and** humans working on this repository: how to set it up,
how it is structured, and how code here is written. Keep it short and current – if a
rule changes, change it here first.

## What this is

I-Aah reads German bank statements (ING-DiBa PDF, generic CSV exports), assigns every
booking to a category via keyword lists, lets the user review and correct that in a
Tkinter GUI, and analyses spending over months and years (charts, budgets, exports).
It merges two earlier tools: the legacy single-file I-Aah app (`kontoanalyse.py`, removed; its
data files are read by `core/migration.py`) and *budgets* (MIT, see `LICENSES/`). I-Aah itself
is MIT-licensed (`LICENSE`).

**Status:** the unification is complete; design and review notes of every step are in `docs/`.
Entry points: `iaah` / `python -m iaah` (GUI) and `iaah-cli`.

## Setup

Requires Python ≥ 3.12 (3.14 is the reference). On Linux install Tk first
(`sudo apt install python3-tk`).

```powershell
py -3.14 -m venv .venv
.venv\Scripts\Activate.ps1        # cmd: .venv\Scripts\activate.bat · Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
```

| Task | Command |
|---|---|
| Start the GUI | `iaah` (or `python -m iaah`) |
| Command line | `iaah-cli --help` |
| Tests | `pytest` |
| Lint / format | `ruff check .` and `ruff format .` |
| Types | `mypy` (checks `src/` and `tests/`) |
| Windows `.exe` | `pip install -e ".[build]"`; the PyInstaller command is documented in the README |

Before calling any change done: `pytest`, `ruff check .`, `ruff format --check .` and
`mypy` must all pass.

## Layout

| Path | Contents |
|---|---|
| `src/iaah/core/` | Pure domain logic: models, parsing, categories, assignments, analysis, library, storage. |
| `src/iaah/charts/` | matplotlib figure builders: prepared data in, `Figure` out. |
| `src/iaah/export/` | File exports: marked PDF, CSV/Excel, summary, PDF report. |
| `src/iaah/gui/` | Tkinter application; `gui/app.py` holds `main()`. |
| `src/iaah/cli.py` | `iaah-cli` entry point. |
| `src/iaah/__main__.py` | `python -m iaah` → GUI. |
| `src/iaah/data/` | Bundled data files (default category catalog). |
| `tests/` | pytest suite for everything below the GUI; `tests/conftest.py` builds the synthetic data. |
| `docs/design/`, `docs/review/` | Design notes and review findings per implementation step. |

## Architecture rules

1. **Dependencies point downward:**
   `gui`, `cli` → `export` → `charts` → `core`, and `export` → `core`.
   `core` imports neither tkinter, matplotlib nor Pillow; `charts` and `export` never import
   tkinter. `tests/test_architecture.py` enforces this.
2. **The GUI holds no business logic.** Widgets display and forward events. GUI state that
   is worth testing (selection, undo, filters, rows, before/after) lives in `gui/session.py`
   and `gui/viewmodel.py`, which do not import tkinter. Tabs talk to the window only through
   the `Host` protocol (`gui/host.py`).
3. **One parsing path.** The parser yields transactions with page number and bounding box;
   PDF view, marked-PDF export and diagnostics all reuse that result.
4. **Categories are keyword lists.** `CategoryCatalog` is the single source of truth and
   answers both directions: category → keywords and keyword → category. Never look
   things up by list index.
5. **Personal data never lives in the working tree.** Library, categories and UI state are
   stored in the user data directory (`platformdirs`, override with `IAAH_HOME`).
6. **Errors:** `core` raises typed exceptions; GUI and CLI turn them into German messages.

## Language

- Code, identifiers, comments, docstrings, design/review docs and commit messages: **English**.
- Text the user reads is **German**. It lives in `gui/`, `cli.py`, `charts/` (titles,
  captions) and `export/` (column headers, report text).
- `core` contains no UI text. German *data* is fine there as named `Final` constants
  (bank keywords such as booking types, CSV header keywords); default category names live in
  `src/iaah/data/default_categories.json`.
- `README.md` is the German user manual.

## Code style

Enforced by tooling (ruff, mypy `--strict`, `tests/test_architecture.py`):

- Type hints on every function signature and class attribute; mypy strict passes for
  `src/` and `tests/`.
- Complexity ≤ 8, ≤ 10 branches, ≤ 30 statements, ≤ 6 arguments per function.
- No magic values in comparisons (numbers, strings, bytes).
- **Imports at the top of the module only**, sorted. No imports inside functions.
- No blind `except Exception`; `pathlib.Path` instead of `os.path`; every module and package
  has a docstring.

Checked in review (no reliable tool support):

- Module-level globals are annotated; constants are `Final`.
- No magic numbers or strings anywhere else either (arithmetic, sizes, keys): name them as
  `Final` constants at the top of the module.
- **Short functions with one job** (prefer ~20 lines) and **early returns** instead of
  `if/else` pyramids; at most three levels of nesting.
- Python ≥ 3.12 syntax: `X | None`, built-in generics, `type` aliases.
- Data containers are `@dataclass(slots=True)`, `frozen=True` where nothing mutates.
- Keep I/O at the edges: a pure `parse_*`/`render_*` function plus a thin `read_*`/`write_*`
  wrapper, so the logic is testable with plain strings, bytes and dicts.
- `logging` instead of `print` (the CLI may print its output).
- Docstrings say *why* and *what*, not *how*.
- No numpy in our code: aggregation happens in `core.analysis` with plain Python; matplotlib
  accepts lists.

### Money

- Amounts are `decimal.Decimal`, never `float`.
- JSON stores them as decimal strings (`"-1056.12"`); parse them back with `Decimal(str)`.
- Chart functions accept `Decimal` and convert to `float` internally – nowhere else.

### GUI code

- One builder method per widget group; a blank line between logical blocks.
- Layout with `grid` and weights or `pack` – no hand-computed pixel positions.
- Paddings, fonts and colors come from `gui/theme.py`; category colors only from the catalog.
- Aggregation and formatting of data belongs to `core`, not to widget code.

### Charts

- A chart function takes prepared data plus a `ChartTheme` and returns a `Chart` (figure plus
  clickable drill targets); it never reads application state. GUI and report build charts only
  through `charts.gallery.build_chart`. Figures come from `matplotlib.figure.Figure` (never
  pyplot), are drawn inside `style.themed(theme)` and use constrained layout. Every chart kind
  has a German title and a caption explaining what it shows and over which period.

## Tests

- pytest covers `core`, `charts` (Agg backend), `export`, the CLI and the display-free GUI
  state (`gui/session.py`, `gui/viewmodel.py`). `tests/test_gui_smoke.py` builds the real
  window and skips without a display; everything else in the GUI is verified by running it.
- Tests are typed like production code; only magic values are allowed in assertions.
- Warnings are errors (`filterwarnings = error`); silence a third-party warning explicitly
  and narrowly in `pyproject.toml` if needed.
- Fixtures are synthetic (pdfplumber-style word dicts, small CSV strings, an ING-like PDF built
  with reportlab) and live in `tests/conftest.py`. **Never commit real statements or personal
  data.**
- Optional regression against a real statement: set `IAAH_SAMPLE_PDF` to its path.
- New behaviour comes with a test; the suite stays green.

## Ported code

Modules that contain code adapted from *budgets* carry a header line
`# Portions adapted from budgets (MIT, © 2026 nikluep) – see LICENSES/budgets-MIT.txt`.
The license files ship with every build (`license-files` in `pyproject.toml`).

## Workflow

Each larger change runs through four phases:

1. **Design** – note modules, public API, data flow and test cases in `docs/design/`.
2. **Implement** – code and tests following this guide.
3. **Review** – independent review against this guide; findings go to `docs/review/`.
4. **Revise** – fix or explicitly reject each finding, then re-run all checks.

## Git

- Conventional Commits in English: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`.
- Never commit statements, bank exports, `library.json`, personal `categories.json` or
  `ui_state.json` (`.gitignore` covers them; synthetic fixtures are the exception).
