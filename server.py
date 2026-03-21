from fastapi import FastAPI, Request

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