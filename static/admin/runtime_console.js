"use strict";

const operatorToken = new URLSearchParams(window.location.search).get("operator_token");

function safe(value, fallback = "-") {
  return value == null || value === "" ? fallback : String(value);
}

function countBy(rows, key) {
  const counts = { total: rows.length };
  for (const row of rows) {
    const value = row?.[key] ?? "unknown";
    counts[value] = (counts[value] || 0) + 1;
  }
  return counts;
}

function formatCounts(counts) {
  return Object.entries(counts)
    .map(([key, value]) => `${key}: ${value}`)
    .join(", ");
}

function classifyMerchant(merchant) {
  const labels = [];
  const displayName = safe(merchant.display_name, "");
  const merchantId = safe(merchant.merchant_id, "");
  const combined = `${displayName} ${merchantId}`.toLowerCase();
  const hasAuth = Boolean(merchant.auth);
  const ready = Boolean(merchant.writes_enabled && merchant.binding_version && hasAuth);
  const looksPlaceholder =
    merchantId === "merchant-1" ||
    combined.includes("store a") ||
    combined.includes("test merchant") ||
    (!hasAuth && !merchant.binding_version && !merchant.writes_enabled);

  labels.push(looksPlaceholder ? "placeholder" : "real");
  labels.push(hasAuth ? "auth" : "no-auth");
  labels.push(merchant.writes_enabled ? "writes-on" : "writes-off");
  if (merchant.binding_version) {
    labels.push(`binding-v${merchant.binding_version}`);
  }
  if (ready) {
    labels.push("ready");
  }

  return {
    placeholder: looksPlaceholder,
    ready,
    labels,
  };
}

function formatMerchant(merchant) {
  const classification = classifyMerchant(merchant);
  return [
    `${safe(merchant.display_name, merchant.merchant_id)} (${safe(merchant.environment)})`,
    `  labels: ${classification.labels.join(", ")}`,
    `  merchant_id: ${safe(merchant.merchant_id)}`,
    `  status: ${safe(merchant.status)}`,
    `  location: ${safe(merchant.selected_location_id)}`,
    `  binding_version: ${safe(merchant.binding_version)}`,
    `  writes_enabled: ${safe(merchant.writes_enabled)}`,
    `  scopes: ${safe((merchant.auth?.scopes || []).join(", "), "none")}`,
  ].join("\n");
}

function formatOrder(order) {
  return [
    `${safe(order.square_order_id)}`,
    `  state: ${safe(order.processing_state)}`,
    `  applied_at: ${safe(order.applied_at)}`,
  ].join("\n");
}

function formatEvent(event) {
  return [
    `${safe(event.event_id)}`,
    `  type: ${safe(event.event_type || event.data_type)}`,
    `  status: ${safe(event.status)}`,
    `  order_id: ${safe(event.order_id || event.data_id)}`,
    `  received_at: ${safe(event.received_at)}`,
  ].join("\n");
}

async function fetchJson(url) {
  const resolvedUrl = new URL(url, window.location.origin);
  if (operatorToken) {
    resolvedUrl.searchParams.set("operator_token", operatorToken);
  }
  const response = await fetch(resolvedUrl);
  if (!response.ok) {
    throw new Error(`${resolvedUrl.pathname} returned ${response.status}`);
  }
  return response.json();
}

function setText(id, text) {
  document.getElementById(id).textContent = text;
}

async function refresh() {
  const [merchantResult, orderResult, eventResult] = await Promise.allSettled([
    fetchJson("/oauth/square/status"),
    fetchJson("/admin/api/order-processing"),
    fetchJson("/admin/api/webhook-events"),
  ]);

  const merchants = merchantResult.status === "fulfilled"
    ? (merchantResult.value.merchants || [])
    : [];
  const orders = orderResult.status === "fulfilled" ? orderResult.value : [];
  const events = eventResult.status === "fulfilled" ? eventResult.value : [];
  const visibleMerchants = merchants.filter(
    (merchant) => !classifyMerchant(merchant).placeholder,
  );
  const hiddenMerchants = merchants.filter(
    (merchant) => classifyMerchant(merchant).placeholder,
  );

  const latestOrder = orders[0] || null;
  const diagram = [
    "Square",
    "  |",
    `  | completed orders: ${orders.filter((row) => row.processing_state === "applied").length}`,
    "  v",
    `Ingress / webhook-events (${formatCounts(countBy(events, "status"))})`,
    "  |",
    "  v",
    `SQS / worker -> latest order state: ${safe(latestOrder?.processing_state, "none")}`,
    "  |",
    "  v",
    `Order processing store (${formatCounts(countBy(orders, "processing_state"))})`,
    "  |",
    "  v",
    `Merchant runtime ready: ${visibleMerchants.some((merchant) => classifyMerchant(merchant).ready) ? "yes" : "no"}`,
  ].join("\n");

  setText("diagram", diagram);
  setText(
    "merchants",
    visibleMerchants.length
      ? visibleMerchants.map(formatMerchant).join("\n\n")
      : "No real merchants found.",
  );
  setText(
    "hidden-merchants",
    hiddenMerchants.length
      ? hiddenMerchants.map(formatMerchant).join("\n\n")
      : "None.",
  );
  setText(
    "orders",
    orders.length ? orders.slice(0, 12).map(formatOrder).join("\n\n") : "No order-processing rows found.",
  );
  setText(
    "events",
    eventResult.status === "fulfilled"
      ? (events.length ? events.slice(0, 12).map(formatEvent).join("\n\n") : "No webhook events found.")
      : `Webhook events unavailable: ${eventResult.reason.message}`,
  );

  const errorNotes = [
    merchantResult.status === "rejected" ? `merchants failed: ${merchantResult.reason.message}` : null,
    orderResult.status === "rejected" ? `orders failed: ${orderResult.reason.message}` : null,
    eventResult.status === "rejected" ? `events failed: ${eventResult.reason.message}` : null,
  ].filter(Boolean);

  setText(
    "meta",
    `Updated ${new Date().toLocaleTimeString()} | real merchants: ${visibleMerchants.length} | hidden placeholders: ${hiddenMerchants.length}${errorNotes.length ? " | " + errorNotes.join(" | ") : ""}`,
  );
}

async function tick() {
  try {
    await refresh();
  } catch (error) {
    setText("meta", `Refresh failed: ${error.message}`);
  }
}

tick();
setInterval(tick, 5000);
