"""لوحة تحكم بيان — بالعربية والإنجليزية، بلا JavaScript، خلف كلمة مرور.

تعرض حالة الفهرس والمتجهات، وأسئلة الجمهور ونتيجة كل منها مع تقييم
إجابتها، والتصحيحات المعتمدة التي يكتبها الفريق، وتجربة بيان دون قناة،
والعتبة والحدّ اليومي وزر الإيقاف، والمحظورين. اللغة تُختار برابط في
الشريط (?lang=en أو ?lang=ar) وتُحفظ في كوكي.

الخصوصية: معرّف واتساب هو رقم الهاتف، فلا تعرض اللوحة أي معرّف. كل
مستخدم يظهر ببصمة مشتقّة بـ SESSION_SECRET لا تُعكس إلى رقمه، والحظر
يُنفَّذ برقم الرسالة لا بالمعرّف.

Bayan's dashboard, in Arabic and English, with no JavaScript, behind a
password.

It shows the state of the index and the vectors, the public's questions
with the outcome of each and the rating of its answer, the approved
corrections the team writes, a way to try Bayan without a channel, the
threshold, the daily limit and the pause button, and the blocked users.
The language is chosen with a link in the bar (?lang=en or ?lang=ar) and
kept in a cookie.

Privacy: a WhatsApp ID is the phone number, so the dashboard shows no
IDs. Each user appears as a fingerprint derived with SESSION_SECRET that
cannot be reversed to their number, and blocking is done by message
number, not by ID.
"""
import asyncio
import datetime
import hashlib
import json
import logging
import secrets
import hmac
import html
import time
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from . import (__version__, brain, broadcast, config, embed, i18n, ingest, keys, opportunities,
               retrieve, role, sources, store)

log = logging.getLogger("dashboard")
router = APIRouter()

COOKIE = "bayan_admin"
LANG_COOKIE = "bayan_lang"
SESSION_HOURS = 12
MAX_FORM_BYTES = 16_384

e = html.escape

# الإعداد الذي عويِرت عليه MIN_RELEVANCE الافتراضية (scripts/calibrate.py)
# The setting the default MIN_RELEVANCE was calibrated for (scripts/calibrate.py)
CALIBRATED_FOR = "voyage-4-nano@1024"
# سبب الحظر يُخزَّن رمزاً ويُعرض بلغة اللوحة. القيمة العربية القديمة مقبولة.
# The block reason is stored as a code and shown in the dashboard's
# language. The old Arabic value is still accepted.
BLOCK_REASON = "dashboard"

OUTCOMES = {
    "answered": "ok", "tool_list": "ok", "refused_gate": "warn",
    "refused_model": "muted", "error": "bad",
}
CHANNELS = ("telegram", "whatsapp", "messenger", "web")

# ───────────────────────────────────────────────────── النصوص / Strings
# كل نص في اللوحة من القسم "dashboard" في ملف لغته (app/locales/<code>.json)،
# وما ينقص من لغة يُؤخذ من الإنجليزية. المفاتيح ثابتة، فلا يُعرض في الصفحة نص
# يأتي من الرابط.
# Every dashboard string comes from the "dashboard" section of its language's
# file (app/locales/<code>.json), and whatever a language lacks is taken from
# English. The keys are fixed, so no text that comes from the URL is shown on
# the page.
def _strings(lang: str) -> dict[str, str]:
    return i18n.LOCALES.get(lang, {}).get("dashboard") or i18n.LOCALES["en"]["dashboard"]


# الإنجليزية: مجموعة المفاتيح والاحتياط / English: the key set and the fallback
TEXT: dict[str, str] = _strings("en")
FLASH_KIND = {"reindex": "ok", "busy": "warn", "saved": "ok", "blocked": "ok",
              "unblocked": "ok", "rated": "ok", "fix_saved": "ok", "fix_novec": "warn",
              "fix_deleted": "ok", "opp_saved": "ok", "opp_deleted": "ok", "opp_sent": "ok",
              "member_saved": "ok", "member_deleted": "ok", "key_saved": "ok",
              "key_cleared": "ok", "role_saved": "ok", "src_added": "ok",
              "src_added_novec": "warn", "src_deleted": "ok", "src_synced": "ok",
              "src_same": "warn"}
RATINGS = ("up", "down", "none")
# نموذج التصحيح أكبر من غيره: الحرف العربي 6 بايتات بعد ترميز الرابط
# The correction form is larger than the others: an Arabic character takes
# 6 bytes once URL-encoded
FIX_FORM_BYTES = 65_536
FIX_ANSWER_CHARS = 3000


def tr(lang: str):
    """دالة ترجمة للغة الطلب: T("key", v=...)، والإنجليزية لما ينقص من لغتها.
    A translation function for the request's language: T("key", v=...), with
    English for whatever its language lacks."""
    texts = _strings(lang)

    def T(key: str, **kw) -> str:
        text = texts.get(key) or TEXT[key]
        return text.format(**kw) if kw else text

    return T


def req_lang(request: Request) -> str:
    """?lang= يتقدّم على الكوكي، واللغة من SUPPORTED_LANGUAGES، والافتراضي
    الإنجليزية (قرار 2026-11-09).
    ?lang= takes precedence over the cookie, the language is one of
    SUPPORTED_LANGUAGES, and the default is English (decided 2026-11-09)."""
    q = request.query_params.get("lang")
    if q in i18n.SUPPORTED_LANGUAGES:
        return q
    c = request.cookies.get(LANG_COOKIE)
    return c if c in i18n.SUPPORTED_LANGUAGES else "en"


def _dir(lang: str) -> str:
    """اتجاه الصفحة: من اليمين للغات الحرف العربي (العربية والفارسية والأردية).
    The page direction: right-to-left for the Arabic-script languages (Arabic,
    Persian, Urdu)."""
    return "rtl" if i18n.script_of(lang) == "arabic" else "ltr"


def _bot_name(lang: str) -> str:
    return config.BOT_NAME if i18n.script_of(lang) == "arabic" else config.BOT_NAME_EN


# ─────────────────────────────────────────────────────── الدخول / Login
def configured() -> bool:
    return len(config.ADMIN_PASSWORD) >= 12 and len(config.SESSION_SECRET) >= 32


def _sign(value: str) -> str:
    # بصمة كلمة المرور داخل التوقيع: تغييرها يُخرج كل الجلسات القائمة.
    # The password's hash is part of the signature: changing the password logs
    # out every existing session.
    pw = hashlib.sha256(config.ADMIN_PASSWORD.encode()).hexdigest()
    return hmac.new(
        config.SESSION_SECRET.encode(), f"{value}:{pw}".encode(), hashlib.sha256
    ).hexdigest()


def _new_session(member_id: int = 0) -> str:
    """جلسة موقّعة تحمل رقم العضو (0 للمالك). / A signed session carrying the
    member's id (0 for the owner)."""
    exp = str(int(time.time()) + SESSION_HOURS * 3600)
    return f"{exp}.{member_id}.{_sign(f'session:{exp}:{member_id}')}"


def google_enabled() -> bool:
    return bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET
                and config.PUBLIC_URL.startswith("http"))


def current_member(request: Request) -> dict | None:
    """العضو صاحب الجلسة، أو None. المالك {id: 0, role: admin}؛ العضو المعطّل لا جلسة له.
    The session's member, or None. The owner is {id: 0, role: admin}; a
    deactivated member has no session."""
    if not configured():
        return None
    parts = (request.cookies.get(COOKIE) or "").split(".")
    if len(parts) != 3:
        return None
    exp, mid, sig = parts
    if not exp.isdigit() or not mid.isdigit() or int(exp) < time.time():
        return None
    if not hmac.compare_digest(sig, _sign(f"session:{exp}:{mid}")):
        return None
    if mid == "0":
        return {"id": 0, "email": "", "name": "", "role": "admin", "active": 1}
    m = store.member(int(mid))
    return m if m and m["active"] else None


def is_admin(request: Request) -> bool:
    """هل الطلب من عضو داخل (بأي دور). / Whether the request is from a signed-in
    member, of any role."""
    return current_member(request) is not None


def who(request: Request) -> str:
    """اسم صاحب الطلب للسجلّ والنسبة: الاسم، وإلا البريد، وإلا «المالك».
    The requester's name for the log and attribution: the name, else the
    email, else the owner."""
    m = getattr(request.state, "member", None) or current_member(request) or {}
    return m.get("name") or m.get("email") or tr(req_lang(request))("owner_label")


def _gate(request: Request, role: str = "viewer") -> Response | None:
    """None إن كان الطلب من عضو بدور كافٍ، وإلا الرد المناسب.
    None if the request comes from a member with a sufficient role, otherwise
    the appropriate response."""
    if not configured():
        T = tr(req_lang(request))
        return page(
            request, T("off_title"),
            f'<div class="card"><p>{T("off_body")}</p><p>{T("off_gen")} '
            "<code>python -c \"import secrets;print(secrets.token_urlsafe(48))\"</code>"
            "</p></div>",
            nav=False, status=503,
        )
    m = current_member(request)
    if m is None:
        return RedirectResponse("/admin/login", status_code=303)
    if RANK.get(m["role"], -1) < RANK[role]:
        return _plain("forbidden", 403)
    request.state.member = m
    return None


def _same_origin(request: Request) -> bool:
    origin = request.headers.get("origin") or request.headers.get("referer")
    if not origin or origin == "null":
        # The SameSite=Strict cookie is enough here
        return True  # الكوكي SameSite=Strict يكفي هنا
    return urlsplit(origin).netloc == request.headers.get("host", "")


def _plain(key: str, status: int) -> Response:
    """رد نصي قصير باللغتين، لطلبات لا صفحة لها.
    A short plain-text response in both languages, for requests with no page."""
    ar, en = _strings("ar")[key], TEXT[key]
    return Response(f"{ar} / {en}", status_code=status)


async def _form(request: Request, limit: int = MAX_FORM_BYTES) -> dict[str, str] | None:
    if int(request.headers.get("content-length") or 0) > limit:
        return None
    body = (await request.body())[:limit].decode("utf-8", "replace")
    return {k: v[0] for k, v in parse_qs(body, keep_blank_values=True).items()}


