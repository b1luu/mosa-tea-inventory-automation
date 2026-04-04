export function safe(value, fallback = "-") {
  return value == null || value === "" ? fallback : String(value);
}

export function countBy(rows, key) {
  const counts = { total: rows.length };
  for (const row of rows) {
    const value = row?.[key] ?? "unknown";
    counts[value] = (counts[value] || 0) + 1;
  }
  return counts;
}

export function formatCounts(counts) {
  return Object.entries(counts)
    .map(([key, value]) => `${key}: ${value}`)
    .join(", ");
}

export function classifyMerchant(merchant) {
  const labels = [];
  const displayName = safe(merchant.display_name, "");
  const merchantId = safe(merchant.merchant_id, "");
  const combined = `${displayName} ${merchantId}`.toLowerCase();
  const hasAuth = Boolean(merchant.auth);
  const ready = Boolean(
    merchant.writes_enabled && merchant.binding_version && hasAuth,
  );
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

export function formatMerchant(merchant) {
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

export function formatOrder(order) {
  return [
    `${safe(order.square_order_id)}`,
    `  state: ${safe(order.processing_state)}`,
    `  applied_at: ${safe(order.applied_at)}`,
  ].join("\n");
}

export function formatEvent(event) {
  return [
    `${safe(event.event_id)}`,
    `  type: ${safe(event.event_type || event.data_type)}`,
    `  status: ${safe(event.status)}`,
    `  order_id: ${safe(event.order_id || event.data_id)}`,
    `  received_at: ${safe(event.received_at)}`,
  ].join("\n");
}
