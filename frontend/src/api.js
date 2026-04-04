async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${url} returned ${response.status}`);
  }
  return response.json();
}

export async function fetchConsoleData() {
  const [merchantResult, orderResult, eventResult] = await Promise.allSettled([
    fetchJson("/oauth/square/status"),
    fetchJson("/admin/api/order-processing"),
    fetchJson("/admin/api/webhook-events"),
  ]);

  return {
    merchantResult,
    orderResult,
    eventResult,
  };
}
