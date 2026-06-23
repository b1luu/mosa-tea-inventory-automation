# Operator recount workflow

How the merchant (the boss) and the operator (you) push a periodic physical
inventory count from a Google Sheet to Square's catalog inventory.

The chain: Google Sheet → Apps Script (`syncAllTeas`) → POST
`/admin/api/manual-count-sync-batch` on the manual-count-sync Lambda → Square
catalog `BatchChangeInventory` with `PHYSICAL_COUNT` type.

> Why a recount at all if the worker auto-deducts every order? Real shops have
> off-the-books consumption — staff drinks, samples, spillage, prep waste,
> deliveries logged loosely. The recount trues up Square to physical reality
> and exposes the size of that gap (see
> [`inventory-variance-interpretation.md`](inventory-variance-interpretation.md)).

## Sheet structure (fixed)

The "Copy of Inventory" sheet has a specific layout the script depends on:

| Col | Purpose | Example |
|---|---|---|
| A | Source (informational) | `Taiwan (3 Month)` / `US (1 week)` |
| B | Display name (Chinese + English) | `鐵觀音 TGY` |
| **C** | **`inventory_key`** (snake_case, machine-readable) | `tgy` |
| D | Monthly usage (informational) | `29.75` |
| E | Order (informational) | `154` |
| F | ROP — 4 month (informational) | `119` |
| G | Unit hint (informational) | `Bag (600g)` |
| **H onwards** | Date-keyed count columns | header `5/19`, value `60` |

Header row 1 has the date for each count column.

**Cyan-highlighted cells (`#00ffff`) in count columns mean "stock received"**
(deliveries / restocks) — NOT a physical count. The script intentionally
skips cyan cells when finding the latest physical count to sync.

## What gets synced

For every row in rows 2–`END_ROW` (currently `END_ROW = 42`):

1. If column C is blank → row silently skipped (intentionally untracked rows
   like `Cup Seal`, `Peach Syrup`, `Peach Can`).
2. If column C has an `inventory_key` not in `COUNTED_UNIT_BY_KEY` → preparation
   error (printed in popup, row skipped).
3. Otherwise → the script walks the row's count columns **right to left**,
   skips cyan-highlighted cells, picks the first non-empty value, and sends it
   as `counted_quantity`.

The Lambda then applies a `PHYSICAL_COUNT` adjustment in Square — which
**overwrites** the current Square count to exactly that number. (`PHYSICAL_COUNT`
is set-the-value semantics, not add-to-current.)

## One-time setup

These steps only need to happen once per Sheet (or whenever the production
operator token rotates).

### Get the production operator token

```bash
grep operator_api_token /Users/brandon/mini/infra/production.tfvars
```

Copy the value between the quotes.

### Configure the Apps Script

1. In the Sheet: Extensions → Apps Script
2. Confirm the latest [Code.gs](#) is pasted in (the version with
   `setProductionConfig`, `syncAllTeas`, `_runSync`, etc.)
3. Cmd+S to save
4. From the function dropdown, select `setProductionConfig` → Run
5. First time: complete the Google OAuth consent (scary "this script is
   unverified" screen — normal for Apps Scripts hitting external APIs)
6. Switch to the Sheet tab → the token prompt appeared there
7. Paste the production operator token → OK
8. Success popup: "Production config saved..."

### Verify Script Properties

Apps Script editor → Project Settings (left sidebar gear icon) → scroll to
Script properties. You should see:

| Property | Value |
|---|---|
| `SYNC_URL` | `https://60ohinmt7k.execute-api.us-west-2.amazonaws.com/admin/api/manual-count-sync-batch` |
| `SYNC_TOKEN` | (the pasted token) |
| `ENVIRONMENT` | `production` |
| `MERCHANT_ID` | `MLXZ38BC27GAD` |
| `LOCATION_ID` | `LZ4JV6WQHPQVE` |

### Assign a sheet button

1. In the Sheet: Insert → Drawing → make a button shape with text "Sync to Square"
2. Save and Close
3. Three-dot menu on the button → Assign script → type `syncAllTeas` → OK

The boss now clicks that button to start a recount sync.

## Boss's recount workflow (recurring)

Every time she does a physical recount:

1. Open the Sheet → Sheet1
2. Add a **new column** to the right with today's date as the header
   (e.g., column `AN`, header `6/19`)
3. Fill in the **physical count** for each row in that column. Leave cells
   blank for items she didn't count this time (those rows just don't get
   synced this round).
