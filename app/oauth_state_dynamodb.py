import uuid
from datetime import UTC, datetime, timedelta

from botocore.exceptions import ClientError

from app.config import (
    get_aws_region,
    get_dynamodb_oauth_state_table_name,
    get_oauth_state_max_age_seconds,
)


def _utcnow():
    return datetime.now(UTC)


def _parse_datetime(value):
    if value is None:
        return None

    normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
    return datetime.fromisoformat(normalized)


def _create_dynamodb_resource():
    import boto3

    return boto3.resource("dynamodb", region_name=get_aws_region())


def _get_table():
    return _create_dynamodb_resource().Table(get_dynamodb_oauth_state_table_name())


def _is_conditional_check_failed(error):
    return error.response["Error"]["Code"] == "ConditionalCheckFailedException"


def _resolve_max_age_seconds(max_age_seconds):
    if max_age_seconds is not None:
        return max_age_seconds
    return get_oauth_state_max_age_seconds()


def create_oauth_state(environment):
    max_attempts = 3
    max_age_seconds = get_oauth_state_max_age_seconds()
    for _ in range(max_attempts):
        state = str(uuid.uuid4())
        created_at_dt = _utcnow()
        created_at = created_at_dt.isoformat()
        expires_at_epoch = int(
            (created_at_dt + timedelta(seconds=max_age_seconds)).timestamp()
        )

        try:
            _get_table().put_item(
                Item={
                    "state": state,
                    "environment": environment,
                    "created_at": created_at,
                    "expires_at_epoch": expires_at_epoch,
                },
                ConditionExpression="attribute_not_exists(#state)",
                ExpressionAttributeNames={"#state": "state"},
            )
        except ClientError as error:
            if _is_conditional_check_failed(error):
                continue
            raise

        return state

    raise RuntimeError(
        f"Unable to allocate a unique OAuth state after {max_attempts} attempts."
    )


def consume_oauth_state(state, *, max_age_seconds=None):
    resolved_max_age_seconds = _resolve_max_age_seconds(max_age_seconds)
    response = _get_table().get_item(
        Key={"state": state},
        ConsistentRead=True,
    )
    item = response.get("Item")
    if not item:
        return None

    created_at = _parse_datetime(item.get("created_at"))
    if created_at is None:
        return None

    if item.get("consumed_at") is not None:
        return None

    now = _utcnow()
    expires_at_epoch = item.get("expires_at_epoch")
    if expires_at_epoch is not None:
        if int(expires_at_epoch) < int(now.timestamp()):
            return None
        condition_expression = (
            "attribute_exists(#state) AND "
            "attribute_not_exists(consumed_at) AND "
            "expires_at_epoch >= :now_epoch"
        )
        expression_attribute_values = {
            ":consumed_at": now.isoformat(),
            ":now_epoch": int(now.timestamp()),
        }
    else:
        if now - created_at > timedelta(seconds=resolved_max_age_seconds):
            return None
        condition_expression = (
            "attribute_exists(#state) AND "
            "attribute_not_exists(consumed_at) AND "
            "created_at >= :min_created_at"
        )
        expression_attribute_values = {
            ":consumed_at": now.isoformat(),
            ":min_created_at": (
                now - timedelta(seconds=resolved_max_age_seconds)
            ).isoformat(),
        }

    consumed_at = now.isoformat()
    try:
        _get_table().update_item(
            Key={"state": state},
            UpdateExpression="SET consumed_at = :consumed_at",
            ConditionExpression=condition_expression,
            ExpressionAttributeNames={"#state": "state"},
            ExpressionAttributeValues=expression_attribute_values,
        )
    except ClientError as error:
        if _is_conditional_check_failed(error):
            return None
        raise

    return {
        "state": item["state"],
        "environment": item["environment"],
        "created_at": item["created_at"],
        "consumed_at": consumed_at,
    }
