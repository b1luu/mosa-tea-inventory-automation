from datetime import UTC, datetime
from decimal import Decimal
import hashlib

from square.core.api_error import ApiError

from app.catalog_binding_resolver import resolve_inventory_variation_id
from app.client import create_square_client_for_merchant
from app.merchant_store import get_active_catalog_binding, get_merchant_context
from app.order_inventory_projection import load_inventory_item_map

DEFAULT_STATES = ("IN_STOCK", "WASTE")
SUPPORTED_INVENTORY_KEYS = {
    "black_tea",
    "green_tea",
    "tgy",
    "4s",
    "barley",
    "buckwheat",
    "genmai",
    "boba",
    "non_dairy_creamer",
    "lychee_jelly",
    "cream_foam_powder",
    "brown_sugar",
    "tj_powder",
    "hk_powder",
    "osmanthus_honey",
    "orange_syrup",
    "grapefruit_syrup",
    "grapefruit_can",
    "apple_syrup",
    "lemon_syrup",
    "strawberry_syrup",
    "mango_syrup",
    "sugar_syrup",
    "small_straw",
    "big_straw",
    "u600_cup",
    "cold_cup_lid",
    "hot_cup",
    "hot_lid",
    "pistachio",
    "sample_cup",
    "matcha",
    "matcha_jelly_matcha",

}


def _utcnow_rfc3339():
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _normalize_decimal(value):
    return Decimal(str(value))


def _normalize_state(value):
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


def _get_inventory_item(inventory_key):
    inventory_item = load_inventory_item_map().get(inventory_key)
    if not inventory_item:
        raise ValueError(f"Unknown inventory key: {inventory_key}")
    return inventory_item


def _build_reference_id(
    environment,
    merchant_id,
    location_id,
    inventory_key,
    counted_quantity,
    source_reference,
):
    digest = hashlib.sha256(
        "|".join(
            [
                environment,
                merchant_id,
                location_id,
                inventory_key,
                str(counted_quantity),
                source_reference or "",
            ]
        ).encode("utf-8")
    ).hexdigest()[:16]
    return f"manual-count:{inventory_key}:{digest}"


def _build_idempotency_key(reference_id, occurred_at):
    digest = hashlib.sha256(
        "|".join([reference_id, occurred_at]).encode("utf-8")
    ).hexdigest()
    return f"manual-count-sync:{digest}"


def _build_batch_idempotency_key(reference_ids, occurred_at):
    digest = hashlib.sha256(
        "|".join([*sorted(reference_ids), occurred_at]).encode("utf-8")
    ).hexdigest()
    return f"manual-count-sync-batch:{digest}"


def _summarize_counts(counts):
    summary = {
        "in_stock_quantity": Decimal("0"),
        "waste_quantity": Decimal("0"),
        "states": {},
    }

    for state in DEFAULT_STATES:
        summary["states"][state] = {
            "quantity": Decimal("0"),
            "calculated_at": None,
        }

    for count in counts:
        state = _normalize_state(getattr(count, "state", None))
        if not state:
            continue
        summary["states"][state] = {
            "quantity": _normalize_decimal(getattr(count, "quantity", "0")),
            "calculated_at": getattr(count, "calculated_at", None),
        }

    summary["in_stock_quantity"] = summary["states"]["IN_STOCK"]["quantity"]
    summary["waste_quantity"] = summary["states"]["WASTE"]["quantity"]
    return summary


def _build_physical_count_request(
    *,
    reference_id,
    catalog_object_id,
    location_id,
    counted_quantity,
    occurred_at,
):
    return {
        "idempotency_key": _build_idempotency_key(reference_id, occurred_at),
        "changes": [
            _build_physical_count_change(
                reference_id=reference_id,
                catalog_object_id=catalog_object_id,
                location_id=location_id,
                counted_quantity=counted_quantity,
                occurred_at=occurred_at,
            )
        ],
        "ignore_unchanged_counts": True,
    }


def _build_physical_count_change(
    *,
    reference_id,
    catalog_object_id,
    location_id,
    counted_quantity,
    occurred_at,
):
    return {
        "type": "PHYSICAL_COUNT",
        "physical_count": {
            "reference_id": reference_id,
            "catalog_object_id": catalog_object_id,
            "state": "IN_STOCK",
            "location_id": location_id,
            "quantity": str(counted_quantity),
            "occurred_at": occurred_at,
        },
    }


