"""لوحة تحكم بيان — عربية، بلا JavaScript، خلف كلمة مرور.

تعرض حالة الفهرس والمتجهات، وأسئلة الجمهور ونتيجة كل منها، وتجربة بيان
دون قناة، والعتبة وزر الإيقاف، والمحظورين.

الخصوصية: معرّف واتساب هو رقم الهاتف، فلا تعرض اللوحة أي معرّف. كل
مستخدم يظهر ببصمة مشتقّة بـ SESSION_SECRET لا تُعكس إلى رقمه، والحظر
يُنفَّذ برقم الرسالة لا بالمعرّف.
"""
import asyncio
import hashlib
import hmac
import html
import time
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from . import brain, config, embed, ingest, retrieve, store

router = APIRouter()

COOKIE = "bayan_admin"
SESSION_HOURS = 12
MAX_FORM_BYTES = 16_384

OUTCOMES = {
    "answered": ("أُجيب", "ok"),
    "tool_list": ("قائمة أدوات", "ok"),
    "refused_gate": ("رفضته البوابة", "warn"),
    "refused_model": ("رفضه النموذج", "muted"),
    "error": ("خطأ", "bad"),
}
CHANNELS = {"telegram": "تيليغرام", "whatsapp": "واتساب", "messenger": "ماسنجر"}
TYPES = {"tool": "أداة", "tool_removed": "أداة مُزالة", "investigation": "تحقيق"}

# رسائل ما بعد الإجراء: مفاتيح ثابتة، فلا يُعرض في الصفحة نص من الرابط.
FLASH = {
    "reindex": ("ok", "بدأت الفهرسة، وتستغرق دقائق. حدّث الصفحة بعدها لترى النتيجة."),
    "busy": ("warn", "فهرسة جارية الآن، وستتبعها دورة أخرى تشمل آخر تعديل."),
    "saved": ("ok", "حُفظت الإعدادات."),
    "blocked": ("ok", "حُظر المستخدم. لن يتلقى بعد الآن إلا رسالة الرفض."),
    "unblocked": ("ok", "رُفع الحظر."),
}

e = html.escape

# الإعداد الذي عويِرت عليه MIN_RELEVANCE الافتراضية (scripts/calibrate.py)
CALIBRATED_FOR = "voyage-4-nano@1024"


# ─────────────────────────────────────────────────────── الدخول
def configured() -> bool:
    return len(config.ADMIN_PASSWORD) >= 12 and len(config.SESSION_SECRET) >= 32


def _sign(value: str) -> str:
    # بصمة كلمة المرور داخل التوقيع: تغييرها يُخرج كل الجلسات القائمة.
    pw = hashlib.sha256(config.ADMIN_PASSWORD.encode()).hexdigest()
    return hmac.new(
        config.SESSION_SECRET.encode(), f"{value}:{pw}".encode(), hashlib.sha256
    ).hexdigest()


def _new_session() -> str:
    exp = str(int(time.time()) + SESSION_HOURS * 3600)
    return f"{exp}.{_sign('session:' + exp)}"


def is_admin(request: Request) -> bool:
    if not configured():
        return False
    exp, _, sig = (request.cookies.get(COOKIE) or "").partition(".")
    if not exp.isdigit() or int(exp) < time.time():
        return False
    return hmac.compare_digest(sig, _sign("session:" + exp))


def _gate(request: Request) -> Response | None:
    """None إن كان الطلب من مسؤول، وإلا الرد المناسب."""
    if not configured():
        return page(
            "اللوحة غير مفعّلة",
            '<div class="card"><p>اللوحة معطّلة لأن ADMIN_PASSWORD أو '
            "SESSION_SECRET غير مضبوط في ملف ⁦.env⁩، أو أقصر من الحد الأدنى. "
            "كلمة المرور 12 حرفاً على الأقل، والسرّ 32 حرفاً على الأقل.</p>"
            "<p>لتوليد سرّ: <code>python -c \"import secrets;"
            "print(secrets.token_urlsafe(48))\"</code></p></div>",
            nav=False, status=503,
        )
    if not is_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    return None


def _same_origin(request: Request) -> bool:
    origin = request.headers.get("origin") or request.headers.get("referer")
    if not origin or origin == "null":
        return True  # الكوكي SameSite=Strict يكفي هنا
    return urlsplit(origin).netloc == request.headers.get("host", "")


