# Daily Order Reconciliation Design

> **Status: approved 2026-10-19, not yet built.** All decisions are recorded
> at the end. Build order: the paid-in-full rule first (its own PR), then the
> daily check.

## Problem

Today the system only emails when something **crashes**: a Lambda errors, or a
job lands in the dead-letter queue. It says nothing when an order is processed
"correctly" but inventory still doesn't move. That second kind of failure has
been the expensive one:

| Gap | How it was found | Size |
|---|---|---|
| Orders **blocked** by an unmapped drink | never alerted | **687 orders** blocked since June (264 in July) |
| **Kiosk** orders never reaching `COMPLETED` | manual digging, 2026-10-17 | **37% of items** for at least a month |
| Orders lost in a **bad deploy** | DLQ alarm, then forgotten | 2 orders on 2026-10-10 |

All three share a shape: **Square has a sale we should have deducted, and we
didn't.** This design adds one daily check that compares what Square sold with
what was deducted, and emails only when they disagree.

## Prerequisite: deduct when paid, not when "completed"

Reconciliation is only useful if the commit rule matches reality. It currently
doesn't for any channel where staff must mark orders complete.

### Evidence (90 days to 2026-10-18)

How long after the order Square marked it `COMPLETED`:

| Channel | Within 1 h | 1 to 24 h | **Over 1 day** |
|---|---|---|---|
| Point of Sale | 1,534 (all under 5 min) | 0 | 0 |
| **Square Online** | 46 | 134 | **120** |
| DoorDash | 338 | 87 | 0 |
| Grubhub | 36 | 56 | 0 |
| Kiosk (until staff stopped completing them, mid-September) | 4 | 80 | **144** |

Pickup and kiosk orders are completed when someone remembers to, often the next
day or in bulk. The drink was made at pickup, but inventory moves only on
"complete". That causes two problems:

- **Lag:** counts are hours or days behind the shelf.
- **Double counting:** an order completed *after* a physical recount is
  deducted on top of a count that already reflects it (design G1 in
  `inventory-resync-design.md`), with no replay involved.

No paid order from any channel stayed `OPEN` more than 2 days in this window,
so these are late, not lost. But late is enough to make both problems real.

### Proposed rule

An order commits when it is **paid in full**: `COMPLETED`, or `OPEN` with a
tender and nothing owed, **from any channel**. This generalises the
2026-10-17 Kiosk rule; `is_paid_kiosk_order` becomes `is_paid_in_full`.

### Cancellations: a 15-minute hold

Square Online orders are sometimes cancelled after payment: **20 in 90 days**,
half within **1 minute**, the slowest after **10.5 hours**. Deducting the moment
payment lands would over-deduct all 20.

So a paid-but-`OPEN` order is queued with a **15-minute delay** (SQS
`DelaySeconds`, maximum 900 s), and the worker **re-fetches the order** when it
runs:

- still paid and not cancelled → deduct, mark `applied`;
- cancelled by then → mark a new terminal state `cancelled_before_apply`, no
  deduction (today a skipped order is recorded as `failed`, which would make
  reconciliation report a false problem).

This catches the typical cancellation. A late one (like the 10.5-hour case) is
still over-deducted; reconciliation reports it under **reversed after
deduction**, and the recount corrects it. `COMPLETED` events skip the hold, as
today. A late `COMPLETED` for an order already applied at payment is ignored,
because the order is reserved once.

How the pieces interact:

- **Completed during the hold.** A Square Online order paid and then completed
  within 15 minutes: the paid event reserves the order and queues the delayed
  job; the `COMPLETED` event finds it reserved and is ignored; the delayed job
  re-fetches, sees `COMPLETED`, and deducts once.
- **Edited during the hold.** The re-fetch deducts what was actually sold, not
  what the first event saw.
- **After `cancelled_before_apply`.** The state is terminal, so later events
  for that order are ignored, as for `applied`.

Kiosk orders pick up the same 15-minute hold. That costs nothing (their
deduction moves from about 9 seconds to 15 minutes after payment) and keeps one
rule for every channel.

### Consequences

- Amends `docs/order-state-handling-decision.md` again: "paid in full" replaces
  "`COMPLETED`, or a paid Kiosk order".
- Ships **before** reconciliation, as its own PR, so the nightly check measures
  the new rule from day one.
