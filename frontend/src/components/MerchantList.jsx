import { formatMerchant } from "../utils.js";

export default function MerchantList({ merchants, emptyText }) {
  if (!merchants.length) {
    return <pre>{emptyText}</pre>;
  }

  return <pre>{merchants.map(formatMerchant).join("\n\n")}</pre>;
}
