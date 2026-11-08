"""خادم الـ webhooks — يستقبل من القنوات الثلاث ويردّ عبر العقل نفسه.

The webhook server: it receives from the three channels and replies
through the same brain.
"""
import asyncio
import hashlib
import hmac
import logging
import threading
import time

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse

from . import (brain, config, dashboard, embed, i18n, ingest, keys, privacy, retrieve, role,
               store)
from .channels import messenger, telegram, whatsapp

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("server")
# httpx يسجّل عنوان كل طلب، وواجهة تيليغرام تضع التوكن في العنوان نفسه
# (/bot<token>/sendMessage)، فلا تُسجَّل طلباته إلا عند خطأ
# httpx logs the address of every request, and the Telegram API puts the token
# in the address itself (/bot<token>/sendMessage), so its requests are logged
# only on errors
for name in ("httpx", "httpx2", "httpcore"):
    logging.getLogger(name).setLevel(logging.WARNING)

# كل كم دقيقة يُستعمل نموذج المتجهات المحلي كي يبقى في الذاكرة: على خادم مشترك
# تنقل لينكس الذاكرة الخاملة إلى ملف المبادلة، فيستغرق أول سؤال بعد ساعات
# خمول نحو 43 ثانية بدل بضع ثوانٍ
# How often, in minutes, the local embedding model is used so it stays in
# memory: on a shared server Linux moves idle memory to swap, so the first
# question after hours of idleness took about 43 seconds instead of a few
KEEP_WARM_MINUTES = 5

