"""خادم الـ webhooks — يستقبل من القنوات الثلاث ويردّ عبر العقل نفسه."""
import asyncio
import hashlib
import hmac
import logging

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from . import brain, config, ingest, retrieve, store
from .channels import messenger, telegram, whatsapp

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("server")

app = FastAPI(title="Bayan", docs_url=None, redoc_url=None)


@app.on_event("startup")
async def startup() -> None:
    store.init()
    retrieve.warm()
    n = store.chunk_count()
    log.info("بيان جاهز — %d مقطع في قاعدة المعرفة", n)
    if n == 0:
        log.warning("قاعدة المعرفة فارغة! شغّل: python -m app.ingest")


@app.get("/healthz")
async def healthz():
    return {"ok": True, "chunks": store.chunk_count()}


def _verify_meta(body: bytes, signature: str | None) -> None:
    """التحقق من توقيع Meta — يمنع أي طرف ثالث من حقن رسائل."""
    if not config.META_APP_SECRET:
        raise HTTPException(500, "META_APP_SECRET غير مضبوط")
    if not signature or not signature.startswith("sha256="):
        raise HTTPException(403, "توقيع مفقود")
    expected = hmac.new(
        config.META_APP_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature.split("=", 1)[1]):
        raise HTTPException(403, "توقيع غير صالح")


async def _reply(channel: str, user_id: str, text: str, sender) -> None:
    try:
        reply = await asyncio.to_thread(brain.handle, text, channel, user_id)
        await sender(user_id, reply)
    except Exception:
        log.exception("فشل في معالجة رسالة %s/%s", channel, user_id)


# ------------------------------------------------------------- تيليغرام
@app.post("/webhooks/telegram")
async def telegram_hook(
    request: Request,
    bg: BackgroundTasks,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    if config.TELEGRAM_WEBHOOK_SECRET and not hmac.compare_digest(
        x_telegram_bot_api_secret_token or "", config.TELEGRAM_WEBHOOK_SECRET
    ):
        raise HTTPException(403, "توقيع غير صالح")

    parsed = telegram.parse(await request.json())
    if parsed:
        event_id, chat_id, text = parsed
        if store.first_time(event_id):
            await telegram.typing(chat_id)
            bg.add_task(_reply, "telegram", chat_id, text, telegram.send)
    return {"ok": True}


# -------------------------------------------- واتساب + ماسنجر (Meta)
@app.get("/webhooks/meta")
async def meta_verify(request: Request):
    params = request.query_params
    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == config.META_VERIFY_TOKEN
    ):
        return PlainTextResponse(params.get("hub.challenge", ""))
    raise HTTPException(403, "فشل التحقق")


@app.post("/webhooks/meta")
async def meta_hook(
    request: Request,
    bg: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None),
):
    body = await request.body()
    _verify_meta(body, x_hub_signature_256)
    payload = await request.json()

    if payload.get("object") == "whatsapp_business_account":
        for event_id, wa_id, text in whatsapp.parse(payload):
            if store.first_time(event_id):
                bg.add_task(_reply, "whatsapp", wa_id, text, whatsapp.send)

    elif payload.get("object") == "page":
        for event_id, psid, text in messenger.parse(payload):
            if store.first_time(event_id):
                await messenger.typing(psid)
                bg.add_task(_reply, "messenger", psid, text, messenger.send)

    return JSONResponse({"ok": True})


# ------------------------------------------------------------- اختبار محلي
@app.post("/debug/ask")
async def debug_ask(request: Request):
    """اختبار العقل بدون أي قناة: POST {"question": "..."}"""
    data = await request.json()
    question = data.get("question", "")
    result = await asyncio.to_thread(retrieve.search, question)
    res = await asyncio.to_thread(
        brain.answer, question, "debug", data.get("user", "local")
    )
    return {
        "reply": res["text"],
        "outcome": res["outcome"],
        "confidence": round(res["confidence"], 3),
        "threshold": config.MIN_RELEVANCE,
        "matched_tools": [t["name"] for t in result["tools"]],
        "matched_category": (result["category"] or {}).get("category_ar"),
        "category_tools": len(result["category_tools"]),
        "passages": [
            {"type": p["type"], "title": p["title"], "url": p["url"]}
            for p in result["passages"]
        ],
    }


@app.post("/admin/reindex")
async def reindex(request: Request, x_bayan_secret: str | None = Header(default=None)):
    """إشارة إعادة الفهرسة من workflow مستودع الموقع.

    هذا هو السرّ الوحيد الذي يملكه مستودع الموقع. لا يمرّ عبره أي مفتاح
    من مفاتيح بيان: الخادم يسحب الموقع بنفسه بمفتاح قراءة فقط.
    """
    if not config.REINDEX_SECRET:
        raise HTTPException(500, "REINDEX_SECRET غير مضبوط")
    if not x_bayan_secret or not hmac.compare_digest(
        x_bayan_secret, config.REINDEX_SECRET
    ):
        raise HTTPException(403, "سرّ غير صالح")

    ok, detail = await asyncio.to_thread(ingest.run, True)
    if ok:
        await asyncio.to_thread(retrieve.warm)
    return JSONResponse({"ok": ok, "detail": detail}, status_code=200 if ok else 500)


@app.get("/admin/status")
async def status():
    return {"counts": store.counts(), "last_run": store.last_run()}
