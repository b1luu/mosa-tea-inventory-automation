from app.config import get_oauth_state_store_mode
from app import oauth_state_db, oauth_state_dynamodb


def _get_store_backend():
    store_mode = get_oauth_state_store_mode()
    if store_mode == "sqlite":
        return oauth_state_db
    if store_mode == "dynamodb":
        return oauth_state_dynamodb
    raise ValueError(f"Unsupported OAuth state store mode: {store_mode}")


def create_oauth_state(environment):
    return _get_store_backend().create_oauth_state(environment)


def consume_oauth_state(state, *, max_age_seconds=None):
    return _get_store_backend().consume_oauth_state(
        state,
        max_age_seconds=max_age_seconds,
    )
