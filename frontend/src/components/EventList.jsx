import { formatEvent } from "../utils.js";

export default function EventList({ events, errorMessage }) {
  if (errorMessage) {
    return <pre>{`Webhook events unavailable: ${errorMessage}`}</pre>;
  }

  if (!events.length) {
    return <pre>No webhook events found.</pre>;
  }

  return <pre>{events.slice(0, 12).map(formatEvent).join("\n\n")}</pre>;
}
