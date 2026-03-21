from fastapi import FastAPI, Request
from app.config import (
    get_square_webhook_signature_key,
    get_square_webhook_notification_url,
)
from square.utils.webhooks_helper import verify_signature

#Minimal viable webhook receiver for learning 

app = FastAPI()

@app.post("/webhook/square")
async def square_webhook(request: Request):
    headers = dict(request.headers)
    body = await request.body()
    text = body.decode("utf-8")

    print(headers)
    print(text)

    return {"ok": True}