async def _post_gate(request: Request, limit: int = MAX_FORM_BYTES,
                     role: str = "editor") -> tuple[Response | None, dict]:
    """بوابة الطلبات التي تغيّر شيئاً: المحرر فأعلى، إلا ما يطلب مديراً.
    The gate for requests that change something: editor and above, unless
    admin is required."""
    denied = _gate(request, role)
    if denied:
        return denied, {}
    if not _same_origin(request):
        return _plain("origin_denied", 403), {}
    form = await _form(request, limit)
    if form is None:
        return _plain("too_large", 413), {}
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
    بتجربة كل أرقام الهواتف كما يُعكس تجزيء غير مفتاحي.

    A stable fingerprint for the user that does not reveal their number. It
    is keyed with the server secret, so it cannot be reversed by trying
    every phone number, as an unkeyed hash can.
    """
    digest = hmac.new(
        config.SESSION_SECRET.encode(), f"uid:{channel}:{user_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return digest[:8]


# ─────────────────────────────────────────────────────── القالب / Template
# القالب: شريط جانبي ثابت للتنقّل، ورأس للصفحة، وألوان من لوحة موقع باكس ميموريا
# (الورقي والأخضر). الإنجليزية افتراضياً والتبديل إلى العربية بزر في الشريط.
# The template: a fixed sidebar for navigation, a page header, and the colours
# of the Pax Memoria site palette (paper and green). English by default, with
# a button in the sidebar to switch to Arabic.
CSS = """
:root{--bg:#f3efe6;--panel:#fcfaf5;--panel-2:#f7f3ea;--ink:#1b1f1c;--muted:#6b6f68;
--line:#e3dbcb;--accent:#3b7350;--accent-soft:#e4efe6;--accent-ink:#fff;--ok:#2b7149;
--ok-bg:#e6f2ea;--warn:#8f5200;--warn-bg:#fdf1dc;--bad:#a8241c;--bad-bg:#fbe7e5;
--code:#efeadf;--side:#10201e;--side-ink:#e8e4d8;--side-muted:#9aa89f;--side-on:#1b3330;
--shadow:0 1px 2px rgba(20,30,25,.06)}
@media (prefers-color-scheme:dark){:root{--bg:#0f1715;--panel:#172926;--panel-2:#1c302c;
--ink:#ecebe6;--muted:#9faea4;--line:#24403a;--accent:#8fd1a6;--accent-soft:#1d3226;
--accent-ink:#0f1a19;--ok:#8fd1a6;--ok-bg:#1d3226;--warn:#f1bf72;--warn-bg:#3a2d16;
--bad:#f39c94;--bad-bg:#3d1f1c;--code:#122320;--side:#0b1514;--side-ink:#e8e4d8;
--side-muted:#8e9c93;--side-on:#1b3330;--shadow:none}}
*{box-sizing:border-box}
html{height:100%}
body{margin:0;min-height:100%;background:var(--bg);color:var(--ink);line-height:1.6;
font-family:"SF Arabic","Noto Sans Arabic","Segoe UI","Geeza Pro",Tahoma,sans-serif;
font-size:15px;-webkit-font-smoothing:antialiased}
html[lang=en] body{font-family:Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--accent)}
/* الهيكل / Shell */
.shell{display:grid;grid-template-columns:232px 1fr;min-height:100vh}
.side{background:var(--side);color:var(--side-ink);padding:18px 14px;display:flex;
flex-direction:column;gap:6px;position:sticky;top:0;height:100vh}
.side .brand{display:flex;align-items:baseline;gap:8px;padding:4px 10px 16px;
font-weight:700;font-size:19px;color:#fff;letter-spacing:.01em}
.side .brand small{color:var(--side-muted);font-weight:500;font-size:12px}
.side nav{display:flex;flex-direction:column;gap:2px}
.side nav a{display:flex;align-items:center;gap:10px;padding:8px 10px;border-radius:8px;
text-decoration:none;color:var(--side-ink);font-size:14.5px;font-weight:500}
.side nav a svg{width:17px;height:17px;flex:none;stroke:currentColor;fill:none;
stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;opacity:.75}
.side nav a:hover{background:var(--side-on)}
.side nav a.on{background:var(--side-on);color:#fff}
.side nav a.on svg{opacity:1;color:#9fd8b2}
.side .foot{margin-top:auto;border-top:1px solid rgba(255,255,255,.08);padding-top:12px;
display:flex;flex-direction:column;gap:8px}
.side .who{font-size:13px;color:var(--side-muted);padding:0 10px;overflow-wrap:anywhere}
.side .who b{display:block;color:var(--side-ink);font-weight:600}
.side .actions{display:flex;gap:8px;padding:0 10px}
.side .actions form{margin:0;flex:1 1 auto}
.side .actions button,.side .actions a{display:block;width:100%;text-align:center;
background:transparent;color:var(--side-ink);border:1px solid rgba(255,255,255,.18);
border-radius:8px;padding:6px 8px;font-size:13px;text-decoration:none;white-space:nowrap}
.side .actions form.langform{display:flex;gap:4px;flex:2 1 auto}
.side .actions form.langform select{flex:1 1 auto;min-width:0;background:transparent;
color:var(--side-ink);border:1px solid rgba(255,255,255,.18);border-radius:8px;
padding:6px 4px;font-size:13px}
.side .actions form.langform select option{color:#1c1c1a}
.side .actions form.langform button{width:auto;flex:0 0 auto}
.side .actions button:hover,.side .actions a:hover{background:var(--side-on)}
.content{min-width:0;padding:28px 36px 72px;max-width:1240px}
.top{display:flex;align-items:center;justify-content:space-between;gap:16px;
margin-bottom:22px}
h1{font-size:26px;margin:0;letter-spacing:-.01em;line-height:1.25}
h2{font-size:16px;margin:30px 0 12px;color:var(--ink);letter-spacing:.01em}
h3{font-size:15px;margin:14px 0 8px}
/* البطاقات / Cards */
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;
padding:18px 20px;margin-bottom:14px;box-shadow:var(--shadow)}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(210px,1fr))}
.grid .card{margin:0}
.stat{display:flex;flex-direction:column;gap:2px}
.stat>span:first-child{color:var(--muted);font-size:12.5px;font-weight:600;
text-transform:uppercase;letter-spacing:.04em}
html[lang=ar] .stat>span:first-child{text-transform:none;letter-spacing:0;font-size:13px}
.stat b{display:block;font-size:32px;line-height:1.15;font-weight:600;
font-variant-numeric:tabular-nums;margin:4px 0 2px}
.stat>span:last-child{color:var(--muted);font-size:13px}
.alert{border-radius:10px;padding:12px 16px;margin-bottom:14px;border:1px solid;
border-inline-start-width:4px}
.alert.bad{background:var(--bad-bg);border-color:var(--bad);color:var(--ink)}
.alert.warn{background:var(--warn-bg);border-color:var(--warn)}
.alert.ok{background:var(--ok-bg);border-color:var(--ok)}
.alert strong{display:block}
.badge{display:inline-block;font-size:12px;padding:1px 9px;border-radius:99px;
border:1px solid currentColor;white-space:nowrap;font-weight:500;line-height:1.6}
.badge.ok{color:var(--ok);background:var(--ok-bg);border-color:transparent}
.badge.warn{color:var(--warn);background:var(--warn-bg);border-color:transparent}
.badge.bad{color:var(--bad);background:var(--bad-bg);border-color:transparent}
.badge.muted{color:var(--muted);background:var(--panel-2);border-color:transparent}
.muted{color:var(--muted)}
.meta{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:13px;color:var(--muted);
align-items:center}
.q{font-size:16px;margin:8px 0;white-space:pre-wrap;overflow-wrap:anywhere;font-weight:500}
pre,.reply{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--code);
border-radius:8px;padding:10px 12px;margin:8px 0;font-family:inherit;font-size:14px}
pre.log{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;direction:ltr;
text-align:left}
code{background:var(--code);padding:1px 5px;border-radius:4px;direction:ltr;
unicode-bidi:embed;font-size:13px}
details summary{cursor:pointer;color:var(--accent);font-size:14px;font-weight:500}
.tabs{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px}
.tabs a{padding:4px 13px;border:1px solid var(--line);border-radius:99px;
text-decoration:none;color:var(--ink);background:var(--panel);font-size:13.5px}
.tabs a.on{border-color:var(--accent);color:var(--accent);background:var(--accent-soft);
font-weight:600}
button,.btn{font:inherit;font-weight:500;background:var(--accent);color:var(--accent-ink);
border:0;border-radius:8px;padding:7px 15px;cursor:pointer;text-decoration:none}
button:hover,.btn:hover{filter:brightness(1.07)}
button.ghost{background:var(--panel);color:var(--ink);border:1px solid var(--line)}
button.danger{background:transparent;color:var(--bad);border:1px solid var(--bad)}
button.small{font-size:13px;padding:2px 11px}
.meta form{margin-inline-start:auto}
button:disabled{opacity:.5;cursor:default}
input,textarea,select{font:inherit;color:var(--ink);background:var(--panel);
border:1px solid var(--line);border-radius:8px;padding:8px 11px;width:100%}
input:focus,textarea:focus,select:focus{outline:2px solid var(--accent);outline-offset:0;
border-color:var(--accent)}
.rate{margin-top:8px}.rate form{max-width:560px}
.turn{margin:14px 0}.turn .meta{margin-bottom:2px}
.turn.me .reply{background:var(--accent-soft);margin-inline-start:12%}
.turn.bot .reply{margin-inline-end:12%}.turn details{margin-inline-end:12%}
.rated{margin-top:6px}
input[type=checkbox]{width:auto}
label{display:block;margin:12px 0 5px;font-weight:600;font-size:13.5px}
.row{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.row form{margin:0}
table{width:100%;border-collapse:collapse;font-size:14px;font-variant-numeric:tabular-nums}
td,th{padding:9px 10px;border-bottom:1px solid var(--line);text-align:start;
vertical-align:top}
tr:last-child td{border-bottom:0}
tbody tr:hover td{background:var(--panel-2)}
td.wrap{overflow-wrap:anywhere}
.state.ok{color:var(--ok);font-weight:600}.state.muted{color:var(--muted)}
th{color:var(--muted);font-weight:600;font-size:12.5px;text-transform:uppercase;
letter-spacing:.04em}
html[lang=ar] th{text-transform:none;letter-spacing:0;font-size:13px}
th[scope=row]{text-transform:none;letter-spacing:0;font-size:14px;color:var(--ink);
font-weight:600}
.keys form.row{flex-wrap:nowrap;margin:0}
.keys form.row input{width:auto;flex:1 1 160px}
.keys td form+form{margin-top:8px}
.sources-add h3{margin:0 0 4px}
.sources-add label{margin-top:10px}
.sources-add input[type=file]{padding:6px}
.fields{display:grid;gap:14px}
.fields.two{grid-template-columns:1fr 1fr}
.fields label{margin-top:0;display:flex;gap:8px;align-items:center}
.fields textarea{font-size:14px;line-height:1.6}
@media (max-width:900px){.fields.two{grid-template-columns:1fr}}
.bar-chart{height:8px;border-radius:4px;background:var(--line);overflow:hidden}
.bar-chart i{display:block;height:100%;background:var(--accent)}
.help{color:var(--muted);font-size:14px;margin:-10px 0 16px;max-width:72ch}
/* الدخول / Login */
body.bare{display:grid;place-items:center;padding:24px}
body.bare .content{padding:0;max-width:440px;width:100%}
body.bare .top{justify-content:center;flex-direction:column;gap:6px;text-align:center}
body.bare h1{font-size:22px}
body.bare .brand{font-weight:700;font-size:22px}
body.bare .brand small{color:var(--muted);font-weight:500;font-size:13px;display:block}
body.bare .card{max-width:none !important}
body.bare .langform{display:inline-flex;gap:6px;margin-top:14px;font-size:14px}
body.bare .langform select,body.bare .langform button{padding:4px 8px;font-size:14px}
@media (max-width:900px){
.shell{grid-template-columns:1fr}
.side{position:static;height:auto;padding:12px 14px;gap:10px}
.side nav{flex-direction:row;flex-wrap:wrap}
.side nav a{padding:6px 10px;font-size:14px}
.side .foot{margin-top:0;border-top:0;padding-top:0;flex-direction:row;align-items:center;
justify-content:space-between;gap:10px}
.side .who{padding:0}
.content{padding:20px 16px 60px}
h1{font-size:22px}}
"""

# أيقونات التنقّل: SVG مضمّن (سياسة CSP تمنع الصور الخارجية)
# Navigation icons: inline SVG (the CSP forbids external images)
ICONS = {
    "home": '<path d="M3 11.5 12 4l9 7.5"/><path d="M5 10v10h14V10"/>',
    "messages": '<path d="M4 5h16v11H9l-5 4z"/>',
    "try": '<path d="M12 3v3M12 18v3M3 12h3M18 12h3"/><circle cx="12" cy="12" r="4"/>',
    "corrections": '<path d="M4 20h4l11-11-4-4L4 16z"/><path d="M13 7l4 4"/>',
    "opportunities": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1.2l2-1.5-2-3.4-2.3 1a7 7 0 0 0-2-1.2L14 3h-4l-.6 2.7a7 7 0 0 0-2 1.2l-2.3-1-2 3.4 2 1.5A7 7 0 0 0 5 12c0 .4 0 .8.1 1.2l-2 1.5 2 3.4 2.3-1a7 7 0 0 0 2 1.2L10 21h4l.6-2.7a7 7 0 0 0 2-1.2l2.3 1 2-3.4-2-1.5c.1-.4.1-.8.1-1.2z"/>',
    "blocked": '<circle cx="12" cy="12" r="9"/><path d="M6 6l12 12"/>',
    "role": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    "sources": '<path d="M4 4h16v16H4z"/><path d="M8 9h8M8 13h8M8 17h5"/>',
    "team": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><circle cx="17" cy="9" r="2.5"/><path d="M16 15a5 5 0 0 1 5.5 5"/>',
}


def icon(key: str) -> str:
    return f'<svg viewBox="0 0 24 24" aria-hidden="true">{ICONS.get(key, "")}</svg>'

NAV = [
    ("/admin", "nav_home", "home"),
    ("/admin/messages", "nav_messages", "messages"),
    ("/admin/try", "nav_try", "try"),
    ("/admin/corrections", "nav_corrections", "corrections"),
    ("/admin/opportunities", "nav_opps", "opportunities"),
    ("/admin/sources", "nav_sources", "sources"),
    ("/admin/role", "nav_role", "role"),
    ("/admin/settings", "nav_settings", "settings"),
    ("/admin/blocked", "nav_blocked", "blocked"),
    ("/admin/team", "nav_team", "team"),
]
RANK = {"viewer": 0, "editor": 1, "admin": 2}
OAUTH_COOKIE = "bayan_oauth"
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"

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


def _lang_form(request: Request, lang: str, T) -> str:
    """قائمة اللغات: الصفحة نفسها بلغة أخرى مع بقية معاملاتها. نموذج GET بلا
    سكربت (سياسة أمن المحتوى تمنعه)، فزرّ صغير يطبّق الاختيار. كل لغة باسمها
    بلغتها.
    The language list: the same page in another language, keeping its other
    parameters. A GET form without a script (the content-security policy
    forbids one), so a small button applies the choice. Each language by its
    own name in that language."""
    hidden = "".join(
        f'<input type="hidden" name="{e(k)}" value="{e(v)}">'
        for k, v in request.query_params.items() if k not in ("lang", "msg")
    )
    options = "".join(
        f'<option value="{code}" lang="{code}"{" selected" if code == lang else ""}>'
        f'{e(i18n.LOCALES[code]["language"]["native"])}</option>'
        for code in i18n.SUPPORTED_LANGUAGES
    )
    return (f'<form method="get" action="{e(request.url.path)}" class="langform">{hidden}'
            f'<select name="lang" aria-label="{e(T("lang_label"))}">{options}</select>'
            f'<button type="submit">{e(T("lang_go"))}</button></form>')


def page(request: Request, title: str, body: str, active: str = "", nav: bool = True,
         status: int = 200, flash: str = "") -> HTMLResponse:
    lang = req_lang(request)
    T = tr(lang)
    lang_btn = _lang_form(request, lang, T)
    note = ""
    if flash in FLASH_KIND:
        note = f'<div class="alert {FLASH_KIND[flash]}">{e(T("flash_" + flash))}</div>'
    name = _bot_name(lang)
    head = f"""<!doctype html>
<html lang="{lang}" dir="{_dir(lang)}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{e(title)} · {e(name)}</title><style>{CSS}</style></head>"""
    if nav:
        links = "".join(
            f'<a href="{href}" class="{"on" if key == active else ""}">{icon(key)}'
            f"<span>{T(label)}</span></a>"
            for href, label, key in NAV
        )
        m = current_member(request)
        who = ""
        if m:
            label = m.get("name") or m.get("email") or T("owner_label")
            who = f'<div class="who"><b>{e(label)}</b>{T("role_" + m["role"])}</div>'
        doc = f"""{head}
<body class="shell"><aside class="side"><div class="brand">{e(name)}
<small>{T("dashboard")} · v{__version__}</small></div><nav>{links}</nav>
<div class="foot">{who}<div class="actions">{lang_btn}
<form method="post" action="/admin/logout"><button type="submit">{T("logout")}</button>
</form></div></div></aside>
<main class="content"><div class="top"><h1>{e(title)}</h1></div>{note}{body}</main>
</body></html>"""
    else:
        doc = f"""{head}
<body class="bare"><main class="content"><div class="top"><div class="brand">{e(name)}
<small>{T("dashboard")}</small></div><h1>{e(title)}</h1></div>{note}{body}
<p style="text-align:center">{lang_btn}</p></main></body></html>"""
    resp = HTMLResponse(doc, status_code=status, headers=HEADERS)
    if request.query_params.get("lang") in i18n.SUPPORTED_LANGUAGES:
        resp.set_cookie(LANG_COOKIE, lang, max_age=365 * 86400, httponly=True,
                        samesite="strict", path="/admin",
                        secure=config.PUBLIC_URL.startswith("https://"))
    return resp


def when(ts: float | None) -> str:
    if not ts:
        return "—"
    # عزل اتجاهي: بدونه يقلب السطر العربي ترتيب التاريخ والساعة
    # Directional isolation: without it, an Arabic line reverses the order of
    # the date and the time
    return "⁦" + time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts)) + " UTC⁩"


