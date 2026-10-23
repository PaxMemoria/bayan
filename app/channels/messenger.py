"""فيسبوك ماسنجر — Messenger Platform.

Facebook Messenger: Messenger Platform.
"""
import logging

import httpx

from .. import config
from .fmt import to_plain

log = logging.getLogger("messenger")


async def send(psid: str, text: str) -> None:
    url = f"https://graph.facebook.com/{config.META_GRAPH_VERSION}/me/messages"
    params = {"access_token": config.MESSENGER_PAGE_TOKEN}
    async with httpx.AsyncClient(timeout=20) as client:
        for part in _split(text):
            r = await client.post(
                url,
                params=params,
                json={
                    "recipient": {"id": psid},
                    "messaging_type": "RESPONSE",
                    "message": {"text": to_plain(part)},
                },
            )
            if r.status_code >= 300:
                log.error("فشل الإرسال: %s", r.text[:300])


async def typing(psid: str) -> None:
    url = f"https://graph.facebook.com/{config.META_GRAPH_VERSION}/me/messages"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                url,
                params={"access_token": config.MESSENGER_PAGE_TOKEN},
                json={"recipient": {"id": psid}, "sender_action": "typing_on"},
            )
    except httpx.HTTPError:
        pass


def parse(payload: dict) -> list[tuple[str, str, str]]:
    """-> [(event_id, psid, text)]"""
    out = []
    for entry in payload.get("entry", []):
        for event in entry.get("messaging", []):
            msg = event.get("message") or {}
            if msg.get("is_echo"):
                continue
            text = msg.get("text") or (event.get("postback") or {}).get("title")
            # مرفق بلا نص: يُجاب صاحبه بأن بيان يقرأ النص فقط
            # An attachment without text: its sender is told Bayan reads text only
            if text is None and msg.get("attachments"):
                text = ""
            psid = (event.get("sender") or {}).get("id")
            if text is not None and psid:
                mid = msg.get("mid") or f"{psid}:{event.get('timestamp')}"
                out.append((f"fb:{mid}", psid, text))
    return out


def _split(text: str, limit: int = 1900) -> list[str]:
    return [text[i : i + limit] for i in range(0, len(text), limit)] or [text]
