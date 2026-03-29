import json
from datetime import datetime

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse
from app.catalog_change_search import (
    get_latest_updated_at,
    search_changed_catalog_objects,
    summarize_changed_object,
)
from app.catalog_sync_state import get_or_create_last_synced_at, update_last_synced_at
from app.config import (
    get_square_webhook_signature_key,
    get_square_webhook_notification_url,
)
from app.order_processing_db import get_order_processing_state, list_order_processing_rows
from app.order_processor import process_orders
from square.utils.webhooks_helper import verify_signature

app = FastAPI()


ADMIN_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Order Processing Admin</title>
  <style>
    :root {
      --bg: #f6f2ea;
      --panel: #fffaf1;
      --text: #1f1a17;
      --muted: #74685d;
      --border: #d9ccbd;
      --pending: #b7791f;
      --blocked: #c05621;
      --failed: #c53030;
      --applied: #2f855a;
    }
    body {
      margin: 0;
      background: linear-gradient(180deg, #f1eadf 0%%, var(--bg) 100%%);
      color: var(--text);
      font-family: Georgia, "Times New Roman", serif;
    }
    main {
      max-width: 1040px;
      margin: 0 auto;
      padding: 24px;
    }
    h1 {
      margin: 0 0 8px;
      font-size: 2rem;
    }
    .meta {
      color: var(--muted);
      margin-bottom: 18px;
    }
    .toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      margin-bottom: 14px;
    }
    .filters {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .filter-btn {
      border: 1px solid var(--border);
      background: #f8efe2;
      color: var(--text);
      border-radius: 999px;
      padding: 8px 12px;
      cursor: pointer;
      font: inherit;
    }
    .filter-btn.active {
      background: #1f1a17;
      color: #fffaf1;
      border-color: #1f1a17;
    }
    .status {
      margin-left: auto;
      color: var(--muted);
      font-size: 0.92rem;
    }
    .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 16px;
      overflow: hidden;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.04);
    }
    table {
      width: 100%%;
      border-collapse: collapse;
    }
    th, td {
      padding: 12px 14px;
      border-bottom: 1px solid var(--border);
      text-align: left;
      vertical-align: top;
      font-size: 0.95rem;
    }
    th {
      background: #f3eadc;
      font-size: 0.82rem;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--muted);
    }
    tr:last-child td {
      border-bottom: 0;
    }
    .state {
      font-weight: 700;
    }
    .pending { color: var(--pending); }
    .blocked { color: var(--blocked); }
    .failed { color: var(--failed); }
    .applied { color: var(--applied); }
    code {
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 0.85rem;
    }
    .action-btn {
      border: 1px solid var(--border);
      background: #fff;
      color: var(--text);
      border-radius: 10px;
      padding: 6px 10px;
      cursor: pointer;
      font: inherit;
    }
    .action-btn:disabled {
      cursor: default;
      opacity: 0.55;
    }
  </style>
</head>
<body>
  <main>
    <h1>Order Processing Admin</h1>
    <div class="meta" id="meta">Loading...</div>
    <div class="toolbar">
      <div class="filters" id="filters"></div>
      <div class="status" id="status"></div>
    </div>
    <div class="panel">
      <table>
        <thead>
          <tr>
            <th>Order ID</th>
            <th>State</th>
            <th>Applied At</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody id="rows"></tbody>
      </table>
    </div>
  </main>
  <script>
    let allRows = [];
    let currentFilter = "all";

    function stateCounts(rows) {
      const counts = { all: rows.length, pending: 0, blocked: 0, failed: 0, applied: 0 };
      for (const row of rows) {
        if (counts[row.processing_state] !== undefined) counts[row.processing_state] += 1;
      }
      return counts;
    }

    function renderFilters(rows) {
      const counts = stateCounts(rows);
      const filters = ["all", "pending", "blocked", "failed", "applied"];
      document.getElementById("filters").innerHTML = filters.map((filter) => `
        <button class="filter-btn ${filter === currentFilter ? "active" : ""}" onclick="setFilter('${filter}')">
          ${filter} (${counts[filter]})
        </button>
      `).join("");
    }

    function filteredRows() {
      if (currentFilter === "all") return allRows;
      return allRows.filter((row) => row.processing_state === currentFilter);
    }

    async function replayOrder(orderId) {
      const status = document.getElementById("status");
      status.textContent = `Replaying ${orderId}...`;
      const response = await fetch(`/admin/api/replay-order/${orderId}`, { method: "POST" });
      const result = await response.json();
      status.textContent = `Replay finished for ${orderId}: ${result.processing_state_after ?? "unknown"}`;
      await refresh();
    }

    function renderRows() {
      const rows = filteredRows();
      const tbody = document.getElementById("rows");
      tbody.innerHTML = rows.map((row) => `
        <tr>
          <td><code>${row.square_order_id}</code></td>
          <td><span class="state ${row.processing_state}">${row.processing_state}</span></td>
          <td>${row.applied_at ?? ""}</td>
          <td>
            ${(row.processing_state === "failed" || row.processing_state === "blocked")
              ? `<button class="action-btn" onclick="replayOrder('${row.square_order_id}')">Replay</button>`
              : `<button class="action-btn" disabled>No Action</button>`}
          </td>
        </tr>
      `).join("");
    }

    function setFilter(filter) {
      currentFilter = filter;
      renderFilters(allRows);
      renderRows();
    }

    async function refresh() {
      const response = await fetch("/admin/api/order-processing");
      allRows = await response.json();
      const meta = document.getElementById("meta");
      meta.textContent = `Auto-refreshing every 3 seconds. Rows: ${allRows.length}. Updated: ${new Date().toLocaleTimeString()}`;
      renderFilters(allRows);
      renderRows();
    }
    refresh();
    setInterval(refresh, 3000);
  </script>