def badge(outcome: str | None, T) -> str:
    kind = OUTCOMES.get(outcome or "", "muted")
    label = T(f"out_{outcome}") if outcome in OUTCOMES else (outcome or "?")
    return f'<span class="badge {kind}">{e(label)}</span>'


def channel_name(channel: str, T) -> str:
    return T(f"ch_{channel}") if channel in CHANNELS else channel


def pct(n: int, total: int) -> str:
    return f"{round(100 * n / total)}%" if total else "0%"


def _provider_label(T) -> str:
    where = T("provider_local") if config.EMBED_PROVIDER == "local" else T("provider_voyage")
    return f"{config.EMBED_MODEL} {where}"


# ─────────────────────────────────────────────────── الدخول والخروج / Login and logout
@router.get("/admin/login")
async def login_form(request: Request, error: str = ""):
    if not configured():
        return _gate(request)
    if is_admin(request):
        return RedirectResponse("/admin", status_code=303)
    T = tr(req_lang(request))
    d = config.ALLOWED_EMAIL_DOMAIN
    msg = {"bad": T("login_bad"), "slow": T("login_slow"), "domain": T("login_domain", d=d),
           "unknown": T("login_unknown"), "inactive": T("login_inactive"),
           "google": T("login_google_fail")}.get(error, "")
    pw_form = f"""<form method="post" action="/admin/login">
<label for="pw">{T("password")}</label>
<input id="pw" name="password" type="password" autocomplete="current-password" required>
<p><button type="submit">{T("login_btn")}</button></p></form>"""
    if google_enabled():
        body = f"""<div class="card" style="max-width:420px">
{f'<div class="alert bad">{e(msg)}</div>' if msg else ''}
<p><a class="btn" href="/admin/auth/google">{T("login_google")}</a></p>
<p class="help">{e(T("login_google_help", d=d))}</p>
<details><summary>{T("login_owner")}</summary>{pw_form}</details></div>"""
    else:
        body = f"""<div class="card" style="max-width:420px">
{f'<div class="alert bad">{e(msg)}</div>' if msg else ''}{pw_form}</div>"""
    return page(request, T("login_title"), body, nav=False)


def _session_response(member_id: int, to: str = "/admin", landing: str | None = None) -> Response:
    """يفتح الجلسة ويحوّل إلى اللوحة.

    بعد العودة من Google يُعرض بدل التحويل صفحة هبوط صغيرة من موقعنا تنتقل
    بنفسها إلى اللوحة: كوكي الجلسة SameSite=Strict لا يُرسل في تحويلة هي جزء
    من تنقّل بدأ من موقع آخر (accounts.google.com)، فكان التحويل المباشر يعيد
    الداخل إلى صفحة الدخول رغم نجاح دخوله. التنقّل من صفحة الهبوط يبدأ من
    موقعنا فيُرسل الكوكي.

    Opens the session and sends the member to the dashboard.

    After the return from Google, a small landing page of our own is shown
    instead of a redirect, and it moves on to the dashboard by itself: a
    SameSite=Strict session cookie is not sent on a redirect that is part
    of a navigation started from another site (accounts.google.com), so a
    direct redirect bounced the member back to the login page although the
    login had succeeded. A navigation from the landing page starts on our
    site, so the cookie is sent.
    """
    if landing is None:
        resp: Response = RedirectResponse(to, status_code=303)
    else:
        T = tr(landing)
        resp = HTMLResponse(
            f'<!doctype html><html lang="{landing}" dir="{_dir(landing)}">'
            f'<head><meta charset="utf-8"><meta http-equiv="refresh" content="0; url={to}">'
            f'<meta name="robots" content="noindex,nofollow"><title>{e(T("login_done"))}</title>'
            f"<style>{CSS}</style></head><body class=\"bare\"><main class=\"content\">"
            f'<div class="card"><p>{e(T("login_done"))}</p>'
            f'<p><a class="btn" href="{to}">{e(T("login_done_link"))}</a></p></div>'
            f"</main></body></html>", headers=HEADERS)
    resp.set_cookie(
        COOKIE, _new_session(member_id), max_age=SESSION_HOURS * 3600, httponly=True,
        samesite="strict", path="/admin",
        secure=config.PUBLIC_URL.startswith("https://"),
    )
    return resp


@router.post("/admin/login")
async def login(request: Request):
    if not configured():
        return _gate(request)
    if not _same_origin(request):
        return _plain("origin_denied", 403)
    ip = request.client.host if request.client else "?"
    if not store.throttle("admin-login", ip, 5, 900):
        return _back("/admin/login", error="slow")
    form = await _form(request) or {}
    if not hmac.compare_digest(
        (form.get("password") or "").encode(), config.ADMIN_PASSWORD.encode()
    ):
        store.audit("?", "login_failed", "owner password")
        return _back("/admin/login", error="bad")
    store.audit(tr("ar")("owner_label"), "login", "owner password")
    return _session_response(0)


# ─────────────────────────────── الدخول بحساب Google / Google sign-in
@router.get("/admin/auth/google")
async def google_start(request: Request):
    if not configured():
        return _gate(request)
    if not google_enabled():
        return _back("/admin/login", error="google")
    state = secrets.token_urlsafe(24)
    exp = int(time.time()) + 600
    params = urlencode({
        "client_id": config.GOOGLE_CLIENT_ID,
        "redirect_uri": _google_redirect(),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "hd": config.ALLOWED_EMAIL_DOMAIN,
        "prompt": "select_account",
    })
    resp = RedirectResponse(f"{GOOGLE_AUTH}?{params}", status_code=303)
    # Lax لا Strict: الكوكي يجب أن يصل مع الرجوع من Google
    # Lax, not Strict: the cookie must come back with the redirect from Google
    resp.set_cookie(OAUTH_COOKIE, f"{exp}.{state}.{_sign(f'oauth:{exp}:{state}')}",
                    max_age=600, httponly=True, samesite="lax", path="/admin",
                    secure=config.PUBLIC_URL.startswith("https://"))
    return resp


def _google_redirect() -> str:
    return config.PUBLIC_URL.rstrip("/") + "/admin/auth/google/callback"


@router.get("/admin/auth/google/callback")
async def google_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if not configured():
        return _gate(request)
    parts = (request.cookies.get(OAUTH_COOKIE) or "").split(".")
    ok = (len(parts) == 3 and parts[0].isdigit() and int(parts[0]) >= time.time()
          and hmac.compare_digest(parts[1], state or "-")
          and hmac.compare_digest(parts[2], _sign(f"oauth:{parts[0]}:{parts[1]}")))
    if not ok or error or not code or not google_enabled():
        return _back("/admin/login", error="google")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            tok = await client.post(GOOGLE_TOKEN, data={
                "code": code, "client_id": config.GOOGLE_CLIENT_ID,
                "client_secret": config.GOOGLE_CLIENT_SECRET,
                "redirect_uri": _google_redirect(), "grant_type": "authorization_code",
            })
            access = tok.json().get("access_token") if tok.status_code == 200 else None
            if not access:
                log.warning("رفض Google تبادل الرمز: %s", tok.text[:200])
                return _back("/admin/login", error="google")
            info = await client.get(GOOGLE_USERINFO, headers={"Authorization": f"Bearer {access}"})
    except Exception:  # noqa: BLE001
        log.exception("تعذّر الاتصال بـ Google للدخول")
        return _back("/admin/login", error="google")
    data = info.json() if info.status_code == 200 else {}
    email = (data.get("email") or "").lower()
    domain = email.rpartition("@")[2]
    hd = (data.get("hd") or "").lower()
    if not data.get("email_verified") or domain != config.ALLOWED_EMAIL_DOMAIN or (hd and hd != domain):
        store.audit("?", "login_denied_domain", email or "?")
        return _back("/admin/login", error="domain")
    m = store.member_by_email(email)
    if m is None and email in config.ADMIN_EMAILS:
        m = store.member(store.add_member(email, "admin", data.get("name") or ""))
    if m is None:
        store.audit("?", "login_denied_unknown", email)
        return _back("/admin/login", error="unknown")
    if not m["active"]:
        store.audit(email, "login_denied_inactive", email)
        return _back("/admin/login", error="inactive")
    store.touch_login(m["id"], data.get("name") or m["name"])
    store.audit(data.get("name") or email, "login", "google")
    resp = _session_response(m["id"], landing=req_lang(request))
    resp.delete_cookie(OAUTH_COOKIE, path="/admin")
    return resp


@router.post("/admin/logout")
async def logout(request: Request):
    if current_member(request):
        store.audit(who(request), "logout")
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie(COOKIE, path="/admin")
    return resp


