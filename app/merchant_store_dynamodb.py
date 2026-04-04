import json
from datetime import UTC, datetime

from botocore.exceptions import ClientError

from app.config import (
    get_aws_region,
    get_dynamodb_merchant_catalog_binding_table_name,
    get_dynamodb_merchant_connection_table_name,
    get_merchant_secret_prefix,
)
from app.merchant_store_constants import (
    AUTH_SOURCE_MANUAL_TOKEN,
    AUTH_SOURCE_OAUTH,
    BINDING_STATUS_APPROVED,
    BINDING_STATUS_ARCHIVED,
    BINDING_STATUS_DRAFT,
    MERCHANT_STATUS_ACTIVE,
    MERCHANT_STATUS_DISABLED,
    MERCHANT_STATUS_PENDING,
    MERCHANT_STATUS_REVOKED,
)


def _utcnow():
    return datetime.now(UTC).isoformat()


def _create_dynamodb_resource():
    import boto3

    return boto3.resource("dynamodb", region_name=get_aws_region())


def _create_secrets_manager_client():
    import boto3

    return boto3.client("secretsmanager", region_name=get_aws_region())


def _get_connection_table():
    return _create_dynamodb_resource().Table(get_dynamodb_merchant_connection_table_name())


def _get_binding_table():
    return _create_dynamodb_resource().Table(
        get_dynamodb_merchant_catalog_binding_table_name()
    )


def _get_connection_pk(environment, merchant_id):
    return f"{environment}#{merchant_id}"


def _get_binding_pk(environment, merchant_id, location_id):
    return f"{environment}#{merchant_id}#{location_id}"


def _get_secret_name(environment, merchant_id):
    return f"{get_merchant_secret_prefix()}/{environment}/{merchant_id}"


def _parse_json(value):
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


def _serialize_secret_payload(payload):
    return json.dumps(payload, sort_keys=True)


def _deserialize_secret_payload(secret_string):
    return json.loads(secret_string)


def _is_not_found(error):
    return error.response["Error"]["Code"] in {
        "ResourceNotFoundException",
        "ResourceNotFound",
    }


def _get_secret_payload(secret_name):
    client = _create_secrets_manager_client()
    try:
        response = client.get_secret_value(SecretId=secret_name)
    except ClientError as error:
        if _is_not_found(error):
            return None
        raise

    secret_string = response.get("SecretString")
    if not secret_string:
        return None
    return _deserialize_secret_payload(secret_string)


def _put_secret_payload(secret_name, payload):
    client = _create_secrets_manager_client()
    secret_string = _serialize_secret_payload(payload)
    try:
        client.create_secret(Name=secret_name, SecretString=secret_string)
    except ClientError as error:
        if not _is_not_found(error) and error.response["Error"]["Code"] != "ResourceExistsException":
            raise
        client.put_secret_value(SecretId=secret_name, SecretString=secret_string)


def _build_connection_item(
    environment,
    merchant_id,
    *,
    status,
    auth_mode,
    display_name=None,
    selected_location_id=None,
    writes_enabled=False,
    active_binding_version=None,
    created_at=None,
):
    now = _utcnow()
    return {
        "environment_merchant_id": _get_connection_pk(environment, merchant_id),
        "environment": environment,
        "merchant_id": merchant_id,
        "status": status,
        "auth_mode": auth_mode,
        "display_name": display_name,
        "selected_location_id": selected_location_id,
        "writes_enabled": bool(writes_enabled),
        "active_binding_version": active_binding_version,
        "created_at": created_at or now,
        "updated_at": now,
    }


def _build_binding_item(
    environment,
    merchant_id,
    location_id,
    version,
    mapping,
    *,
    status,
    notes=None,
    approved_at=None,
    created_at=None,
):
    now = _utcnow()
    return {
        "environment_merchant_location_id": _get_binding_pk(
            environment,
            merchant_id,
            location_id,
        ),
        "version": version,
        "environment": environment,
        "merchant_id": merchant_id,
        "location_id": location_id,
        "status": status,
        "mapping_json": json.dumps(mapping, sort_keys=True),
        "notes": notes,
        "approved_at": approved_at,
        "created_at": created_at or now,
        "updated_at": now,
    }


