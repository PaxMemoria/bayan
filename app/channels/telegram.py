"""تيليغرام — Bot API.

Telegram: Bot API.
"""
import logging

import httpx

from .. import config
from .fmt import to_plain, to_telegram_html

log = logging.getLogger("telegram")
API = "https://api.telegram.org/bot{token}/{method}"


async def send(chat_id: str, text: str) -> None:
    url = API.format(token=config.TELEGRAM_BOT_TOKEN, method="sendMessage")
    async with httpx.AsyncClient(timeout=20) as client:
        for part in _split(text):
            body = {"chat_id": chat_id, "disable_web_page_preview": True}
            r = await client.post(
                url, json={**body, "text": to_telegram_html(part), "parse_mode": "HTML"}
            )
            # إن رفض تيليغرام التنسيق يُعاد الجزء نصاً عادياً: الرسالة لا تضيع
            # If Telegram rejects the formatting, the part is resent as plain
            # text: the message is never lost
            if r.status_code == 400:
                log.warning("رُفض التنسيق، يُعاد نصاً عادياً: %s", r.text[:200])
                r = await client.post(url, json={**body, "text": to_plain(part)})
            if r.status_code != 200:
                log.error("فشل الإرسال: %s", r.text[:300])


async def typing(chat_id: str) -> None:
    url = API.format(token=config.TELEGRAM_BOT_TOKEN, method="sendChatAction")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json={"chat_id": chat_id, "action": "typing"})
    except httpx.HTTPError:
        pass


def parse(update: dict) -> tuple[str, str, str, str | None] | None:
    """-> (event_id, chat_id, text, language_code)

    رسالة بلا نص (صورة، صوت، ملف…) تُعاد بنص فارغ كي يُجاب صاحبها بأن بيان
    يقرأ النص فقط، بدل أن يُترك بلا رد. language_code لغة واجهة تيليغرام
    عنده، وتحدد لغة الترحيب.
    A message without text (a photo, audio, a file, ...) comes back with empty
    text, so its sender is told Bayan reads text only instead of getting no
    reply. language_code is their Telegram interface language, and sets the
    welcome's language.
    """
    msg = update.get("message") or update.get("edited_message")
    if not msg or "chat" not in msg:
        return None
    text = msg.get("text") or msg.get("caption") or ""
    chat_id = str(msg["chat"]["id"])
    event_id = f"tg:{update.get('update_id')}"
    hint = (msg.get("from") or {}).get("language_code")
    return event_id, chat_id, text, hint


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
