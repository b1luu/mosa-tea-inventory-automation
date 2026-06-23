# Inventory variance — what it means and how to read it

The variance between **Square's automated inventory count** (driven by
per-order recipe-aware deductions) and the merchant's **physical recount**
is the truth-metric for this whole system. This doc explains what variance
signals, how to interpret patterns, and how it eventually feeds recipe
calibration and reorder-point logic.

## Definition

```
variance = square_count_before_recount - physical_count
```

Sign convention:

| variance sign | What it means |
|---|---|
| **Positive** (e.g., Square says 205, physical 191 → variance = +14) | Square thinks the merchant has *more* than they actually do. That gap is unaccounted consumption — staff drinks, samples, spillage, prep waste, shrinkage, or pre-system usage. **The common case.** |
| **Negative** (Square says 80, physical 92 → variance = -12) | Square thinks the merchant has *less* than they actually do. Usually means a restock wasn't entered in the sheet (cyan-highlighted "in" column missed), OR a recipe over-states actual usage (staff pours less than the recipe says), OR a voided/returned order that should have reversed didn't. |
| **Near zero** | Square + recipe + recount are aligned. System is working as designed. |

## Why variance per ingredient is more useful than overall variance

If TGY shows +13% variance and matcha shows +1%, that's a very different
story than every ingredient showing +7%. The per-ingredient breakdown tells
you whether the issue is:

- **Recipe-level** (one ingredient under-specified)
- **Drink-level** (multiple ingredients consistently off for drinks using
  them — staff portion control)
- **Shop-wide** (every ingredient drifts similarly — generic shrinkage /
  off-the-books usage)

