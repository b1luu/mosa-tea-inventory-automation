from datetime import UTC, datetime

from botocore.exceptions import ClientError

from app.config import get_aws_region, get_dynamodb_order_processing_table_name
from app.order_processing_db import (
    PROCESSING_STATE_APPLIED,
    PROCESSING_STATE_BLOCKED,
    PROCESSING_STATE_FAILED,
    PROCESSING_STATE_PENDING,
)


def _create_dynamodb_resource():
    import boto3

    return boto3.resource("dynamodb", region_name=get_aws_region())


def _get_table():
    return _create_dynamodb_resource().Table(get_dynamodb_order_processing_table_name())


def _build_item(order_id, processing_state):
    now = datetime.now(UTC).isoformat()
    item = {
        "square_order_id": order_id,
        "processing_state": processing_state,
        "updated_at": now,
    }
    if processing_state == PROCESSING_STATE_APPLIED:
        item["applied_at"] = now
    return item


def _is_conditional_check_failed(error):
    return error.response["Error"]["Code"] == "ConditionalCheckFailedException"


def is_order_applied(order_id):
    return get_order_processing_state(order_id) == PROCESSING_STATE_APPLIED


def get_order_processing_state(order_id):
    response = _get_table().get_item(
        Key={"square_order_id": order_id},
        ConsistentRead=True,
    )
    item = response.get("Item")
    return item.get("processing_state") if item else None


def list_order_processing_rows(processing_state=None):
    scan_kwargs = {}
    if processing_state:
        from boto3.dynamodb.conditions import Attr

        scan_kwargs["FilterExpression"] = Attr("processing_state").eq(processing_state)

    items = []
    table = _get_table()
    response = table.scan(**scan_kwargs)
    items.extend(response.get("Items", []))

    while "LastEvaluatedKey" in response:
        response = table.scan(
            ExclusiveStartKey=response["LastEvaluatedKey"],
            **scan_kwargs,
        )
        items.extend(response.get("Items", []))

    items.sort(key=lambda item: item.get("updated_at", ""), reverse=True)

    return [
        {
            "square_order_id": item["square_order_id"],
            "processing_state": item["processing_state"],
            "applied_at": item.get("applied_at"),
        }
        for item in items
    ]


def set_order_processing_state(order_id, processing_state):
    return _get_table().put_item(Item=_build_item(order_id, processing_state))


def reserve_order_processing(order_id):
    try:
        _get_table().put_item(
            Item=_build_item(order_id, PROCESSING_STATE_PENDING),
            ConditionExpression="attribute_not_exists(square_order_id)",
        )
    except ClientError as error:
        if _is_conditional_check_failed(error):
            return False
        raise

    return True


def clear_order_processing_reservation(order_id):
    try:
        _get_table().delete_item(
            Key={"square_order_id": order_id},
            ConditionExpression="processing_state = :pending",
            ExpressionAttributeValues={":pending": PROCESSING_STATE_PENDING},
        )
    except ClientError as error:
        if _is_conditional_check_failed(error):
            return False
        raise

    return True


def mark_order_applied(order_id):
    set_order_processing_state(order_id, PROCESSING_STATE_APPLIED)


def mark_order_pending(order_id):
    set_order_processing_state(order_id, PROCESSING_STATE_PENDING)


def mark_order_failed(order_id):
    set_order_processing_state(order_id, PROCESSING_STATE_FAILED)


def mark_order_blocked(order_id):
    set_order_processing_state(order_id, PROCESSING_STATE_BLOCKED)