- The **paid but not deductible** bucket below becomes a true safety net. Under
  the new rule it should be near-empty, and anything in it (a partially paid
  order, an unknown source) is genuinely odd.

## What it checks

Once a day, for the **previous shop day** (midnight to midnight,
`America/Los_Angeles`), it fetches every order Square has at the location and
puts each one in exactly one bucket.

### Buckets that mean something went wrong (each triggers the email)

| Bucket | Meaning | Example cause |
|---|---|---|
| **blocked** | should commit; processing state `blocked` | unmapped drink, hot drink with jelly |
| **failed** | should commit; state `failed` | Square API error during apply |
| **stuck** | should commit; state `pending` or `processing` | crash mid-job (the 2026-10-10 deploy) |
| **missed** | should commit; **no processing record at all** | webhook never arrived, or ingress ignored it |
| **reversed after deduction** | state `applied`, but Square now shows `CANCELED` | refund or cancellation after we deducted |

"Should commit" means `is_committable_order(order)` from
`app/order_commit_rules.py`, the **same rule the worker uses**, so the check and
the worker can never disagree about which orders count.

### A safety net for the rule itself

Using the worker's own rule has a blind spot: if the rule is wrong, the check
agrees with it. That is exactly how the kiosk gap went unseen (every kiosk order
was "correctly" skipped). So there is one more bucket:

| Bucket | Meaning | Alert rule |
|---|---|---|
| **paid but not deductible** | has a tender, owes nothing, not `CANCELED`, but `is_committable_order` says no | email when **3 or more** come from the **same source** in a day |

Once the paid-in-full rule (above) ships, a paid order should almost never
land here. Three or more from one channel in a day means a pattern the rule
misses, as the Kiosk was under the old `COMPLETED`-only rule. Had this check
existed on 2026-09-17, it would have reported about 30 Kiosk orders that day.

### Buckets that are fine (counted, never emailed alone)

- **applied**: should commit, state `applied`.
- **not a sale**: `DRAFT`, `CANCELED` without a deduction, or unpaid `OPEN`.

## Finding the reason for a block

Processing records store the state but **not why** an order was blocked. Rather
than change the worker, the check works the reason out: for each blocked,
failed or stuck order, it runs a **dry run** of the same projection the worker
runs (`process_orders(..., apply_changes=False)` with the active binding) and
reports the skipped line items' reasons, e.g.
`No recipe mapping found for sold variation 'XYZ' (Momo Frost)`.

The reason reflects **today's** recipes and binding. If the problem has since
been fixed, the dry run comes back clean, and the email says *"would apply now"*
instead of a reason. That is useful too: it means a replay would succeed.

## When it runs

**3:00 am Pacific**, daily (`cron(0 10 * * ? *)` in UTC, which is 3 am PDT and
2 am PST; EventBridge cron has no time zones). It runs after closing, so the
previous day is final, and before opening.

The binding coverage check moves to the same schedule. It currently fires at
**6:26 pm Pacific**, mid-service, only because `rate(1 day)` repeats from
whenever the rule was created.

## Where it runs

Inside the existing daily Lambda (`mosa-tea-binding-coverage-check-prod`), as a
second step after the coverage check:

- one scheduled job, one daily email, no new Lambda;
- a new module, `app/order_reconciliation.py`, keeps the logic separate and
  testable; the coverage check is not changed;
- if either step finds something, **one** email covers both; if the
  reconciliation step itself crashes, the Lambda errors and the existing
  `binding-coverage-check-errors` alarm fires.

**Alternative considered:** a separate Lambda. Cleaner separation, but another
role, schedule, alarm and deploy entry for the same once-a-day cadence. Not
worth it at this scale.

## The email

Sent only when there is something to act on. Subject:

```
Mosa Tea daily check (Oct 17): 3 orders not deducted
```

Body, plain text, problems first:

```
Orders not deducted on Fri Oct 17 (Pacific):

BLOCKED (2)
  12:41 pm  Kiosk        1 x Momo Frost; 1 x Matcha Latte
            reason: no recipe for "Momo Frost"
  3:05 pm   POS          1 x Hot Chestnut Forest (Lychee Jelly)
            reason: jelly not supported on hot drinks

MISSED (1)
  6:12 pm   DoorDash     2 x TGY Special
            no processing record: the webhook never arrived or was ignored
            would apply now: yes

PAID BUT NOT DEDUCTIBLE, by source
  Square Online: 4  (pattern threshold is 3)

Day totals: 124 orders in Square, 90 deducted (143 items), 3 not deducted,
31 not sales (drafts, unpaid, cancelled).

These are not replayed automatically. Replaying an order from before a
physical recount counts it twice. See docs/ops-runbook.md, "Daily check".
```