The Variance Log (planned, see [Schema](#variance-log-schema-future)) records
the per-ingredient breakdown per recount session.

## The calibration ratio

For each ingredient over a window between two recounts:

```
predicted_consumption = sum over all orders in window:
    quantity_ordered × recipe_amount_per_drink_for_this_ingredient

actual_consumption = (square_count_at_prev_recount
                      + restocks_added_during_window)
                     - square_count_just_before_this_recount

calibration_ratio = actual_consumption / predicted_consumption
```

Healthy = ~1.0. Persistent deviations point to actionable issues:

| Calibration ratio | Interpretation |
|---|---|
| `1.00 ± 0.05` | System is honest. Recipe matches reality. |
| `1.05 – 1.15` | Normal operational overhead — small spillage, occasional staff drinks, minor sample-cup usage. Accept as a fixed multiplier in ROP. |
| `1.15 – 1.30` | Recipe likely under-states pour amount OR meaningful off-book usage. Worth investigating. |
| `> 1.30` | Either the recipe is significantly wrong, or there's a systemic operational problem (untracked catering, theft, equipment leak, expired stock dumped). |
| `< 0.95` | Restocks not logged, OR recipe over-states usage, OR refunds/voids handled wrong. |

## Disambiguating recipe-wrong from operational-overhead

Variance alone can't tell you which is which. But the **pattern across
multiple ingredients used in the same drinks** can.

**Example: TGY Special uses `tgy`, `non_dairy_creamer`, `hk_powder`,
`powdered_sugar`, `brown_sugar`.** If after 4 recounts the ratios look like:

| Ingredient | Avg ratio |
|---|---|
| `tgy` | 1.28 |
| `non_dairy_creamer` | 1.05 |
| `hk_powder` | 1.04 |
| `powdered_sugar` | 1.06 |
| `brown_sugar` | 1.05 |

→ Only `tgy` is consistently high. **The TGY ml-per-drink in the recipe is
probably under-specified** (true pour is ~300ml × 1.28 ≈ 385ml). Fix the
recipe.

Whereas if all five ingredients show ~1.13:

→ The DRINK as a whole over-consumes. Recipe is fine; the kitchen is using
~13% more per drink (spillage, generous pours, sample tasting). Either accept
the overhead or tighten ops.

## Variance pattern → operational meaning

The translation from numbers to actions:

| Pattern | Probable cause | Action |
|---|---|---|
| Consistent +5–10% across all ingredients | Normal shop overhead | Accept; factor into ROP buffer |
| +20%+ on one ingredient, normal on others | Recipe specifies less than actual usage | Update recipe; OR investigate why staff over-pours |
| +50%+ on a high-value ingredient (TGY, SSR, matcha) | Likely shop drinks / sample-cup leakage / prep waste | Conversation with staff; portion controls; possibly limit free samples |
| Negative on one ingredient | Restock not logged OR recipe over-pours | Audit restock entries; verify recipe is realistic |
| Variance grows month over month | Operational discipline is slipping | Operational review |
| Variance stable around a non-zero value | Predictable steady-state overhead | Bake the multiplier into reorder logic |
| Spiky variance — one recount way off, others normal | One-off event (catering, batch dumped, equipment failure) | Investigate that specific date; not a systemic issue |

## What variance enables downstream

Once a stable calibration ratio is established per ingredient, three
operational improvements unlock:

### Reorder Point (ROP)

```
ROP = (avg_predicted_daily × calibration_ratio × lead_time_days)
      + safety_stock_buffer
```

Without the calibration ratio, ROP under-estimates demand and causes
stockouts (especially painful for Taiwan-sourced items with 3-month lead
time).

### True consumption forecasting

"Selling 200 TGY drinks next month" → recipe alone says
`200 × 6.38g = 1276g dry leaf`. With a 1.13 calibration ratio:
`1276 × 1.13 = 1442g`. That extra 13% is what stops you from running out
mid-month.

### Cost per drink (eventual)

Includes ingredient cost × calibration ratio. The recipe-based cost
under-states reality if there's spillage; the calibrated cost is closer to
the truth.

## Variance log schema (future)

When the Apps Script variance log addition is implemented (designed in
chat, paused), it will append rows to a dedicated `Variance Log` tab on
the Inventory sheet:

| Col | Field | Example |
|---|---|---|
| A | Timestamp | `2026-06-23T14:32:18Z` |
| B | Recount Session | `2026-06-23T14:32:18Z` (same value for all rows in one sync) |
| C | Display Name | `鐵觀音 TGY` |
| D | Inventory Key | `tgy` |
| E | Counted Unit | `bag` |
| F | Square Before | `204.88` |
| G | Physical Count | `191` |
| H | Variance | `13.88` |
| I | Variance % | `6.78%` |
| J | Source Cell | `Sheet1!AN4` |

Append-only. One row per ingredient per recount session. After 3–4
recounts you have enough data for the per-ingredient calibration analysis
above.

## When NOT to act on variance

Some judgement calls:

- **First 1–2 recounts** post-go-live: don't read too much into variance.
  The recipe might be untested, the boss might still be calibrating
  pour amounts, and the data is too sparse for trends.
- **Items with very low daily consumption** (e.g., pistachio, sample_cup):
  variance percentages can swing wildly on small counts. Look at absolute
  variance, not %.
- **Right after a recipe change**: variance from before vs after isn't
  comparable. Treat the recipe change as a new starting baseline.

## Real example from Mosa Tea

First production recount (2026-06-23, 9 days after go-live):

| Ingredient | Square before | Physical | Variance | Variance % |
|---|---|---|---|---|
| 紅茶 Black | 55.0 | 55 | 0.0 | 0% |
| 綠茶 Green | 106.0 | 106 | 0.0 | 0% |
| 鐵觀音 TGY | 204.88 | 191 | +13.88 | +6.78% |
| 青茶 4S | 75.89 | 71 | +4.89 | +6.44% |
| 麥茶 Barley | 4.86 | 3.5 | +1.36 | +27.98% |

Read:
- Black and Green: low-volume teas, no measurable usage gap.
- TGY and 4S: highest-volume teas, both at ~6-7% variance. Consistent
  shop-floor leakage — likely staff drinks, sample cups, prep waste.
  Worth one recount's worth of data; not yet a recipe issue.
- Barley: 28% variance, but absolute is only 1.36 bags. The percentage is
  loud but the absolute leak is small. Watch over future recounts before
  acting.

After the 4th recount (when the variance log has data), revisit. The TGY +
4S pattern may show a stable ~6% calibration ratio worth baking into ROP
math, or it may have been a one-recount outlier.