async def _form(request: Request) -> dict[str, str] | None:
    if int(request.headers.get("content-length") or 0) > MAX_FORM_BYTES:
        return None
    body = (await request.body())[:MAX_FORM_BYTES].decode("utf-8", "replace")
    return {k: v[0] for k, v in parse_qs(body, keep_blank_values=True).items()}


async def _post_gate(request: Request) -> tuple[Response | None, dict]:
    denied = _gate(request)
    if denied:
        return denied, {}
    if not _same_origin(request):
        return Response("مصدر الطلب غير مسموح", status_code=403), {}
    form = await _form(request)
    if form is None:
        return Response("الطلب أكبر من المسموح", status_code=413), {}
    return None, form


def _back(path: str, **params) -> RedirectResponse:
    query = urlencode({k: v for k, v in params.items() if v})
    return RedirectResponse(path + (f"?{query}" if query else ""), status_code=303)


def _safe_next(value: str) -> str:
    if value.startswith("/admin") and "//" not in value and "\n" not in value:
        return value
    return "/admin"


def fingerprint(channel: str, user_id: str) -> str:
    """بصمة ثابتة للمستخدم لا تكشف رقمه. مفتاحها سرّ الخادم، فلا تُعكس
    بتجربة كل أرقام الهواتف كما يُعكس تجزيء غير مفتاحي."""
    digest = hmac.new(
        config.SESSION_SECRET.encode(), f"uid:{channel}:{user_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return digest[:8]


# ─────────────────────────────────────────────────────── القالب
CSS = """
:root{--bg:#f5f4f0;--panel:#fff;--ink:#1c1c1a;--muted:#696962;--line:#e2e0d9;
--accent:#1d5c57;--accent-ink:#fff;--ok:#2b7149;--ok-bg:#e6f2ea;--warn:#8f5200;
--warn-bg:#fdf1dc;--bad:#a8241c;--bad-bg:#fbe7e5;--code:#efede7}
@media (prefers-color-scheme:dark){:root{--bg:#151614;--panel:#1e201d;--ink:#ecebe6;
--muted:#a3a29b;--line:#34362f;--accent:#7cc4bc;--accent-ink:#0f1a19;--ok:#8fd1a6;
--ok-bg:#1d3226;--warn:#f1bf72;--warn-bg:#3a2d16;--bad:#f39c94;--bad-bg:#3d1f1c;
--code:#2a2c27}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);line-height:1.7;
font-family:"SF Arabic","Noto Sans Arabic","Segoe UI","Geeza Pro",Tahoma,sans-serif;
font-size:15px}
a{color:var(--accent)}
header{background:var(--panel);border-bottom:1px solid var(--line)}
.bar{max-width:1100px;margin:auto;padding:10px 16px;display:flex;flex-wrap:wrap;
align-items:center;gap:6px 18px}
.brand{font-weight:700;font-size:17px;margin-inline-end:auto}
.brand small{color:var(--muted);font-weight:400}
nav{display:flex;flex-wrap:wrap;gap:4px}
nav a{padding:4px 10px;border-radius:6px;text-decoration:none;color:var(--ink)}
nav a.on{background:var(--accent);color:var(--accent-ink)}
nav form{display:inline}
main{max-width:1100px;margin:auto;padding:20px 16px 60px}
h1{font-size:22px;margin:0 0 14px}
h2{font-size:17px;margin:26px 0 10px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;
padding:14px 16px;margin-bottom:12px}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
.stat b{display:block;font-size:26px;line-height:1.3}
.stat span{color:var(--muted);font-size:13px}
.alert{border-radius:10px;padding:12px 16px;margin-bottom:12px;border:1px solid}
.alert.bad{background:var(--bad-bg);border-color:var(--bad);color:var(--ink)}
.alert.warn{background:var(--warn-bg);border-color:var(--warn)}
.alert.ok{background:var(--ok-bg);border-color:var(--ok)}
.alert strong{display:block}
.badge{display:inline-block;font-size:12px;padding:1px 8px;border-radius:99px;
border:1px solid currentColor;white-space:nowrap}
.badge.ok{color:var(--ok)}.badge.warn{color:var(--warn)}.badge.bad{color:var(--bad)}
.badge.muted{color:var(--muted)}
.muted{color:var(--muted)}
.meta{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:13px;color:var(--muted);
align-items:center}
.q{font-size:16px;margin:6px 0;white-space:pre-wrap;overflow-wrap:anywhere}
pre,.reply{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--code);
border-radius:8px;padding:10px 12px;margin:8px 0;font-family:inherit;font-size:14px}
pre.log{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;direction:ltr;
text-align:left}
code{background:var(--code);padding:1px 5px;border-radius:4px;direction:ltr;
unicode-bidi:embed;font-size:13px}
details summary{cursor:pointer;color:var(--accent);font-size:14px}
.tabs{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px}
.tabs a{padding:3px 12px;border:1px solid var(--line);border-radius:99px;
text-decoration:none;color:var(--ink);background:var(--panel);font-size:14px}
.tabs a.on{border-color:var(--accent);color:var(--accent);font-weight:700}
button,.btn{font:inherit;background:var(--accent);color:var(--accent-ink);border:0;
border-radius:7px;padding:6px 14px;cursor:pointer;text-decoration:none}
button.ghost{background:transparent;color:var(--ink);border:1px solid var(--line)}
button.danger{background:transparent;color:var(--bad);border:1px solid var(--bad)}
button.small{font-size:13px;padding:1px 10px}
.meta form{margin-inline-start:auto}
button:disabled{opacity:.5;cursor:default}
input,textarea{font:inherit;color:var(--ink);background:var(--bg);
border:1px solid var(--line);border-radius:7px;padding:7px 10px;width:100%}
input[type=checkbox]{width:auto}
label{display:block;margin:10px 0 4px;font-weight:600}
.row{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.row form{margin:0}
table{width:100%;border-collapse:collapse;font-size:14px}
td,th{padding:6px 8px;border-bottom:1px solid var(--line);text-align:start;
vertical-align:top}
td.wrap{overflow-wrap:anywhere}
.state.ok{color:var(--ok);font-weight:600}.state.muted{color:var(--muted)}
th{color:var(--muted);font-weight:600}
.bar-chart{height:8px;border-radius:4px;background:var(--line);overflow:hidden}
.bar-chart i{display:block;height:100%;background:var(--accent)}
.help{color:var(--muted);font-size:14px;margin:-6px 0 14px}
"""

NAV = [
    ("/admin", "نظرة عامة", "home"),
    ("/admin/messages", "الأسئلة", "messages"),
    ("/admin/try", "جرّب بيان", "try"),
    ("/admin/settings", "الإعدادات", "settings"),
    ("/admin/blocked", "المحظورون", "blocked"),
]

HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
        "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    ),
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


def page(title: str, body: str, active: str = "", nav: bool = True,
         status: int = 200, flash: str = "") -> HTMLResponse:
    links = ""
    if nav:
        links = "".join(
            f'<a href="{href}" class="{"on" if key == active else ""}">{label}</a>'
            for href, label, key in NAV
        )
        links += ('<form method="post" action="/admin/logout">'
                  '<button class="ghost" type="submit">خروج</button></form>')
    note = ""
    if flash in FLASH:
        kind, text = FLASH[flash]
        note = f'<div class="alert {kind}">{e(text)}</div>'
    doc = f"""<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{e(title)} · {e(config.BOT_NAME)}</title><style>{CSS}</style></head>
<body><header><div class="bar"><div class="brand">{e(config.BOT_NAME)}
<small>لوحة التحكم</small></div><nav>{links}</nav></div></header>
<main><h1>{e(title)}</h1>{note}{body}</main></body></html>"""
    return HTMLResponse(doc, status_code=status, headers=HEADERS)


def when(ts: float | None) -> str:
    if not ts:
        return "—"
    # عزل اتجاهي: بدونه يقلب السطر العربي ترتيب التاريخ والساعة
    return "\u2066" + time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts)) + " UTC\u2069"


