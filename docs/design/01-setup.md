# Step 1 – Project setup

## Goal

Turn the repository into an installable, linted, type-checked Python package so the
following steps (core, charts/export/CLI, GUI) land in a clean structure. The legacy app
(`kontoanalyse.py`, `parser.py`, `highlight.py`) keeps working until step 5 removes it.

## Decisions

| Topic | Decision | Why |
|---|---|---|
| Package | `iaah` in `src/` layout | src layout prevents accidentally importing from the working tree instead of the installed package. |
| Python | `requires-python >= 3.12`, developed on 3.14 | Matches the review (3.12 in use); 3.14 is the current stable line with wheels for all deps. |
| Version | `4.0.0` | The legacy README already counted versions 2 and 3. |
| Dependencies | all hard dependencies (pdfplumber, pypdf, reportlab, Pillow, matplotlib, openpyxl, cryptography, platformdirs) | Every feature ships; removes all function-level optional imports. |
| Dev tooling | pytest, ruff (lint + format), mypy `--strict` | Enforces the style rules from `AGENTS.md` mechanically instead of by review only. |
| Entry points | `iaah` (GUI script), `iaah-cli` (console), `python -m iaah` | Replaces `Start.bat`; `.exe` build becomes a documented PyInstaller command. |
| Agent/human guide | `AGENTS.md`, `CLAUDE.md` imports it | One source of truth for setup and code style. |
| Third-party code | `LICENSES/budgets-MIT.txt` | BRA (budgets) is MIT; ported code must keep its notice. |
| Personal data | untrack `settings.json` | Still tracked despite `.gitignore`; history cleanup is a separate user decision. |

## Ruff rule selection

`E W F I UP B SIM RET C90 N ANN PL PTH RUF ERA T20`, with
`max-complexity = 8`, `max-branches = 10`, `max-statements = 30`, `max-args = 6`.
`PLR2004` (magic values) and `PLC0415` (imports inside functions) stay enabled on purpose.
Tests relax `PLR2004`, `ANN`; the CLI may `print` (`T201`).
Legacy files are excluded until they are deleted in step 5.

## Tests in this step

`tests/test_package.py`: the package imports and exposes `__version__`.