Each order line shows the Pacific time, the channel, the items and modifiers,
and the Square order ID (omitted above for width) so it can be found or
replayed.

On clean days, **no daily email**. The run still logs a one-line summary
(`reconciliation_clean | orders=124 applied=90 ...`), and a crash still alarms.

### Weekly summary (every Monday)

Silence should never be ambiguous, so the Monday 3 am run also sends a short
summary of the previous Monday to Sunday, **every week, clean or not**. If it
stops arriving, the check has stopped running.

```
Mosa Tea weekly check (Oct 12 to Oct 18): all clean
```
or
```
Mosa Tea weekly check (Oct 12 to Oct 18): 3 orders not deducted (already emailed)
```

Body: one line per day (orders in Square, orders deducted, items, problems),
the week's totals, and the binding coverage status. Problems are not repeated
in detail; they went out in that day's email. The Monday run reconciles all 7
days again for this (about 1,000 orders), which is still well inside the free
tier.

## What it deliberately does not do

- **No automatic replay.** Replaying an order sold before a recount deducts it
  twice (design G1 in `inventory-resync-design.md`). The email gives what is
  needed to decide; a person decides.
- **No automatic reversal** for "reversed after deduction". It is reported
  because its volume is a revisit trigger in
  `order-state-handling-decision.md`; the recount still corrects the count.
- **No re-alerting on old days.** Each run checks one day. A problem from
  Tuesday appears in Wednesday's email only.

## Data, permissions, cost

| Need | How |
|---|---|
| Square orders for the day | `orders.search` with a `created_at` window, about 150 orders, 1 to 2 calls |
| Processing state per order | `GetItem` on `mosa-tea-order-processing-prod`: **new read permission** for the daily Lambda's role |
| Dry-run reasons | the active binding (already readable) and the recipe map (bundled) |
| Sending | the existing `mosa-tea-ops` topic |

Cost: about 150 extra DynamoDB reads and 2 Square calls per day. Free.

Orders are selected by **creation time**. An order created at 11:50 pm and
completed at 12:10 am still counts on its creation day, and by 3 am it is
final.

## Implementation outline

1. `app/order_reconciliation.py`
   - `fetch_orders_for_local_day(client, location_id, day, tz)`
   - `classify(orders, processing_records)`: pure, returns the buckets
   - `explain(order_ids, binding)`: dry-run reasons
   - `format_email(report)`
2. `app/lambda_binding_coverage_check.py`: after the coverage step, run the
   reconciliation for yesterday; merge findings into one email; one subject
   line covering both. On Mondays (Pacific), also send the weekly summary.
3. Terraform: `cron(0 10 * * ? *)` schedule; `dynamodb:GetItem` on the order
   processing table for the coverage check role.
4. Tests: every bucket; the paid-but-not-deductible threshold; Pacific day
   boundaries including the Nov 1 switch to standard time; the dry-run reason
   path including "would apply now"; no email on a clean day; one email when
   both steps have findings; the weekly summary goes out on Mondays only,
   clean or not, and never repeats problem detail.
5. Validation before merge, read-only against real days:
   - **Oct 17**, current rule: expect the 19 Kiosk orders paid before the fix
     as **missed** ("would apply now: yes"), everything else applied.
   - **Sept 17**, current rule: expect about 30 Kiosk orders as **missed**.
   - **Sept 17**, with the old `COMPLETED`-only rule swapped in: expect Kiosk
     flagged under **paid but not deductible** as a pattern. This proves the
     safety net catches a gap the rule itself misses.
6. Runbook: a "Daily check" section in `docs/ops-runbook.md`: what each bucket
   means and what to do.

## Decisions (operator, 2026-10-18 and 2026-10-19)

0. **Deduct when paid in full, from every channel, after a 15-minute hold:**
   yes. See *Prerequisite*.
1. **Run time:** 3:00 am Pacific.
2. **Pattern threshold** for *paid but not deductible*: 3 per channel per day.
3. **Reversed after deduction:** emailed.
4. **Emails:** one combined daily email covering coverage and reconciliation.
5. **Heartbeat:** a weekly summary every Monday, clean or not.
