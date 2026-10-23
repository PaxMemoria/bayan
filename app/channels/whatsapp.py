"""واتساب — WhatsApp Cloud API (Meta).

WhatsApp: WhatsApp Cloud API (Meta).
"""
import logging

import httpx

from .. import config

log = logging.getLogger("whatsapp")


async def send(to: str, text: str) -> None:
    url = (
        f"https://graph.facebook.com/{config.META_GRAPH_VERSION}/"
        f"{config.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    headers = {"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"}
    async with httpx.AsyncClient(timeout=20) as client:
        for part in _split(text):
            r = await client.post(
                url,
                headers=headers,
                json={
                    "messaging_product": "whatsapp",
                    "to": to,
                    "type": "text",
                    "text": {"body": part, "preview_url": False},
                },
            )
            if r.status_code >= 300:
                log.error("فشل الإرسال: %s", r.text[:300])


async def mark_read(message_id: str) -> None:
    url = (
        f"https://graph.facebook.com/{config.META_GRAPH_VERSION}/"
        f"{config.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                url,
                headers={"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"},
                json={
                    "messaging_product": "whatsapp",
                    "status": "read",
                    "message_id": message_id,
                },
            )
    except httpx.HTTPError:
        pass


def parse(payload: dict) -> list[tuple[str, str, str]]:
    """-> [(event_id, wa_id, text)]"""
    out = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []):
                if msg.get("type") == "text":
                    text = msg["text"]["body"]
                elif msg.get("type") == "interactive":
                    inter = msg["interactive"]
                    text = (
                        inter.get("button_reply", {}).get("title")
                        or inter.get("list_reply", {}).get("title", "")
                    )
                else:
                    continue
                if text:
                    out.append((f"wa:{msg['id']}", msg["from"], text))
    return out


def _split(text: str, limit: int = 3800) -> list[str]:
    return [text[i : i + limit] for i in range(0, len(text), limit)] or [text]
