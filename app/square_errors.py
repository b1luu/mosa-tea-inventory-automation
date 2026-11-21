def square_error_details(error):
    """The structured errors from a Square ApiError: category, code, detail, field.

    Use this, not str(error), for anything that is logged: str(ApiError)
    includes the response headers and the whole response body.
    """
    details = []
    for item in getattr(error, "errors", None) or []:
        details.append(
            {
                "category": _as_text(getattr(item, "category", None)),
                "code": _as_text(getattr(item, "code", None)),
                "detail": _as_text(getattr(item, "detail", None)),
                "field": _as_text(getattr(item, "field", None)),
            }
        )
    return details


def _as_text(value):
    return None if value is None else str(value)
