import { useEffect, useState } from "react";

import { fetchConsoleData } from "./api.js";
import {
  classifyMerchant,
  countBy,
  formatCounts,
  safe,
} from "./utils.js";
import Section from "./components/Section.jsx";
import BackendDiagram from "./components/BackendDiagram.jsx";
import MerchantList from "./components/MerchantList.jsx";
import OrderList from "./components/OrderList.jsx";
import EventList from "./components/EventList.jsx";

function buildDiagram(orders, events, visibleMerchants) {
  const latestOrder = orders[0] || null;
  return [
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
}

function buildMeta({
  visibleMerchants,
  hiddenMerchants,
  merchantResult,
  orderResult,
  eventResult,
}) {
  const errorNotes = [
    merchantResult.status === "rejected"
      ? `merchants failed: ${merchantResult.reason.message}`
      : null,
    orderResult.status === "rejected"
      ? `orders failed: ${orderResult.reason.message}`
      : null,
    eventResult.status === "rejected"
      ? `events failed: ${eventResult.reason.message}`
      : null,
  ].filter(Boolean);

  return `Updated ${new Date().toLocaleTimeString()} | real merchants: ${visibleMerchants.length} | hidden placeholders: ${hiddenMerchants.length}${errorNotes.length ? ` | ${errorNotes.join(" | ")}` : ""}`;
}

export default function App() {
  const [meta, setMeta] = useState("Loading...");
  const [diagram, setDiagram] = useState("Loading...");
  const [visibleMerchants, setVisibleMerchants] = useState([]);
  const [hiddenMerchants, setHiddenMerchants] = useState([]);
  const [orders, setOrders] = useState([]);
  const [events, setEvents] = useState([]);
  const [eventError, setEventError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    async function refresh() {
      try {
        const { merchantResult, orderResult, eventResult } = await fetchConsoleData();

        if (cancelled) {
          return;
        }

        const merchants =
          merchantResult.status === "fulfilled"
            ? (merchantResult.value.merchants || [])
            : [];
        const nextOrders =
          orderResult.status === "fulfilled" ? orderResult.value : [];
        const nextEvents =
          eventResult.status === "fulfilled" ? eventResult.value : [];
        const nextVisibleMerchants = merchants.filter(
          (merchant) => !classifyMerchant(merchant).placeholder,
        );
        const nextHiddenMerchants = merchants.filter((merchant) =>
          classifyMerchant(merchant).placeholder,
        );

        setVisibleMerchants(nextVisibleMerchants);
        setHiddenMerchants(nextHiddenMerchants);
        setOrders(nextOrders);
        setEvents(nextEvents);
        setEventError(
          eventResult.status === "rejected" ? eventResult.reason.message : null,
        );
        setDiagram(buildDiagram(nextOrders, nextEvents, nextVisibleMerchants));
        setMeta(
          buildMeta({
            visibleMerchants: nextVisibleMerchants,
            hiddenMerchants: nextHiddenMerchants,
            merchantResult,
            orderResult,
            eventResult,
          }),
        );
      } catch (error) {
        if (!cancelled) {
          setMeta(`Refresh failed: ${error.message}`);
        }
      }
    }

    refresh();
    const timerId = window.setInterval(refresh, 5000);

    return () => {
      cancelled = true;
      window.clearInterval(timerId);
    };
  }, []);

  return (
    <main>
      <h1>Mosa Tea React Console</h1>
      <p>Minimal React version of the backend console. Auto-refreshes every 5 seconds.</p>
      <p>{meta}</p>

      <Section title="Backend Flow">
        <BackendDiagram text={diagram} />
      </Section>

      <Section title="Merchants">
        <MerchantList
          merchants={visibleMerchants}
          emptyText="No real merchants found."
        />
      </Section>

      <Section title="Hidden Placeholder/Test Merchants">
        <MerchantList merchants={hiddenMerchants} emptyText="None." />
      </Section>

      <Section title="Recent Order Processing">
        <OrderList orders={orders} />
      </Section>

      <Section title="Recent Webhook Events">
        <EventList events={events} errorMessage={eventError} />
      </Section>
    </main>
  );
}