def _normalize_connection_item(item):
    if not item:
        return None

    return {
        "environment": item["environment"],
        "merchant_id": item["merchant_id"],
        "status": item["status"],
        "auth_mode": item["auth_mode"],
        "display_name": item.get("display_name"),
        "selected_location_id": item.get("selected_location_id"),
        "writes_enabled": bool(item.get("writes_enabled")),
        "active_binding_version": item.get("active_binding_version"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
    }


def _normalize_binding_item(item):
    if not item:
        return None

    return {
        "environment": item["environment"],
        "merchant_id": item["merchant_id"],
        "location_id": item["location_id"],
        "version": item["version"],
        "status": item["status"],
        "mapping": _parse_json(item.get("mapping_json")),
        "notes": item.get("notes"),
        "approved_at": item.get("approved_at"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
    }


def get_merchant_connection(environment, merchant_id):
    response = _get_connection_table().get_item(
        Key={"environment_merchant_id": _get_connection_pk(environment, merchant_id)},
        ConsistentRead=True,
    )
    return _normalize_connection_item(response.get("Item"))


def list_merchant_connections(status=None):
    table = _get_connection_table()
    scan_kwargs = {}
    if status is not None:
        from boto3.dynamodb.conditions import Attr

        scan_kwargs["FilterExpression"] = Attr("status").eq(status)

    response = table.scan(**scan_kwargs)
    items = response.get("Items", [])
    while "LastEvaluatedKey" in response:
        response = table.scan(
            ExclusiveStartKey=response["LastEvaluatedKey"],
            **scan_kwargs,
        )
        items.extend(response.get("Items", []))

    normalized = [_normalize_connection_item(item) for item in items]
    normalized.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return normalized


def upsert_merchant_connection(
    environment,
    merchant_id,
    *,
    status,
    auth_mode,
    display_name=None,
    selected_location_id=None,
    writes_enabled=False,
    active_binding_version=None,
):
    existing = get_merchant_connection(environment, merchant_id)
    _get_connection_table().put_item(
        Item=_build_connection_item(
            environment,
            merchant_id,
            status=status,
            auth_mode=auth_mode,
            display_name=display_name,
            selected_location_id=selected_location_id,
            writes_enabled=writes_enabled,
            active_binding_version=active_binding_version,
            created_at=(existing or {}).get("created_at"),
        )
    )


def set_merchant_connection_status(environment, merchant_id, status):
    connection = get_merchant_connection(environment, merchant_id)
    if not connection:
        return False

    upsert_merchant_connection(
        environment,
        merchant_id,
        status=status,
        auth_mode=connection["auth_mode"],
        display_name=connection["display_name"],
        selected_location_id=connection["selected_location_id"],
        writes_enabled=connection["writes_enabled"],
        active_binding_version=connection["active_binding_version"],
    )
    return True


def set_selected_location_id(environment, merchant_id, selected_location_id):
    connection = get_merchant_connection(environment, merchant_id)
    if not connection:
        return False

    upsert_merchant_connection(
        environment,
        merchant_id,
        status=connection["status"],
        auth_mode=connection["auth_mode"],
        display_name=connection["display_name"],
        selected_location_id=selected_location_id,
        writes_enabled=connection["writes_enabled"],
        active_binding_version=connection["active_binding_version"],
    )
    return True


def set_writes_enabled(environment, merchant_id, writes_enabled):
    connection = get_merchant_connection(environment, merchant_id)
    if not connection:
        return False

    upsert_merchant_connection(
        environment,
        merchant_id,
        status=connection["status"],
        auth_mode=connection["auth_mode"],
        display_name=connection["display_name"],
        selected_location_id=connection["selected_location_id"],
        writes_enabled=writes_enabled,
        active_binding_version=connection["active_binding_version"],
    )
    return True


def set_active_binding_version(environment, merchant_id, active_binding_version):
    connection = get_merchant_connection(environment, merchant_id)
    if not connection:
        return False

    upsert_merchant_connection(
        environment,
        merchant_id,
        status=connection["status"],
        auth_mode=connection["auth_mode"],
        display_name=connection["display_name"],
        selected_location_id=connection["selected_location_id"],
        writes_enabled=connection["writes_enabled"],
        active_binding_version=active_binding_version,
    )
    return True


def upsert_merchant_auth(
    environment,
    merchant_id,
    access_token,
    *,
    refresh_token=None,
    token_type=None,
    expires_at=None,
    short_lived=None,
    scopes=None,
    source,
):
    secret_name = _get_secret_name(environment, merchant_id)
    existing = get_merchant_auth(environment, merchant_id)
    now = _utcnow()
    payload = {
        "environment": environment,
        "merchant_id": merchant_id,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": token_type,
        "expires_at": expires_at,
        "short_lived": short_lived,
        "scopes": list(scopes) if scopes is not None else None,
        "source": source,
        "created_at": (existing or {}).get("created_at", now),
        "updated_at": now,
    }
    _put_secret_payload(secret_name, payload)


def get_merchant_auth(environment, merchant_id):
    payload = _get_secret_payload(_get_secret_name(environment, merchant_id))
    if not payload:
        return None
    return payload


def get_merchant_access_token(environment, merchant_id):
    record = get_merchant_auth(environment, merchant_id)
    if not record:
        return None
    return record["access_token"]


def upsert_merchant_catalog_binding(
    environment,
    merchant_id,
    location_id,
    version,
    mapping,
    *,
    status=BINDING_STATUS_DRAFT,
    notes=None,
    approved_at=None,
):
    existing = get_merchant_catalog_binding(environment, merchant_id, location_id, version)
    _get_binding_table().put_item(
        Item=_build_binding_item(
            environment,
            merchant_id,
            location_id,
            version,
            mapping,
            status=status,
            notes=notes,
            approved_at=approved_at,
            created_at=(existing or {}).get("created_at"),
        )
    )


def get_merchant_catalog_binding(environment, merchant_id, location_id, version):
    response = _get_binding_table().get_item(
        Key={
            "environment_merchant_location_id": _get_binding_pk(
                environment,
                merchant_id,
                location_id,
            ),
            "version": version,
        },
        ConsistentRead=True,
    )
    return _normalize_binding_item(response.get("Item"))


def get_active_catalog_binding(environment, merchant_id, location_id):
    from boto3.dynamodb.conditions import Key

    response = _get_binding_table().query(
        KeyConditionExpression=Key("environment_merchant_location_id").eq(
            _get_binding_pk(environment, merchant_id, location_id)
        ),
        ScanIndexForward=False,
    )
    for item in response.get("Items", []):
        if item.get("status") == BINDING_STATUS_APPROVED:
            return _normalize_binding_item(item)

    while "LastEvaluatedKey" in response:
        response = _get_binding_table().query(
            KeyConditionExpression=Key("environment_merchant_location_id").eq(
                _get_binding_pk(environment, merchant_id, location_id)
            ),
            ExclusiveStartKey=response["LastEvaluatedKey"],
            ScanIndexForward=False,
        )
        for item in response.get("Items", []):
            if item.get("status") == BINDING_STATUS_APPROVED:
                return _normalize_binding_item(item)

    return None


def list_merchant_catalog_bindings(environment, merchant_id, location_id=None, status=None):
    items = []
    table = _get_binding_table()

    if location_id is not None:
        from boto3.dynamodb.conditions import Key

        response = table.query(
            KeyConditionExpression=Key("environment_merchant_location_id").eq(
                _get_binding_pk(environment, merchant_id, location_id)
            ),
            ScanIndexForward=False,
        )
        items.extend(response.get("Items", []))
        while "LastEvaluatedKey" in response:
            response = table.query(
                KeyConditionExpression=Key("environment_merchant_location_id").eq(
                    _get_binding_pk(environment, merchant_id, location_id)
                ),
                ExclusiveStartKey=response["LastEvaluatedKey"],
                ScanIndexForward=False,
            )
            items.extend(response.get("Items", []))
    else:
        from boto3.dynamodb.conditions import Attr

        response = table.scan(
            FilterExpression=(
                Attr("environment").eq(environment)
                & Attr("merchant_id").eq(merchant_id)
            )
        )
        items.extend(response.get("Items", []))
        while "LastEvaluatedKey" in response:
            response = table.scan(
                ExclusiveStartKey=response["LastEvaluatedKey"],
                FilterExpression=(
                    Attr("environment").eq(environment)
                    & Attr("merchant_id").eq(merchant_id)
                ),
            )
            items.extend(response.get("Items", []))

    normalized = [_normalize_binding_item(item) for item in items]
    if status is not None:
        normalized = [item for item in normalized if item["status"] == status]

    normalized.sort(key=lambda item: (item["location_id"], -item["version"]))
    return normalized


def set_catalog_binding_status(
    environment,
    merchant_id,
    location_id,
    version,
    status,
    *,
    approved_at=None,
):
    binding = get_merchant_catalog_binding(environment, merchant_id, location_id, version)
    if not binding:
        return False

    upsert_merchant_catalog_binding(
        environment,
        merchant_id,
        location_id,
        version,
        binding["mapping"],
        status=status,
        notes=binding.get("notes"),
        approved_at=approved_at,
    )
    return True