def _validate_manual_sync_context(environment, merchant_id, location_id, apply_changes):
    merchant_context = get_merchant_context(environment, merchant_id)
    if not merchant_context or merchant_context.status != "active":
        raise ValueError("No active merchant context is available for this sync request.")

    binding = get_active_catalog_binding(environment, merchant_id, location_id)
    if binding is None:
        raise ValueError(
            "No approved catalog binding is available for this merchant/location."
        )

    if apply_changes and not merchant_context.writes_enabled:
        raise ValueError("Inventory writes are disabled pending owner approval.")

    return merchant_context, binding


def _prepare_manual_count_entry(
    *,
    environment,
    merchant_id,
    location_id,
    inventory_key,
    counted_quantity,
    counted_unit,
    source_reference,
    binding,
):
    if inventory_key not in SUPPORTED_INVENTORY_KEYS:
        raise ValueError(
            f"Unsupported inventory key for manual count sync: {inventory_key!r}."
        )

    inventory_item = _get_inventory_item(inventory_key)
    expected_unit = inventory_item.get("stock_unit") or inventory_item["unit"]
    if counted_unit != expected_unit:
        raise ValueError(
            f"Unsupported counted unit for {inventory_key!r}: {counted_unit!r}. "
            f"Expected {expected_unit!r}."
        )

    counted_quantity_decimal = _normalize_decimal(counted_quantity).quantize(
        Decimal("0.00001")
    )
    catalog_object_id = resolve_inventory_variation_id(inventory_key, binding)
    reference_id = _build_reference_id(
        environment,
        merchant_id,
        location_id,
        inventory_key,
        counted_quantity_decimal,
        source_reference,
    )

    return {
        "inventory_key": inventory_key,
        "catalog_object_id": catalog_object_id,
        "counted_quantity": counted_quantity_decimal,
        "counted_unit": counted_unit,
        "source_reference": source_reference,
        "reference_id": reference_id,
    }


def _fetch_current_square_counts_by_catalog_object_id(
    client,
    *,
    catalog_object_ids,
    location_id,
):
    try:
        counts = list(
            client.inventory.batch_get_counts(
                catalog_object_ids=catalog_object_ids,
                location_ids=[location_id],
                states=list(DEFAULT_STATES),
            )
        )
    except ApiError as error:
        raise ValueError(f"Square API error while fetching inventory counts: {error}") from error

    counts_by_catalog_object_id = {catalog_object_id: [] for catalog_object_id in catalog_object_ids}
    for count in counts:
        catalog_object_id = getattr(count, "catalog_object_id", None)
        if catalog_object_id is None and len(catalog_object_ids) == 1:
            catalog_object_id = catalog_object_ids[0]
        if catalog_object_id in counts_by_catalog_object_id:
            counts_by_catalog_object_id[catalog_object_id].append(count)

    return {
        catalog_object_id: _summarize_counts(catalog_counts)
        for catalog_object_id, catalog_counts in counts_by_catalog_object_id.items()
    }


def _serialize_response_model(response):
    if hasattr(response, "model_dump"):
        return response.model_dump(mode="json")
    if hasattr(response, "dict"):
        return response.dict()
    return str(response)


def sync_manual_inventory_count(
    *,
    environment,
    merchant_id,
    location_id,
    inventory_key,
    counted_quantity,
    counted_unit,
    apply_changes=False,
    source_reference=None,
):
    _, binding = _validate_manual_sync_context(
        environment,
        merchant_id,
        location_id,
        apply_changes,
    )
    client = create_square_client_for_merchant(environment, merchant_id)
    prepared_entry = _prepare_manual_count_entry(
        environment=environment,
        merchant_id=merchant_id,
        location_id=location_id,
        inventory_key=inventory_key,
        counted_quantity=counted_quantity,
        counted_unit=counted_unit,
        source_reference=source_reference,
        binding=binding,
    )
    current_summary_by_catalog_object_id = _fetch_current_square_counts_by_catalog_object_id(
        client,
        catalog_object_ids=[prepared_entry["catalog_object_id"]],
        location_id=location_id,
    )
    current_summary = current_summary_by_catalog_object_id[prepared_entry["catalog_object_id"]]
    delta_in_stock = (
        prepared_entry["counted_quantity"] - current_summary["in_stock_quantity"]
    )
    inventory_request = _build_physical_count_request(
        reference_id=prepared_entry["reference_id"],
        catalog_object_id=prepared_entry["catalog_object_id"],
        location_id=location_id,
        counted_quantity=prepared_entry["counted_quantity"],
        occurred_at=_utcnow_rfc3339(),
    )

    inventory_response = None
    if apply_changes:
        if delta_in_stock == Decimal("0"):
            inventory_response = {"message": "Square inventory already matches the sheet count."}
        else:
            try:
                response = client.inventory.batch_create_changes(**inventory_request)
            except ApiError as error:
                raise ValueError(f"Square API error while applying physical count: {error}") from error
            inventory_response = _serialize_response_model(response)

    return {
        "mode": {"apply": apply_changes},
        "environment": environment,
        "merchant_id": merchant_id,
        "location_id": location_id,
        "inventory_key": inventory_key,
        "catalog_object_id": prepared_entry["catalog_object_id"],
        "counted_quantity": prepared_entry["counted_quantity"],
        "counted_unit": counted_unit,
        "current_square_count": current_summary,
        "delta": {
            "in_stock_quantity": delta_in_stock,
        },
        "inventory_request": inventory_request,
        "inventory_response": inventory_response,
    }