def badge(outcome: str | None) -> str:
    label, kind = OUTCOMES.get(outcome or "", (outcome or "؟", "muted"))
    return f'<span class="badge {kind}">{e(label)}</span>'


def pct(n: int, total: int) -> str:
    return f"{round(100 * n / total)}%" if total else "0%"


# ─────────────────────────────────────────────────── الدخول والخروج
@router.get("/admin/login")
async def login_form(request: Request, error: str = ""):
    if not configured():
        return _gate(request)
    if is_admin(request):
        return RedirectResponse("/admin", status_code=303)
    msg = {
        "bad": "كلمة المرور غير صحيحة.",
        "slow": "محاولات كثيرة. انتظر ربع ساعة ثم أعد المحاولة.",
    }.get(error, "")
    body = f"""<div class="card" style="max-width:420px">
{f'<div class="alert bad">{e(msg)}</div>' if msg else ''}
<form method="post" action="/admin/login">
<label for="pw">كلمة المرور</label>
<input id="pw" name="password" type="password" autocomplete="current-password" required autofocus>
<p><button type="submit">دخول</button></p></form></div>"""
    return page("الدخول إلى اللوحة", body, nav=False)


@router.post("/admin/login")
async def login(request: Request):
    if not configured():
        return _gate(request)
    if not _same_origin(request):
        return Response("مصدر الطلب غير مسموح", status_code=403)
    ip = request.client.host if request.client else "?"
    if not store.throttle("admin-login", ip, 5, 900):
        return _back("/admin/login", error="slow")
    form = await _form(request) or {}
    if not hmac.compare_digest(
        (form.get("password") or "").encode(), config.ADMIN_PASSWORD.encode()
    ):
        return _back("/admin/login", error="bad")
    resp = RedirectResponse("/admin", status_code=303)
    resp.set_cookie(
        COOKIE, _new_session(), max_age=SESSION_HOURS * 3600, httponly=True,
        samesite="strict", path="/admin",
        secure=config.PUBLIC_URL.startswith("https://"),
    )
    return resp


