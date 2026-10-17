from boto3.dynamodb.conditions import Key

from app.config import get_aws_region, get_dynamodb_usage_log_table_name


def _create_dynamodb_resource():
    import boto3

    return boto3.resource("dynamodb", region_name=get_aws_region())


def _get_table():
    return _create_dynamodb_resource().Table(get_dynamodb_usage_log_table_name())


def put_usage_rows(rows):
    # Keys are deterministic per (order, ingredient), so a retried write
    # overwrites the same item instead of double-counting.
    with _get_table().batch_writer(overwrite_by_pkeys=["usage_key", "sold_at_order_id"]) as batch:
        for row in rows:
            batch.put_item(Item=row)


def query_usage_rows(usage_key, start_sold_at, end_sold_at):
    table = _get_table()
    condition = Key("usage_key").eq(usage_key) & Key("sold_at_order_id").between(
        start_sold_at, end_sold_at
    )
    items = []
    kwargs = {"KeyConditionExpression": condition}
    while True:
        response = table.query(**kwargs)
        items.extend(
            item for item in response.get("Items", []) if item["sold_at_order_id"] < end_sold_at
        )
        if "LastEvaluatedKey" not in response:
            return items
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