def sync_manual_inventory_counts_batch(
    *,
    environment,
    merchant_id,
    location_id,
    rows,
    apply_changes=False,
):
    if not rows:
        raise ValueError("At least one inventory row is required for batch manual sync.")

    _, binding = _validate_manual_sync_context(
        environment,
        merchant_id,
        location_id,
        apply_changes,
    )
    client = create_square_client_for_merchant(environment, merchant_id)

    prepared_entries = [
        _prepare_manual_count_entry(
            environment=environment,
            merchant_id=merchant_id,
            location_id=location_id,
            inventory_key=row["inventory_key"],
            counted_quantity=row["counted_quantity"],
            counted_unit=row["counted_unit"],
            source_reference=row.get("source_reference"),
            binding=binding,
        )
        for row in rows
    ]

    current_summary_by_catalog_object_id = _fetch_current_square_counts_by_catalog_object_id(
        client,
        catalog_object_ids=[entry["catalog_object_id"] for entry in prepared_entries],
        location_id=location_id,
    )

    occurred_at = _utcnow_rfc3339()
    row_results = []
    changes = []
    changed_reference_ids = []

    for entry in prepared_entries:
        current_summary = current_summary_by_catalog_object_id[entry["catalog_object_id"]]
        delta_in_stock = entry["counted_quantity"] - current_summary["in_stock_quantity"]
        change = _build_physical_count_change(
            reference_id=entry["reference_id"],
            catalog_object_id=entry["catalog_object_id"],
            location_id=location_id,
            counted_quantity=entry["counted_quantity"],
            occurred_at=occurred_at,
        )
        result = {
            "inventory_key": entry["inventory_key"],
            "catalog_object_id": entry["catalog_object_id"],
            "counted_quantity": entry["counted_quantity"],
            "counted_unit": entry["counted_unit"],
            "source_reference": entry["source_reference"],
            "current_square_count": current_summary,
            "delta": {
                "in_stock_quantity": delta_in_stock,
            },
            "inventory_change": change,
            "result": "unchanged" if delta_in_stock == Decimal("0") else "changed",
            "message": (
                "Square inventory already matches the sheet count."
                if delta_in_stock == Decimal("0")
                else "Included in batch physical count apply."
            ),
        }
        row_results.append(result)
        if delta_in_stock != Decimal("0"):
            changes.append(change)
            changed_reference_ids.append(entry["reference_id"])

    inventory_request = {
        "idempotency_key": (
            _build_batch_idempotency_key(changed_reference_ids, occurred_at)
            if changes
            else None
        ),
        "changes": changes,
        "ignore_unchanged_counts": True,
    }

    inventory_response = None
    if apply_changes:
        if not changes:
            inventory_response = {"message": "Square inventory already matches all sheet counts."}
        else:
            try:
                response = client.inventory.batch_create_changes(**inventory_request)
            except ApiError as error:
                raise ValueError(
                    f"Square API error while applying batch physical counts: {error}"
                ) from error
            inventory_response = _serialize_response_model(response)

    return {
        "mode": {"apply": apply_changes},
        "environment": environment,
        "merchant_id": merchant_id,
        "location_id": location_id,
        "summary": {
            "total_rows": len(row_results),
            "changed_rows": len(changes),
            "unchanged_rows": len(row_results) - len(changes),
        },
        "rows": row_results,
        "inventory_request": inventory_request,
        "inventory_response": inventory_response,
    }
