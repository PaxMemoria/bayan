"""الدردشة على الموقع: قناة «web» يضمّنها موقع المنظمة بسطر واحد.

‎<script src="https://<PUBLIC_URL>/widget.js" defer></script>‎ يضع فقاعة في
زاوية الصفحة تفتح نافذة محادثة، والنافذة ترسل الأسئلة إلى POST /chat. يمرّ
كل سؤال بالمسار نفسه الذي تمرّ به القنوات الأخرى (brain.handle): البوابة
والقواعد والمصادر واللغات والحدّ اليومي.

الخصوصية: لا تسجيل دخول ولا كوكي. المتصفح ينشئ معرّفاً عشوائياً للمحادثة
ويحفظه في تخزينه المحلي، وهو المعرّف الوحيد الذي يصل إلى القاعدة. عنوان IP
يُستعمل في ذاكرة الخادم وحدها، ببصمة مملّحة، لحدود منع الإساءة، ولا يُحفظ.

لا يُقبل طلب إلا من موقع في WEB_CHAT_ORIGINS (CORS)، ويُطفأ من اللوحة.

The website chat: a "web" channel the organisation's site embeds with one
line. The script puts a bubble in the corner of the page that opens a chat
window, and the window sends questions to POST /chat. Every question goes
through the same path as the other channels (brain.handle): the gate, the
rules, the sources, the languages and the daily limit.

Privacy: no sign-in and no cookie. The browser creates a random
conversation ID and keeps it in its local storage, and that ID is the only
identifier that reaches the database. The IP address is used in the
server's memory only, as a salted fingerprint, for the abuse limits, and is
never stored.

A request is accepted only from a site in WEB_CHAT_ORIGINS (CORS), and the
channel can be switched off from the dashboard.
"""
import asyncio
import hashlib
import ipaddress
import json
import logging
import re
import secrets
import threading
import time
from collections import deque
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from . import brain, config, geo, i18n, store
from .channels import fmt

log = logging.getLogger("web")
router = APIRouter()

CHANNEL = "web"
_SESSION = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
MAX_BODY = 8192
_TEMPLATE = (Path(__file__).parent / "static" / "widget.js").read_text(encoding="utf-8")
_PLACEHOLDER = "__BAYAN_CONFIG__"


def enabled() -> bool:
    """القناة مفعّلة: لها موقع مسموح، ولم تُطفأ من اللوحة.
    The channel is on: it has an allowed site and was not switched off from
    the dashboard."""
    return bool(config.WEB_CHAT_ORIGINS) and store.setting("web_chat", "1") == "1"


# ────────────────────────────── حدود IP في الذاكرة / In-memory IP limits
_SALT = secrets.token_bytes(16)
_hits: dict[str, deque] = {}
_lock = threading.Lock()


def client_ip(host: str | None, forwarded_for: str | None) -> str:
    """عنوان السائل. خلف nginx على الخادم نفسه يأتي الطلب من عنوان محلي أو
    خاص، فيُؤخذ آخر عنوان في X-Forwarded-For (الذي أضافه nginx، لا ما أرسله
    المتصفح)؛ وإلا فعنوان الاتصال نفسه.
    The asker's address. Behind nginx on the same server, the request comes
    from a local or private address, so the last address in X-Forwarded-For
    is used (the one nginx appended, not what the browser sent); otherwise the
    connection's own address."""
    host = host or ""
    try:
        private = ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback
    except ValueError:
        private = False
    if private and forwarded_for:
        last = forwarded_for.split(",")[-1].strip()
        if last:
            return last
    return host or "?"


def _key(ip: str) -> str:
    return hashlib.sha256(_SALT + ip.encode()).hexdigest()[:20]


def ip_allowed(ip: str, now: float | None = None) -> bool:
    """يسجّل طلباً ويُرجع False إن تجاوز العنوان دفعة WEB_IP_BURST خلال
    WEB_IP_BURST_WINDOW ثانية أو WEB_IP_DAILY في 24 ساعة.
    Records a request and returns False if the address went over
    WEB_IP_BURST within WEB_IP_BURST_WINDOW seconds or WEB_IP_DAILY in 24
    hours."""
    now = time.time() if now is None else now
    k = _key(ip)
    with _lock:
        q = _hits.setdefault(k, deque())
        while q and q[0] < now - 86400:
            q.popleft()
        recent = sum(1 for t in q if t >= now - config.WEB_IP_BURST_WINDOW)
        if recent >= config.WEB_IP_BURST or len(q) >= config.WEB_IP_DAILY:
            return False
        q.append(now)
        # ذاكرة محدودة: يُحذف من لم يطلب شيئاً منذ يوم
        # Bounded memory: those with no request for a day are dropped
        if len(_hits) > 20000:
            for key in [key for key, d in _hits.items() if not d or d[-1] < now - 86400]:
                del _hits[key]
    return True


def reset_limits() -> None:
    with _lock:
        _hits.clear()