app = FastAPI(title="Bayan", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(dashboard.router)


@app.on_event("startup")
async def startup() -> None:
    store.init()
    # مفاتيح API المحفوظة من اللوحة تتقدّم على .env
    # API keys saved from the dashboard take precedence over .env
    if n := keys.apply_saved():
        log.info("طُبّق %d مفتاح API من اللوحة", n)
    if n := role.apply_saved():
        log.info("طُبّق %d نص من صفحة «دور بيان»", n)
    # الخادم يبدأ للتوّ، فلا فهرسة جارية: ما بقي مفتوحاً قطعته إعادة التشغيل
    # The server is just starting, so no indexing is running: whatever was
    # left open was cut off by the restart
    if n := store.close_interrupted_runs():
        log.warning("أُغلقت %d دورة فهرسة قطعتها إعادة التشغيل", n)
    retrieve.warm()
    # تحميل النموذج المحلي يستغرق ثوانيَ، فيجري في الخلفية والخادم يستقبل
    # Loading the local model takes seconds, so it runs in the background
    # while the server accepts requests
    threading.Thread(target=_preload, daemon=True).start()
    # حذف الأسئلة الأقدم من مدة الحفظ: عند الإقلاع ثم كل 6 ساعات
    # Delete questions older than the retention period: at startup, then
    # every 6 hours
    app.state.retention = asyncio.create_task(_retention_loop())
    app.state.comment_poll = asyncio.create_task(_comment_poll_loop())
    if config.EMBED_PROVIDER == "local":
        app.state.keep_warm = asyncio.create_task(_keep_warm_loop())
    if "local" in (config.ANSWER_MODEL, config.COMMENT_ANSWER_MODEL):
        app.state.local_warm = asyncio.create_task(_local_warm_loop())


def _preload() -> None:
    embed.preload()
    # تصحيح بلا متجه، أو بمتجه من نموذج سابق، يُولَّد متجهه بعد تحميل النموذج
    # A correction with no vector, or one from an earlier model, gets its
    # vector once the model is loaded
    try:
        if n := retrieve.refresh_correction_vectors():
            log.info("وُلّدت متجهات %d تصحيح", n)
    except Exception:  # noqa: BLE001
        log.exception("تعذّر توليد متجهات التصحيحات")


async def _keep_warm_loop() -> None:
    while True:
        await asyncio.sleep(KEEP_WARM_MINUTES * 60)
        try:
            if embed.enabled():
                await asyncio.to_thread(embed.embed, ["."], "query", 1)
        except Exception:  # noqa: BLE001
            log.exception("تعذّر إبقاء نموذج المتجهات في الذاكرة")


LOCAL_WARM_MINUTES = 30


async def _local_warm_loop() -> None:
    """يسخّن النموذج المحلي بعد الإقلاع ثم كل نصف ساعة: الطلب الأول يقرأ الجزء
    الثابت من الطلب (دقائق على المعالج)، وما بعده ثوانٍ ما دام محفوظاً. إن تعذّر
    (خادم النموذج لم يُقلع بعد) يعيد المحاولة بعد دقيقة.
    Warms the local model after start-up and then every half hour: the first
    request reads the fixed part of the prompt (minutes on the CPU), later ones
    take seconds while it stays cached. On failure (the model server not up
    yet) it retries after a minute."""
    delay = 20
    while True:
        await asyncio.sleep(delay)
        try:
            t = time.time()
            ok = await asyncio.to_thread(brain.warm_local)
            log.info("تسخين النموذج المحلي: %s في %.0f ث", "تم" if ok else "رُفض", time.time() - t)
            delay = LOCAL_WARM_MINUTES * 60 if ok else 60
        except Exception:  # noqa: BLE001
            log.warning("تعذّر تسخين النموذج المحلي، محاولة أخرى بعد دقيقة", exc_info=True)
            delay = 60


# ردود التعليقات تُعالج بالتوازي (ثلاثة في وقت واحد): رد محلي يستغرق دقائق لا يؤخّر
# ردود «فرص» الفورية خلفه
# Comment replies run concurrently (three at a time): a local reply that takes
# minutes does not hold up the instant «فرص» replies behind it
_comment_slots = asyncio.Semaphore(3)


async def _reply_comment_task(user_id: str, comment_id: str, text: str) -> None:
    async with _comment_slots:
        await _reply_comment(user_id, comment_id, text)


async def _comment_poll_loop() -> None:
    seeded = False
    while True:
        if not config.MESSENGER_PAGE_TOKEN:
            await asyncio.sleep(15)
            continue
        try:
            comments = await messenger.fetch_recent_comments()
            if not seeded:
                for event_id, _, _, _ in comments:
                    store.first_time(event_id)
                seeded = True
            else:
                for event_id, user_id, comment_id, text in comments:
                    if store.first_time(event_id):
                        asyncio.create_task(_reply_comment_task(user_id, comment_id, text))
        except Exception:  # noqa: BLE001
            log.exception("تعذّر فحص تعليقات فيسبوك الدورية")
        await asyncio.sleep(15)


async def _retention_loop() -> None:
    days = config.MESSAGE_RETENTION_DAYS
    while True:
        try:
            n = await asyncio.to_thread(store.purge_old_messages, days)
            if n:
                log.info("حُذفت %d رسالة أقدم من %d يوماً", n, days)
        except Exception:  # noqa: BLE001
            log.exception("تعذّر حذف الرسائل القديمة")
        await asyncio.sleep(6 * 3600)
    n = store.chunk_count()
    log.info("بيان جاهز — %d مقطع في قاعدة المعرفة", n)
    if n == 0:
        log.warning("قاعدة المعرفة فارغة! شغّل: python -m app.ingest")


@app.get("/", include_in_schema=False)
async def root():
    """لا صفحة لبيان على الويب: الزائر يُحال إلى موقع المنظمة.
    Bayan has no web page: visitors are redirected to the organization's site."""
    return RedirectResponse(config.SITE_URL, status_code=302)


@app.get("/privacy", include_in_schema=False)
async def privacy_page():
    """سياسة الخصوصية، بالعربية والإنجليزية.
    The privacy policy, in Arabic and English."""
    return privacy.page()


@app.get("/healthz")
async def healthz():
    return {"ok": True, "chunks": store.chunk_count()}


def _verify_meta(body: bytes, signature: str | None) -> None:
    """التحقق من توقيع Meta — يمنع أي طرف ثالث من حقن رسائل.
    Verify Meta's signature, which stops any third party from injecting messages."""
    if not config.META_APP_SECRET:
        raise HTTPException(500, "META_APP_SECRET غير مضبوط")
    if not signature or not signature.startswith("sha256="):
        raise HTTPException(403, "توقيع مفقود")
    expected = hmac.new(
        config.META_APP_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature.split("=", 1)[1]):
        raise HTTPException(403, "توقيع غير صالح")


async def _reply(channel: str, user_id: str, text: str, sender,
                 lang_hint: str | None = None) -> None:
    try:
        reply = await asyncio.to_thread(brain.handle, text, channel, user_id, lang_hint)
    except Exception:
        log.exception("فشل في معالجة رسالة من %s", channel)
        reply = i18n.msg("error", i18n.detect(text))
    try:
        for part in brain.messages(reply):
            await sender(user_id, part)
    except Exception:
        log.exception("فشل إرسال الرد على %s", channel)


async def _reply_comment(user_id: str, comment_id: str, text: str) -> None:
    try:
        reply = await asyncio.to_thread(brain.handle_comment, text, "messenger", user_id)
    except Exception:
        log.exception("فشل في معالجة تعليق من فيسبوك")
        return
    if not reply:
        return
    await messenger.like_comment(comment_id)
    try:
        await messenger.send_private_reply(comment_id, reply)
    except Exception:
        log.exception("فشل إرسال الرد الخاص على تعليق فيسبوك")


# ------------------------------------------------------------- تيليغرام / Telegram
@app.post("/webhooks/telegram")
async def telegram_hook(
    request: Request,
    bg: BackgroundTasks,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    # بلا سرّ يستطيع أي أحد أن يرسل إلى هذا الرابط تحديثات مزيّفة، فيجعل
    # بيان يراسل محادثات باسم المنظمة ويستهلك رصيد النموذج.
    # Without a secret, anyone could send fake updates to this URL, making
    # Bayan message chats in the organization's name and use up model credit.
    if not config.TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(500, "TELEGRAM_WEBHOOK_SECRET غير مضبوط")
    if not hmac.compare_digest(
        x_telegram_bot_api_secret_token or "", config.TELEGRAM_WEBHOOK_SECRET
    ):
        raise HTTPException(403, "توقيع غير صالح")

    parsed = telegram.parse(await request.json())
    if parsed:
        event_id, chat_id, text, hint = parsed
        if store.first_time(event_id):
            await telegram.typing(chat_id)
            bg.add_task(_reply, "telegram", chat_id, text, telegram.send, hint)
    return {"ok": True}


# --------------------------------- واتساب + ماسنجر (Meta) / WhatsApp + Messenger (Meta)
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
        for event_id, user_id, address, text in whatsapp.parse(payload):
            if store.first_time(event_id):
                bg.add_task(_reply, "whatsapp", user_id, text, whatsapp.sender(address))

    elif payload.get("object") == "page":
        for event_id, psid, text in messenger.parse(payload):
            if store.first_time(event_id):
                await messenger.typing(psid)
                bg.add_task(_reply, "messenger", psid, text, messenger.send)
        for event_id, user_id, comment_id, text in messenger.parse_comments(payload):
            if store.first_time(event_id):
                bg.add_task(_reply_comment, user_id, comment_id, text)

    return JSONResponse({"ok": True})


# ---------------------------------------------------------- اختبار محلي / Local testing
LOOPBACK = {"127.0.0.1", "::1"}


@app.post("/debug/ask")
async def debug_ask(request: Request):
    """اختبار العقل بدون أي قناة: POST {"question": "..."}

    من داخل الخادم وحده (docker compose exec). مفتوحاً للعموم كان سيتيح
    لأي أحد استدعاء النموذج بلا حدّ معدل ورؤية المقاطع المسترجعة.
    من المتصفح: صفحة «جرّب بيان» في اللوحة.

    Test the brain without any channel: POST {"question": "..."}

    Only from inside the server (docker compose exec). Open to the public,
    it would let anyone call the model with no rate limit and see the
    retrieved passages. From a browser: the Try Bayan («جرّب بيان») page in
    the dashboard.
    """
    if not request.client or request.client.host not in LOOPBACK:
        raise HTTPException(404)
    data = await request.json()
    question = data.get("question", "")
    res = await asyncio.to_thread(brain.answer, question, "debug", "local")
    result = res["retrieval"] or {"tools": [], "category": None,
                                  "category_tools": [], "passages": []}
    return {
        "reply": res["text"],
        "outcome": res["outcome"],
        "confidence": round(res["confidence"], 3),
        "threshold": brain.threshold(),
        "used_vectors": result.get("used_vectors", False),
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

    The reindex signal from the site repository's workflow.

    This is the only secret the site repository holds. None of Bayan's keys
    pass through it: the server pulls the site itself with a read-only key.
    """
    if not config.REINDEX_SECRET:
        raise HTTPException(500, "REINDEX_SECRET غير مضبوط")
    if not x_bayan_secret or not hmac.compare_digest(
        x_bayan_secret, config.REINDEX_SECRET
    ):
        raise HTTPException(403, "سرّ غير صالح")

    # الفهرسة تستغرق دقائق على معالج خادم، فتبدأ في الخلفية ويعود الرد فوراً.
    # النتيجة في اللوحة، والخادم يلتقط الفهرس الجديد بنفسه عند اكتماله.
    # Indexing takes minutes on a server CPU, so it starts in the background
    # and the response returns at once. The result is in the dashboard, and
    # the server picks up the new index by itself when it is complete.
    state = ingest.start_background(pull=True)
    detail = {
        "started": "بدأت الفهرسة. النتيجة في لوحة التحكم.",
        "queued": "فهرسة جارية الآن، وستتبعها دورة تشمل هذا التعديل.",
    }[state]
    return JSONResponse({"ok": True, "state": state, "detail": detail}, status_code=202)


@app.get("/admin/status")
async def status(request: Request):
    if not dashboard.is_admin(request):
        raise HTTPException(404)
    return {"counts": store.counts(), "last_run": store.last_run(),
            "retrieval": retrieve.status()}
