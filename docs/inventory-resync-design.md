# Inventory Resync Design

> **Status: proposal, written 2026-10-08, updated 2026-10-24.** Nothing in the
> Design section is built yet. The 10/24 update records what changed since:
> binding v5 (2026-10-17), the paid-in-full deduction rule and the daily check
> (2026-10-19), and grapefruit becoming a recipe ingredient (2026-10-19).
> Originally written after the production OAuth connection lapsed (token
> expired 2026-07, reconnected 2026-10-07) and Square's counts drifted from the
> shelf.

## The problem

Three things changed while the system was inactive:

1. **Counts are stale.** No order was deducted for roughly three months, so
   Square's inventory numbers no longer mean anything.
2. **The count sheet grew.** The coworker who does the biweekly physical count
   added rows to the Google Sheet.
3. **The menu moved.** Some drinks we have recipes for are not sold, some sold
   drinks have no recipe, and some drinks were removed.

We want one resync procedure that fixes today's drift, and a design that
tolerates sheet rows and menu items appearing or disappearing without an
engineering change each time.

## What already exists
- **The recount path is the resync path.** Sheet → Apps Script (`syncAllTeas`)
  → `POST /admin/api/manual-count-sync-batch` → Square `PHYSICAL_COUNT`. A
  physical count *overwrites* Square's number, so one full recount fixes any
  amount of drift. See [`operator-recount-workflow.md`](operator-recount-workflow.md).
- **Dry run before apply.** The batch endpoint returns "Square before →
  physical count" per row, and the sheet shows it as a preview.
- **Count-only ingredients already work.** `sample_cup` is bound and countable
  but appears in no recipe; the coverage report lists it under
  `count_only_inventory_keys`, not as a warning. (`grapefruit_can` was the
  other example until 2026-10-19, when it became a recipe ingredient at 30 g
  per grapefruit drink.)
- **Ignored menu items already work.** The binding's
  `ignored_live_variation_ids` (23 items in v5) and `ignored_live_modifier_ids`
  (24) drop merchandise, catering, retired and seasonal items from an order
  without blocking it. See
  [`menu-coverage-and-demand-tracking-decision.md`](menu-coverage-and-demand-tracking-decision.md).
- **Fail-closed worker.** Orders are deducted only when the merchant is active,
  has a usable token and an approved binding.
- **Orders deduct when paid in full** (since 2026-10-19), from any channel,
  after a 15-minute hold; not when staff mark them completed. See
  [`order-state-handling-decision.md`](order-state-handling-decision.md).
- **The usage log records each order's sale time per ingredient**
  (`mosa-tea-usage-log-prod`, since 2026-10-17). This is the data D1 needs.
- **A daily check compares Square's orders with what was deducted**
  (3 am Pacific, since 2026-10-19), combined with the coverage check in one
  email, plus a weekly summary every Monday. See
  [`daily-order-reconciliation-design.md`](daily-order-reconciliation-design.md).

## Findings

### Current (verified 2026-10-24 against production, read-only)

Coverage report for Mosa Tea, binding version 5: **0 blocking issues, 0
warnings.** The daily check found 0 orders not deducted on every shop day from
Oct 19 to Oct 23.

| Finding | Detail |
|---|---|
| Sold drinks with no recipe | none. The Brown Sugar series has recipes; Momo Frost, Momo Forest and Fresh Peach Tea are ignored as seasonal; the crochet Bubbi and catering order are ignored as non-drinks |
| Modifiers with no mapping | none. "Sub w/ Oat Milk" is a substitution (oat milk, log-only); ice levels, merch designs and the Genmai tea bases and Extra Matcha Shot (retired drinks only) are ignored |
| Removed drinks | none flagged |
| Missing inventory items | none |
| Count-only keys | `sample_cup` |

### Original (2026-10-08, binding version 3)

0 blocking issues and 43 warnings: 10 sold variations with no recipe, 31
unmapped modifiers. Binding v5 resolved all of them; kept here because the
gaps below were written against this state.

Not verified: the sheet itself. The Apps Script (`Code.gs`) is not in this
repo, so its behaviour below is taken from the workflow doc.

## Gaps

### G1. Replaying old orders after a recount double-deducts

A physical count already reflects every drink sold before it. If someone later
deducts those old orders, they are deducted *again* on top of the fresh count.
Paths that can do this today:

- `scripts.replay_failed_orders` and the replay-order admin route;
- a dead-letter-queue redrive;
- recovering **missed** orders (paid orders with no processing record), which
  the daily check now reports. `scripts/recover_missed_orders.py` exists
  locally but is uncommitted; it has no recount cutoff and, as written, finds
  only COMPLETED orders, which predates the paid-in-full rule.

