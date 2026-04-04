import { formatOrder } from "../utils.js";

export default function OrderList({ orders }) {
  if (!orders.length) {
    return <pre>No order-processing rows found.</pre>;
  }

  return <pre>{orders.slice(0, 12).map(formatOrder).join("\n\n")}</pre>;
}