@router.post("/admin/logout")
async def logout():
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie(COOKIE, path="/admin")
    return resp


# ─────────────────────────────────────────────────────── نظرة عامة
def _alerts(counts: dict, emb: int, status: dict, last: dict | None) -> str:
    out = []
    if brain.paused():
        out.append(("bad", "بيان متوقف الآن.",
                    "كل سؤال يُجاب برسالة الإيقاف. أعِد تشغيله من الإعدادات."))
    if counts["_chunks"] == 0:
        out.append(("bad", "قاعدة المعرفة فارغة.",
                    "بيان يرفض كل سؤال. شغّل الفهرسة من أسفل هذه الصفحة."))
    if status["vector_note"]:
        out.append((
            "bad", "البحث الدلالي معطّل.",
            f"{status['vector_note']}. يرفض بيان الآن كل سؤال مصاغ بكلمات غير "
            "كلمات الموقع، ومنها أسئلة مشروعة كثيرة.",
        ))
    elif (emb and store.setting("min_relevance", "") == ""
          and embed.model_id() != CALIBRATED_FOR):
        out.append((
            "warn", f"العتبة على قيمتها الابتدائية {config.MIN_RELEVANCE:.2f}.",
            f"هذه القيمة معايَرة لـ {CALIBRATED_FOR} لا لـ {embed.model_id()}. "
            "شغّل scripts/calibrate.py واضبط العتبة من الإعدادات.",
        ))
    if last and last.get("finished") and not last.get("ok"):
        out.append(("warn", f"فشلت آخر فهرسة ({when(last['started'])}).",
                    "الفهرس السابق ما زال يعمل. التفاصيل في أسفل الصفحة."))
    return "".join(
        f'<div class="alert {k}"><strong>{e(t)}</strong>{e(d)}</div>'
        for k, t, d in out
    )


