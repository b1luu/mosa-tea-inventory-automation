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

## Scope justification — what each permission is for

The production OAuth ask, every scope mapped to the Square endpoint it gates and
the tool that uses it. Nothing in this list can move money, take payments, or
create orders — those scopes (`PAYMENTS_WRITE`, `ORDERS_WRITE`, etc.) are
explicitly **not** requested.

### `MERCHANT_PROFILE_READ`
| Endpoint | SDK | Used by | Why |
|---|---|---|---|
| `GET /v2/merchants/{id}` (`RetrieveMerchant`) | `client.merchants.get(...)` | OAuth callback / merchant context resolution | Identify the merchant just connected; persist `merchant_id` + display name |

### `ORDERS_READ`
| Endpoint | SDK | Used by | Why |
|---|---|---|---|
| `GET /v2/orders/{id}` (`RetrieveOrder`) | `client.orders.get(...)` | **Webhook worker** (hot path); `scripts/inspect_order.py` | Fetch the full order to compute deductions from line items + modifiers |

### `INVENTORY_READ`
| Endpoint | SDK | Used by | Why |
|---|---|---|---|
| `POST /v2/inventory/counts/batch-retrieve` (`BatchRetrieveInventoryCounts`) | `client.inventory.batch_get_counts(...)` | `scripts/inspect_inventory_count.py`; manual-count-sync; ops tooling | Read current stock levels before/after a change |

### `INVENTORY_WRITE`
| Endpoint | SDK | Used by | Why |
|---|---|---|---|
| `POST /v2/inventory/changes/batch-create` (`BatchChangeInventory`) | `client.inventory.batch_create_changes(...)` | **Webhook worker** (hot path); `scripts/apply_inventory_adjustments.py`; manual-count-sync | **The actual inventory deductions per sale — the whole point of the system** |

### `ITEMS_READ`
| Endpoint | SDK | Used by | Why |
|---|---|---|---|
| `GET /v2/catalog/list` (`ListCatalog`) | `client.catalog.list(types=...)` | Binding coverage cron; binding builder; organize script; create-script greenfield guard | Enumerate sold items / modifiers / categories for binding validation + name-matching |
| `POST /v2/catalog/batch-retrieve` (`BatchRetrieveCatalogObjects`) | `client.catalog.batch_get(...)` | **Binding coverage cron (#2 backfill)** | Fetch archived inventory items by ID that `list` won't return |
| `GET /v2/catalog/object/{id}` (`RetrieveCatalogObject`) | `client.catalog.object.get(...)` | Organize script (pre-upsert version fetch); ad-hoc inspection | Read a specific item's current version + fields before updating |

### `ITEMS_WRITE`
| Endpoint | SDK | Used by | Why |
|---|---|---|---|
| `POST /v2/catalog/object` (`UpsertCatalogObject`) | `client.catalog.object.upsert(...)` | `scripts/create_backend_inventory.py`; `scripts/organize_backend_inventory.py` (create the "Backend Inventory" category once, then archive + recategorize each item, and revert) | The **only** catalog mutation we make — one endpoint, used four ways (create item, create category, archive+categorize, revert) |

### Boss-facing one-liner

> *"The app needs to **read** the menu + orders + stock counts, **write** stock
> deductions (the whole product), **read** the merchant profile (to know who
> connected), and **edit catalog items** for one purpose: a one-time scripted
> setup that creates the backend inventory items and archives + categorizes
> them. Nothing it can do can move money, take payments, or create orders."*

## Revoking access (for the merchant)

The merchant can revoke this app at any time, without involving the developer,
from the **Square Seller Dashboard → Account & Settings → My Business → Apps &
integrations → Authorized applications** (label varies). Selecting the app shows
its permissions + a Revoke / Disconnect button. After revocation:

- The access token and refresh token become invalid immediately.
- The deployed worker fails-closed on the next inventory write (already wired
  via `disable_merchant_writes` / `revoke_merchant` in `app/webhook_ingress.py`)
  and an alarm should fire.
- Re-onboarding = redo the OAuth consent (same one-button landing page).

To revoke programmatically from our side (e.g. on detected compromise), the
endpoint is `POST /oauth2/revoke` (`RevokeToken`) via
`client.o_auth.revoke_token(...)`.

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
