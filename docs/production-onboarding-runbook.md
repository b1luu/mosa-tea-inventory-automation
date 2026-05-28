# Production Onboarding Runbook

> **Status: ready to rehearse, not yet executable on real production.** All the
> tools exist; the blockers are access/infra (production OAuth + `ITEMS_WRITE`
> consent + a production webhook stack). This runbook sequences the tools and —
> crucially — defines a **fresh-sandbox-as-TEST-PRODUCTION dress rehearsal** to
> validate the whole OAuth flow before touching the real shop.

## ⚠️ Read first: the access-token dependency

Everything will run on **OAuth in production** (no personal access token is
available there). But our operational scripts currently authenticate via the
**env token** (`create_square_client()` → `SQUARE_ACCESS_TOKEN`), which is the
default-sandbox PAT. Affected tools:

- `scripts/create_backend_inventory.py`
- `scripts/organize_backend_inventory.py`
- the binding builder's live-catalog reads
- `testing/run_live_cloud_canary`

**These must be able to run against an OAuth-authorized merchant
(`create_square_client_for_merchant`) before production.** Auditing and adapting
that is a prerequisite — see "Token-dependency audit (next)" below. The dress
rehearsal exists largely to *surface* these.

## Prerequisites (access/infra — gated on the business)

1. **Production OAuth app** with `ITEMS_WRITE` added to the scopes; merchant
   completes the one-time re-consent.
2. **Production webhook stack**: a production-pinned deployment with
   `SQUARE_ENVIRONMENT=production` and the **production** webhook signature key,
   plus a production webhook subscription pointed at it.
3. Production merchant connected via OAuth (token in the merchant store).

## Stage 0 — Dress rehearsal on a FRESH sandbox account ("TEST PRODUCTION")

The default sandbox account is *not* a faithful prod stand-in: it already has the
inventory items and we reach it via the PAT. A **brand-new sandbox test account**
is faithful because it is:

- **Greenfield** — no backend inventory items (like real production), so
  create-and-capture actually creates them.
- **OAuth-only** — connect the app to it via the sandbox OAuth flow (including
  the `ITEMS_WRITE` consent), exercising the exact path production will use and
  surfacing every PAT-vs-OAuth dependency.

Rehearsal steps:

1. Create a fresh sandbox test account in the Square Developer Dashboard.
2. Build its menu (or import) so the **sold drinks** exist (the inventory items
   should *not* — that's what we create).
3. Connect the app to it via **sandbox OAuth** with `ITEMS_WRITE`.
4. Run the full onboarding sequence below against it (via OAuth, not the PAT).
5. Confirm: coverage report `ready_for_approval`, and a canary deducts
   end-to-end. Only then is the OAuth turnkey trusted for real production.

## The onboarding sequence (same for rehearsal and production)

Run in this order — **capture IDs before archiving** (build-then-archive):

1. **Create backend inventory items + capture IDs**
   `python -m scripts.create_backend_inventory --apply`
   → writes `data/backend_inventory_created_ids.json` = the account's
   `inventory_variation_ids`. (Greenfield only.)
2. **Set initial stock** for each item (in the units the recipe map assumes).
3. **Build the sold-side binding** (name-match the drinks that already exist) →
   `sold_variation_aliases` + `modifier_aliases`. Merge with the inventory IDs
   from step 1 into the merchant binding.
4. **Validate**: run the coverage report → require `ready_for_approval`
   (`blocking_issue_count == 0`); resolve warnings (unmapped items) as needed.
5. **Approve + activate** the binding version.
6. **Archive + categorize** the backend items:
   `python -m scripts.organize_backend_inventory --apply` (backs up first;
   reversible).
7. **Deploy** the Lambdas from main (the binding-coverage cron picks up the #2
   by-ID backfill so it doesn't false-flag the now-archived items).
8. **Verify end-to-end**: run a canary (or one real order) → confirm the order is
   processed `applied`, 0 failed, and inventory deducts as projected.

## Rollback

- Un-archive / restore categories:
  `python -m scripts.organize_backend_inventory --revert <backup.json>`
- The created items can be deleted via the Catalog API if a rehearsal needs a
  clean reset.

## Token-dependency audit (next)

Before this runbook is truly turnkey, plan and execute:
- An audit of every tool that calls `create_square_client()` (env PAT) and a path
  to run them against an OAuth merchant (`create_square_client_for_merchant`).
- A detailed fresh-sandbox-as-production test plan (Stage 0 expanded) that
  doubles as the OAuth-dependency shakeout.

(Tracked as the immediate next planning task.)
