# Review – Step 2a (models, text helpers, parsing)

Independent review against `AGENTS.md` and `docs/design/02a-models-parsing.md`. 15 findings
(1 high, 5 medium, 9 low). The reviewer also confirmed on the real statement: 48 bookings,
correct total, reconciles, payees and types identical to the legacy parser – and that the new
parser fixes two legacy bugs (legacy glued the next page's "Valuta" header into 4 bookings and
≈ 3 900 characters of page footer into one booking).

After revision: 132 tests green (incl. the real-statement regression), ruff, ruff format and
mypy clean; assignment keys still identical to the legacy parser on the real statement.

| # | Sev. | Finding | Disposition |
|---|---|---|---|
| 1 | high | Unreadable booking line silently merged into the previous booking; `BAD_HEAD` from the design missing. | **Fixed.** Layout takes a `LineClassifier`; `BAD_HEAD` closes the open booking and is reported (`has_problems`). First attempt ("date + booking type") was wrong – it cut off purpose lines like `01.03.2026 Gehalt März`; caught by tests. Final rule: date in front + unreadable amount-like end. A head with no amount at all stays undetectable (documented). |
| 2 | med | CSV column matching picks wrong columns (Sparkasse amount → "Lastschrift Ursprungsbetrag"; one column for two fields). | **Fixed.** Match quality exact → word start → substring, ties by keyword priority; a column is never assigned twice. Sparkasse and DKB header tests added. |
| 3 | med | Header accepted only if the very next row parses. | **Fixed.** Any of the next 5 rows may hold the first booking (test with a pending booking). |
| 4 | med | `"2.000 €"` read as 2.000; `"1e5"` accepted. | **Fixed.** `DecimalStyle` detected per column; strict layouts per style, no exponents. |
| 5 | low/med | Delimiter by raw character count. | **Fixed.** Delimiter with the most rows sharing one column count ≥ 2. |
| 6 | med | Booking continuing on the next page is cut off. | **Fixed.** One builder over all pages; after a page break the first text line skips the gap rule; `Placement.details` is per page. |
| 7 | low | Greedy IBAN regex swallows `BIC …`. | **Fixed.** Groups are joined while the result passes the ISO 13616 mod-97 check. |
| 8 | low | Booking types matched without word boundary; unknown types differ from design. | **Fixed** boundary + `Gutschrift/Dauerauftrag`. First-word fallback **kept** (keys) and the design updated. Legacy payees `/Dauerauftrag …` (3 real bookings) are re-split during migration – noted in the 2d design. |
| 9 | low | Bare value-date line stays in the purpose. | **Fixed** (`(?:\s+|$)`, empty parts dropped). |
| 10 | low | Broken umlaut (U+FFFD) not repaired for keys/matching. | **Fixed.** `normalize_text` applies the known-word repair first. |
| 11 | med | No tests for `key`, `search_text`, `month`, `reconciles is False`, IBAN fallback, page continuation, malformed head, real bank headers. | **Fixed.** `test_models.py` pins the key string; all listed cases now tested. |
| 12 | low | Deviations from design; no single CSV file wrapper; skipped rows only counted. | **Fixed.** Design updated; `read_csv(path)`; `skipped_rows` holds indexes. |
| 13 | low | Magic strings in `text.py`; missing ported-code header in `ing.py`. | **Fixed** (named separators, translation table, header added). `" ".join(...)` kept – idiomatic, not a magic value. |
| 14 | low | Architecture test skips relative imports. | **Fixed.** Relative imports banned (`TID252`, `ban-relative-imports = "all"`) and checked by `test_no_relative_imports`. |
| 15 | low | Detail limit checked before column/gap → misleading status. | **Fixed.** Order now: column, gap, limit (test added). |

## Second round (revised code only)

The reviewer verified first-round fixes #1, #2, #4, #6, #7, #8, #10 with the original
reproducers and found five new issues – one a real regression on the reference statement that
no test caught.

After revision: 148 tests green, ruff/format/mypy clean; on the reference statement 48 bookings,
keys identical to the legacy parser, no booking spans pages, no problems, reconciles.

| # | Sev. | Finding | Disposition |
|---|---|---|---|
| R1 | med | Page-spanning builder: the last booking stayed open after "Neuer Saldo", so three lines of the next page's customer information became its purpose (invisible in diagnostics). | **Fixed.** New `LineKind.END` ("Neuer Saldo") closes the booking list; "Kunden-Information" added to noise. Regression tests: synthetic last page + `test_sample_statement` asserts every booking stays on one page. |
| R2 | low/med | `HEAD_SHAPE` matched value-dated purpose lines ("01.07.2026 Zinssatz 3,5" → bad head; "… Miete 450,00" → phantom head). | **Fixed with geometry.** Classifier receives the `Line`; heads must reach the amount column (x1 ≥ 540 pt, measured 552.6–552.8 for all 48 heads). |
| R3 | low | Generic keywords beat specific ones ("buchung" → Buchungstext, "wert" → Wertstellung). | **Fixed.** Whole-word matching for generic keywords; ranking by keyword specificity first (first attempt kept quality-first and let "Umsatzart" beat "Buchungsbetrag" – caught by the new test). |
| R4 | low | Two balance lines in a preamble made "," look like the delimiter. | **Fixed.** Delimiters tried by consistency; first one with a findable header wins. |
| R5 | low | "2,000" (English thousands) parsed as 2.000; "-12-" accepted; unnamed `"+-"`. | **Fixed.** Max two decimals, thousands-only columns decided by grouping, sign on one side only, literal removed. Also repaired "F�r". |
