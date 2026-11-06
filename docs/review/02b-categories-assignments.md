# Review – Step 2b (categories, assignments, suggestions)

Independent review against `AGENTS.md` and `docs/design/02b-categories-assignments.md`.
12 findings (1 high, 6 medium, 5 low), all reproduced by the reviewer with scratch scripts or
the reference statement.

After revision: 261 tests green, ruff/format/mypy clean. The real budgets file
(`budgets-master/data/categories.json`, invalid JSON) now loads (8 categories, 20 keywords).
On the reference statement every suggested keyword matches its own booking, no card payment
suggests its city and all 12 PayPal bookings yield a merchant. (A timing of 0.12 s claimed here
was measured on copies of identical bookings; realistic numbers are in the second round.)

| # | Sev. | Finding | Disposition |
|---|---|---|---|
| 1 | high | budgets files not importable: trailing commas in its JSON; its CSV format (`name,keywords,excluded`, `,` + `;`) unrecognised. | **Fixed.** Strict JSON first, retry without trailing commas; CSV dialect detected from the header, `excluded` mapped to `IGNORED`. Tests use the real file's shape. |
| 2 | med | Raw exceptions escape (cp1252 CSV → `UnicodeDecodeError`; wrong field types → `TypeError`; `"NaN"` budget → `InvalidOperation`; `"keywords":"rewe"` split into letters). | **Fixed.** Shared `text.decode_text` / `TEXT_ENCODINGS` (also used by the CSV import); keyword lists type-checked; budgets must be finite and whole cents; everything surfaces as `CategoryFileError`. |
| 3 | med | Candidates not always matching their booking: ASCII tokens vs. Unicode `isalnum`; `normalize_text` not idempotent (`F�R`). | **Fixed.** One Unicode token definition; normalization lower-cases before the repair (case-insensitive) – idempotence tested. |
| 4 | med | Weak candidates on real data: cut-off PayPal merchants, cities from card payments, missing generic words. | **Fixed.** PayPal merchant from the first copy, second copy as fallback; card-payment city (incl. cut-short forms) excluded; more generic words. The spaces inside words come from the PDF's glyph spacing itself (visible in the rendered statement) – not a parser bug; noted as a limitation. |
| 5 | med | Income keywords match outgoing payments ("lohn" → Lohnsteuer); over-broad defaults ("strom", "depot", "otto"). | **Fixed.** Keywords of income categories only match money coming in; defaults made specific. |
| 6 | med | Rename not consistent across catalog and assignments (whitespace; split parts duplicated). | **Fixed.** `Categorizer.rename_category` / `remove_category` change both with the catalog's canonical name; split parts that collapse merge; names looked up trimmed. |
| 7 | med | `suggest_keywords` 3.3 s on 5 000 bookings. | **Fixed.** Search texts computed once per call; only bookings containing the keyword are re-resolved (exact also for moved keywords). The "27× faster" measured here was on copies of identical bookings and did not hold – see S-perf below. |
| 8 | low | Redundant manual entries remain after adding a keyword; no atomic `move_keyword`. | **Fixed.** `Categorizer.prune_redundant`; `CategoryCatalog.move_keyword` (one commit). |
| 9 | low | `match` does not normalize; punctuation-only keywords; no reordering. | **Fixed.** `match` normalizes; keywords need a letter or digit; `CategoryCatalog.move`. |
| 10 | low | CSV keyword with `|`; English budget rejected; silent kind switch of an excluded fallback; sub-cent split parts. | **Fixed.** Export rejects separator in keywords; budget German then English; warning logged; parts must be whole cents. |
| 11 | low | Missing ported-code header (palette); unannotated `logger`; literal encodings. | **Fixed.** |
| 12 | low | Tests passing for the wrong reason / gaps (tie order, non-ASCII, real budgets shape, encodings, field types, stale splits). | **Fixed.** Tie order tested in both directions; non-ASCII, PayPal fallback and city cases; budgets JSON/CSV shapes; cp1252; invalid budgets tested on an otherwise valid file (the first version would have failed on missing fallbacks instead). |

## Second round (revised code only)

The reviewer confirmed that no assignment key changed (48 statement bookings, 48 legacy-parser
payees, 329 legacy `data.json` payees, 51 legacy overrides) and verified first-round fixes
#1, #3, #5, #8, #9, #10, #12; #2, #6 and #7 were only partly done. It also corrected the
performance claim above: on realistically shaped data `suggest_keywords` took 0.45–0.92 s,
because the same texts were normalized again and again.

After revision: 319 tests green, ruff/format/mypy clean. Measured with 5 040 *distinct*
bookings (so the cache cannot help): resolving all takes 0.80 s cold, 0.21 s warm;
`suggest_keywords` 0.07 s median, 0.14 s worst.

| # | Sev. | Finding | Disposition |
|---|---|---|---|
| S1 | med | Lower-casing before NFKD made 655 code points non-idempotent ("Shop™" → `shopTM`); a candidate then showed 0 matches on its own booking. | **Fixed.** Lower case again after decomposition; ™, №, black-letter H in the idempotence test. |
| S2 | med | `assign`/`split` stored untrimmed names → decisions lost on rename, orphans on remove. | **Fixed.** Decisions store the catalog's name; test covers assign, rename, keyword case, split. |
| S3 | med | Huge budgets (`1E+30`) / NaN split parts raised raw `InvalidOperation`. | **Fixed.** `text.is_whole_cents` (finite, representable, whole cents) used for budgets and split parts. |
| S4 | low | Preview `matches` ignored the income-only rule. | **Fixed.** Income keywords count money coming in only. |
| S5 | low | budgets CSV stricter than budgets JSON (duplicate or punctuation-only keywords). | **Fixed.** Same lenient path (`_unclaimed`) for budgets CSV. |
| S6 | low | CSV layout chosen by delimiter; trailing-comma repair edited strings; `[null]` became "none". | **Fixed.** Layout from the header columns (own file re-saved with commas keeps `|`); string-aware comma repair; keyword lists must contain strings. |
| S7 | low | `prune_redundant` deleted decisions irrecoverably and scanned everything. | **Fixed.** Returns the dropped decisions (`ManualAssignments.restore` for undo); optional `keyword` limits the scan. |
| – | perf | Repeated normalization of identical texts. | **Fixed.** `normalize_text` is memoized (`lru_cache`, 65 536 entries). |
