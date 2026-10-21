"""تيليغرام — Bot API."""
import logging

import httpx

from .. import config

log = logging.getLogger("telegram")
API = "https://api.telegram.org/bot{token}/{method}"


async def send(chat_id: str, text: str) -> None:
    url = API.format(token=config.TELEGRAM_BOT_TOKEN, method="sendMessage")
    async with httpx.AsyncClient(timeout=20) as client:
        for part in _split(text):
            r = await client.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": part,
                    "disable_web_page_preview": True,
                },
            )
            if r.status_code != 200:
                log.error("فشل الإرسال: %s", r.text[:300])


async def typing(chat_id: str) -> None:
    url = API.format(token=config.TELEGRAM_BOT_TOKEN, method="sendChatAction")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json={"chat_id": chat_id, "action": "typing"})
    except httpx.HTTPError:
        pass


def parse(update: dict) -> tuple[str, str, str] | None:
    """-> (event_id, chat_id, text)"""
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return None
    text = msg.get("text") or msg.get("caption")
    if not text:
        return None
    chat_id = str(msg["chat"]["id"])
    event_id = f"tg:{update.get('update_id')}"
    return event_id, chat_id, text


def _split(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]
    out, buf = [], ""
    for line in text.split("\n"):
        if len(buf) + len(line) + 1 > limit:
            out.append(buf)
            buf = line
        else:
            buf = f"{buf}\n{line}" if buf else line
    if buf:
        out.append(buf)
    return out