# ─────────────────────────────────────────────────────── نظرة عامة / Overview
def _alerts(T, lang: str, counts: dict, emb: int, status: dict, last: dict | None) -> str:
    out = []
    if brain.paused():
        out.append(("bad", T("a_paused"), T("a_paused_d")))
    if counts["_chunks"] == 0:
        out.append(("bad", T("a_empty"), T("a_empty_d")))
    note = status["vector_note"] if lang == "ar" else status["vector_note_en"]
    if note:
        out.append(("bad", T("a_novec"), T("a_novec_d", note=note)))
    elif (emb and store.setting("min_relevance", "") == ""
          and embed.model_id() != CALIBRATED_FOR):
        out.append(("warn", T("a_thr", v=f"{config.MIN_RELEVANCE:.2f}"),
                    T("a_thr_d", cal=CALIBRATED_FOR, cur=embed.model_id())))
    if last and last.get("finished") and not last.get("ok"):
        out.append(("warn", T("a_failed", when=when(last["started"])), T("a_failed_d")))
    return "".join(
        f'<div class="alert {k}"><strong>{e(t)}</strong>{e(d)}</div>'
        for k, t, d in out
    )


@router.get("/admin")
async def overview(request: Request, msg: str = ""):
    if denied := _gate(request):
        return denied
    lang = req_lang(request)
    T = tr(lang)
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
    rates = store.rating_stats(week)
    fixes = len(store.corrections(active_only=True))

    vec_ok = T("vec_on") if status["vectors"] else T("vec_off")
    thr_src = T("thr_dash") if store.setting("min_relevance", "") else T("thr_init")
    cards = f"""<div class="grid">
<div class="card stat"><span>{T("c_chunks")}</span><b>{counts['_chunks']}</b>
<span>{T("c_chunks_d", i=counts.get('investigation', 0), t=counts.get('tool', 0),
          r=counts.get('tool_removed', 0), s=counts.get('safety', 0),
          m=counts.get('team', 0))}</span></div>
<div class="card stat"><span>{T("c_tools")}</span><b>{counts['_tools']}</b>
<span>{T("c_tools_d", s=counts['_tools_sensitive'], r=counts['_tools_removed'])}</span></div>
<div class="card stat"><span>{e(T("c_vec", p=_provider_label(T)))}</span><b>{vec_ok}</b>
<span>{T("c_vec_d", n=emb, t=counts['_chunks'])}</span></div>
<div class="card stat"><span>{T("c_thr")}</span><b>{thr:.2f}</b>
<span>{thr_src}</span></div>
<div class="card stat"><span>{T("c_ratings")}</span>
<b><a href="/admin/messages?rating=down">{rates.get('down', 0)}</a></b>
<span>{T("c_ratings_d", up=rates.get('up', 0), down=rates.get('down', 0), fixes=fixes)}</span></div>
<div class="card stat"><span>{T("c_unanswered")}</span>
<b><a href="/admin/messages?outcome=refused_gate">{outcomes.get('refused_gate', 0) + outcomes.get('refused_model', 0)}</a></b>
<span>{T("c_unanswered_d", g=outcomes.get('refused_gate', 0), m=outcomes.get('refused_model', 0))}</span></div>
</div>"""

    rows = ""
    for key in OUTCOMES:
        n = outcomes.get(key, 0)
        rows += (
            f'<tr><td><a href="/admin/messages?outcome={key}">{badge(key, T)}</a></td>'
            f"<td>{n}</td><td>{pct(n, total)}</td>"
            f'<td style="width:40%"><div class="bar-chart"><i style="width:{pct(n, total)}">'
            f"</i></div></td></tr>"
        )
    ch_rows = "".join(
        f"<tr><td>{e(channel_name(c, T))}</td><td>{v['questions']}</td>"
        f"<td>{v['users']}</td></tr>"
        for c, v in sorted(channels.items())
    ) or f'<tr><td colspan="3" class="muted">{T("none_yet")}</td></tr>'
    activity = f"""<h2>{T("week")}</h2><p class="help">{T("week_n", n=total)}</p>
<div class="grid"><div class="card"><table>
<tr><th>{T("th_outcome")}</th><th>{T("th_count")}</th><th>{T("th_share")}</th><th></th></tr>
{rows}</table></div>
<div class="card"><table><tr><th>{T("th_channel")}</th><th>{T("th_questions")}</th>
<th>{T("th_users")}</th></tr>{ch_rows}</table></div></div>"""

    # مواضيع الأسئلة: الأسبوع ومنذ البداية، ثم أكثر التفاصيل سؤالاً هذا الأسبوع
    # Question topics: the week and since the start, then the week's most asked details
    tw, ta = store.topic_stats(week), store.topic_totals()
    tw_total = sum(v["questions"] for v in tw.values())
    tp_rows = "".join(
        f'<tr><td>{T("tp_" + t)}</td><td>{tw.get(t, {}).get("questions", 0)}</td>'
        f'<td>{pct(tw.get(t, {}).get("questions", 0), tw_total)}</td>'
        f'<td>{ta.get(t, {}).get("questions", 0)}</td></tr>'
        for t in brain.TOPICS
    )
    titles = store.investigation_titles()
    top = sorted(
        ((n, t, d) for t, v in tw.items() for d, n in v["details"].items()),
        key=lambda x: -x[0],
    )[:8]
    top_rows = "".join(
        f'<tr><td>{T("tp_" + t)}</td><td>{e(titles.get(d, d))}</td><td>{n}</td></tr>'
        for n, t, d in top
    ) or f'<tr><td colspan="3" class="muted">{T("none_yet")}</td></tr>'
    activity += f"""<h2>{T("topics_h")}</h2><p class="help">{T("topics_help")}</p>
<div class="grid"><div class="card"><table><tr><th>{T("th_topic")}</th><th>{T("th_week")}</th>
<th>{T("th_share")}</th><th>{T("th_all")}</th></tr>{tp_rows}</table></div>
<div class="card"><h3>{T("top_h")}</h3><table><tr><th>{T("th_topic")}</th><th></th>
<th>{T("th_count")}</th></tr>{top_rows}</table></div></div>"""

    totals = store.usage_totals()
    tt_rows = "".join(
        f"<tr><td>{e(channel_name(c, T))}</td><td>{v['questions']}</td>"
        f"<td>{v['users']}</td><td>{e(v['first'])}</td></tr>"
        for c, v in sorted(totals.items())
    ) or f'<tr><td colspan="4" class="muted">{T("none_yet")}</td></tr>'
    tt_all = (f'<tr><th>{T("th_total")}</th><th>{sum(v["questions"] for v in totals.values())}</th>'
              f'<th>{sum(v["users"] for v in totals.values())}</th><th></th></tr>') if totals else ""
    activity += f"""<h2>{T("total_h")}</h2><p class="help">{T("total_help")}</p>
<div class="card"><table><tr><th>{T("th_channel")}</th><th>{T("th_questions")}</th>
<th>{T("th_users")}</th><th>{T("th_first")}</th></tr>{tt_rows}{tt_all}</table></div>"""

    if last:
        took = (T("run_took", s=round(last["finished"] - last["started"]))
                if last.get("finished") else "")
        state = (T("run_running") if not last.get("finished")
                 else T("run_ok") if last.get("ok") else T("run_failed"))
        run_html = (f'<p>{T("run_line", when=when(last["started"]), took=took, state=f"<strong>{state}</strong>")}</p>'
                    f'<pre class="log">{e(last.get("detail") or "")}</pre>')
    else:
        run_html = f'<p class="muted">{T("run_none")}</p>'
    busy = ingest.running()
    reindex = f"""<h2>{T("indexing")}</h2><div class="card">{run_html}
<form method="post" action="/admin/reindex-now" class="row">
<button type="submit" {'disabled' if busy else ''}>{T("reindex_btn")}</button>
<span class="muted">{T("reindex_help")}</span></form></div>"""

    alerts = _alerts(T, lang, counts, emb, status, last)
    return page(request, T("nav_home"), alerts + cards + activity + reindex, "home",
                flash=msg)


@router.post("/admin/reindex-now")
async def reindex_now(request: Request):
    denied, _ = await _post_gate(request, role="admin")
    if denied:
        return denied
    store.audit(who(request), "reindex")
    state = ingest.start_background(pull=True)
    return _back("/admin", msg="reindex" if state == "started" else "busy")


# ─────────────────────────────────────────────────────── الأسئلة / Questions
@router.get("/admin/messages")
async def messages(request: Request, outcome: str = "", channel: str = "",
                   before: int = 0, sort: str = "", rating: str = "", msg: str = ""):
    if denied := _gate(request):
        return denied
    T = tr(req_lang(request))
    outcome = outcome if outcome in OUTCOMES else ""
    channel = channel if channel in CHANNELS else ""
    rating = rating if rating in RATINGS else ""
    by_conf = sort == "confidence"
    items = store.questions(outcome, channel, 0 if by_conf else before, by_conf,
                            limit=100 if by_conf else 50, rating=rating)

    def link(**kw) -> str:
        params = {"outcome": outcome, "channel": channel, "rating": rating,
                  "sort": sort if by_conf else ""}
        params.update(kw)
        query = urlencode({k: v for k, v in params.items() if v})
        return "/admin/messages" + (f"?{query}" if query else "")

    tabs = f'<a href="{link(outcome="")}" class="{"on" if not outcome else ""}">{T("all")}</a>'
    tabs += "".join(
        f'<a href="{link(outcome=k)}" class="{"on" if k == outcome else ""}">'
        f'{e(T("out_" + k))}</a>'
        for k in OUTCOMES
    )
    ch_tabs = (f'<a href="{link(channel="")}" class="{"on" if not channel else ""}">'
               f'{T("all_channels")}</a>')
    ch_tabs += "".join(
        f'<a href="{link(channel=k)}" class="{"on" if k == channel else ""}">'
        f'{e(channel_name(k, T))}</a>'
        for k in CHANNELS
    )
    sort_tab = (
        f'<a href="{link(sort="")}" class="{"" if by_conf else "on"}">{T("newest")}</a>'
        f'<a href="{link(sort="confidence")}" class="{"on" if by_conf else ""}">'
        f'{T("highest")}</a>'
    )
    r_tabs = (f'<a href="{link(rating="")}" class="{"on" if not rating else ""}">'
              f'{T("r_all")}</a>')
    r_tabs += "".join(
        f'<a href="{link(rating=k)}" class="{"on" if k == rating else ""}">'
        f'{T({"up": "rate_up", "down": "rate_down", "none": "r_none"}[k])}</a>'
        for k in RATINGS
    )
    head = (f'<div class="tabs">{tabs}</div><div class="tabs">{ch_tabs}</div>'
            f'<div class="tabs">{r_tabs}</div><div class="tabs">{sort_tab}</div>')
    if outcome in ("refused_gate", "refused_model", "error"):
        head += f'<p class="help">{e(T("help_" + outcome))}</p>'

    here = link(before=str(before) if before and not by_conf else "")
    cards = []
    for m in items:
        fp = fingerprint(m["channel"], m["user_id"])
        sources = "".join(
            f'<li><a href="{e(s)}" rel="noreferrer">{e(s)}</a></li>' for s in m["sources"]
        )
        reply = (f'<details><summary>{T("reply")}</summary>'
                 f'<div class="reply">{e(m["reply"])}</div>'
                 f'{f"<ul>{sources}</ul>" if sources else ""}</details>'
                 if m.get("reply") else "")
        conf = f"{m['confidence']:.2f}" if m["confidence"] is not None else "—"
        cards.append(f"""<div class="card" id="m{m['id']}">
<div class="meta">{badge(m['outcome'], T)}<span>{T("conf", c=conf)}</span>
<span>{e(channel_name(m['channel'], T))}</span>
<span title="{T("fp_title")}">{T("user", fp=fp)}</span><span>{when(m['ts'])}</span>
<form method="post" action="/admin/block">
<input type="hidden" name="msg_id" value="{m['id']}">
<input type="hidden" name="next" value="{e(here)}">
<button class="danger small" type="submit">{T("block_btn")}</button></form></div>
<div class="q">{e(m['content'])}</div>{reply}{_rating_html(m, here, T)}</div>""")
    body = head + ("".join(cards) or f'<div class="card muted">{T("none_here")}</div>')
    if items and not by_conf and len(items) == 50:
        body += (f'<p><a class="btn" href="{e(link(before=str(items[-1]["id"])))}">'
                 f'{T("older")}</a></p>')
    return page(request, T("q_title"), body, "messages", flash=msg)


