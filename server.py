from fastapi import FastAPI, Request

app = FastAPI()

@app.get("/")
def root():
    return {"message": "Mosa Tea backend running"}

@app.post("/webhook")
async def webhook(request: Request):
    body = await request.json()
    print("Webhook received:", body)
    return {"status": "ok"}