import asyncio
from collections import deque
import hashlib
import hmac
import json

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from config import APP_SECRET, VERIFY_TOKEN, log_startup_config
from flows import handle_button, process_and_reply, process_location_reply
from storage import accept_booking_by_runner
from whatsapp_client import send_text

log_startup_config()

app = FastAPI(title="WhatsApp Civic Proxy Bot")

_bg: set = set()
_seen: deque = deque(maxlen=5000)


class RunnerAcceptPayload(BaseModel):
    runner_name: str = Field(..., min_length=1, max_length=100)


@app.post("/bookings/{ref}/accept")
async def runner_accept_booking(ref: str, payload: RunnerAcceptPayload):
    updated = await accept_booking_by_runner(ref.strip().upper(), payload.runner_name)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Booking {ref} not found")
    return {"status": "ok", "booking": updated}


@app.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
):
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        return PlainTextResponse(hub_challenge, status_code=200)
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Verification token mismatch")


@app.post("/webhook")
async def receive_webhook(request: Request):
    raw = await request.body()
    if APP_SECRET:
        expected = "sha256=" + hmac.new(APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, request.headers.get("x-hub-signature-256", "")):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bad signature")
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        return {"status": "invalid_json"}

    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            for msg in change.get("value", {}).get("messages", []):
                msg_id = msg.get("id")
                if msg_id in _seen:
                    continue
                if msg_id:
                    _seen.append(msg_id)
                sender, mtype = msg.get("from"), msg.get("type")

                if mtype == "text":
                    coro = process_and_reply(sender, msg["text"]["body"].strip())
                elif mtype == "location":
                    coro = process_location_reply(sender, msg.get("location", {}))
                elif mtype == "interactive":
                    coro = handle_button(sender, msg["interactive"].get("button_reply", {}).get("id", ""))
                else:
                    coro = send_text(
                        sender,
                        "Kripya apni request text mein likhein ya location ke liye 📎 *Location Pin* bhejein 🙏",
                    )

                task = asyncio.create_task(coro)
                _bg.add(task)
                task.add_done_callback(_bg.discard)
    return {"status": "success"}