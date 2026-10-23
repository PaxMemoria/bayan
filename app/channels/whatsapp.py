"""واتساب — WhatsApp Cloud API (Meta).

منذ نيسان/أبريل 2026 يحمل كل webhook معرّفاً خاصاً بنشاطنا (BSUID، مثل
US.13491208655302741918) في from_user_id، وقد يغيب رقم الهاتف (from) عمّن
اتخذ اسم مستخدم. لذا يُعرَّف المستخدم بالـBSUID، ويُرسل الرد إلى الرقم إن
وصل، وإلا إلى الـBSUID.

WhatsApp: WhatsApp Cloud API (Meta).

Since April 2026 every webhook carries an identifier scoped to our business
(a BSUID, such as US.13491208655302741918) in from_user_id, and the phone
number (from) may be missing for users who have adopted a username. So users
are identified by their BSUID, and the reply goes to the phone number when it
arrived, otherwise to the BSUID.
"""
import logging

import httpx

from .. import config
from .fmt import to_whatsapp

log = logging.getLogger("whatsapp")


async def send(to: str, text: str) -> None:
    """to: رقم هاتف (أرقام فقط) أو BSUID.
    to: a phone number (digits only) or a BSUID."""
    url = (
        f"https://graph.facebook.com/{config.META_GRAPH_VERSION}/"
        f"{config.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    headers = {"Authorization": f"Bearer {config.WHATSAPP_TOKEN}"}
    target = {"to": to} if to.isdigit() else {"recipient": to}
    async with httpx.AsyncClient(timeout=20) as client:
        for part in _split(text):
            r = await client.post(
                url,
                headers=headers,
                json={
                    "messaging_product": "whatsapp",
                    **target,
                    "type": "text",
                    "text": {"body": to_whatsapp(part), "preview_url": False},
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


def sender(address: str):
    """مُرسِل يردّ على عنوان الرسالة نفسها، لا على معرّف المستخدم المحفوظ.
    A sender that replies to the message's own address, not to the stored
    user identifier."""
    async def _send(_user_id: str, text: str) -> None:
        await send(address, text)
    return _send


def parse(payload: dict) -> list[tuple[str, str, str, str]]:
    """-> [(event_id, user_id, address, text)]

    user_id: الـBSUID، أو الرقم إن غاب. address: الرقم إن وصل، وإلا الـBSUID.
    user_id: the BSUID, or the phone number if it is missing. address: the
    phone number if it arrived, otherwise the BSUID.
    """
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
                    # صورة أو صوت أو ملف أو موقع: يُجاب صاحبها بأن بيان يقرأ النص فقط
                    # A photo, audio, file or location: its sender is told Bayan
                    # reads text only
                    text = ""
                phone, bsuid = msg.get("from"), msg.get("from_user_id")
                if not (phone or bsuid):
                    continue
                out.append((f"wa:{msg['id']}", bsuid or phone, phone or bsuid, text))
    return out


def _split(text: str, limit: int = 3800) -> list[str]:
    return [text[i : i + limit] for i in range(0, len(text), limit)] or [text]