Nothing in the code prevents this: adjustments are stamped with the time of
the replay, not the time of the sale.

### G2. Added sheet rows can be silently skipped

- The Apps Script reads a fixed range (`END_ROW = 42`). Rows added below it are
  never sent, with no warning.
- Three lists must agree by hand: `COUNTED_UNIT_BY_KEY` in the Apps Script,
  `SUPPORTED_INVENTORY_KEYS` in `app/manual_count_sync.py`, and
  `data/inventory_item_map.json`. The item map is the real source; the other
  two are copies.
- The batch endpoint rejects the *whole batch* if any one row has an unknown
  key or the wrong unit. The Apps Script pre-filters to avoid this, which is
  why its copy of the key list exists.

The five ingredients this section originally listed as "not recountable"
(`milk`, `heavy_cream`, `frozen_mango`, `frozen_strawberry`, `powdered_sugar`)
are no longer a gap. They are bought at Costco when shelf stock drops below a
par level on the shop's whiteboard, and are deliberately never counted on the
sheet (operator, 2026-10-20). `milk`, `frozen_mango` and `frozen_strawberry`
are `"tracking": "demand"`: deducted per order, with the usage log as the
trustworthy record, and Square's on-hand number is expected to go negative.
`heavy_cream` and `powdered_sugar` have no `tracking` value yet but are in the
same situation.

### G3. One unmapped drink blocks the whole order

If an order contains any drink without a recipe, the worker refuses the entire
order (`can_apply = not skipped_line_items`). A ticket with one unmapped drink
and three mapped drinks deducts nothing for all four.

As of v5 no live drink is unmapped, so this does not happen today. It returns
whenever the shop adds a drink before its recipe is written. The daily check
reports such orders as blocked, with the reason, the next morning.

### G4. Coverage rules assume the shop sells everything we have a recipe for

- **Drinks we have recipes for but the shop does not sell** are harmless for
  orders, but every ingredient used by *any* recipe must exist in Square or the
  binding is blocked (`missing_required_keys`).
- **Drinks removed from the menu** turn their alias into a "stale binding
  source", which counts as a blocking issue: the daily check emails and the
  next binding version cannot be approved until the alias is hand-removed.
  Archived items are still found by ID, so this only bites on deletion.

### G5. The first recount after an outage is not a variance signal

Variance (`Square before − physical count`) after three months of no
deductions measures the outage, not recipe accuracy. It must not feed the
calibration ratio in [`inventory-variance-interpretation.md`](inventory-variance-interpretation.md).

The same applies to the kiosk gap: before 2026-10-17, paid Kiosk orders were
never deducted (about 37% of items), and before 2026-10-19 late-completed
Square Online and delivery orders were deducted late or not at all. The
first recount after 2026-10-19 absorbs both.

Recipe or unit changes also restart the comparison for the keys they touch:
`non_dairy_creamer` (bag 1 kg → 20 kg), `grapefruit_can` (now deducted per
drink, 850 g per can, provisional) and `grapefruit_syrup` (added to Grapefruit
Bloom), all on 2026-10-19.

## Design

### D1. A recount is a hard cutoff for replays

Record, per merchant and inventory key, the time of the last applied physical
count (`last_counted_at`). The store is the existing merchant DynamoDB table
family; one item per sync session plus a per-key latest timestamp.

Replay, redrive and missed-order recovery then follow one rule: **an order
sold before a key's `last_counted_at` does not deduct that key.** If every key
an order touches was counted after the sale, the order is closed out as
`superseded_by_recount` instead of `applied`.

"Sold" means the order's sale time (`created_at`, as the usage log's
`sold_at_order_id` uses), not its completion time. Since the paid-in-full
rule, completion is irrelevant to deduction, and staff complete Square Online
orders a day or more late, so a completion-time cutoff would let pre-recount
orders through.

Why per key and not one merchant-wide timestamp: the coworker leaves cells
blank for items not counted that round, so a sync is often partial.

Rejected alternative: stamping adjustments with the sale time and letting
Square order them. Square only accepts recent `occurred_at` values, so
backdating a three-month-old sale is not available. (To confirm in sandbox
before relying on this reasoning.)

### D2. The server owns the key list; the sheet sends everything

- The Apps Script sends every row down to the last non-empty row, with column
  C's key, the display name and the latest non-cyan count. No `END_ROW`, no
  `COUNTED_UNIT_BY_KEY`.
- The endpoint classifies each row instead of failing the batch:

  | Row status | Meaning | Action |
  |---|---|---|
  | `changed` / `unchanged` | synced | none |
  | `untracked` | column C blank | none; listed so it is a choice, not an accident |
  | `unknown_key` | key not in the item map | fix the typo or add the ingredient |
  | `not_bound` | key known but no Square item for this merchant | create and bind the item |
  | `no_count` | no non-cyan value in the row | count it next time |