def _rating_html(m: dict, here: str, T) -> str:
    """التقييم الحالي، ونموذج التقييم، ورابط كتابة تصحيح، تحت إجابة السؤال.
    The current rating, the rating form and the link to write a correction,
    under the question's answer."""
    mid = m["id"]
    shown = ""
    if m.get("rating"):
        up = m["rating"] > 0
        parts = [f'<span class="badge {"ok" if up else "bad"}">'
                 f'{T("rated_up") if up else T("rated_down")}</span>']
        if m.get("rating_reason") in store.RATING_REASONS:
            parts.append(f'<span>{T("rr_" + m["rating_reason"])}</span>')
        if m.get("rating_note"):
            parts.append(f'<span>{e(m["rating_note"])}</span>')
        if m.get("rating_author"):
            parts.append(f'<span>{e(T("by", who=m["rating_author"]))}</span>')
        shown = f'<div class="meta rated">{"".join(parts)}</div>'
    options = "".join(
        f'<option value="{r}" {"selected" if m.get("rating_reason") == r else ""}>'
        f'{T("rr_" + r)}</option>'
        for r in store.RATING_REASONS
    )
    clear = (f'<button class="ghost small" name="rating" value="clear" type="submit">'
             f'{T("rate_clear")}</button>' if m.get("rating") else "")
    return f"""{shown}<details class="rate"><summary>{T("rate_summary")}</summary>
<form method="post" action="/admin/rate">
<input type="hidden" name="msg_id" value="{mid}">
<input type="hidden" name="next" value="{e(here)}">
<label for="rr{mid}">{T("rate_reason")}</label>
<select id="rr{mid}" name="reason"><option value="">{T("rr_none")}</option>{options}</select>
<label for="rn{mid}">{T("rate_note")}</label>
<input id="rn{mid}" name="note" maxlength="300" value="{e(m.get('rating_note') or '')}">
<p class="row"><button name="rating" value="up" type="submit">{T("rate_up")}</button>
<button class="danger" name="rating" value="down" type="submit">{T("rate_down")}</button>
{clear}<a href="/admin/corrections/new?from={mid}">{T("write_fix")}</a></p>
</form></details>"""


@router.post("/admin/rate")
async def rate(request: Request):
    denied, form = await _post_gate(request)
    if denied:
        return denied
    nxt = _safe_next(form.get("next", ""))
    mid = form.get("msg_id") or ""
    if mid.isdigit():
        choice = form.get("rating")
        if choice == "clear":
            store.clear_rating(int(mid))
        elif choice in ("up", "down"):
            store.set_rating(int(mid), 1 if choice == "up" else -1,
                             form.get("reason", ""), (form.get("note") or "")[:300], author=who(request))
    sep = "&" if "?" in nxt else "?"
    return RedirectResponse(f"{nxt}{sep}msg=rated#m{mid if mid.isdigit() else ''}",
                            status_code=303)


@router.post("/admin/block")
async def block(request: Request):
    denied, form = await _post_gate(request)
    if denied:
        return denied
    nxt = _safe_next(form.get("next", ""))
    owner = store.message_owner(int(form.get("msg_id") or 0)) \
        if (form.get("msg_id") or "").isdigit() else None
    if owner:
        store.block(*owner, BLOCK_REASON)
        store.audit(who(request), "block")
    sep = "&" if "?" in nxt else "?"
    return RedirectResponse(f"{nxt}{sep}msg=blocked", status_code=303)


# ─────────────────────────────────────────────────────── المحظورون / Blocked
@router.get("/admin/blocked")
async def blocked(request: Request, msg: str = ""):
    if denied := _gate(request):
        return denied
    T = tr(req_lang(request))

    def reason(r: str | None) -> str:
        return T("reason_dashboard") if r in (BLOCK_REASON, "حُظر من اللوحة") else (r or "")

    rows = "".join(
        f"""<tr><td>{fingerprint(b['channel'], b['user_id'])}</td>
<td>{e(channel_name(b['channel'], T))}</td><td>{e(reason(b['reason']))}</td>
<td>{when(b['ts'])}</td><td><form method="post" action="/admin/unblock">
<input type="hidden" name="channel" value="{e(b['channel'])}">
<input type="hidden" name="fp" value="{fingerprint(b['channel'], b['user_id'])}">
<button class="ghost" type="submit">{T("unblock_btn")}</button></form></td></tr>"""
        for b in store.blocked_list()
    )
    body = f'<p class="help">{T("blocked_help")}</p>'
    body += (f'<div class="card"><table><tr><th>{T("th_user")}</th><th>{T("th_channel")}</th>'
             f'<th>{T("th_reason")}</th><th>{T("th_since")}</th><th></th></tr>{rows}</table></div>'
             if rows else f'<div class="card muted">{T("nobody")}</div>')
    return page(request, T("nav_blocked"), body, "blocked", flash=msg)


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
            store.audit(who(request), "unblock")
    return _back("/admin/blocked", msg="unblocked")


# ─────────────────────────────────────────────────────── التجربة / Try Bayan
# محادثة كل عضو مع بيان داخل اللوحة: قناة «team» ومعرّف المستخدم هو بريد العضو
# (أو «owner» لصاحب كلمة المرور)، فتُحفظ ذاكرتها كما تُحفظ لأي قناة عامة
# Each member's conversation with Bayan inside the dashboard: the «team»
# channel with the member's email as the user id (or «owner» for the password
# login), so its memory is kept exactly as for any public channel
def _team_user(request: Request) -> str:
    m = getattr(request.state, "member", None) or current_member(request) or {}
    return m.get("email") or "owner"


def _try_form(T, q: str = "") -> str:
    return f"""<div class="card"><form method="post" action="/admin/try">
<label for="q">{T("question")}</label>
<textarea id="q" name="q" rows="3" maxlength="{config.MAX_QUESTION_CHARS}" required>{e(q)}</textarea>
<p class="row"><button type="submit" name="action" value="ask">{T("send_btn")}</button>
<button type="submit" class="ghost" name="action" value="new" formnovalidate>{T("new_conv")}</button>
</p></form></div>"""


def _retrieval_details(r: dict | None, T, lang: str) -> str:
    """تفاصيل الاسترجاع لإجابة واحدة، من الملخّص المحفوظ معها.
    One answer's retrieval details, from the summary saved with it."""
    if not r:
        return ""
    sep = "، " if _dir(lang) == "rtl" else ", "
    tools = sep.join(e(t) for t in r.get("tools", [])) or T("nothing")
    cat = r.get("category")
    cat_name = ((cat.get("en") if lang != "ar" else None) or cat.get("ar", "")) if cat else ""
    cat_html = e(T("cat_shown", c=cat_name, n=cat.get("n", 0))) if cat else T("nothing")
    passages = "".join(
        f'<tr><td>{e(T("type_" + p["type"]) if ("type_" + p["type"]) in TEXT else p["type"])}</td>'
        f'<td class="wrap">{e(p.get("title") or "")}</td>'
        f'<td class="wrap"><a href="{e(p["url"])}" rel="noreferrer">{e(p["url"])}</a></td></tr>'
        for p in r.get("passages", [])
    )
    fixes = sep.join(
        f'<a href="/admin/corrections/edit?id={int(c["id"])}">{e(c["question"])}</a> '
        f'<span class="muted">({T("fix_sim", s=c["similarity"])})</span>'
        for c in r.get("corrections", [])
    ) or T("nothing")
    mode = T("mode_vec") if r.get("used_vectors") else T("mode_text")
    table = (f'<table><tr><th>{T("th_type")}</th><th>{T("th_title")}</th>'
             f'<th>{T("th_link")}</th></tr>{passages}</table>'
             if passages else f'<p class="muted">{T("no_passages")}</p>')
    return f"""<details><summary>{T("retr_details")}</summary>
<div class="meta"><span>{T("search_mode", m=mode)}</span></div>
<table><tr><th>{T("fix_matched")}</th><td>{fixes}</td></tr>
<tr><th>{T("th_name_match")}</th><td>{tools}</td></tr>
<tr><th>{T("th_cat_match")}</th><td>{cat_html}</td></tr></table>
<h3>{T("passages")}</h3>{table}</details>"""


def _thread(request: Request, T, lang: str) -> str:
    """خيط محادثة العضو: فقاعات متناوبة، الأحدث في الأسفل.
    The member's thread: alternating bubbles, newest at the bottom."""
    turns = store.thread(store.TEAM_CHANNEL, _team_user(request), 20)
    if not turns:
        return f'<div class="card"><p class="muted">{T("thread_empty")}</p></div>'
    thr = brain.threshold()
    parts = []
    for m in turns:
        if m["role"] == "user":
            parts.append(f"""<div class="turn me"><div class="meta"><span>{T("you_label")}</span>
<span>{when(m['ts'])}</span></div><div class="reply" dir="auto">{e(m['content'])}</div></div>""")
            continue
        bubbles = "".join(f'<div class="reply" dir="auto">{e(part)}</div>'
                          for part in brain.messages(m["content"]))
        links = "".join(f' <a href="{e(u)}" rel="noreferrer">{e(u)}</a>' for u in m["sources"])
        src = f'<span>{T("sources_label")}{links}</span>' if links else ""
        conf = f"{m['confidence']:.3f}" if m["confidence"] is not None else "—"
        parts.append(f"""<div class="turn bot"><div class="meta"><span>{e(_bot_name(lang))}</span>
{badge(m['outcome'], T)}<span>{T("conf", c=conf)}</span><span>{T("thr_v", t=f"{thr:.2f}")}</span>{src}</div>
{bubbles}{_retrieval_details(m.get("retrieval"), T, lang)}</div>""")
    return f'<div class="card">{"".join(parts)}</div>'


@router.get("/admin/try")
async def try_form(request: Request, q: str = ""):
    if denied := _gate(request):
        return denied
    lang = req_lang(request)
    T = tr(lang)
    # ?q= يملأ الخانة فقط (من رابط «جرّبه» في التصحيحات)، ولا يستدعي النموذج
    # ?q= only fills in the box (from the "Try it" link on a correction), and
    # does not call the model
    body = (f'<p class="help">{T("try_note", n=config.HISTORY_TURNS)}</p>'
            + _thread(request, T, lang) + _try_form(T, q[: config.MAX_QUESTION_CHARS]))
    return page(request, T("nav_try"), body, "try")


@router.post("/admin/try")
async def try_ask(request: Request):
    # المشاهد يحادث أيضاً: المحادثة لا تغيّر المعرفة / Viewers chat too: the
    # conversation changes nothing in the knowledge base
    denied, form = await _post_gate(request, role="viewer")
    if denied:
        return denied
    user = _team_user(request)
    if form.get("action") == "new":
        store.clear_history(store.TEAM_CHANNEL, user)
        return _back("/admin/try")
    q = (form.get("q") or "").strip()[: config.MAX_QUESTION_CHARS]
    if q:
        await asyncio.to_thread(brain.converse, q, store.TEAM_CHANNEL, user)
    # إعادة التوجيه إلى الصفحة فلا يُعاد إرسال السؤال عند التحديث
    # Redirect to the page so a refresh does not send the question again
    return _back("/admin/try")


# ─────────────────────────────────────────── التصحيحات المعتمدة / Approved corrections
@router.get("/admin/corrections")
async def corrections_list(request: Request, msg: str = ""):
    if denied := _gate(request):
        return denied
    T = tr(req_lang(request))
    model = embed.model_id()
    cards = []
    for c in store.corrections():
        state = (f'<span class="badge ok">{T("fix_on")}</span>' if c["active"]
                 else f'<span class="badge muted">{T("fix_off")}</span>')
        novec = ("" if c["vector"] is not None and c["embed_model"] == model
                 else f'<span class="badge warn">{T("fix_novec")}</span>')
        link = (f'<a href="{e(c["url"])}" rel="noreferrer">{e(c["url"])}</a>'
                if c["url"] else "")
        cards.append(f"""<div class="card">
<div class="meta">{state}{novec}<span>{T("fix_updated", when=when(c['updated']))}</span>
{f'<span>{e(T("by", who=c["author"]))}</span>' if c.get("author") else ''}</div>
<div class="q">{e(c['question'])}</div>
<details><summary>{T("fix_a")}</summary><div class="reply">{e(c['answer'])}</div>{link}</details>
<p class="row"><a class="btn" href="/admin/corrections/edit?id={c['id']}">{T("fix_edit")}</a>
<a href="/admin/try?{urlencode({'q': c['question']})}">{T("fix_try")}</a>
<form method="post" action="/admin/corrections/delete">
<input type="hidden" name="id" value="{c['id']}">
<button class="danger small" type="submit">{T("fix_delete")}</button></form></p></div>""")
    body = (f'<p class="help">{T("fix_help")}</p>'
            f'<p><a class="btn" href="/admin/corrections/new">{T("fix_new")}</a></p>'
            + ("".join(cards) or f'<div class="card muted">{T("fix_none")}</div>'))
    return page(request, T("fix_title"), body, "corrections", flash=msg)