# ─────────────────────────────────────────── CORS
def _origin(request: Request) -> str | None:
    origin = (request.headers.get("origin") or "").rstrip("/")
    return origin if origin in config.WEB_CHAT_ORIGINS else None


def _cors(origin: str) -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Max-Age": "600",
        "Vary": "Origin",
    }


@router.options("/chat", include_in_schema=False)
async def chat_preflight(request: Request):
    origin = _origin(request)
    if not origin:
        return Response(status_code=403)
    return Response(status_code=204, headers=_cors(origin))


@router.post("/chat", include_in_schema=False)
async def chat(request: Request):
    origin = _origin(request)
    if not origin:
        return JSONResponse({"error": "origin"}, status_code=403)
    headers = _cors(origin)
    if int(request.headers.get("content-length") or 0) > MAX_BODY:
        return JSONResponse({"error": "too_large"}, status_code=413, headers=headers)
    try:
        data = json.loads((await request.body())[:MAX_BODY] or b"{}")
    except ValueError:
        return JSONResponse({"error": "bad_request"}, status_code=400, headers=headers)
    if not isinstance(data, dict):
        return JSONResponse({"error": "bad_request"}, status_code=400, headers=headers)
    session = str(data.get("session") or "")
    text = str(data.get("message") or "").strip()[: config.MAX_QUESTION_CHARS]
    lang_hint = str(data.get("lang") or "")[:12] or None
    if not _SESSION.match(session) or not text:
        return JSONResponse({"error": "bad_request"}, status_code=400, headers=headers)
    lang = i18n.detect(text) if text else (i18n.from_hint(lang_hint) or "en")
    if not enabled():
        return JSONResponse({"error": "disabled", "messages": [i18n.msg("paused", lang)]},
                            status_code=503, headers=headers)
    ip = client_ip(request.client.host if request.client else None,
                   request.headers.get("x-forwarded-for"))
    if not ip_allowed(ip):
        return JSONResponse({"error": "rate", "messages": [i18n.msg("rate", lang)]},
                            status_code=429, headers=headers)
    try:
        reply = await asyncio.to_thread(brain.handle, text, CHANNEL, session, lang_hint)
    except Exception:  # noqa: BLE001
        log.exception("فشل في معالجة رسالة من الموقع")
        reply = i18n.msg("error", lang)
    return JSONResponse({"messages": [fmt.to_web(m) for m in brain.messages(reply)]},
                        headers=headers)


@router.get("/lang", include_in_schema=False)
async def visitor_lang(request: Request):
    """لغة الودجت حسب بلد الزائر، من قاعدة محلية؛ لا يُحفظ العنوان ولا البلد،
    ولا يُحسب الطلب من حدود الأسئلة.
    The widget's language from the visitor's country, from a local database;
    neither the address nor the country is stored, and the request does not
    count towards the question limits."""
    origin = _origin(request)
    if not origin:
        return JSONResponse({"error": "origin"}, status_code=403)
    headers = {**_cors(origin), "Cache-Control": "private, no-store"}
    code = None
    if enabled():
        code = geo.language(client_ip(request.client.host if request.client else None,
                                      request.headers.get("x-forwarded-for")))
    return JSONResponse({"lang": code}, headers=headers)


# ─────────────────────────────────────────── الودجت / The widget
def widget_config() -> dict:
    """ما يحقنه الخادم في widget.js: نقطة الإرسال، ورابط الخصوصية، ونصوص
    الودجت بكل اللغات بأسماء البوت والمنظمة المناسبة لكل لغة.
    What the server injects into widget.js: the endpoint, the privacy link,
    and the widget's texts in every language with the bot's and the
    organisation's names that fit each language."""
    base = (config.PUBLIC_URL or "").rstrip("/")
    strings, rtl = {}, []
    for code in i18n.SUPPORTED_LANGUAGES:
        names = i18n._names(code)
        section = i18n.LOCALES[code].get("widget") or i18n.LOCALES[i18n.FALLBACK]["widget"]
        strings[code] = {k: v.format(**names) for k, v in section.items()}
        if i18n.script_of(code) == "arabic":
            rtl.append(code)
    return {"endpoint": f"{base}/chat", "privacy": f"{base}/privacy",
            "geo": f"{base}/lang" if config.GEO_LANG else "",
            "languages": list(i18n.SUPPORTED_LANGUAGES), "rtl": rtl, "strings": strings}


@router.get("/widget.js", include_in_schema=False)
async def widget():
    headers = {"Cache-Control": "public, max-age=600", "X-Content-Type-Options": "nosniff"}
    if not enabled():
        # بلا فقاعة حين تكون القناة مطفأة / No bubble while the channel is off
        return Response("/* Bayan web chat is switched off */\n",
                        media_type="application/javascript", headers=headers)
    cfg = json.dumps(widget_config(), ensure_ascii=False).replace("</", "<\\/")
    return Response(_TEMPLATE.replace(_PLACEHOLDER, cfg),
                    media_type="application/javascript", headers=headers)