- The preview popup shows these groups, so a newly added row is visible the
  first time it is synced, whatever its state.
- The expected unit comes from the item map on the server. The sheet's unit
  column stays informational.
- `SUPPORTED_INVENTORY_KEYS` is replaced by the item map itself. Keys with
  `"tracking": "demand"` or `"log_only"` are not countable; an optional
  `"manual_count": false` opts out any other key (`heavy_cream` and
  `powdered_sugar`, unless they get a `tracking` value).
- `Code.gs` is checked into this repo so the script and the endpoint change
  together.

A new row then falls into one of three cases:

| The new row is… | What it takes |
|---|---|
| something nobody needs in Square | leave column C blank |
| a count-only item (supplies, packaging) | item map entry + Square item + binding id; no recipe |
| an ingredient drinks consume | the full [`add-new-ingredient-runbook.md`](add-new-ingredient-runbook.md) |

### D3. Deduct what we can map, record what we cannot

Change the worker from all-or-nothing to partial apply: mapped line items are
deducted, unmapped ones are recorded on the order as `unaccounted_line_items`,
and the order ends in a new state `applied_partial`. The daily check reports
which unmapped drinks sold and how many, which is also the priority list for
writing recipes. (It already reports whole blocked orders with their reason.)

This reverses a deliberate fail-closed choice, so it is an open decision
(below), and was explicitly deferred on 2026-10-17. The argument for it: the
recount corrects under-deduction either way, and blocking four drinks because
one is unknown creates more drift than it prevents. The argument for waiting:
with 0 unmapped drinks today, it only matters when the menu changes.

### D4. Coverage follows the shop's actual menu

- **Required ingredients** are derived from the drinks and modifiers the
  binding actually aliases, not from every recipe in `recipe_map.json`.
- **Stale sold and modifier aliases** become warnings. The binding builder
  proposes a new version with them moved to a `retired_aliases` list, so a
  removed drink costs one approval instead of a hand edit.
- **Stale inventory ids stay blocking.** A missing ingredient item means
  deductions have nowhere to land.

### D5. Mark outage recounts as a baseline

The sync request takes an optional `baseline: true`. A baseline session is
applied normally but excluded from variance and calibration. The Apps Script
offers it as a second button ("Reset counts after downtime").

## Resync runbook for the next recount (no code needed)

1. Token and live access: done 2026-10-08. The daily refresh Lambda should
   first renew the token on or after 2026-10-28 (it expires 2026-11-07);
   confirm it did before the recount.
2. **Do not** run `replay_failed_orders`, the replay route, a dead-letter
   redrive or missed-order recovery for anything sold before the recount.
3. Check the grapefruit can's net weight on the label and correct
   `stock_unit_size` for `grapefruit_can` (850 g is provisional).
4. In the Apps Script, raise `END_ROW` to cover the added rows. For each new
   row, either leave column C blank or use an existing key.
5. Have the coworker do a full count, with no blanks for tracked rows. Carry
   the new date column into the synced copy of the sheet.
6. Click **Sync to Square**, read the preview, apply. Expect large deltas; this
   one is a baseline (G5).
7. Note the recount time, so later replays are known to be unsafe before it.
8. Ring up one real mapped drink and confirm its ingredients drop.

The Costco items (G2) are not part of the recount and need no manual Square
edit.

## Build order

| Phase | Contents | Why this order |
|---|---|---|
| 1 | D2 (row-tolerant sync, `Code.gs` in repo) | Removes the silent-skip risk on the next biweekly count |
| 2 | D1 + D5 (recount cutoff, baseline flag) | Makes replays and missed-order recovery safe; needed before the next outage |
| 3 | D3 + D4 (partial apply, menu-driven coverage) | Largest behaviour change; needs the decision below; low urgency while no drink is unmapped |

Done since the first version: recipes for the unmapped drinks (Brown Sugar
series mapped, seasonal and non-drink items ignored, v5), and keeping the
token alive (daily OAuth refresh Lambda, PR #58).

## Open decisions

1. **Partial apply (D3)** or keep whole-order blocking? Recommended: partial
   apply. Deferred on 2026-10-17.
2. **Where sync sessions live:** DynamoDB only, or also the planned `Variance
   Log` sheet tab so the owner can see them?

Resolved:

- **The five excluded ingredients** were left off the sheet on purpose: they
  are Costco items run from a whiteboard par level (operator, 2026-10-20). See
  G2.
- **Unmapped stock-consuming modifiers:** oat milk is a log-only substitution;
  the Genmai tea bases and Extra Matcha Shot only existed on retired drinks and
  are ignored (binding v5, 2026-10-17).