@router.get("/admin")
async def overview(request: Request, msg: str = ""):
    if denied := _gate(request):
        return denied
    retrieve.ensure_fresh()
    counts = store.counts()
    emb = store.embedded_count()
    status = retrieve.status()
    last = store.last_run()
    week = time.time() - 7 * 86400
    outcomes = store.outcome_stats(week)
    channels = store.channel_stats(week)
    total = sum(outcomes.values())
    thr = brain.threshold()

    vec_ok = "تعمل" if status["vectors"] else "معطّلة"
    cards = f"""<div class="grid">
<div class="card stat"><span>مقاطع قاعدة المعرفة</span><b>{counts['_chunks']}</b>
<span>التحقيقات: {counts.get('investigation', 0)}، الأدوات: {counts.get('tool', 0)}،
الأدوات المُزالة: {counts.get('tool_removed', 0)}.</span></div>
<div class="card stat"><span>أدوات الدليل</span><b>{counts['_tools']}</b>
<span>الحسّاسة: {counts['_tools_sensitive']}، المُزالة: {counts['_tools_removed']}.</span></div>
<div class="card stat"><span>المتجهات ({e(_provider_label())})</span><b>{vec_ok}</b>
<span>مقاطع لها متجهات: {emb} من {counts['_chunks']}.</span></div>
<div class="card stat"><span>عتبة البوابة</span><b>{thr:.2f}</b>
<span>{'مضبوطة من اللوحة.' if store.setting('min_relevance', '') else 'قيمة ابتدائية لم تُعدَّل من اللوحة.'}</span></div>
</div>"""

    rows = ""
    for key, (label, kind) in OUTCOMES.items():
        n = outcomes.get(key, 0)
        rows += (
            f'<tr><td><a href="/admin/messages?outcome={key}">{badge(key)}</a></td>'
            f"<td>{n}</td><td>{pct(n, total)}</td>"
            f'<td style="width:40%"><div class="bar-chart"><i style="width:{pct(n, total)}">'
            f"</i></div></td></tr>"
        )
    ch_rows = "".join(
        f"<tr><td>{e(CHANNELS.get(c, c))}</td><td>{v['questions']}</td>"
        f"<td>{v['users']}</td></tr>"
        for c, v in sorted(channels.items())
    ) or '<tr><td colspan="3" class="muted">لا أسئلة بعد.</td></tr>'
    activity = f"""<h2>آخر 7 أيام</h2><p class="help">عدد الأسئلة: {total}.</p>
<div class="grid"><div class="card"><table>
<tr><th>النتيجة</th><th>العدد</th><th>النسبة</th><th></th></tr>{rows}</table></div>
<div class="card"><table><tr><th>القناة</th><th>الأسئلة</th><th>المستخدمون</th></tr>
{ch_rows}</table></div></div>"""

    if last:
        took = (f"، والمدة بالثواني: {round(last['finished'] - last['started'])}"
                if last.get("finished") else "")
        state = ("جارية الآن" if not last.get("finished")
                 else "نجحت" if last.get("ok") else "فشلت")
        run_html = (f"<p>بدأت {when(last['started'])}{took}. الحالة: "
                    f"<strong>{state}</strong>.</p>"
                    f'<pre class="log">{e(last.get("detail") or "")}</pre>')
    else:
        run_html = '<p class="muted">لم تُشغَّل أي فهرسة بعد.</p>'
    busy = ingest.running()
    reindex = f"""<h2>الفهرسة</h2><div class="card">{run_html}
<form method="post" action="/admin/reindex-now" class="row">
<button type="submit" {'disabled' if busy else ''}>أعد الفهرسة الآن</button>
<span class="muted">تسحب آخر نسخة من مستودع الموقع، وتشغّل المُستخرِج، وتولّد
المتجهات، وتستغرق بضع دقائق. الفهرس الحالي يبقى يعمل حتى تكتمل.</span></form></div>"""

    alerts = _alerts(counts, emb, status, last)
    return page("نظرة عامة", alerts + cards + activity + reindex, "home", flash=msg)


def _provider_label() -> str:
    where = "على الخادم" if config.EMBED_PROVIDER == "local" else "عبر Voyage"
    return f"{config.EMBED_MODEL} {where}"


@router.post("/admin/reindex-now")
async def reindex_now(request: Request):
    denied, _ = await _post_gate(request)
    if denied:
        return denied
    state = ingest.start_background(pull=True)
    return _back("/admin", msg="reindex" if state == "started" else "busy")


# ─────────────────────────────────────────────────────── الأسئلة
HELP = {
    "refused_gate": (
        "أسئلة رفضتها البوابة قبل استدعاء النموذج. رتّبها حسب الثقة: إن وجدت "
        "بين الأعلى ثقةً أسئلة مشروعة عن الأدوات أو التحقيقات، فالعتبة أعلى "
        "مما ينبغي."
    ),
    "refused_model": (
        "أسئلة تجاوزت البوابة ثم رفضها النموذج. كثرتها تعني أن العتبة أدنى مما "
        "ينبغي، وكل واحد منها استدعاء مدفوع للنموذج."
    ),
    "error": "أسئلة فشل فيها استدعاء النموذج. راجع سجلّ الخادم.",
}