4. Click the **Sync to Square** button.
5. Wait ~5 seconds — a popup appears titled "Inventory sync preview"
   showing `CHANGED` rows with `Square before → Physical count` deltas.
6. **Review** the changes:
   - Big surprises (e.g., TGY going from 200 → 0) probably mean a typo
   - Familiar deltas (e.g., TGY 205 → 191, lost ~14 bags) are normal recount-vs-reality drift
7. Click **YES** to apply, or **NO** to cancel without pushing anything.
8. On YES: a second popup confirms `APPLIED` — Square is now synced.

Within a few seconds of YES, Mosa Tea's Square dashboard reflects the new
counts.

## The five keys the script CAN'T sync

The Lambda's `SUPPORTED_INVENTORY_KEYS` whitelist (see
[`app/manual_count_sync.py`](../app/manual_count_sync.py)) intentionally
excludes:

- `milk`
- `heavy_cream`
- `frozen_mango`
- `frozen_strawberry`
- `powdered_sugar`

These items still get **deducted** by the worker when orders fire (their
recipes use them) — they just can't be **seeded or recounted** via the
batch endpoint right now. Until they're added to the whitelist, the boss
must set their counts via the **Square dashboard directly**:

1. Items & services → Item library → Backend Inventory filter
2. Click the item → variation → Stock action → **Physical count**
3. Enter the count → Save

This is annoying for 5 items but acceptable. Tracked as a followup PR.

## Troubleshooting

### Popup never appears after clicking the sync button

Apps Script bound to a Sheet shows dialogs in the **Sheet tab**, not the
Apps Script editor tab. If you ran `syncAllTeas` from the editor, switch to
the Sheet tab — the dialog is there.

If neither tab shows a dialog: open the Apps Script editor → Executions tab
(left sidebar clock icon) → check the latest run for an error.

### "Missing Script Property: SYNC_URL"

`setProductionConfig` wasn't run yet, or the Script Properties got cleared.
Re-run `setProductionConfig` and re-paste the token.

### "no counted_unit configured for inventory_key 'XYZ'"

Column C of that row has a value not in `COUNTED_UNIT_BY_KEY` in the script.
Either:
- Typo in column C (most common — should be e.g. `tgy` not `TGY` or `tgy_oolong`)
- New inventory key the script doesn't know about → add to
  `COUNTED_UNIT_BY_KEY` in the Apps Script, OR leave column C blank to skip

### "no non-highlighted count found for X"

The row has only cyan-highlighted cells in its count columns, or all cells
are empty. The script skipped it. Fill in a non-cyan physical count to
include it next sync.

### HTTP 401 / "Invalid or missing operator token"

`SYNC_TOKEN` Script Property is wrong or stale. Re-grep the current value
from `infra/production.tfvars` and re-run `setProductionConfig`. Don't
forget to rotate the production operator token (see
[`secrets-and-security.md`](secrets-and-security.md)) if you suspect leak.

### HTTP 500

Lambda crashed. Check `/aws/lambda/mosa-tea-manual-count-sync-prod`
CloudWatch logs. Most common cause historically: Python ABI mismatch after
a botched deploy. Re-deploy via Deploy Lambda Functions workflow.

### "PREPARATION ERRORS" listed but the sync still goes

The script intentionally syncs the rows it can prepare and reports the
ones it couldn't. Fix the reported rows for next sync. Already-synced rows
landed correctly.

## Switching to sandbox (testing only)

To run against the Default Test Account sandbox merchant instead of
Mosa Tea's production catalog, run `setSandboxConfig` instead of
`setProductionConfig`. All five Script Properties flip to sandbox values.
Same `syncAllTeas` function works either way.

Flip back to production with `setProductionConfig` when done.