def _fix_form(T, c: dict, error: str = "", original: tuple[str, str | None] | None = None
              ) -> str:
    err = f'<div class="alert bad">{e(error)}</div>' if error else ""
    ref = ""
    if original:
        q, reply = original
        ref = (f'<details class="card"><summary>{T("fix_orig")}</summary>'
               f'<div class="q">{e(q)}</div>'
               f'{f"<div class=reply>{e(reply)}</div>" if reply else ""}</details>')
    return f"""{err}{ref}<div class="card"><form method="post" action="/admin/corrections/save">
<input type="hidden" name="id" value="{c.get('id') or ''}">
<label for="fq">{T("fix_q")}</label><p class="help">{T("fix_q_help")}</p>
<textarea id="fq" name="question" rows="2" maxlength="{config.MAX_QUESTION_CHARS}"
required>{e(c.get('question') or '')}</textarea>
<label for="fa">{T("fix_a")}</label><p class="help">{T("fix_a_help")}</p>
<textarea id="fa" name="answer" rows="8" maxlength="{FIX_ANSWER_CHARS}"
required>{e(c.get('answer') or '')}</textarea>
<label for="fu">{T("fix_url")}</label>
<p class="help">{e(T("fix_url_help", site=config.SITE_URL))}</p>
<input id="fu" name="url" type="url" dir="ltr" value="{e(c.get('url') or '')}">
<label><input type="checkbox" name="active" value="1"
{'checked' if c.get('active', 1) else ''}> {T("fix_active")}</label>
<p><button type="submit">{T("save")}</button></p></form></div>"""


@router.get("/admin/corrections/new")
async def correction_new(request: Request):
    if denied := _gate(request):
        return denied
    T = tr(req_lang(request))
    src = request.query_params.get("from", "")
    original = store.question_text(int(src)) if src.isdigit() else None
    # السؤال الأصلي يملأ الخانة ليُعاد صوغه، لا ليُحفظ كما هو
    # The original question fills the box to be reworded, not saved as it is
    c = {"question": original[0] if original else "", "active": 1}
    return page(request, T("fix_new"), _fix_form(T, c, original=original), "corrections")


@router.get("/admin/corrections/edit")
async def correction_edit(request: Request, id: int = 0):
    if denied := _gate(request):
        return denied
    T = tr(req_lang(request))
    c = store.correction(id)
    if not c:
        return _back("/admin/corrections")
    return page(request, T("fix_edit"), _fix_form(T, c), "corrections")


def _valid_fix_url(url: str) -> bool:
    site = urlsplit(config.SITE_URL)
    u = urlsplit(url)
    return u.scheme == "https" and u.netloc == site.netloc and "\n" not in url


@router.post("/admin/corrections/save")
async def correction_save(request: Request):
    denied, form = await _post_gate(request, FIX_FORM_BYTES)
    if denied:
        return denied
    T = tr(req_lang(request))
    cid = int(form["id"]) if (form.get("id") or "").isdigit() else 0
    c = {"id": cid, "question": (form.get("question") or "").strip(),
         "answer": (form.get("answer") or "").strip(),
         "url": (form.get("url") or "").strip(), "active": bool(form.get("active"))}
    title = T("fix_edit") if cid else T("fix_new")
    if (not c["question"] or not c["answer"]
            or len(c["question"]) > config.MAX_QUESTION_CHARS
            or len(c["answer"]) > FIX_ANSWER_CHARS):
        error = T("err_fix", q=config.MAX_QUESTION_CHARS, a=FIX_ANSWER_CHARS)
        return page(request, title, _fix_form(T, c, error), "corrections", status=400)
    if c["url"] and not _valid_fix_url(c["url"]):
        error = T("err_fix_url", site=config.SITE_URL)
        return page(request, title, _fix_form(T, c, error), "corrections", status=400)
    if cid and not store.correction(cid):
        return _back("/admin/corrections")
    vector, model = await asyncio.to_thread(retrieve.embed_correction, c["question"])
    saved = store.save_correction(c["question"], c["answer"], c["url"], c["active"],
                                  vector, model, cid, author=who(request))
    store.audit(who(request), "correction_edit" if cid else "correction_add", str(saved))
    return _back("/admin/corrections", msg="fix_saved" if vector is not None else "fix_novec")


@router.post("/admin/corrections/delete")
async def correction_delete(request: Request):
    denied, form = await _post_gate(request)
    if denied:
        return denied
    if (form.get("id") or "").isdigit():
        store.delete_correction(int(form["id"]))
        store.audit(who(request), "correction_delete", form["id"])
    return _back("/admin/corrections", msg="fix_deleted")


# ─────────────────────────────────────────────────────── الفرص / Opportunities
def _opp_form(T, c: dict, error: str = "") -> str:
    err = f'<div class="alert bad">{e(error)}</div>' if error else ""
    return f"""{err}<div class="card"><form method="post" action="/admin/opportunities/save">
<label for="ow">{T("opp_week")}</label>
<input id="ow" name="week" type="number" min="1" max="53" required value="{e(str(c['week']))}">
<label for="oy">{T("opp_year")}</label>
<input id="oy" name="year" type="number" min="2000" max="2100" required value="{e(str(c['year']))}">
<label for="ot">{T("opp_paste")}</label>
<textarea id="ot" name="text" rows="14" dir="auto" required>{e(c.get('text') or '')}</textarea>
<p><button type="submit">{T("opp_save")}</button></p></form></div>"""


@router.get("/admin/opportunities")
async def opportunities_list(request: Request, msg: str = ""):
    if denied := _gate(request):
        return denied
    T = tr(req_lang(request))
    iso = datetime.date.today().isocalendar()
    cards = []
    for w in store.opportunity_weeks():
        items = "".join(
            f'<li>{e(i["title"])} <a href="{e(i["url"])}" rel="noreferrer" dir="ltr">{e(i["url"][:60])}</a></li>'
            for i in store.opportunity_week_items(w["year"], w["week"]))
        cards.append(f"""<div class="card"><div class="meta"><span>{w['year']} · {T("opp_week")} {w['week']}</span>
<span>{T("opp_count", n=w['n'])}</span></div><details><summary>{T("opp_paste")}</summary><ol>{items}</ol></details>
<p class="row"><form method="post" action="/admin/opportunities/send">
<input type="hidden" name="year" value="{w['year']}"><input type="hidden" name="week" value="{w['week']}">
<button class="small" type="submit">{T("opp_send")}</button></form>
<form method="post" action="/admin/opportunities/delete">
<input type="hidden" name="year" value="{w['year']}"><input type="hidden" name="week" value="{w['week']}">
<button class="danger small" type="submit">{T("opp_delete")}</button></form></p></div>""")
    subs = store.subscriber_counts()
    sub_rows = "".join(
        f'<tr><td>{e(channel_name(c, T))}</td><td>{subs.get(c, 0)}</td>'
        f'<td>{T("sub_on") if c in config.BROADCAST_CHANNELS else T("sub_off")}</td></tr>'
        for c in CHANNELS
    )
    last_html = ""
    try:
        lb = json.loads(store.setting("last_broadcast", "") or "null")
    except ValueError:
        lb = None
    if lb:
        line = T("last_broadcast", w=lb.get("week"), when=when(lb.get("ts", 0)),
                 s=lb.get("sent", 0), f=lb.get("failed", 0), k=lb.get("skipped", 0))
        last_html = f'<p class="muted">{e(line)}</p>'
    sub_card = f"""<h2>{T("sub_h")}</h2><p class="help">{T("sub_help")}</p>
<div class="card"><table><tr><th>{T("th_channel")}</th><th>{T("th_users")}</th><th>{T("th_state")}</th></tr>
{sub_rows}</table>{last_html}</div>"""
    body = (f'<p class="help">{T("opp_help", n=config.OPPORTUNITY_WEEKS)}</p>'
            + _opp_form(T, {"week": iso[1], "year": iso[0]})
            + sub_card
            + ("".join(cards) or f'<div class="card muted">{T("opp_none")}</div>'))
    return page(request, T("opp_title"), body, "opportunities", flash=msg)


@router.post("/admin/opportunities/save")
async def opportunities_save(request: Request):
    denied, form = await _post_gate(request, FIX_FORM_BYTES)
    if denied:
        return denied
    T = tr(req_lang(request))
    text = (form.get("text") or "").strip()
    try:
        week, year = int(form.get("week") or ""), int(form.get("year") or "")
    except ValueError:
        week = year = 0
    items = opportunities.parse_list(text) if text else []
    if not (1 <= week <= 53 and 2000 <= year <= 2100) or not items or len(text) > FIX_ANSWER_CHARS:
        c = {"week": form.get("week") or "", "year": form.get("year") or "", "text": text}
        return page(request, T("opp_title"), _opp_form(T, c, T("err_opp")),
                    "opportunities", status=400)
    store.save_opportunity_week(year, week, items)
    store.audit(who(request), "opportunities_save", f"{year}-W{week}")
    # تصحيح «فرص الأسبوع N» ليجيب «فرص» بالقائمة كاملة، ويُحدَّث إن وُجد
    # The «فرص الأسبوع N» correction, so «فرص» answers with the whole list; updated if it exists
    question = f"فرص الأسبوع {week}"
    existing = next((c for c in store.corrections() if c["question"] == question), None)
    vector, model = await asyncio.to_thread(retrieve.embed_correction, question)
    store.save_correction(question, text, "", True, vector, model,
                          existing["id"] if existing else 0, author=who(request))
    return _back("/admin/opportunities", msg="opp_saved")


@router.post("/admin/opportunities/send")
async def opportunities_send(request: Request):
    denied, form = await _post_gate(request)
    if denied:
        return denied
    if (form.get("year") or "").isdigit() and (form.get("week") or "").isdigit():
        # البثّ قد يستغرق دقائق مع مشتركين كثر، فيجري في الخلفية والنتيجة في الصفحة
        # With many subscribers the broadcast can take minutes, so it runs in
        # the background and the result shows on the page
        store.audit(who(request), "opportunities_send", f"{form['year']}-W{form['week']}")
        asyncio.create_task(broadcast.send_week(int(form["year"]), int(form["week"])))
    return _back("/admin/opportunities", msg="opp_sent")


@router.post("/admin/opportunities/delete")
async def opportunities_delete(request: Request):
    denied, form = await _post_gate(request)
    if denied:
        return denied
    if (form.get("year") or "").isdigit() and (form.get("week") or "").isdigit():
        store.delete_opportunity_week(int(form["year"]), int(form["week"]))
        store.audit(who(request), "opportunities_delete", f"{form['year']}-W{form['week']}")
    return _back("/admin/opportunities", msg="opp_deleted")


# ─────────────────────────────────────────────────────── الفريق / Team
def _valid_member_email(email: str) -> bool:
    local, at, domain = email.partition("@")
    return bool(at and local and domain == config.ALLOWED_EMAIL_DOMAIN
                and not any(ch in email for ch in " \n\r\t<>\""))


@router.get("/admin/team")
async def team(request: Request, msg: str = "", error: str = ""):
    if denied := _gate(request, "admin"):
        return denied
    T = tr(req_lang(request))
    me = request.state.member
    d = config.ALLOWED_EMAIL_DOMAIN
    err = {"member": T("err_member", d=d), "self": T("err_self")}.get(error, "")
    err_html = f'<div class="alert bad">{e(err)}</div>' if err else ""

    def role_opts(cur: str) -> str:
        return "".join(
            f'<option value="{r}" {"selected" if r == cur else ""}>{T("role_" + r)}</option>'
            for r in store.ROLES)

    add = f"""<div class="card"><h2>{T("team_add")}</h2><form method="post" action="/admin/team/add">
<label for="te">{T("team_email")}</label>
<input id="te" name="email" type="email" dir="ltr" required placeholder="name@{e(d)}">
<label for="tn">{T("team_name")}</label><input id="tn" name="name" type="text" maxlength="80">
<label for="tr">{T("team_role")}</label><select id="tr" name="role">{role_opts("editor")}</select>
<p><button type="submit">{T("team_add")}</button></p></form></div>"""
    rows = []
    for m in store.members():
        is_me = m["id"] == me.get("id")
        state = (f'<span class="badge ok">{T("m_active")}</span>' if m["active"]
                 else f'<span class="badge muted">{T("m_inactive")}</span>')
        you = f' <small>({T("m_you")})</small>' if is_me else ""
        rows.append(f"""<tr><td dir="ltr">{e(m['email'])}{you}</td><td>{e(m['name'])}</td>
<td><form method="post" action="/admin/team/update" class="row"><input type="hidden" name="id" value="{m['id']}">
<select name="role">{role_opts(m['role'])}</select> <button class="small" type="submit">{T("team_save")}</button></form></td>
<td>{state}</td><td>{when(m['last_login'])}</td>
<td class="row"><form method="post" action="/admin/team/update"><input type="hidden" name="id" value="{m['id']}">
<input type="hidden" name="active" value="{0 if m['active'] else 1}">
<button class="small" type="submit">{T("team_deactivate") if m['active'] else T("team_activate")}</button></form>
<form method="post" action="/admin/team/delete"><input type="hidden" name="id" value="{m['id']}">
<button class="danger small" type="submit">{T("team_delete")}</button></form></td></tr>""")
    table = (f'<div class="card"><table><tr><th>{T("th_email")}</th><th>{T("th_name")}</th>'
             f'<th>{T("th_role")}</th><th>{T("th_state")}</th><th>{T("th_last_login")}</th><th></th></tr>'
             f'{"".join(rows)}</table></div>' if rows else f'<div class="card muted">{T("team_none")}</div>')
    log_rows = "".join(
        f'<tr><td>{when(a["ts"])}</td><td>{e(a["member"])}</td><td>{e(a["action"])}</td>'
        f'<td dir="ltr">{e(a["target"] or "")}</td></tr>'
        for a in store.audit_log(100)
    ) or f'<tr><td colspan="4" class="muted">{T("none_yet")}</td></tr>'
    audit_html = (f'<h2>{T("audit_h")}</h2><p class="help">{T("audit_help")}</p>'
                  f'<div class="card"><table><tr><th>{T("th_when")}</th><th>{T("th_by")}</th>'
                  f'<th>{T("th_action")}</th><th>{T("th_target")}</th></tr>{log_rows}</table></div>')
    body = err_html + f'<p class="help">{e(T("team_help", d=d))}</p>' + add + table + audit_html
    return page(request, T("team_title"), body, "team", flash=msg)


