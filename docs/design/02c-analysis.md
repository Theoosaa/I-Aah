# Step 2c – Analysis

## Goal

All numbers behind the evaluation tab, the budget tab and the exports are computed here as
pure functions on `Decimal`. In the legacy app this logic lived inside the chart methods
(float arithmetic, numpy, Tk colors mixed in); charts in step 3 only *draw* these results.

## Input: entries

```python
@dataclass(frozen=True, slots=True)
class Entry:                     # one categorized part of a booking (a split yields several)
    transaction: Transaction
    category: str
    kind: CategoryKind
    amount: Decimal              # signed like the booking

build_entries(transactions, categorizer) -> list[Entry]
```

Every analysis function takes `Sequence[Entry]` (plus a `Period` where relevant), so
categorization happens exactly once per refresh and analysis never touches the catalog.

## Semantics (one definition, used everywhere)

* `IGNORED` entries never count – not as income, expense, payee, or day.
* **Income** = sum of `INCOME` entries; **expense** = minus the sum of `EXPENSE` entries.
  Both are *net*: a refund (positive amount in an expense category) lowers that category's
  spending instead of counting as income – as in the legacy app. Deliberate change: a negative
  amount manually put into an income category now lowers income instead of being counted as
  expense, so every category is one net figure.
* **Savings rate** = net / income, `None` if income ≤ 0.

## Periods

```python
class PeriodKind(StrEnum): ALL, YEAR, MONTH
@dataclass(frozen=True, slots=True)
class Period:
    kind: PeriodKind; year: int | None = None; month: int | None = None
    parse(text) / contains(day) / previous() / __str__   # "", "2026", "2026-07"
```

## Functions

| Function | Result | Used by |
|---|---|---|
| `in_period(entries, period)` | entries | everything |
| `totals(entries)` | `Totals(income, expense, net, savings_rate)` | KPI tiles, report |
| `kpis(entries)` | `Kpis(totals, months, average_monthly_expense)` | KPI tiles |
| `change(current, previous)` | `Change(difference, percent \| None)` | KPI deltas |
| `monthly_cashflow(entries)` | `list[MonthFlow]` | overview chart |
| `expense_by_category(entries)` | `dict[str, Decimal]`, descending, > 0 | donut, Sankey, budgets |
| `category_comparison(current, previous, limit)` | `list[CategoryChange]` | comparison chart |
| `monthly_by_category(entries)` | `MonthlySeries(months, series)` | stacked chart, trend (top n) |
| `recurring_payments(entries)` | `RecurringReport` | fixed vs. variable chart |
| `top_payees(entries, limit)` | `list[PayeeTotal]` | top payees chart |
| `cumulative_flow(transactions)` | `list[BalancePoint]` | relative balance chart |
| `account_balances(statements, transactions)` | `dict[account, list[BalancePoint]]` | real balance chart |
| `money_flow(entries)` | `MoneyFlow(income, outflows, saved)` | Sankey |
| `daily_expenses(entries)` + `calendar_grid(daily)` | `CalendarGrid(start, weeks, cells)` | heatmap |
| `year_over_year(entries)` | `dict[int, list[Decimal \| None]]` (12 months) | year comparison |
| `budget_status(entries, catalog)` | `list[BudgetStatus(category, limit, spent, ratio, level)]` | budget tab/chart |
| `missing_months(months)` | `list[str]` | import warnings |

* **Recurring payments** keep the legacy rule, now with named constants: a payee counts as
  fixed cost if it appears in at least `min(3, months)` months, has at most 1.6 bookings per
  month and a coefficient of variation below 0.35. Next expected booking = last month + 1.
* **Budget levels:** ≤ 80 % `OK`, ≤ 100 % `WARNING`, above `OVER`; the limit is the monthly
  budget times the number of months in the period.
* **Calendar grid:** weeks start on Monday; days without spending inside the range are `0`,
  cells outside the range `None`.
* Drill-down helpers: `entries_of_category(entries, name)`, `entries_of_payee(entries, payee)`.

## Refinements before implementation

1. **A package instead of one module** – about 20 functions would make `analysis.py` long:
   `analysis/ledger.py` (entries, periods, month arithmetic, drill-down),
   `analysis/totals.py` (totals, KPIs, change, per-month and per-category figures, Sankey,
   year comparison, budgets), `analysis/timeline.py` (balances, calendar, missing months),
   `analysis/recurring.py` (fixed costs).
2. **Merchants instead of raw payees.** Top payees and fixed-cost detection group by merchant:
   all PayPal or VISA payments otherwise collapse into one "payee", and a Netflix subscription
   paid via PayPal is never recognised as recurring (a legacy blind spot). The merchant logic
   from `suggestions.py` moves to its own module `core/merchants.py` and serves both.
3. **Analysis stays catalog-free:** `budget_status` takes `budgets: Mapping[str, Decimal]`
   (built by the caller from the catalog), entries already carry the category kind.
4. **Real balance per statement:** bookings belong to a statement through `Transaction.source`
   (the legacy app matched account + month, which mixes statements of one month).
5. Ratios (savings rate, budget use, changes) are `Decimal` fractions (`0.25`); formatting as
   percent is the chart's job.

## Deviations during implementation

* `top_payees` became `top_merchants` (grouped by `merchants.merchant_key`); drill-down is
  `entries_of_merchant`. On the real legacy data, grouping by raw text split chains into one
  "merchant" per branch (107 merchants vs. 70 payees); `merchant_key` drops branch numbers and
  the card-payment city (87 merchants, one more fixed cost recognised). `merchant_label` shows
  the same grouping in the booking's own spelling.
* `daily_expenses` became `daily_spending` and is **gross** (refunds not subtracted): a refund
  day would otherwise show negative spending in the calendar.
* `suggestions.py` now uses `merchants.py`; the merchant logic exists once.

## Tests

`test_analysis.py` with a small hand-built ledger (two months, income, expenses, a refund, a
split, an ignored transfer): totals and savings rate, period parsing/previous/contains,
per-month cashflow, category comparison, recurring detection (positive and negative cases),
budget levels at the thresholds, calendar grid shape, year-over-year gaps, missing months,
real balance per account from statement opening balances.