@router.get("/admin/messages")
async def messages(request: Request, outcome: str = "", channel: str = "",
                   before: int = 0, sort: str = "", msg: str = ""):
    if denied := _gate(request):
        return denied
    outcome = outcome if outcome in OUTCOMES else ""
    channel = channel if channel in CHANNELS else ""
    by_conf = sort == "confidence"
    items = store.questions(outcome, channel, 0 if by_conf else before, by_conf,
                            limit=100 if by_conf else 50)

    def link(**kw) -> str:
        params = {"outcome": outcome, "channel": channel, "sort": sort if by_conf else ""}
        params.update(kw)
        query = urlencode({k: v for k, v in params.items() if v})
        return "/admin/messages" + (f"?{query}" if query else "")

    tabs = f'<a href="{link(outcome="")}" class="{"on" if not outcome else ""}">الكل</a>'
    tabs += "".join(
        f'<a href="{link(outcome=k)}" class="{"on" if k == outcome else ""}">{e(v[0])}</a>'
        for k, v in OUTCOMES.items()
    )
    ch_tabs = f'<a href="{link(channel="")}" class="{"on" if not channel else ""}">كل القنوات</a>'
    ch_tabs += "".join(
        f'<a href="{link(channel=k)}" class="{"on" if k == channel else ""}">{e(v)}</a>'
        for k, v in CHANNELS.items()
    )
    sort_tab = (
        f'<a href="{link(sort="")}" class="{"" if by_conf else "on"}">الأحدث أولاً</a>'
        f'<a href="{link(sort="confidence")}" class="{"on" if by_conf else ""}">'
        "الأعلى ثقةً أولاً</a>"
    )
    head = (f'<div class="tabs">{tabs}</div><div class="tabs">{ch_tabs}</div>'
            f'<div class="tabs">{sort_tab}</div>')
    if outcome in HELP:
        head += f'<p class="help">{e(HELP[outcome])}</p>'

    here = link(before=str(before) if before and not by_conf else "")
    cards = []
    for m in items:
        fp = fingerprint(m["channel"], m["user_id"])
        sources = "".join(
            f'<li><a href="{e(s)}" rel="noreferrer">{e(s)}</a></li>' for s in m["sources"]
        )
        reply = (f'<details><summary>ردّ بيان</summary><div class="reply">{e(m["reply"])}</div>'
                 f'{f"<ul>{sources}</ul>" if sources else ""}</details>'
                 if m.get("reply") else "")
        conf = f"{m['confidence']:.2f}" if m["confidence"] is not None else "—"
        cards.append(f"""<div class="card">
<div class="meta">{badge(m['outcome'])}<span>الثقة {conf}</span>
<span>{e(CHANNELS.get(m['channel'], m['channel']))}</span>
<span title="بصمة المستخدم">المستخدم {fp}</span><span>{when(m['ts'])}</span>
<form method="post" action="/admin/block">
<input type="hidden" name="msg_id" value="{m['id']}">
<input type="hidden" name="next" value="{e(here)}">
<button class="danger small" type="submit">احظر</button></form></div>
<div class="q">{e(m['content'])}</div>{reply}</div>""")
    body = head + ("".join(cards) or '<div class="card muted">لا أسئلة هنا.</div>')
    if items and not by_conf and len(items) == 50:
        body += f'<p><a class="btn" href="{e(link(before=str(items[-1]["id"])))}">أقدم</a></p>'
    return page("أسئلة الجمهور", body, "messages", flash=msg)


@router.post("/admin/block")
async def block(request: Request):
    denied, form = await _post_gate(request)
    if denied:
        return denied
    nxt = _safe_next(form.get("next", ""))
    owner = store.message_owner(int(form.get("msg_id") or 0)) \
        if (form.get("msg_id") or "").isdigit() else None
    if owner:
        store.block(*owner, "حُظر من اللوحة")
    sep = "&" if "?" in nxt else "?"
    return RedirectResponse(f"{nxt}{sep}msg=blocked", status_code=303)