@router.post("/admin/team/add")
async def team_add(request: Request):
    denied, form = await _post_gate(request, role="admin")
    if denied:
        return denied
    email = (form.get("email") or "").strip().lower()
    role = form.get("role") or "editor"
    name = (form.get("name") or "").strip()[:80]
    if not _valid_member_email(email) or role not in store.ROLES:
        return _back("/admin/team", error="member")
    store.add_member(email, role, name)
    store.audit(who(request), "member_add", f"{email} ({role})")
    return _back("/admin/team", msg="member_saved")


@router.post("/admin/team/update")
async def team_update(request: Request):
    denied, form = await _post_gate(request, role="admin")
    if denied:
        return denied
    mid = int(form["id"]) if (form.get("id") or "").isdigit() else 0
    m = store.member(mid)
    if not m:
        return _back("/admin/team")
    role, active = form.get("role"), form.get("active")
    # المدير لا يعطّل نفسه ولا يخفض دوره، كي لا تبقى اللوحة بلا مدير
    # An admin cannot deactivate themselves or lower their own role, so the
    # dashboard is never left without an admin
    if mid == request.state.member.get("id") and ((role and role != m["role"]) or active == "0"):
        return _back("/admin/team", error="self")
    if role in store.ROLES and role != m["role"]:
        store.set_member(mid, role=role)
        store.audit(who(request), "member_role", f"{m['email']} → {role}")
    if active in ("0", "1") and bool(int(active)) != bool(m["active"]):
        store.set_member(mid, active=active == "1")
        store.audit(who(request), "member_activate" if active == "1" else "member_deactivate", m["email"])
    return _back("/admin/team", msg="member_saved")


@router.post("/admin/team/delete")
async def team_delete(request: Request):
    denied, form = await _post_gate(request, role="admin")
    if denied:
        return denied
    mid = int(form["id"]) if (form.get("id") or "").isdigit() else 0
    if mid == request.state.member.get("id"):
        return _back("/admin/team", error="self")
    m = store.member(mid)
    if m:
        store.delete_member(mid)
        store.audit(who(request), "member_delete", m["email"])
    return _back("/admin/team", msg="member_deleted")


# ─────────────────────────────────────────────────────── الإعدادات / Settings
def _channel_state(T) -> str:
    def row(name: str, ok: bool, need: str) -> str:
        state = (f'<span class="state ok">{T("st_ok")}</span>' if ok
                 else f'<span class="state muted">{e(T("st_missing", need=need))}</span>')
        return f'<tr><td>{e(name)}</td><td class="wrap">{state}</td></tr>'

    meta = bool(config.META_APP_SECRET and config.META_VERIFY_TOKEN)
    return (
        row(T("ch_telegram"),
            bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_WEBHOOK_SECRET), T("need_tg"))
        + row(T("ch_whatsapp"),
              meta and bool(config.WHATSAPP_TOKEN and config.WHATSAPP_PHONE_NUMBER_ID),
              T("need_wa"))
        + row(T("ch_messenger"), meta and bool(config.MESSENGER_PAGE_TOKEN), T("need_ms"))
        + row(T("ch_web"), bool(config.WEB_CHAT_ORIGINS), T("need_web"))
    )


@router.get("/admin/settings")
async def settings(request: Request, msg: str = "", error: str = ""):
    if denied := _gate(request, "admin"):
        return denied
    lang = req_lang(request)
    T = tr(lang)
    thr = brain.threshold()
    paused = brain.paused()
    err = {"threshold": "err_threshold", "limit": "err_limit", "key": "err_key"}.get(error)
    err_html = f'<div class="alert bad">{T(err)}</div>' if err else ""
    fixed = [
        (T("f_answer_model"), config.ANSWER_MODEL),
        (T("f_embed_model"), _provider_label(T)),
        (T("f_dim"), config.EMBED_DIM),
        (T("f_top_k"), config.TOP_K),
        (T("f_max_tools"), config.MAX_TOOLS_LISTED),
        (T("f_rate"), config.RATE_LIMIT_MESSAGES),
        (T("f_window"), config.RATE_LIMIT_WINDOW),
        (T("f_history"), config.HISTORY_TURNS),
        (T("f_sources"), T("yes") if config.SHOW_SOURCES else T("no")),
    ]
    fixed_rows = "".join(f"<tr><th>{e(k)}</th><td>{e(str(v))}</td></tr>" for k, v in fixed)
    paused_msg = i18n.msg("paused", lang)
    web_on = store.setting("web_chat", "1") == "1"
    web_tag = f'<script src="{(config.PUBLIC_URL or "").rstrip("/")}/widget.js" defer></script>'
    body = f"""{err_html}<div class="card"><form method="post" action="/admin/settings">
<label for="t">{T("s_thr")}</label>
<p class="help">{T("s_thr_help", v=f"{config.MIN_RELEVANCE:.2f}")}</p>
<input id="t" name="threshold" type="number" step="0.01" min="0.05" max="0.9"
value="{thr:.2f}" style="max-width:140px">
<label for="dl">{T("s_limit")}</label>
<p class="help">{T("s_limit_help", v=config.DAILY_LIMIT)}</p>
<input id="dl" name="daily_limit" type="number" step="1" min="0" max="1000"
value="{brain.daily_limit()}" style="max-width:140px">
<label><input type="checkbox" name="paused" value="1" {'checked' if paused else ''}>
{T("s_pause")}</label>
<p class="help">{e(T("s_pause_help", m=paused_msg))}</p>
<label><input type="checkbox" name="web_chat" value="1" {'checked' if web_on else ''}>
{T("s_web")}</label>
<p class="help">{e(T("s_web_help", tag=web_tag))}</p>
<p class="row"><button type="submit">{T("save")}</button>
<button class="ghost" type="submit" name="reset" value="1">{T("reset_thr")}</button></p>
</form></div>
<h2>{T("channels")}</h2><div class="card"><table>{_channel_state(T)}</table></div>
<h2>{T("keys_h")}</h2>
<p class="help">{T("keys_help")}</p>
<div class="card"><table class="keys">{_keys_rows(T, lang)}</table></div>
<h2>{T("env_settings")}</h2>
<p class="help">{T("env_help")}</p>
<div class="card"><table>{fixed_rows}</table></div>"""
    return page(request, T("nav_settings"), body, "settings", flash=msg)


@router.post("/admin/settings")
async def save_settings(request: Request):
    denied, form = await _post_gate(request, role="admin")
    if denied:
        return denied
    limit = (form.get("daily_limit") or "").strip()
    if limit:
        if not limit.isdigit() or int(limit) > 1000:
            return _back("/admin/settings", error="limit")
        store.set_setting("daily_limit", str(int(limit)))
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
    store.set_setting("web_chat", "1" if form.get("web_chat") else "0")
    store.audit(who(request), "settings")
    return _back("/admin/settings", msg="saved")


def _keys_rows(T, lang: str) -> str:
    """صفوف مفاتيح API: الاسم وحاله ونموذج حفظ، بلا قيمة المفتاح.
    The API key rows: name, state and a save form, without the key's value."""
    i = 0 if lang == "ar" else 1
    rows = []
    for k in keys.status():
        if k["source"] == "dashboard":
            state = (f'<span class="badge ok">{T("key_dash")}</span> <code>{e(k["mask"])}</code>'
                     f'<div class="muted">{e(T("key_by", who=k["by"] or "?", when=when(k["updated"])))}</div>')
        elif k["source"] == "env":
            state = f'<span class="badge muted">{T("key_env")}</span> <code>{e(k["mask"])}</code>'
        else:
            state = f'<span class="badge warn">{T("key_none")}</span>'
        clear = ""
        if k["source"] == "dashboard":
            clear = (f'<form method="post" action="/admin/keys/clear">'
                     f'<input type="hidden" name="name" value="{k["name"]}">'
                     f'<button class="ghost small" type="submit">{T("key_clear")}</button></form>')
        rows.append(
            f'<tr><th scope="row">{e(k["label"][i])}<div class="muted"><code>{k["name"]}</code></div></th>'
            f"<td>{state}</td>"
            f'<td><form method="post" action="/admin/keys/set" class="row">'
            f'<input type="hidden" name="name" value="{k["name"]}">'
            f'<input type="password" name="value" autocomplete="off" spellcheck="false" '
            f'placeholder="{T("key_new")}" style="max-width:260px" required>'
            f'<button type="submit" class="small">{T("key_save")}</button></form>{clear}</td></tr>'
        )
    return (f'<tr><th>{T("th_key")}</th><th>{T("th_source")}</th><th>{T("key_new")}</th></tr>'
            + "".join(rows))


@router.get("/admin/sources")
async def sources_page(request: Request, msg: str = "", error: str = ""):
    if denied := _gate(request):
        return denied
    lang = req_lang(request)
    T = tr(lang)
    err = {"text": "err_src_text", "url": "err_src_url", "fetch": "err_src_fetch",
           "type": "err_src_type", "big": "err_src_big", "empty": "err_src_empty"}.get(error)
    err_html = f'<div class="alert bad">{T(err)}</div>' if err else ""
    can_edit = RANK.get(request.state.member["role"], -1) >= RANK["editor"]
    forms = ""
    if can_edit:
        forms = f"""<div class="grid sources-add">
<div class="card"><form method="post" action="/admin/sources/note">
<h3>{T("src_add_note")}</h3>
<label for="nt">{T("src_title")}</label><input id="nt" name="title" maxlength="{sources.MAX_TITLE}" required>
<label for="ntx">{T("src_text")}</label><textarea id="ntx" name="text" rows="7" required></textarea>
<p class="row"><button type="submit">{T("src_add")}</button></p></form></div>
<div class="card"><form method="post" action="/admin/sources/url">
<h3>{T("src_add_url")}</h3>
<label for="su">{T("src_url")}</label>
<input id="su" name="url" type="url" placeholder="https://" dir="ltr" required>
<p class="row"><button type="submit">{T("src_add")}</button></p></form></div>
<div class="card"><form method="post" action="/admin/sources/file" enctype="multipart/form-data">
<h3>{T("src_add_file")}</h3>
<label for="sf">{T("src_file")}</label>
<input id="sf" name="file" type="file" accept=".pdf,.docx,.md,.markdown,.txt,.html,.htm" required>
<p class="row"><button type="submit">{T("src_add")}</button></p></form></div></div>"""
    counts_by = sources.chunk_counts()
    rows = []
    for s in store.team_sources():
        if s["kind"] == "url":
            title = (f'<a href="{e(s["origin"])}" rel="noopener noreferrer" target="_blank">'
                     f'{e(s["title"])}</a>')
        else:
            title = e(s["title"])
            if s["origin"]:
                title += f'<div class="muted"><code>{e(s["origin"])}</code></div>'
        state = (f'<span class="badge ok">{T("src_ok")}</span>' if s["status"] == "ok"
                 else f'<span class="badge bad">{T("src_error")}</span>'
                      f'<div class="muted">{e(s["error"])}</div>')
        actions = ""
        if can_edit:
            if s["kind"] == "url":
                actions += (f'<form method="post" action="/admin/sources/sync">'
                            f'<input type="hidden" name="id" value="{s["id"]}">'
                            f'<button class="ghost small" type="submit">{T("src_sync")}</button></form>')
            actions += (f'<form method="post" action="/admin/sources/delete">'
                        f'<input type="hidden" name="id" value="{s["id"]}">'
                        f'<button class="danger small" type="submit">{T("src_delete")}</button></form>')
        rows.append(
            f'<tr><td class="wrap">{title}</td>'
            f'<td><span class="badge muted">{e(sources.kind_label(s["kind"], lang))}</span></td>'
            f'<td>{s["chars"]:,}</td><td>{counts_by.get(s["id"], 0)}</td>'
            f'<td>{state}</td>'
            f'<td class="muted">{e(s["added_by"])}<br>{when(s["added"])}</td>'
            f'<td class="muted">{when(s["synced"]) if s["kind"] == "url" else "—"}</td>'
            f'<td><div class="row">{actions}</div></td></tr>'
        )
    table = (f'<table><tr><th>{T("src_title")}</th><th>{T("th_kind")}</th><th>{T("th_chars")}</th>'
             f'<th>{T("th_chunks")}</th><th>{T("th_state")}</th><th>{T("th_added")}</th>'
             f'<th>{T("th_synced")}</th><th></th></tr>{"".join(rows)}</table>'
             if rows else f'<p class="muted">{T("src_none")}</p>')
    body = (f'{err_html}<p class="help">{T("src_help")}</p>{forms}'
            f'<h2>{T("src_list")}</h2><div class="card">{table}</div>')
    return page(request, T("nav_sources"), body, "sources", flash=msg)


