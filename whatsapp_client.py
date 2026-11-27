from typing import List
import httpx

from config import GRAPH_API_VERSION, PHONE_NUMBER_ID, WHATSAPP_TOKEN


async def wa_post(payload: dict) -> None:
    if not WHATSAPP_TOKEN or not PHONE_NUMBER_ID:
        print("[wa] WHATSAPP_TOKEN / PHONE_NUMBER_ID missing, not sending")
        return
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{PHONE_NUMBER_ID}/messages"
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.post(
                url,
                headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
                json={"messaging_product": "whatsapp", "recipient_type": "individual", **payload},
            )
            if r.status_code != 200:
                print(f"[wa] Meta rejected: {r.status_code} {r.text}")
        except httpx.HTTPError as ex:
            print(f"[wa] send error: {ex}")


async def send_text(to: str, body: str) -> None:
    await wa_post({"to": to, "type": "text", "text": {"preview_url": False, "body": body}})


async def send_buttons(to: str, body: str, buttons: List[dict]) -> None:
    await wa_post(
        {
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body[:1024]},
                "action": {"buttons": [{"type": "reply", "reply": b} for b in buttons]},
            },
        }
    )