# ─────────────────────────────────────────────────────── المحظورون
@router.get("/admin/blocked")
async def blocked(request: Request, msg: str = ""):
    if denied := _gate(request):
        return denied
    rows = "".join(
        f"""<tr><td>{fingerprint(b['channel'], b['user_id'])}</td>
<td>{e(CHANNELS.get(b['channel'], b['channel']))}</td><td>{e(b['reason'] or '')}</td>
<td>{when(b['ts'])}</td><td><form method="post" action="/admin/unblock">
<input type="hidden" name="channel" value="{e(b['channel'])}">
<input type="hidden" name="fp" value="{fingerprint(b['channel'], b['user_id'])}">
<button class="ghost" type="submit">ارفع الحظر</button></form></td></tr>"""
        for b in store.blocked_list()
    )
    body = ('<p class="help">المحظور يتلقى رسالة الرفض على كل سؤال، ولا يُستدعى '
            "النموذج لأجله.</p>")
    body += (f'<div class="card"><table><tr><th>المستخدم</th><th>القناة</th>'
             f"<th>السبب</th><th>منذ</th><th></th></tr>{rows}</table></div>"
             if rows else '<div class="card muted">لا أحد محظور.</div>')
    return page("المحظورون", body, "blocked", flash=msg)


@router.post("/admin/unblock")
async def unblock(request: Request):
    denied, form = await _post_gate(request)
    if denied:
        return denied
    for b in store.blocked_list():
        if (b["channel"] == form.get("channel")
                and hmac.compare_digest(fingerprint(b["channel"], b["user_id"]),
                                        form.get("fp", ""))):
            store.unblock(b["channel"], b["user_id"])
    return _back("/admin/blocked", msg="unblocked")


# ─────────────────────────────────────────────────────── التجربة
def _try_form(q: str = "") -> str:
    return f"""<div class="card"><form method="post" action="/admin/try">
<label for="q">السؤال</label>
<textarea id="q" name="q" rows="3" maxlength="{config.MAX_QUESTION_CHARS}" required>{e(q)}</textarea>
<p class="row"><button type="submit">اسأل بيان</button>
<span class="muted">التجربة لا تُسجَّل في سجل الأسئلة. السؤال الذي يتجاوز البوابة
يستدعي النموذج فعلاً.</span></p></form></div>"""


@router.get("/admin/try")
async def try_form(request: Request):
    if denied := _gate(request):
        return denied
    return page("جرّب بيان", _try_form(), "try")


@router.post("/admin/try")
async def try_ask(request: Request):
    denied, form = await _post_gate(request)
    if denied:
        return denied
    q = (form.get("q") or "").strip()[: config.MAX_QUESTION_CHARS]
    if not q:
        return page("جرّب بيان", _try_form(), "try")
    res = await asyncio.to_thread(brain.answer, q, "admin", "console")
    r = res["retrieval"] or {"tools": [], "category": None, "category_tools": [],
                             "passages": [], "used_vectors": False}
    thr = brain.threshold()
    tools = "، ".join(e(t["name"]) for t in r["tools"]) or "لا شيء"
    cat = r["category"]
    cat_html = (f"{e(cat['category_ar'])}، والأدوات المعروضة منه: "
                f"{len(r['category_tools'])}" if cat else "لا شيء")
    passages = "".join(
        f'<tr><td>{e(TYPES.get(p["type"], p["type"]))}</td><td class="wrap">{e(p["title"] or "")}</td>'
        f'<td class="wrap"><a href="{e(p["url"])}" rel="noreferrer">{e(p["url"])}</a></td></tr>'
        for p in r["passages"]
    )
    mode = "متجهات ونص" if r.get("used_vectors") else "نص فقط"
    body = _try_form(q) + f"""<div class="card">
<div class="meta">{badge(res['outcome'])}<span>الثقة {res['confidence']:.3f}</span>
<span>العتبة {thr:.2f}</span><span>البحث: {mode}</span></div>
<div class="reply">{e(res['text'])}</div></div>
<div class="card"><table>
<tr><th>أدوات مطابقة بالاسم</th><td>{tools}</td></tr>
<tr><th>تصنيف مطابق</th><td>{cat_html}</td></tr></table></div>
<h2>المقاطع المسترجعة</h2>
<div class="card">{f'<table><tr><th>النوع</th><th>العنوان</th><th>الرابط</th></tr>{passages}</table>' if passages else '<p class="muted">لا مقاطع.</p>'}</div>"""
    return page("جرّب بيان", body, "try")


