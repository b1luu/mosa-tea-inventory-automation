from fastapi import FastAPI, Request, Response
from app.config import (
    get_square_webhook_signature_key,
    get_square_webhook_notification_url,
)
from square.utils.webhooks_helper import verify_signature

# Minimal viable Square webhook receiver for learning.

app = FastAPI()


@app.post("/webhook/square")
async def square_webhook(request: Request):
    signature_header = request.headers.get("x-square-hmacsha256-signature", "")
    request_body = (await request.body()).decode("utf-8")

    is_valid = verify_signature(
        request_body=request_body,
        signature_header=signature_header,
        signature_key=get_square_webhook_signature_key(),
        notification_url=get_square_webhook_notification_url(),
    )

    if not is_valid:
        return Response(
            content='{"error":"invalid signature"}',
            media_type="application/json",
            status_code=403,
        )

    headers = dict(request.headers)

    print(headers)
    print(request_body)

    return {"ok": True}
