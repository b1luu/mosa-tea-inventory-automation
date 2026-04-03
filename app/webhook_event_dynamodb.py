from datetime import UTC, datetime
from botocore.exceptions import ClientError

from app.config import get_aws_region, get_dynamodb_webhook_event_table_name
from app.webhook_event_db import (
    EVENT_STATUS_ENQUEUED,
    EVENT_STATUS_FAILED,
    EVENT_STATUS_IGNORED,
    EVENT_STATUS_PROCESSED,
    EVENT_STATUS_RECEIVED,
)

_ALLOWED_CURRENT_STATUSES_BY_TARGET_STATUS = {
    EVENT_STATUS_RECEIVED: {EVENT_STATUS_RECEIVED, EVENT_STATUS_FAILED},
    EVENT_STATUS_IGNORED: {
        EVENT_STATUS_IGNORED,
        EVENT_STATUS_RECEIVED,
        EVENT_STATUS_FAILED,
    },
    EVENT_STATUS_ENQUEUED: {EVENT_STATUS_ENQUEUED, EVENT_STATUS_RECEIVED},
    EVENT_STATUS_PROCESSED: {
        EVENT_STATUS_PROCESSED,
        EVENT_STATUS_RECEIVED,
        EVENT_STATUS_ENQUEUED,
    },
    EVENT_STATUS_FAILED: {
        EVENT_STATUS_FAILED,
        EVENT_STATUS_RECEIVED,
        EVENT_STATUS_ENQUEUED,
    },
}


def _create_dynamodb_resource():
    import boto3

    return boto3.resource("dynamodb", region_name=get_aws_region())


def _get_table():
    return _create_dynamodb_resource().Table(get_dynamodb_webhook_event_table_name())


def _is_conditional_check_failed(error):
    return error.response["Error"]["Code"] == "ConditionalCheckFailedException"


def get_webhook_event(event_id):
    response = _get_table().get_item(
        Key={"event_id": event_id},
        ConsistentRead=True,
    )
    item = response.get("Item")
    if not item:
        return None

    return {
        "event_id": item["event_id"],
        "merchant_id": item["merchant_id"],
        "event_type": item["event_type"],
        "event_created_at": item.get("event_created_at"),
        "data_type": item.get("data_type"),
        "data_id": item.get("data_id"),
        "order_id": item.get("order_id"),
        "order_state": item.get("order_state"),
        "location_id": item.get("location_id"),
        "version": item.get("version"),
        "status": item["status"],
        "received_at": item["received_at"],
        "updated_at": item["updated_at"],
    }


def has_webhook_event(event_id):
    return get_webhook_event(event_id) is not None


def upsert_webhook_event(
    *,
    event_id,
    merchant_id,
    event_type,
    event_created_at=None,
    data_type=None,
    data_id=None,
    order_id=None,
    order_state=None,
    location_id=None,
    version=None,
    status=EVENT_STATUS_RECEIVED,
):
    now = datetime.now(UTC).isoformat()
    _get_table().update_item(
        Key={"event_id": event_id},
        UpdateExpression=(
            "SET merchant_id = :merchant_id, "
            "event_type = :event_type, "
            "event_created_at = :event_created_at, "
            "data_type = :data_type, "
            "data_id = :data_id, "
            "order_id = :order_id, "
            "order_state = :order_state, "
            "location_id = :location_id, "
            "version = :version, "
            "#status = :status, "
            "received_at = if_not_exists(received_at, :received_at), "
            "updated_at = :updated_at"
        ),
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":merchant_id": merchant_id,
            ":event_type": event_type,
            ":event_created_at": event_created_at,
            ":data_type": data_type,
            ":data_id": data_id,
            ":order_id": order_id,
            ":order_state": order_state,
            ":location_id": location_id,
            ":version": version,
            ":status": status,
            ":received_at": now,
            ":updated_at": now,
        },
    )


def create_webhook_event(
    *,
    event_id,
    merchant_id,
    event_type,
    event_created_at=None,
    data_type=None,
    data_id=None,
    order_id=None,
    order_state=None,
    location_id=None,
    version=None,
    status=EVENT_STATUS_RECEIVED,
):
    now = datetime.now(UTC).isoformat()
    try:
        _get_table().put_item(
            Item={
                "event_id": event_id,
                "merchant_id": merchant_id,
                "event_type": event_type,
                "event_created_at": event_created_at,
                "data_type": data_type,
                "data_id": data_id,
                "order_id": order_id,
                "order_state": order_state,
                "location_id": location_id,
                "version": version,
                "status": status,
                "received_at": now,
                "updated_at": now,
            },
            ConditionExpression="attribute_not_exists(event_id)",
        )
    except ClientError as error:
        if _is_conditional_check_failed(error):
            return False
        raise

    return True


def set_webhook_event_status(event_id, status):
    allowed_current_statuses = _ALLOWED_CURRENT_STATUSES_BY_TARGET_STATUS.get(status)
    if not allowed_current_statuses:
        raise ValueError(f"Unsupported webhook event status transition target: {status}")

    expression_attribute_values = {
        ":status": status,
        ":updated_at": datetime.now(UTC).isoformat(),
    }
    allowed_status_placeholders = []
    for index, allowed_status in enumerate(sorted(allowed_current_statuses)):
        placeholder = f":allowed_{index}"
        allowed_status_placeholders.append(placeholder)
        expression_attribute_values[placeholder] = allowed_status

    try:
        _get_table().update_item(
            Key={"event_id": event_id},
            UpdateExpression="SET #status = :status, updated_at = :updated_at",
            ConditionExpression=(
                "attribute_exists(event_id) AND "
                f"#status IN ({', '.join(allowed_status_placeholders)})"
            ),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues=expression_attribute_values,
        )
    except ClientError as error:
        if _is_conditional_check_failed(error):
            return False
        raise

    return True


def list_webhook_events(status=None):
    scan_kwargs = {}
    if status:
        from boto3.dynamodb.conditions import Attr

        scan_kwargs["FilterExpression"] = Attr("status").eq(status)

    table = _get_table()
    response = table.scan(**scan_kwargs)
    items = response.get("Items", [])

    while "LastEvaluatedKey" in response:
        response = table.scan(
            ExclusiveStartKey=response["LastEvaluatedKey"],
            **scan_kwargs,
        )
        items.extend(response.get("Items", []))

    items.sort(key=lambda item: item.get("received_at", ""), reverse=True)

    return [
        {
            "event_id": item["event_id"],
            "merchant_id": item["merchant_id"],
            "event_type": item["event_type"],
            "event_created_at": item.get("event_created_at"),
            "data_type": item.get("data_type"),
            "data_id": item.get("data_id"),
            "order_id": item.get("order_id"),
            "order_state": item.get("order_state"),
            "location_id": item.get("location_id"),
            "version": item.get("version"),
            "status": item["status"],
            "received_at": item["received_at"],
            "updated_at": item["updated_at"],
        }
        for item in items
    ]