def _src_error(exc: Exception) -> str:
    """رمز الخطأ للوحة من ValueError في app/sources.py. The dashboard's error code
    from a ValueError in app/sources.py."""
    code = str(exc)
    return code if code in ("text", "url", "fetch", "type", "big") else "fetch"


@router.post("/admin/sources/note")
async def sources_add_note(request: Request):
    denied, form = await _post_gate(request, limit=2_000_000)
    if denied:
        return denied
    try:
        _, vectors = sources.add_note(form.get("title", ""), form.get("text", ""), who(request))
    except ValueError:
        return _back("/admin/sources", error="text")
    return _back("/admin/sources", msg="src_added" if vectors else "src_added_novec")


@router.post("/admin/sources/url")
async def sources_add_url(request: Request):
    denied, form = await _post_gate(request)
    if denied:
        return denied
    try:
        _, vectors = await asyncio.to_thread(sources.add_url, form.get("url", ""), who(request))
    except ValueError as exc:
        return _back("/admin/sources", error=_src_error(exc))
    except Exception:  # noqa: BLE001 — فشل الشبكة أو الخادم البعيد / network or remote failure
        log.warning("تعذّر جلب مصدر فريق", exc_info=True)
        return _back("/admin/sources", error="fetch")
    return _back("/admin/sources", msg="src_added" if vectors else "src_added_novec")


@router.post("/admin/sources/file")
async def sources_add_file(request: Request):
    if denied := _gate(request, "editor"):
        return denied
    if not _same_origin(request):
        return _plain("origin_denied", 403)
    if int(request.headers.get("content-length") or 0) > sources.MAX_UPLOAD + 65_536:
        return _back("/admin/sources", error="big")
    form = await request.form(max_files=1, max_fields=4)
    upload = form.get("file")
    if upload is None or not getattr(upload, "filename", ""):
        return _back("/admin/sources", error="type")
    data = await upload.read(sources.MAX_UPLOAD + 1)
    try:
        _, vectors = await asyncio.to_thread(sources.add_file, upload.filename, data, who(request))
    except ValueError as exc:
        return _back("/admin/sources", error=_src_error(exc))
    except Exception:  # noqa: BLE001 — ملف تالف / a broken file
        log.warning("تعذّر قراءة ملف مرفوع", exc_info=True)
        return _back("/admin/sources", error="type")
    return _back("/admin/sources", msg="src_added" if vectors else "src_added_novec")


@router.post("/admin/sources/sync")
async def sources_sync(request: Request):
    denied, form = await _post_gate(request)
    if denied:
        return denied
    sid = form.get("id", "")
    if not sid.isdigit():
        return _back("/admin/sources", error="url")
    changed = await asyncio.to_thread(sources.sync_url, int(sid))
    src = store.team_source(int(sid)) or {}
    if src.get("status") == "error":
        return _back("/admin/sources", error="fetch")
    return _back("/admin/sources", msg="src_synced" if changed else "src_same")


@router.post("/admin/sources/delete")
async def sources_delete(request: Request):
    denied, form = await _post_gate(request)
    if denied:
        return denied
    sid = form.get("id", "")
    if sid.isdigit():
        sources.remove(int(sid), who(request))
    return _back("/admin/sources", msg="src_deleted")


def _scenario_form(T, lang: str, scenario: str = "", qlang: str = "", result: dict | None = None) -> str:
    """بطاقة معاينة السيناريوهات: النموذج ثم النتيجة إن وُجدت.
    The scenario preview card: the form, then the result if there is one."""
    i = 0 if lang == "ar" else 1
    options = "".join(
        f'<option value="{s["key"]}"{" selected" if s["key"] == scenario else ""}>'
        f'{e(s["label"][i])}</option>' for s in role.SCENARIOS
    )
    qlang = qlang or lang
    out = f"""<h2>{T("role_scen_h")}</h2><p class="help">{T("role_scen_help")}</p>
<div class="card"><form method="post" action="/admin/role/preview" class="row">
<label for="scen" style="margin:0">{T("role_scen")}</label>
<select id="scen" name="scenario" style="max-width:320px">{options}</select>
<label style="margin:0">{T("role_scen_lang")}</label>
<select name="lang" style="max-width:160px">
<option value="ar"{" selected" if qlang == "ar" else ""}>{T("role_ar")}</option>
<option value="en"{" selected" if qlang == "en" else ""}>{T("role_en")}</option></select>
<button type="submit">{T("role_scen_again") if result else T("role_scen_btn")}</button></form>"""
    if result:
        msgs = "".join(
            f'<p class="muted" style="margin:10px 0 2px">{T("role_scen_msg", n=n)}</p>'
            f'<div class="reply" dir="{"ltr" if qlang == "en" else "rtl"}">{e(m)}</div>'
            for n, m in enumerate(result["messages"], 1)
        )
        meta = ""
        if result["outcome"]:
            meta = (f'<div class="meta">{badge(result["outcome"], T)}'
                    f'<span>{T("conf", c=f"{result["confidence"]:.3f}")}</span></div>')
        srcs = "".join(f'<li><a href="{e(u)}" rel="noreferrer">{e(u)}</a></li>'
                       for u in result["sources"])
        q = (f'<p><b>{T("role_scen_q")}:</b> {e(result["question"])}</p>'
             if result["question"] else "")
        out += (f'<hr style="border:0;border-top:1px solid var(--line);margin:16px 0">{q}'
                f'<p><b>{T("role_scen_reply")}</b></p>{meta}{msgs}'
                + (f"<ul>{srcs}</ul>" if srcs else ""))
    return out + "</div>"


@router.post("/admin/role/preview")
async def role_preview(request: Request):
    denied, form = await _post_gate(request, role="admin")
    if denied:
        return denied
    scenario = form.get("scenario", "")
    qlang = "en" if form.get("lang") == "en" else "ar"
    try:
        result = await asyncio.to_thread(role.preview, scenario, qlang)
    except ValueError:
        return _back("/admin/role", error="scen")
    return _role_page(request, preview=(scenario, qlang, result))


@router.get("/admin/role")
async def role_page(request: Request, msg: str = "", error: str = ""):
    if denied := _gate(request, "admin"):
        return denied
    return _role_page(request, msg, error)


def _role_page(request: Request, msg: str = "", error: str = "",
               preview: tuple | None = None) -> HTMLResponse:
    lang = req_lang(request)
    T = tr(lang)
    # عناوين أقسام الدور وتسمياتها (عربية، إنجليزية) من app/role.py: الإنجليزية
    # لبقية اللغات / The role sections' titles and labels (Arabic, English) from
    # app/role.py: English for the other languages
    i = 0 if lang == "ar" else 1
    err = {"role": T("err_role", n=role.MAX_CHARS), "scen": T("err_scen"),
           "role_name": T("err_role_name", n=role.MAX_NAME_CHARS),
           "role_choice": T("err_role_choice")}.get(error, "")
    err_html = f'<div class="alert bad">{err}</div>' if err else ""
    sections = []
    for s in role.SECTIONS:
        kind = s.get("kind", "text")
        boxes = []
        for field, _attr, flabel, extra in s["fields"]:
            value, custom = role.current(field)
            state = (f'<span class="badge ok">{T("role_custom")}</span>' if custom
                     else f'<span class="badge muted">{T("role_default")}</span>')
            # التسمية: «بالعربية/بالإنجليزية» للنصوص باللغتين، أو اسم الحقل الخاص
            # The label: "Arabic/English" for texts in both languages, or the field's own name
            label = T("role_" + flabel) if isinstance(flabel, str) else e(flabel[i])
            if kind == "select":
                opts = "".join(
                    f'<option value="{v}"{" selected" if v == value else ""}>{e(names[i])}</option>'
                    for v, names in extra)
                control = f'<select id="{field}" name="{field}">{opts}</select>'
            elif kind == "line":
                control = (f'<input type="text" id="{field}" name="{field}" lang="{flabel}" '
                           f'dir="{"rtl" if flabel == "ar" else "ltr"}" maxlength="{extra}" '
                           f'value="{e(value)}">')
            else:
                control = (f'<textarea id="{field}" name="{field}" rows="{extra}" lang="{flabel}" '
                           f'dir="{"rtl" if flabel == "ar" else "ltr"}" maxlength="{role.MAX_CHARS}">'
                           f"{e(value)}</textarea>")
            boxes.append(f'<div><label for="{field}">{label} {state}</label>{control}</div>')
        cols = "two" if len(boxes) == 2 else "one"
        sections.append(
            f'<h2>{e(s["title"][i])}</h2><p class="help">{e(s["help"][i])}</p>'
            f'<div class="card"><form method="post" action="/admin/role/save">'
            f'<input type="hidden" name="section" value="{s["key"]}">'
            f'<div class="fields {cols}">{"".join(boxes)}</div>'
            f'<p class="row"><button type="submit">{T("save")}</button>'
            f'<button class="ghost" type="submit" name="reset" value="1">{T("role_reset")}</button>'
            f"</p></form></div>"
        )
    scen = _scenario_form(T, lang, *(preview or ("", "", None)))
    prompt_html = (f'<h2>{T("role_preview")}</h2><div class="card"><details><summary>'
                   f'{T("prompt_chars", n=len(brain.system_prompt()))}'
                   f'</summary><pre dir="rtl">{e(brain.system_prompt())}</pre></details></div>')
    body = f'{err_html}<p class="help">{T("role_help")}</p>{"".join(sections)}{scen}{prompt_html}'
    return page(request, T("nav_role"), body, "role", flash=msg)


@router.post("/admin/role/save")
async def role_save(request: Request):
    denied, form = await _post_gate(request, limit=200_000, role="admin")
    if denied:
        return denied
    section = next((s for s in role.SECTIONS if s["key"] == form.get("section")), None)
    if section is None:
        return _back("/admin/role", error="role")
    reset = bool(form.get("reset"))
    try:
        for field, _attr, _label, _extra in section["fields"]:
            role.save(field, "" if reset else (form.get(field) or ""), who(request))
    except ValueError as exc:
        return _back("/admin/role",
                     error={"name": "role_name", "choice": "role_choice"}.get(str(exc), "role"))
    return _back("/admin/role", msg="role_saved")


@router.post("/admin/keys/set")
async def key_set(request: Request):
    denied, form = await _post_gate(request, limit=4096, role="admin")
    if denied:
        return denied
    name = (form.get("name") or "").strip()
    value = (form.get("value") or "").strip()
    try:
        keys.set_key(name, value, who(request))
    except ValueError:
        return _back("/admin/settings", error="key")
    return _back("/admin/settings", msg="key_saved")


@router.post("/admin/keys/clear")
async def key_clear(request: Request):
    denied, form = await _post_gate(request, role="admin")
    if denied:
        return denied
    try:
        keys.clear_key((form.get("name") or "").strip(), who(request))
    except ValueError:
        return _back("/admin/settings", error="key")
    return _back("/admin/settings", msg="key_cleared")
