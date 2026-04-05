const operatorToken = new URLSearchParams(window.location.search).get("operator_token");

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
