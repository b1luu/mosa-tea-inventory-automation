# Order State Handling Decision

## Decision

Inventory is committed if and only if Square reports `order.state == "COMPLETED"`.

This is the only state that triggers the worker Lambda's inventory write path.

The system will not decrement inventory for:

- `DRAFT` orders
- `OPEN` orders
- `CANCELED` orders

## Why This Is Locked In

Square's documented order states are:

- `DRAFT`
- `OPEN`
- `COMPLETED`
- `CANCELED`

Per Square's Pay for Orders documentation, an order transitions to `COMPLETED` when the sum of all recorded payments equals the order total.

That makes `COMPLETED` the only state that represents both:

- payment captured
- line items finalized enough to commit inventory

The other states do not meet that bar:

- `DRAFT`: order is not payable and has no inventory impact
- `OPEN`: order is still mutable and payment may fail, so decrementing here would corrupt counts on abandoned or edited orders
- `CANCELED`: no sale occurred and there is no inventory impact

## Decision Gate

The gate for automated inventory writes is:

**Has Square reported a finalized paid sale?**

If the answer is no, inventory does not move.

This is the governing gate for future implementation decisions in this area.

## Required Production Behavior

To satisfy that gate, the deployed system must provide all of the following:

1. `COMPLETED`-only write behavior
- automated inventory writes happen only when `order.state == "COMPLETED"`
- no other order state reaches the inventory write path

2. Explicit ignore behavior for non-terminal states
- `DRAFT`, `OPEN`, and `CANCELED` events are recorded for observability
- those events do not reserve or commit inventory

3. Reversal events stay out of scope
- refunds
- voids of previously-`COMPLETED` orders
- comps applied after `COMPLETED`
- partial completions
- post-`COMPLETED` line item edits

4. Reconciliation remains operator-backed
- rare reversal or post-sale correction events are handled by manual recount and sync
- the automated system does not guess at reversal math or attempt a second inventory-credit path

## Why The Manual Count Sync Path Exists

The manual count sync path exists to keep this scope decision operationally correct.

The operator reports that refunds, voids, comps, and other post-sale corrections occur at well under 1% of order volume based on roughly a year of store operations.

That makes the tradeoff straightforward:

- the Google Sheets recount flow plus `app/lambda_manual_count_sync.py` is the corrective path for rare drift
- operators already perform physical recounts on a known cadence
- that recount path corrects any inventory drift caused by intentionally unhandled reversal events

Automated reversal handling would add disproportionate runtime complexity at the current scale:

- a separate inventory-credit code path
- separate reversal state handling
- double-write idempotency concerns
- refund and partial-payment accounting edge cases

That complexity is not justified for a single-merchant deployment with low reversal volume.

## Consequences

Because this decision is locked in:

- `app/webhook_ingress.py` and `app/order_loader.py` gate on `order.state == "COMPLETED"` exclusively
- the webhook event ledger records non-`COMPLETED` order events as ignored for observability
- the manual count sync path is load-bearing for reconciliation correctness
- the manual reconciliation path must not be deprecated without revisiting this decision

## How This Scope Decision Is Monitored

This scope decision is intended to be tested empirically in production.

A planned discovery alarm, not yet implemented, should fire when:

- an `order.updated` webhook arrives
- the local `processing_state == "applied"`
- the incoming Square order version exceeds the version recorded at apply time

That alarm is meant to answer one question:

**Do post-`COMPLETED` edits actually occur often enough to justify automated reversal handling?**

The intended interpretation is:

- if the alarm never fires across normal operations, the current manual-reconciliation approach is validated
- if the alarm fires repeatedly, this decision should be revisited

### Revisit Triggers

This decision should be reconsidered if:

- refund, void, or comp volume exceeds approximately 1% of monthly orders on a sustained basis
- the planned post-applied edit alarm, once built, fires more than incidentally
- the merchant expands to a multi-location footprint where per-location reconciliation becomes heavier
- a second merchant onboards with meaningfully different operating patterns

## Non-Goals

This decision does not mean:

- refund or reversal handling can never be implemented
- operator reconciliation is optional
- the manual sync path can be removed once automation is live

It only documents the current scope boundary for automated inventory writes.
