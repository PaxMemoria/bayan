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


def parse_comments(payload: dict) -> list[tuple[str, str, str, str]]:
    """تعليقات جديدة على منشورات صفحة فيسبوك -> [(event_id, user_id, comment_id, text)].

    يُستثنى تعليق الصفحة نفسها كي لا تردّ على نفسها.
    New comments on Facebook Page posts -> [(event_id, user_id, comment_id, text)].
    Comments posted by the Page itself are ignored so it never replies to itself.
    """
    out = []
    for entry in payload.get("entry", []):
        page_id = str(entry.get("id") or "")
        for change in entry.get("changes", []):
            if change.get("field") != "feed":
                continue
            val = change.get("value") or {}
            if val.get("item") != "comment" or val.get("verb") != "add":
                continue
            comment_id = val.get("comment_id")
            text = (val.get("message") or "").strip()
            sender_id = str((val.get("from") or {}).get("id") or "")
            if not comment_id or not text or sender_id == page_id:
                continue
            user_id = sender_id or f"comment:{comment_id}"
            out.append((f"fb_comment:{comment_id}", user_id, comment_id, text))
    return out


async def send_private_reply(comment_id: str, text: str) -> None:
    """يرسل رسالة خاصة على ماسنجر رداً على تعليق في منشور الصفحة (Private Reply).

    Meta تسمح برسالة خاصة واحدة فقط لكل تعليق (حتى 2000 حرف).
    Sends a private Messenger reply to a Page post comment (Private Reply).
    Meta allows only a single private reply per comment (up to 2000 chars).
    """
    url = f"https://graph.facebook.com/{config.META_GRAPH_VERSION}/me/messages"
    params = {"access_token": config.MESSENGER_PAGE_TOKEN}
    body = to_plain(text)[:1950]
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            url,
            params=params,
            json={
                "recipient": {"comment_id": comment_id},
                "message": {"text": body},
            },
        )
        if r.status_code >= 300:
            log.error("فشل إرسال الرد الخاص على التعليق: %s", r.text[:300])


async def fetch_recent_comments() -> list[tuple[str, str, str, str]]:
    """يجلب أحدث التعليقات من آخر منشورات الصفحة عبر Graph API.

    يعمل حتى حين يكون تطبيق Meta في وضع التطوير (Unpublished) ولا يرسل
    إشعارات feed webhook تلقائياً.
    Fetches recent comments from the Page's latest posts via the Graph API.
    Works even when the Meta app is in Development (Unpublished) mode and
    does not push feed webhooks automatically.
    """
    if not config.MESSENGER_PAGE_TOKEN:
        return []
    url = f"https://graph.facebook.com/{config.META_GRAPH_VERSION}/me/published_posts"
    params = {
        "access_token": config.MESSENGER_PAGE_TOKEN,
        "fields": "id,comments.limit(15){id,message,from,created_time}",
        "limit": 5,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, params=params)
        if r.status_code != 200:
            return []
        data = r.json()
    except Exception:  # noqa: BLE001
        return []

    out = []
    for post in data.get("data") or []:
        page_id = str(post.get("id") or "").split("_", 1)[0]
        for cm in (post.get("comments") or {}).get("data") or []:
            cid = cm.get("id")
            text = (cm.get("message") or "").strip()
            sender_id = str((cm.get("from") or {}).get("id") or "")
            if not cid or not text or (page_id and sender_id == page_id):
                continue
            user_id = sender_id or f"comment:{cid}"
            out.append((f"fb_comment:{cid}", user_id, cid, text))
    return out


def _split(text: str, limit: int = 1900) -> list[str]:
    return [text[i : i + limit] for i in range(0, len(text), limit)] or [text]