</body>
</html>
"""


def _parse_rfc3339(timestamp):
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


def _get_event_type(payload):
    return payload.get("type", "")


def _get_order_event_data(payload):
    data = payload.get("data", {})
    object_data = data.get("object", {})
    return object_data.get("order_created") or object_data.get("order_updated") or {}


def _get_order_id_from_payload(payload):
    order_data = _get_order_event_data(payload)
    return order_data.get("order_id")


@app.get("/admin/api/order-processing")
async def admin_order_processing_api():
    return list_order_processing_rows()


@app.get("/admin/order-processing", response_class=HTMLResponse)
async def admin_order_processing_page():
    return HTMLResponse(content=ADMIN_HTML)


@app.post("/admin/api/replay-order/{order_id}")
async def admin_replay_order(order_id: str):
    current_processing_state = get_order_processing_state(order_id)
    result = process_orders([order_id], apply_changes=True)
    processing_state_after = get_order_processing_state(order_id)
    return {
        "order_id": order_id,
        "current_processing_state": current_processing_state,
        "processing_state_after": processing_state_after,
        "inventory_response": result["inventory_response"],
        "skipped_orders": result["skipped_orders"],
        "skipped_line_items": result["skipped_line_items"],
    }


@app.post("/webhook/square")
async def square_webhook(request: Request):
    signature_header = request.headers.get("x-square-hmacsha256-signature", "")
    request_body = (await request.body()).decode("utf-8")

    is_valid = verify_signature(
        request_body=request_body,
        signature_header=signature_header,
        signature_key=get_square_webhook_signature_key(),
        notification_url=get_square_webhook_notification_url(),
    )

    if not is_valid:
        return Response(
            content='{"error":"invalid signature"}',
            media_type="application/json",
            status_code=403,
        )

    payload = json.loads(request_body)
    event_type = _get_event_type(payload)
    order_event_data = _get_order_event_data(payload)
    order_id = _get_order_id_from_payload(payload)
    order_state = order_event_data.get("state")
    location_id = order_event_data.get("location_id")
    updated_at = order_event_data.get("updated_at")
    version = order_event_data.get("version")

    if event_type in {"order.created", "order.updated"}:
        current_processing_state = (
            get_order_processing_state(order_id) if order_id else None
        )
        should_start_processing = (
            order_state == "COMPLETED"
            and order_id is not None
            and current_processing_state is None
        )

        if should_start_processing:
            process_orders([order_id], apply_changes=True)

        processing_state_after = (
            get_order_processing_state(order_id) if order_id else None
        )

        print("order_webhook:")
        print(
            json.dumps(
                {
                    "event_type": event_type,
                    "order_id": order_id,
                    "state": order_state,
                    "location_id": location_id,
                    "updated_at": updated_at,
                    "version": version,
                    "current_processing_state": current_processing_state,
                    "marked_pending": should_start_processing,
                    "processing_state_after": processing_state_after,
                },
                indent=2,
            )
        )
        return {"ok": True}

    if payload.get("type") == "catalog.version.updated":
        last_synced_at = get_or_create_last_synced_at()
        print("catalog_webhook:")
        print(
            json.dumps(
                {
                    "event_type": event_type,
                    "last_synced_at": last_synced_at,
                },
                indent=2,
            )
        )

        changed_objects = search_changed_catalog_objects(last_synced_at)
        changed_summaries = [
            summarize_changed_object(catalog_object)
            for catalog_object in changed_objects
        ]
        print("catalog_changes:")
        print(json.dumps(changed_summaries, indent=2))

        latest_object_updated_at = get_latest_updated_at(changed_objects)

        if not latest_object_updated_at:
            print("checkpoint unchanged: no changed objects found")
            return {"ok": True}

        if _parse_rfc3339(latest_object_updated_at) <= _parse_rfc3339(last_synced_at):
            print("checkpoint unchanged: latest changed object is not newer")
            return {"ok": True}

        update_last_synced_at(latest_object_updated_at)
        print(f"updated checkpoint to: {latest_object_updated_at}")

    return {"ok": True}