# ─────────────────────────────────────────────────────── الإعدادات
def _channel_state() -> str:
    def row(name: str, ok: bool, need: str) -> str:
        state = ('<span class="state ok">مضبوطة.</span>' if ok
                 else f'<span class="state muted">ينقصها {e(need)}.</span>')
        return f'<tr><td>{e(name)}</td><td class="wrap">{state}</td></tr>'

    meta = bool(config.META_APP_SECRET and config.META_VERIFY_TOKEN)
    return (
        row("تيليغرام", bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_WEBHOOK_SECRET),
            "TELEGRAM_BOT_TOKEN و TELEGRAM_WEBHOOK_SECRET")
        + row("واتساب", meta and bool(config.WHATSAPP_TOKEN and config.WHATSAPP_PHONE_NUMBER_ID),
              "مفاتيح Meta وواتساب")
        + row("ماسنجر", meta and bool(config.MESSENGER_PAGE_TOKEN),
              "مفاتيح Meta و MESSENGER_PAGE_TOKEN")
    )


@router.get("/admin/settings")
async def settings(request: Request, msg: str = "", error: str = ""):
    if denied := _gate(request):
        return denied
    thr = brain.threshold()
    paused = brain.paused()
    err = ('<div class="alert bad">العتبة رقم بين 0.05 و 0.90.</div>'
           if error == "threshold" else "")
    fixed = [
        ("نموذج الإجابة", config.ANSWER_MODEL),
        ("نموذج المتجهات", _provider_label()),
        ("أبعاد المتجه", config.EMBED_DIM),
        ("المقاطع لكل سؤال", config.TOP_K),
        ("أقصى عدد أدوات في القائمة", config.MAX_TOOLS_LISTED),
        ("أقصى رسائل المستخدم الواحد", config.RATE_LIMIT_MESSAGES),
        ("خلال (ثانية)", config.RATE_LIMIT_WINDOW),
        ("الأسئلة السابقة التي يتذكرها", config.HISTORY_TURNS),
        ("عرض المصادر", "نعم" if config.SHOW_SOURCES else "لا"),
    ]
    fixed_rows = "".join(f"<tr><th>{e(k)}</th><td>{e(str(v))}</td></tr>" for k, v in fixed)
    body = f"""{err}<div class="card"><form method="post" action="/admin/settings">
<label for="t">عتبة البوابة</label>
<p class="help">السؤال الذي تقلّ ثقته عن العتبة يُرفض قبل استدعاء النموذج. رفعها
يقلّل الإجابات الخاطئة ويزيد رفض الأسئلة المشروعة، وخفضها يفعل العكس. القيمة
الابتدائية في ⁦.env⁩ هي {config.MIN_RELEVANCE:.2f}.</p>
<input id="t" name="threshold" type="number" step="0.01" min="0.05" max="0.9"
value="{thr:.2f}" style="max-width:140px">
<label><input type="checkbox" name="paused" value="1" {'checked' if paused else ''}>
أوقف بيان مؤقتاً</label>
<p class="help">حين يتوقف بيان يُجاب كل سؤال بهذه الرسالة: «{e(config.PAUSED_MESSAGE)}»</p>
<p class="row"><button type="submit">احفظ</button>
<button class="ghost" type="submit" name="reset" value="1">أعِد العتبة إلى قيمة ⁦.env⁩</button></p>
</form></div>
<h2>القنوات</h2><div class="card"><table>{_channel_state()}</table></div>
<h2>إعدادات من ⁦.env⁩</h2>
<p class="help">تتغيّر بتعديل ملف ⁦.env⁩ على الخادم ثم إعادة تشغيله.</p>
<div class="card"><table>{fixed_rows}</table></div>"""
    return page("الإعدادات", body, "settings", flash=msg)


@router.post("/admin/settings")
async def save_settings(request: Request):
    denied, form = await _post_gate(request)
    if denied:
        return denied
    if form.get("reset"):
        store.clear_setting("min_relevance")
    else:
        try:
            thr = float(form.get("threshold", ""))
        except ValueError:
            thr = -1
        if not 0.05 <= thr <= 0.9:
            return _back("/admin/settings", error="threshold")
        store.set_setting("min_relevance", f"{thr:.2f}")
    store.set_setting("paused", "1" if form.get("paused") else "0")
    return _back("/admin/settings", msg="saved")
