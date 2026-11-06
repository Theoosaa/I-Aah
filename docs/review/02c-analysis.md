# Review – Step 2c (analysis, merchants)

Independent review against `AGENTS.md` and `docs/design/02c-analysis.md`. 12 findings
(1 high, 5 medium, 6 low); the high one and several medium ones were found on the real legacy
data (`data.json`, read in memory only).

After revision: 344 tests green (incl. `tests/test_analysis_review.py` with one regression test
per finding), ruff/format/mypy clean. On the legacy data: 45 of 55 PayPal bookings yield their
merchant – the other 10 carry no merchant name at all (PayPal left both places empty) and are
grouped as "PayPal"; no "ihreinkaufbei" keyword is suggested any more; the longest of the top-12
merchant labels has 46 characters (was 115); 8 fixed costs detected, 2 of them flagged as
stopped.

| # | Sev. | Finding | Disposition |
|---|---|---|---|
| 1 | high | Legacy PayPal purposes are glued ("…/.netflix.com,ihreinkaufbei Netflix.com"): 0 of 55 matched; labels of 84–115 characters with mandate numbers; "ihreinkaufbei…" suggested as keyword. | **Fixed.** PayPal patterns tolerate missing spaces; the raw purpose is never used as merchant (falls back to the payee). Test with glued text. Also affected step 2b's suggestions – fixed there by the shared module. |
| 2 | med | Card payee without usable words fell back to the purpose; dropping every word with a digit merged "O2 GmbH" and "3M GmbH". | **Fixed.** Purpose only for PayPal-style merchants; only pure numbers dropped; label built from the same words as the key. |
| 3 | med | Fixed costs counted split parts, not bookings – a split rent was no longer detected (legacy regression). | **Fixed.** `ledger.bookings` regroups parts by booking (identity, so twin bookings stay two); recurring works per booking. |
| 4 | med | A payment last booked months ago still announced a "next booking". | **Fixed.** `RecurringPayment.active` / `last_month`, `RecurringReport.last_month`; stopped payments have no `next_month` and sort last. |
| 5 | med | Comparison order of ties depended on hash seeds. | **Fixed.** Sorted by (−current, −previous, name). |
| 6 | med | Missing for step 3: KPI deltas incl. "no previous period" and savings-rate points; period-filterable balance inputs; calendar per selected period; day drill-down; merchant drill-down adding up to the bar; gross vs. net in fixed/variable. | **Fixed:** `kpi_changes` (`None` without previous bookings, rate delta in points), `transactions_of`, `statements_in_period`, `calendar_grid(daily, bounds)` + `Period.bounds()` + `CalendarGrid.day_at`, `entries_of_day`, expense-only `entries_of_merchant`; gross amounts documented in `recurring.py`. |
| 7 | low | Sankey parts did not add up with refunds. | **Fixed.** `saved = income − Σ outflows` (≥ 0). |
| 8 | low | Stacked months could be negative. | **Fixed.** Clamped to zero, documented on `MonthlySeries`. |
| 9 | low | Balance points re-sorted across statements; a booking before the period start came before its own opening point. | **Fixed.** Statement order kept; a statement starts at min(period start, first booking). |
| 10 | low | `months=0` gave limit 0 and level OK; ratio computed twice. | **Fixed.** At least one month; `ratio` is a field. |
| 11 | low | `ZERO` defined three times; magic `- 2`; unused `counted()`; `Period` unvalidated, non-ASCII digits accepted; undocumented deviations. | **Fixed.** One `ZERO` in `ledger`; month index helpers; `counted` removed; `Period.__post_init__` validates; `re.ASCII`; design note updated. `Period` keeps `0` for unused fields (simpler than `None`, now validated). |
| 12 | low | Test gaps (all of the above, bookings-per-month rule, variation boundary, two-month detection, multiple accounts, balance without bookings, income in cash flow, year boundary in calendar). | **Fixed** in `test_analysis_review.py`. One of my own new tests was wrong (February 2026 needs 5 week columns, not 4) – the code was right. |

## Second round (revised code only)

The reviewer verified first-round fixes 2–12 (active/stopped payments across a year boundary
and for past-year views, calendar with bounds, all 688 keyword candidates on the legacy data
matching their own booking) and found that fix 1 held only partly and fixes 3 and 6 only while
entries keep their original order.

After revision: 350 tests green, ruff/format/mypy clean. Legacy PayPal labels: at most 41
characters, none with reference digits; 11 bookings without a merchant are grouped as "PayPal".

| # | Sev. | Finding | Disposition |
|---|---|---|---|
| R1 | med | PayPal merchant ran to the end of the purpose or started with "mandat:"; monthly reference numbers split one subscription into several merchants (never recurring). | **Fixed.** The merchant ends before `mandat:`/`referenz:` and may not start with them; tests for empty merchants and a monthly-changing reference. |
| R2 | low | Purpose patterns also applied to Klarna/card payments ("… bei Reklamation"); PayPal without merchant lost the word "PayPal". | **Fixed.** Purpose parsed for PayPal only; without a usable name the full payee is key and label. |
| R3 | med | `bookings()` relied on consecutive parts – sorting the entries broke fixed costs and balances. | **Fixed.** Grouped by transaction identity in a dict (order of first appearance); test with entries sorted by category. |
| R4 | med | Balance of a period lost bookings dated before their statement's period when fed date-filtered transactions. | **Documented and tested:** `account_balances` takes all transactions and selects through `statements_in_period`; test with a booking on 31 Dec in a January statement. |
| R5 | low | Magic numbers `max(months, 1)`, `date(…, 1)`. | **Fixed** (`MIN_BUDGET_MONTHS`, `FIRST_DAY`). |
