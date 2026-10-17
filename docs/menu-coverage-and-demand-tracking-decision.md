# Menu Coverage and Demand Tracking Decision

> **Decided and deployed 2026-10-17** (binding v5, PR #56, commit `cc48f87`).
> Written so a future engineer or agent can see what was chosen, why, and what
> was deliberately left out. Read this before changing the binding's ignore
> lists, the coverage check's alert rules, or how an ingredient is tracked.

## Why this came up

A review of the daily binding coverage check found it had **crashed on 369 of
371 runs since 2026-06-03** and had never notified anyone:

- `alarm_notification_topic_arn` was commented out in `infra/production.tfvars`,
  so the check raised `ALARM_NOTIFICATION_TOPIC_ARN must be set` whenever it
  had findings, and its error alarm had no recipients either.
- The findings themselves were mostly leftovers: drinks removed from the
  binding but still listed in Square, plus 25 modifiers the check had no way to
  mark as harmless. That noise hid a real gap: **"Sub w/ Oat Milk" (about 200
  drinks per 90 days) was skipped at deduction time, so dairy milk was
  over-deducted and oat milk was not tracked at all.**
- Chestnut Forest (about 35/week since 2026-08-31, seasonal) was on the ignore
  list, so none of its ingredients were deducted.

## Decisions

### 1. Alerts must reach a person, and Terraform enforces it

- Production alarms and the coverage check publish to the `mosa-tea-ops` SNS
  topic (email: `brandonluu.dev@gmail.com`).
- `infra/lambda.tf` has a `precondition` on the coverage-check Lambda:
  `terraform plan` fails if no topic is set.

**Why:** a check that fails silently is worse than no check, because it looks
like coverage is fine.

### 2. Items we don't control are ignored, not archived

Retired and seasonal drinks are put on the binding's ignore lists instead of
being archived in Square.

**Why:** the Square catalog's menu items belong to the shop owner. This system's
operator owns only the backend inventory items they created. So the respectful
default for menu items we cannot clean up is **"assume retired"**: ignore them
in the binding and leave Square untouched.

How the three states behave (see `app/catalog_binding_resolver.py`):

| Live item is… | At order time | In the coverage check |
|---|---|---|
| **mapped** (alias) | deducted by recipe | covered |
| **ignored** | dropped from the order; the rest of the order still applies | listed, not a warning |
| **neither** | **blocks the whole order** for drinks; **silently skipped** for modifiers | warning, and emailed |

Removing a mapping moves an item to "neither", not to "ignored". Retiring a
drink therefore takes two steps: drop the alias **and** add the ID to the
ignore list.

**A seasonal item coming back** must be moved from the ignore list back to a
mapping. Until then, its sales are dropped without deduction, and the check
cannot see it, because the ignore list is exactly what hides it.

### 3. Modifiers get their own ignore list

The binding has `ignored_live_modifier_ids`, mirroring `ignored_live_variation_ids`.
v5 ignores 24 modifiers in these groups:

- ice levels (ice is not inventory);
- sticker and tote-bag designs (merch choices);
- the Genmai tea bases, Extra Matcha Shot, Pistachio Foam and No Peach Cream
  (they only existed on retired drinks);
- the catering "Utensils" add-ons (rare; not worth tracking).

**Why:** before this list existed, 23 of the check's 27 warnings were permanent
and harmless, which is how the oat milk gap went unnoticed.

### 4. The check emails on unmapped modifiers

`app/lambda_binding_coverage_check.py` now alerts when there is any blocking
issue, any unmapped drink, **or any unmapped modifier**, and names them in the
email. Ingredients that are only counted from the sheet (on the manual-count
allowlist but used by no recipe, e.g. `grapefruit_can`, `sample_cup`) are
reported as `count_only_inventory_keys` instead of warnings.

**Why:** the order Lambda skips unknown modifiers without error
(`_resolve_modifier_additions`). With the harmless ones ignored, any modifier
still unmapped is a real inventory gap. The design goal is **a clean run with
zero warnings**, so a new warning is always worth acting on.

### 5. Matcha jelly is retired, following the pistachio pattern

Removed: the Genmai Matcha with Matcha Jelly recipe, the Matcha Jelly topping,
the `matcha_jelly_matcha` inventory key, and the Genmai tea-base options. The
operator deleted the jelly inventory item in Square. The drink itself is off
the menu but not archived (we don't own it), so it is on the ignore list.

**Why:** ignoring is not enough when the *ingredient* is gone. As long as any
recipe uses a key, the binding must point that key at a live Square item. This
mirrors commit `aadf7e4` (pistachio). To bring it back, restore it from git
history.

### 6. Chestnut Forest deducts as a Matcha Latte clone

The live iced and hot Chestnut Forest variations are aliased to the canonical
Matcha Latte and Hot Matcha Latte. The chestnut foam is **not** tracked.

**Why:** the chestnut supply is a one-time, owner-controlled purchase that is
not reordered when it runs out, so tracking it automates nothing. Every one of
the 244 orders in the 60 days checked carried a sugar choice, so the clone does
not block any. Hot Chestnut Forest with a jelly topping is blocked by the
existing "no jelly on hot drinks" rule; it sold 3 times in 90 days.

Orders sold before v5 were **not** replayed. Their other drinks were already
deducted, so a replay would double-count them. The next recount absorbs the
drift.

### 7. Two tracking modes: counted vs demand

`data/inventory_item_map.json` entries may set `"tracking"`:

| `tracking` | Meaning | Examples | Square item? | Sheet recount? |
|---|---|---|---|---|
| *(absent)* | counted: deducted per order, corrected by the biweekly recount | teas, syrups, cups | yes | yes |
| `"demand"` | deducted per order, never recounted; the usage log is the trustworthy record | `milk`, `frozen_mango`, `frozen_strawberry` | yes | no |
| `"log_only"` | **never sent to Square**; recorded only in the usage log | `oat_milk` | no | no |

**Why:** for perishables that nobody counts, Square's on-hand number drifts and
means nothing. What the shop actually needs is **demand** (how much is used per
day), so reorders can be planned. `log_only` keeps oat milk out of Square so
there is no Square item to keep tidy. Log-only keys are excluded from the
binding's required keys (`get_canonical_binding_targets`) and from Square
adjustments (`inventory_plan._build_adjustment_changes`).

### 8. "Sub w/ Oat Milk" is a substitution, 1:1

`recipe_map.json` has a new `modifier_substitutions` section. "Sub w/ Oat Milk"
replaces `milk` with `oat_milk` by volume (150 ml in a latte). It is applied
after tea bases are expanded (`_apply_modifier_substitutions`). Oat milk is the
Oatly 64 fl oz (1,890 ml) carton, bought in cases of 3.

**Why:** modifiers could previously only *add* ingredients, so the swap needed
its own mechanism. In 90 days of orders oat milk only appeared on matcha drinks,
all of which use exactly 150 ml of milk.

### 9. Usage log: one row per order per ingredient

DynamoDB table `mosa-tea-usage-log-prod` (`app/usage_log_store.py`):

- Key: `usage_key` = `environment#merchant#location#inventory_key`;
  sort key `sold_at_order_id` = `<order created_at>#<order_id>`.
- The worker writes it for every applied order, for **every** ingredient, not
  only the demand-tracked ones. It is cheap, and the same data is what a future
  "recount cutoff" (design D1 in `inventory-resync-design.md`) needs.
- The sale time comes from the Square order, so a retried order overwrites its
  own rows instead of double-counting.
- The write happens **before** the order is marked applied. If it fails, the
  job is retried, Square's idempotency key absorbs the repeat deduction, and
  after the retry limit the job goes to the DLQ, whose alarm emails.
- Read it with `scripts/usage_demand_report.py` (daily usage and average, in
  recipe and stock units).

**Rejected:** using Square's own inventory history as the demand record.
Log-only ingredients have no Square item, and the history mixes in manual
dashboard edits.

## Deliberately not done (yet)

- **Restock tracking and reorder alerts.** The log measures demand, not stock
  on hand. That needs a way to record deliveries ("a case arrived"), possibly
  its own small app. Deferred by the operator on 2026-10-17.
- **Partial order apply** (design D3 in `inventory-resync-design.md`). An
  unmapped drink still blocks its whole order. The ignore lists reduce how often
  that happens; they don't change the rule.
- **Deleting the 2 sandbox Secrets Manager secrets** ($0.80/month). AWS usage is
  about $1.20/month in total and is covered by credits ($114 remaining as of
  2026-10-17). Revisit when the credits expire.

## Known risks at deploy time

The DynamoDB backend of the usage log (`usage_log_dynamodb.py`), the worker's
log write and the `BatchWriteItem` IAM grant were **not** run against real AWS
before the production deploy (unit tests cover the SQLite backend and a mocked
worker). The operator chose to deploy and review after the first full day of
sales. If that write fails, it fails for every order: watch the DLQ alarm.

## How to…

- **Retire a drink:** remove its alias and add its live ID to
  `ignored_live_variation_ids` in a new binding version. If an ingredient is
  also gone, retire it from `recipe_map.json` and `inventory_item_map.json`
  too, as in section 5 and commit `aadf7e4`.
- **Bring a seasonal drink back:** move its live ID from the ignore list to
  `sold_variation_aliases` (a clone alias is fine if the recipe matches an
  existing drink).
- **Add a demand-tracked ingredient:** add it to `inventory_item_map.json` with
  `"tracking": "demand"` (it needs a Square item) or `"log_only"` (it doesn't),
  then reference it from recipes. It will appear in `usage_demand_report.py`
  by default.
- **Validate a binding before approving:** run `scripts.build_binding_coverage_report`
  with `--binding-version N`. The target is 0 blocking issues and 0 warnings.

## Where it lives

| Concern | File |
|---|---|
| Ignore lists at order time | `app/catalog_binding_resolver.py` |
| Coverage rules, count-only keys | `app/binding_coverage_report.py` |
| Alert rules and email | `app/lambda_binding_coverage_check.py` |
| Substitution, log-only flag | `app/order_inventory_projection.py` |
| Log-only keys skipped for Square | `app/inventory_plan.py`, `app/order_processor.py` |
| Usage log | `app/usage_log_store.py`, `usage_log_db.py`, `usage_log_dynamodb.py` |
| Worker log write | `app/webhook_worker.py` (`_record_applied_usage`) |
| Demand report | `scripts/usage_demand_report.py` |
| Binding v5 | `data/bindings/draft_mosa_tea_prod_v5.json` |
| Alert wiring, usage log table | `infra/production.tfvars`, `infra/lambda.tf`, `infra/dynamodb.tf`, `infra/iam.tf` |
