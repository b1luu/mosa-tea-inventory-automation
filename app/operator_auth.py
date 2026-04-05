from secrets import compare_digest

from fastapi import Header, HTTPException, Query, status

from app.config import get_operator_api_token


def _extract_bearer_token(authorization):
    if not authorization:
        return None

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def require_operator_access(
    authorization: str | None = Header(default=None),
    x_operator_token: str | None = Header(default=None, alias="X-Operator-Token"),
    operator_token: str | None = Query(default=None),
):
    try:
        expected_token = get_operator_api_token()
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error

    provided_token = (
        x_operator_token
        or operator_token
        or _extract_bearer_token(authorization)
    )
    if not provided_token or not compare_digest(provided_token, expected_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing operator token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

