"""اختبارات لا تحتاج مستودع الموقع ولا أي مفتاح.  التشغيل: python tests/test_offline.py

تبني فهرساً صغيراً في مجلد مؤقت، وتحاكي Voyage، وتختبر ما يحمي بيان حين
يُضاف المفتاح أو يتعطّل، ثم أمان اللوحة.

Tests that need neither the site repository nor any key.
Run: python tests/test_offline.py

They build a small index in a temporary folder, simulate Voyage, and test
what protects Bayan when the key is added or stops working, then the
dashboard's security.
"""
import json
import os
import pathlib
import re
import sys
import tempfile
import time

TMP = pathlib.Path(tempfile.mkdtemp(prefix="bayan-test-"))
os.environ.update({
    "DATA_DIR": str(TMP / "data"),
    "KNOWLEDGE_PATH": str(TMP / "knowledge.jsonl"),
    "TOOLS_PATH": str(TMP / "tools.json"),
    "VOYAGE_API_KEY": "", "ANTHROPIC_API_KEY": "", "GEMINI_API_KEY": "",
    "ADMIN_PASSWORD": "", "SESSION_SECRET": "", "TELEGRAM_WEBHOOK_SECRET": "",
    "PUBLIC_URL": "",
})
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import brain, config, embed, i18n, ingest, retrieve, store  # noqa: E402
from app import main as server  # noqa: E402

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"✔ {name}")
    else:
        fail += 1
        print(f"✘ {name}   {detail}")


TOOLS = [
    {"name": "Hunchly", "category_ar": "الملاحظات والتوثيق", "category_en": "Notes",
     "summary_ar": "توثيق الصفحات أثناء البحث.", "link": "https://hunch.ly",
     "verification": "direct", "sensitive": False, "removed": False},
    {"name": "Domain Enquiries", "category_ar": "محركات البحث", "category_en": "Search",
     "summary_ar": "بحث مخصص.", "link": "https://cse.google.com/cse",
     "verification": "direct", "sensitive": True, "removed": False},
    {"name": "Custom Search", "category_ar": "محركات البحث", "category_en": "Search",
     "summary_ar": "بحث مخصص آخر.", "link": "https://cse.google.com/cse?cx=123:abc",
     "verification": "direct", "sensitive": False, "removed": False},
    {"name": "Discord Multi-Tool", "category_ar": "Discord", "category_en": "Discord",
     "domain": "github.com/AstraaDev", "sensitive": True, "removed": True,
     "removal_type_ar": "غير آمنة", "removal_reason_ar": "تضمّن أداة لسرقة رموز الدخول.",
     "removal_date": "2026-10-11"},
    {"name": "archive.is", "category_ar": "الأرشفة", "category_en": "Archiving",
     "domain": "archive.is", "sensitive": False, "removed": True,
     "removal_type_ar": "مكررة", "removal_reason_ar": "الخدمة نفسها التي يقدّمها Archive.today.",
     "removal_date": "2026-10-11"},
]
CHUNKS = [
    {"id": "tool:0", "type": "tool", "title": "Hunchly", "url": "https://paxmemoria.org/osint-tools",
     "text": "الأداة: Hunchly\nتوثّق كل صفحة تزورها أثناء البحث مع التوقيت."},
    {"id": "tool-removed:0", "type": "tool_removed", "title": "Discord Multi-Tool",
     "url": "https://paxmemoria.org/osint-tools",
     "text": "الأداة: Discord Multi-Tool\nأُزيلت.\nنطاقها السابق (لا يُفتح): github.com/AstraaDev"},
    {"id": "inv:x:0", "type": "investigation", "lang": "ar", "title": "تحقيق السيول",
     "url": "https://paxmemoria.org/investigations/x", "meta": {"slug": "x"},
     "text": "تحقيق السيول — صور الأقمار الصناعية تكشف حجم الكارثة.\n\n"
             "كشفت صور الأقمار الصناعية حجم السيول في محافظة الحديدة اليمنية."},
    {"id": "inv:x-en:0", "type": "investigation", "lang": "en", "title": "Floods investigation",
     "url": "https://paxmemoria.org/investigations/x-en", "meta": {"slug": "x-en"},
     "text": "Satellite images revealed the scale of the floods in Yemen's Hodeidah governorate."},
    {"id": "about:ar:0", "type": "about", "lang": "ar", "title": "عن Pax Memoria",
     "url": "https://paxmemoria.org/about", "meta": {"slug": "about", "position": 0},
     "text": "عن Pax Memoria\nالقسم: من نحن\n\nPax Memoria منظمة دولية غير ربحية مسجلة في السويد."},
]
pathlib.Path(os.environ["TOOLS_PATH"]).write_text(json.dumps(TOOLS, ensure_ascii=False))
pathlib.Path(os.environ["KNOWLEDGE_PATH"]).write_text(
    "\n".join(json.dumps(c, ensure_ascii=False) for c in CHUNKS))


def fake_vectors(texts, input_type="document", retries=6):
    """متجهات حتمية من كلمات النص: تكفي لاختبار المسار لا لجودته.
    Deterministic vectors from the words of the text: enough to test the
    path, not its quality."""
    out = []
    for t in texts:
        v = [0.0] * config.EMBED_DIM
        for w in t.split():
            v[hash(w) % config.EMBED_DIM] += 1.0
        out.append(v)
    return out


real_embed = embed.embed

# ── ٠. المزوّد المحلي: ما يمنعه من العمل يُعلَن بسببه ────────────────
# ── 0. Local provider: whatever stops it working is reported with its reason
print("── المزوّد المحلي ──")
from app import nano  # noqa: E402

config.EMBED_PROVIDER, config.EMBED_MODEL = "local", "voyage-4-nano"
config.LOCAL_MODEL_DIR = TMP / "no-model"
check("بلا نموذج: المتجهات معطّلة والسبب يذكر fetch_model",
      not embed.enabled() and "fetch_model" in embed.unavailable_reason(),
      embed.unavailable_reason())
fake_dir = TMP / "fake-model"
fake_dir.mkdir()
for f in nano.FILES:
    (fake_dir / f).write_text("x")
(fake_dir / "REVISION").write_text("deadbeef\n")
config.LOCAL_MODEL_DIR = fake_dir
check("نموذج من مراجعة أخرى يُرفض", "المراجعة المثبّتة" in embed.unavailable_reason(),
      embed.unavailable_reason())
(fake_dir / "REVISION").write_text(nano.REVISION + "\n")
check("نموذج بالمراجعة المثبّتة يُقبل", embed.enabled(), embed.unavailable_reason())
config.EMBED_MODEL = "voyage-4"
check("المزوّد المحلي لا يقبل نموذجاً غير voyage-4-nano",
      "voyage-4-nano" in embed.unavailable_reason())
check("الكود المنقول بلا اتصال بالشبكة",
      "requests" not in (pathlib.Path(nano.__file__).parent / "modeling.py").read_text()
      and "urllib" not in (pathlib.Path(nano.__file__).parent / "modeling.py").read_text())

# بقية الاختبارات بمزوّد Voyage المحاكى
# The remaining tests use the simulated Voyage provider
config.EMBED_PROVIDER, config.EMBED_MODEL = "voyage", "voyage-4"

# ── ١. Voyage: إعادة المحاولة ورسالة حساب بلا وسيلة دفع ─────────────
# ── 1. Voyage: retries, and the message for an account with no payment method
print("\n── Voyage ──")
config.VOYAGE_API_KEY = "test"
calls = []


def transport(responses):
    def handler(request):
        calls.append(request)
        status = responses.pop(0) if responses else 429
        if status == 200:
            n = len(json.loads(request.content)["input"])
            return httpx.Response(200, json={"data": [
                {"index": i, "embedding": [0.1] * 4} for i in range(n)]})
        return httpx.Response(status, text="rate limited")
    return httpx.MockTransport(handler)


real_client = httpx.Client
sleeps = []
real_sleep = embed.time.sleep
embed.time.sleep = sleeps.append
httpx_client = lambda responses: (lambda **kw: real_client(transport=transport(responses), **kw))  # noqa: E731

embed.httpx.Client = httpx_client([429, 503, 200])
vecs = embed.embed(["أ", "ب"])
check("429 ثم 503 ثم نجاح: تُعاد المحاولة", vecs and len(vecs) == 2 and len(calls) == 3)
check("الطلب إلى عنوان MongoDB Atlas", str(calls[-1].url) == "https://ai.mongodb.com/v1/embeddings",
      str(calls[-1].url))
check("الطلب يحدّد أبعاد المتجه", json.loads(calls[-1].content).get("output_dimension") == 1024)
check("الانتظار بين المحاولات", len(sleeps) == 2, sleeps)

embed.httpx.Client = httpx_client([])
try:
    embed.embed(["أ"], retries=2)
    check("429 دائم يرفع خطأ", False)
except embed.EmbedError as err:
    check("429 دائم يرفع خطأ يذكر وسيلة الدفع", "وسيلة دفع" in str(err), str(err))

calls.clear()
embed.httpx.Client = httpx_client([401])
try:
    embed.embed(["أ"])
except embed.EmbedError:
    pass
check("401 لا يُعاد (المفتاح خاطئ)", len(calls) == 1)

batches = list(embed._batches(["x" * 70_000, "y" * 70_000, "z"]))
check("الدفعات تُقسَم بعدد الأحرف", [len(b) for b in batches] == [1, 2], [len(b) for b in batches])
embed.httpx.Client = real_client
# time.sleep هو دالة الوحدة نفسها: يُعاد كي لا يبقى معطّلاً لبقية الاختبارات
# time.sleep is the module's own function: restore it so it does not stay
# disabled for the remaining tests
embed.time.sleep = real_sleep

# ── ٢. الفهرسة: الفشل لا يمسح الفهرس / 2. Indexing: a failure does not wipe the index ──
print("\n── الفهرسة ──")
config.VOYAGE_API_KEY = ""
okk, detail = ingest.run(pull=False)
check("فهرسة بلا مفتاح تنجح", okk, detail)
store.init()
retrieve.warm()
before = store.chunk_count()
v1 = store.index_version()

config.VOYAGE_API_KEY = "test"


def broken(*a, **k):
    raise embed.EmbedError("Voyage 429")


embed.embed = broken
okk, detail = ingest.run(pull=False)
check("فشل المتجهات يُفشل الفهرسة ويُعلنها", not okk and "429" in detail, detail)
check("الفهرس السابق باقٍ بعد الفشل", store.chunk_count() == before == len(CHUNKS))
check("رقم إصدار الفهرس لم يتغيّر", store.index_version() == v1)

embed.embed = fake_vectors
okk, detail = ingest.run(pull=False)
check("فهرسة بالمتجهات تنجح", okk and store.embedded_count() == len(CHUNKS), detail)
check("رقم الإصدار تغيّر", store.index_version() != v1)

# الخادم لم يُعِد التحميل بعد، والبحث التالي يلتقط الفهرس الجديد بنفسه
# The server has not reloaded yet, and the next search picks up the new
# index by itself
r = retrieve.search("كيف تبدو السيول في اليمن من الفضاء؟")
check("البحث يعيد التحميل تلقائياً ويستعمل المتجهات", r["used_vectors"],
      retrieve.status())

# ── ٣. المتجهات: تعطّل Voyage وتغيّر النموذج / 3. Vectors: a Voyage outage and a model change ──
print("\n── المسار الدلالي ──")
embed.embed = broken
r = retrieve.search("كيف تبدو السيول في اليمن من الفضاء؟")
check("تعطّل Voyage أثناء سؤال حيّ لا يرفع خطأ", r["has_any"] and not r["used_vectors"])
embed.embed = fake_vectors

config.EMBED_MODEL = "voyage-other"
retrieve.warm()
check("تغيّر نموذج المتجهات يعطّل المتجهات حتى إعادة الفهرسة",
      retrieve.status()["vectors"] == 0 and "voyage-other" in retrieve.status()["vector_note"],
      retrieve.status())
config.EMBED_MODEL = "voyage-4"
config.EMBED_DIM = 512
retrieve.warm()
check("تغيّر أبعاد المتجه يعطّل المتجهات حتى إعادة الفهرسة",
      retrieve.status()["vectors"] == 0 and "@512" in retrieve.status()["vector_note"],
      retrieve.status())
config.EMBED_DIM = 1024
retrieve.warm()

r = retrieve.search("كيف تبدو السيول في اليمن من الفضاء؟")
check("IDF محمّل (التداخل موزون بالندرة)", len(retrieve._S.idf) > 0)

# ── ٤. الطبقة ٤ على فهرس الاختبار / 4. Layer 4 on the test index ──
print("\n── مرشّح الروابط ──")
t, n = brain.strip_forbidden("حمّلها من github.com/AstraaDev/tool أو https://cse.google.com/cse.")
check("نطاق مُزال ورابط حسّاس يُحذفان", n == 2 and "AstraaDev" not in t and "cse.google" not in t, t)
t, n = brain.strip_forbidden("ابحث عبر https://cse.google.com/cse?cx=123:abc")
check("رابط عادي يشترك في البادئة يبقى", n == 0, t)
t, n = brain.strip_forbidden("أُزيلت أداة archive.is من الدليل، فلا تفتح https://www.archive.is/abc.")
check("نطاق هو اسم الأداة يُكتب معطَّلاً بلا مسار ولا يُستبدل بصفحة الدليل",
      n == 2 and t == "أُزيلت أداة archive[.]is من الدليل، فلا تفتح www[.]archive[.]is.", t)
t, n = brain.strip_forbidden("المستودع github.com/AstraaDev/tool")
check("أداة على منصة مشتركة تُستبدل بصفحة الدليل",
      n == 1 and t.endswith("/osint-tools") and "github" not in t, t)

# ── ٥. اللوحة / 5. Dashboard ─────────────────────────────────────
print("\n── اللوحة ──")
# المتجهات المزيّفة تقرّب أي سؤال من أي مقطع، فتُطفأ هنا ليبقى رفض البوابة حتمياً
# Fake vectors bring any question close to any passage, so they are turned
# off here to keep the gate's refusal deterministic
config.VOYAGE_API_KEY = ""
retrieve.warm()
client = TestClient(server.app)
r = client.get("/admin", follow_redirects=False)
check("بلا كلمة مرور: اللوحة معطّلة", r.status_code == 503)
import logging  # noqa: E402
check("طلبات httpx لا تُسجَّل، فتوكن تيليغرام في عنوانها لا يصل إلى السجلّ",
      all(logging.getLogger(n).getEffectiveLevel() >= logging.WARNING
          for n in ("httpx", "httpx2")))

# سجلّ الطلبات: رمز Google وتوكن تحقق ميتا في سلسلة الاستعلام يُحجبان
# The access log: the Google code and the Meta verify token in the query
# string are hidden
from app import logfilter  # noqa: E402


def access_record(path, method="GET"):
    return logging.LogRecord("uvicorn.access", logging.INFO, "h11_impl.py", 0,
                             '%s - "%s %s HTTP/%s" %d',
                             ("1.2.3.4:5", method, path, "1.1", 303), None)


access_filter = logfilter.RedactQueryFilter()
rec = access_record("/admin/auth/google/callback?state=st4te&code=4/0Asecret")
access_filter.filter(rec)
check("رجوع Google في سجلّ الطلبات بلا code ولا state",
      rec.args[2] == "/admin/auth/google/callback?…" and "secret" not in rec.getMessage()
      and rec.getMessage().endswith('"GET /admin/auth/google/callback?… HTTP/1.1" 303'),
      rec.getMessage())
rec = access_record("/webhooks/meta?hub.mode=subscribe&hub.verify_token=vt&hub.challenge=1")
access_filter.filter(rec)
check("تحقق ميتا في سجلّ الطلبات بلا hub.verify_token",
      rec.args[2] == "/webhooks/meta?…" and "verify_token" not in rec.getMessage())
rec = access_record("/admin/messages?lang=ar&page=2")
access_filter.filter(rec)
check("طلب عادي باستعلام يبقى كما هو في السجلّ",
      rec.args[2] == "/admin/messages?lang=ar&page=2")
rec = access_record("/admin/auth/google/callback")
access_filter.filter(rec)
check("الرجوع بلا استعلام يبقى كما هو", rec.args[2] == "/admin/auth/google/callback")
check("المرشّح مركّب على uvicorn.access مرة واحدة عند تحميل الخادم",
      sum(isinstance(f, logfilter.RedactQueryFilter)
          for f in logging.getLogger("uvicorn.access").filters) == 1)

config.ADMIN_PASSWORD = "correct horse battery"
config.SESSION_SECRET = "s" * 40
r = client.get("/admin", follow_redirects=False)
check("بلا دخول: تحويل إلى صفحة الدخول", r.status_code == 303 and r.headers["location"] == "/admin/login")
check("/admin/status بلا دخول غير موجود", client.get("/admin/status").status_code == 404)
check("/debug/ask من خارج الخادم غير موجود",
      client.post("/debug/ask", json={"question": "x"}).status_code == 404)

r = client.post("/admin/login", data={"password": "wrong"}, follow_redirects=False)
check("كلمة مرور خاطئة تُرفض", "error=bad" in r.headers.get("location", ""))

# رسالة من الجمهور فيها شيفرة، ومعرّفها رقم هاتف
# A message from the public that contains code, and whose ID is a phone number
store.remember("whatsapp", "966500000001", "user", "<script>alert(1)</script> ما أدوات Hunchly؟",
               outcome="refused_gate", confidence=0.21, sources=[])
store.remember("whatsapp", "966500000001", "assistant", "رد <b>تجريبي</b>")

r = client.post("/admin/login", data={"password": "correct horse battery"}, follow_redirects=False)
check("كلمة المرور الصحيحة تفتح جلسة", r.status_code == 303 and "bayan_admin" in r.cookies)
# الافتراضي الإنجليزية؛ هذه الاختبارات تقرأ النصوص العربية فتختارها أولاً
# The default is English; these tests read the Arabic texts, so they pick it first
r = client.get("/admin")
check("بلا كوكي تُعرض اللوحة بالإنجليزية", r.status_code == 200 and 'dir="ltr"' in r.text
      and "Overview" in r.text and 'class="side"' in r.text)
r = client.get("/admin?lang=ar")
check("نظرة عامة تعمل", r.status_code == 200 and "نظرة عامة" in r.text)
check("اللوحة تعرض بطاقة «بلا جواب» وقسم المواضيع",
      "بلا جواب، آخر 7 أيام" in r.text and "مواضيع الأسئلة" in r.text and "الأكثر سؤالاً" in r.text)
check("اللوحة تعرض الأعداد منذ البداية", "منذ البداية (أعداد فقط)" in r.text and "المجموع" in r.text)
check("ترويسة CSP تمنع كل سكربت", "default-src 'none'" in r.headers.get("content-security-policy", ""))
r = client.get("/admin/messages")
check("الأسئلة تُعرض", "ما أدوات Hunchly" in r.text)
check("نص الجمهور مُهرَّب", "<script>alert" not in r.text and "&lt;script&gt;" in r.text)
check("رقم الهاتف لا يظهر في اللوحة", "966500000001" not in r.text)
check("/admin/status بعد الدخول يعمل", client.get("/admin/status").status_code == 200)

r = client.get("/admin?lang=en")
check("?lang=en يعرض اللوحة بالإنجليزية ومن اليسار",
      "Overview" in r.text and 'dir="ltr"' in r.text and "نظرة عامة" not in r.text)
check("ملاحظة البحث الدلالي بالإنجليزية في اللوحة الإنجليزية",
      "Semantic search is off." in r.text and "VOYAGE_API_KEY is not set" in r.text)
check("اختيار اللغة يُحفظ في كوكي", r.cookies.get("bayan_lang") == "en")
check("الصفحة التالية تبقى بالإنجليزية", "Gate threshold" in client.get("/admin/settings").text)
check("رابط العودة إلى العربية في الشريط", "lang=ar" in r.text and "العربية" in r.text)
r = client.get("/admin/messages?lang=ar")
check("?lang=ar يعيد العربية ومن اليمين",
      "أسئلة الجمهور" in r.text and 'dir="rtl"' in r.text)
check("قيمة لغة غير معروفة لا تُقبل: تبقى لغة الكوكي", 'dir="rtl"' in client.get("/admin?lang=xx").text)
check("الشريط الجانبي: قائمة اللغات وخروج والصفحة الفعّالة",
      'class="langform"' in r.text and '<select name="lang"' in r.text and "English" in r.text
      and "/admin/logout" in r.text and 'class="on"' in r.text, r.text[:200])

msg_id = store.questions()[0]["id"]
r = client.post("/admin/block", data={"msg_id": str(msg_id), "next": "/admin/messages"},
                headers={"origin": "https://evil.example"}, follow_redirects=False)
check("طلب من مصدر آخر يُرفض", r.status_code == 403 and not store.is_blocked("whatsapp", "966500000001"))
r = client.post("/admin/block", data={"msg_id": str(msg_id), "next": "https://evil.example"},
                follow_redirects=False)
check("الحظر برقم الرسالة يعمل", store.is_blocked("whatsapp", "966500000001"))
check("التحويل بعد الحظر يبقى داخل اللوحة", r.headers["location"].startswith("/admin"))
check("المحظور يتلقى الرفض", brain.handle("ما أدوات Hunchly؟", "whatsapp", "966500000001")
      == config.OUT_OF_SCOPE_MESSAGE)
fp = server.dashboard.fingerprint("whatsapp", "966500000001")
client.post("/admin/unblock", data={"channel": "whatsapp", "fp": fp})
check("رفع الحظر بالبصمة يعمل", not store.is_blocked("whatsapp", "966500000001"))

# ── التقييم والتصحيحات في اللوحة / Ratings and corrections in the dashboard ──
r = client.post("/admin/rate", data={"msg_id": str(msg_id), "rating": "down", "reason": "wrong",
                                     "note": "<b>x</b>", "next": "/admin/messages"},
                follow_redirects=False)
check("التقييم يُحفظ ويعود إلى بطاقة السؤال",
      r.status_code == 303 and f"#m{msg_id}" in r.headers["location"]
      and [q["id"] for q in store.questions(rating="down")] == [msg_id], r.headers.get("location"))
r = client.get("/admin/messages?rating=down")
check("تصفية الأسئلة بالتقييم، والسبب يظهر، والملاحظة مُهرَّبة",
      "التقييم: تحتاج تصحيحاً" in r.text and "معلومة خاطئة" in r.text
      and "&lt;b&gt;x" in r.text and "<b>x</b>" not in r.text)
check("«بلا تقييم» يستثني المقيَّم", msg_id not in [q["id"] for q in store.questions(rating="none")])
client.post("/admin/rate", data={"msg_id": str(msg_id), "rating": "clear", "next": "/admin/messages"})
check("مسح التقييم", not store.questions(rating="down"))
r = client.post("/admin/rate", data={"msg_id": str(msg_id), "rating": "up"},
                headers={"origin": "https://evil.example"}, follow_redirects=False)
check("تقييم من مصدر آخر يُرفض", r.status_code == 403 and not store.questions(rating="up"))

store.remember("telegram", "u-rate", "user", "سؤال للتقييم", outcome="answered",
               confidence=0.5, sources=[])
rid = store.questions(channel="telegram")[0]["id"]
store.set_rating(rid, -1)
store.clear_history("telegram", "u-rate")
with store.db() as conn:
    left = conn.execute("SELECT COUNT(*) FROM ratings WHERE message_id=?", (rid,)).fetchone()[0]
check("التقييم يُحذف مع رسالته", left == 0)

run_id = store.start_run()
check("عند الإقلاع تُغلق دورة فهرسة قطعتها إعادة التشغيل",
      store.close_interrupted_runs() == 1 and store.last_run()["id"] == run_id
      and store.last_run()["ok"] == 0 and "Interrupted" in store.last_run()["detail"])

r = client.get(f"/admin/corrections/new?from={msg_id}")
check("نموذج التصحيح يُملأ بالسؤال الأصلي ويعرض ردّ بيان للرجوع إليه",
      r.status_code == 200 and "ما أدوات Hunchly" in r.text and "رد &lt;b&gt;تجريبي" in r.text)
fix = {"question": "ما أداة Hunchly؟", "answer": "Hunchly توثّق الصفحات أثناء البحث.",
       "url": "https://evil.example/x", "active": "1"}
r = client.post("/admin/corrections/save", data=fix)
check("رابط مصدر من خارج الموقع يُرفض", r.status_code == 400 and not store.corrections())
r = client.post("/admin/corrections/save", data={**fix, "answer": ""})
check("إجابة فارغة تُرفض", r.status_code == 400 and not store.corrections())
r = client.post("/admin/corrections/save",
                data={**fix, "url": "https://paxmemoria.org/osint-tools"}, follow_redirects=False)
saved = store.corrections()
check("التصحيح يُحفظ، وبلا متجهات يُنبَّه إلى أنه يطابق السؤال نفسه وحده",
      r.status_code == 303 and "fix_novec" in r.headers["location"]
      and len(saved) == 1 and saved[0]["vector"] is None, r.headers.get("location"))
cid = saved[0]["id"]
r = client.get("/admin/corrections")
check("صفحة التصحيحات تعرضه مع رابط تجربته",
      "ما أداة Hunchly؟" in r.text and "/admin/try?q=" in r.text)
check("رابط «جرّبه» يملأ خانة التجربة ولا يستدعي النموذج",
      "ما أداة Hunchly؟" in client.get("/admin/try?q=ما أداة Hunchly؟").text)
client.post("/admin/corrections/save",
            data={"id": str(cid), "question": fix["question"], "answer": "معدّلة", "url": ""})
check("تعديل التصحيح وإطفاؤه", store.correction(cid)["answer"] == "معدّلة"
      and not store.correction(cid)["active"])
client.post("/admin/corrections/delete", data={"id": str(cid)})
check("حذف التصحيح", store.correction(cid) is None)
# صفحة الفرص في اللوحة: لصق قائمة أسبوع يحفظ فرصها وتصحيح «فرص الأسبوع N»
r = client.get("/admin/opportunities")
check("صفحة الفرص تفتح وفيها نموذج اللصق", r.status_code == 200 and "الفرص الأسبوعية" in r.text)
r = client.post("/admin/opportunities/save", data={"week": "99", "year": "2026", "text": "x"})
check("رقم أسبوع أو قائمة غير صالحة تُرفض", r.status_code == 400 and not store.opportunity_weeks())
r = client.post("/admin/opportunities/save", follow_redirects=False, data={
    "week": "45", "year": "2026",
    "text": "قائمة:\n1. زمالة اليمن\n   https://yhms-ye.org/f/\n2. منحة دافوس https://ijp.org/a.pdf"})
fx = [c for c in store.corrections() if c["question"] == "فرص الأسبوع 45"]
check("لصق الأسبوع يحفظ فرصتين وتصحيح «فرص الأسبوع 45»",
      r.status_code == 303 and "opp_saved" in r.headers["location"]
      and [w["n"] for w in store.opportunity_weeks()] == [2] and len(fx) == 1, r.headers.get("location"))
client.post("/admin/opportunities/save", data={
    "week": "45", "year": "2026", "text": "1. منحة وحيدة https://ijp.org/b.pdf"})
check("إعادة لصق الأسبوع تستبدل قائمته ولا تكرّر تصحيحه",
      [w["n"] for w in store.opportunity_weeks()] == [1]
      and len([c for c in store.corrections() if c["question"] == "فرص الأسبوع 45"]) == 1)
client.post("/admin/opportunities/delete", data={"year": "2026", "week": "45"})
check("حذف الأسبوع", store.opportunity_weeks() == [])
for c in store.corrections():
    store.delete_correction(c["id"])
check("الإنجليزية في صفحة التصحيحات", "Approved corrections" in
      client.get("/admin/corrections?lang=en").text)
client.get("/admin?lang=ar")

r = client.post("/admin/settings", data={"threshold": "2"}, follow_redirects=False)
check("عتبة خارج المدى تُرفض", "error=threshold" in r.headers["location"])
client.post("/admin/settings", data={"threshold": "0.47"})
check("العتبة تُحفظ وتُطبَّق دون إعادة تشغيل", abs(brain.threshold() - 0.47) < 1e-9)
client.post("/admin/settings", data={"threshold": "0.47", "paused": "1"})
check("الإيقاف المؤقت يعمل", brain.handle("سؤال", "telegram", "1") == config.PAUSED_MESSAGE)
client.post("/admin/settings", data={"threshold": "0.47", "reset": "1"})
check("العتبة تعود إلى قيمة ‎.env، والإيقاف يُرفع",
      brain.threshold() == config.MIN_RELEVANCE and not brain.paused())

r = client.post("/admin/try", data={"q": "ما هي عاصمة فرنسا؟"})
check("صفحة التجربة ترفض سؤالاً خارجياً دون نموذج", r.status_code == 200 and "رفضته البوابة" in r.text)

old = config.ADMIN_PASSWORD
config.ADMIN_PASSWORD = "a different long password"
check("تغيير كلمة المرور يُخرج الجلسات القائمة",
      client.get("/admin", follow_redirects=False).status_code == 303)
config.ADMIN_PASSWORD = old

fresh = TestClient(server.app)
codes = [fresh.post("/admin/login", data={"password": "x"}, follow_redirects=False)
         .headers["location"] for _ in range(6)]
check("محاولات الدخول محدودة", "error=slow" in codes[-1], codes[-1])

# ── ٥ب. حدّ الأسئلة اليومي / 5b. Daily question limit ────────────
print("\n── الحدّ اليومي ──")
store.set_setting("daily_limit", "3")
replies = [brain.handle(f"ما هي عاصمة بلد رقم {i}؟", "telegram", "u-limit") for i in range(4)]
check("الأسئلة الثلاثة الأولى تُجاب أو تُرفض كالعادة",
      all("الحدّ اليومي للأسئلة" not in r for r in replies[:3]))
check("الرابع يتلقى رسالة الحدّ ومتى يعود",
      "بلغت الحدّ اليومي للأسئلة" in replies[3] and "3" not in replies[3].split("\n")[0] and "بعد" in replies[3], replies[3])
check("رسالة الحدّ لا تُحسب سؤالاً",
      len(store.questions_since("telegram", "u-limit", time.time() - 86400)) == 3)
check("/start يعمل بعد بلوغ الحدّ",
      brain.handle("/start", "telegram", "u-limit") == i18n.welcome(None, brain.daily_limit()))
check("مستخدم آخر لا يتأثر", "الحدّ اليومي للأسئلة" not in brain.handle("سؤال", "telegram", "u-other"))
check("المعرّف نفسه في قناة أخرى لا يتأثر",
      "الحدّ اليومي للأسئلة" not in brain.handle("سؤال", "whatsapp", "u-limit"))
store.set_setting("daily_limit", "0")
check("0 يعني بلا حدّ", "الحدّ اليومي للأسئلة" not in brain.handle("سؤال", "telegram", "u-limit"))
r = client.post("/admin/settings", data={"threshold": "0.30", "daily_limit": "abc"},
                follow_redirects=False)
check("حدّ يومي غير صالح يُرفض من اللوحة", "error=limit" in r.headers["location"])
client.post("/admin/settings", data={"threshold": "0.30", "daily_limit": "10"})
check("الحدّ اليومي يُحفظ من اللوحة", brain.daily_limit() == 10)

# ── ٥ج. اللغتان / 5c. The two languages ──────────────────────────
print("\n── اللغتان ──")

check("سؤال عربي فيه اسم أداة إنجليزي طويل يبقى عربياً",
      i18n.detect("ما هي أداة Google Earth Pro؟") == "ar")
check("سؤال بالإنجليزية يُكشف إنجليزياً", i18n.detect("How do I track a flight?") == "en")
check("أرقام ورموز وحدها تُجاب بالعربية", i18n.detect("123 ؟!") == "ar")
check("سؤال إنجليزي خارج النطاق يُرفض بالإنجليزية",
      brain.handle("What is the capital of France?", "telegram", "u-en")
      == config.OUT_OF_SCOPE_MESSAGE_EN)
check("/help باللغتين، و«مساعدة» بالعربية وحدها",
      config.BOT_NAME_EN in brain.handle("/help", "telegram", "u-en")
      and config.BOT_NAME_EN not in brain.handle("مساعدة", "telegram", "u-en"))
check("/start بلا لغة معروفة: الترحيب باللغتين",
      "Hello" in brain.handle("/start", "telegram", "u-w") and "أهلاً" in brain.handle("/start", "telegram", "u-w"))
w_ar = brain.handle("/start", "telegram", "u-w", "ar")
w_en = brain.handle("/start", "telegram", "u-w", "en-GB")
check("/start بواجهة عربية: بالعربية وحدها", "أهلاً" in w_ar and "Hello" not in w_ar)
check("/start بواجهة إنجليزية: بالإنجليزية وحدها", "Hello" in w_en and "أهلاً" not in w_en)
check("الترحيب يقول ما يستطيع بيان وما لا يستطيع",
      "ما أستطيع فعله" in w_ar and "ما لا أستطيع فعله" in w_ar
      and "What I can do" in w_en and "What I can't do" in w_en)
check("الترحيب لا يذكر عدد الأسئلة المسموح",
      "حدّ الأسئلة" not in w_ar and str(brain.daily_limit()) not in w_ar.split("\n\n", 1)[-1]
      and "Limit:" not in w_en)
before = len(store.questions_since("whatsapp", "u-greet", time.time() - 86400))
g_ar = brain.handle("مرحباً!", "whatsapp", "u-greet")
g_en = brain.handle("Hello 👋", "whatsapp", "u-greet")
check("تحية عربية: ترحيب بالعربية", "أهلاً" in g_ar and "Hello" not in g_ar)
check("تحية إنجليزية: ترحيب بالإنجليزية", "Hello" in g_en and "أهلاً" not in g_en)
parts = brain.messages(g_ar)
check("التحية تُجاب برسالتين: ردّ التحية ثم الترحيب بلا سطر «أهلاً بك»",
      parts == ["أهلاً وسهلاً 👋", i18n.welcome("ar", brain.daily_limit(), opener="")]
      and "أهلاً بك" not in parts[1] and "ما أستطيع فعله" in parts[1], parts[:1])
check("ردّ التحية بمثلها: السلام عليكم، صباح الخير، مساء الخير، good morning",
      brain.messages(brain.handle("السلام عليكم", "whatsapp", "u-greet"))[0] == "وعليكم السلام ورحمة الله وبركاته 👋"
      and brain.messages(brain.handle("صباح الخير!", "whatsapp", "u-greet"))[0] == "صباح النور 👋"
      and brain.messages(brain.handle("مساء الخير", "whatsapp", "u-greet"))[0] == "مساء النور 👋"
      and brain.messages(brain.handle("Good morning", "whatsapp", "u-greet"))[0] == "Good morning 👋"
      and brain.messages(g_en)[0] == "Hello 👋")
check("/start يبقى رسالة واحدة تبدأ بـ«أهلاً بك»",
      brain.messages(brain.handle("بدء", "whatsapp", "u-greet")) == [i18n.welcome("ar", brain.daily_limit())]
      and i18n.welcome("ar", brain.daily_limit()).startswith("أهلاً بك 👋\n\n"))
check("الترحيب يذكر الأجزاء الأربعة",
      all(k in w_ar for k in ("دليلنا", "تحقيقاتنا", "«فرص»", "السلامة الرقمية"))
      and all(k in w_en for k in ("our guide", "investigations", "فرص", "digital-safety")))
check("التحية لا تُحسب سؤالاً",
      len(store.questions_since("whatsapp", "u-greet", time.time() - 86400)) == before)
check("سؤال يبدأ بتحية يبقى سؤالاً", "أهلاً" not in brain.handle("مرحبا، ما هي عاصمة فرنسا؟", "whatsapp", "u-greet"))
check("رسالة بلا نص: بيان يقرأ النص فقط، بلغة الواجهة",
      brain.handle("", "telegram", "u-img", "en") == i18n.msg("text_only", "en"))
from app.channels import messenger as ms, telegram as tgp, whatsapp as wa  # noqa: E402
check("تيليغرام: صورة بلا تعليق تصل بنص فارغ ولغة الواجهة",
      tgp.parse({"update_id": 7, "message": {"chat": {"id": 1}, "photo": [{}],
                 "from": {"language_code": "ar"}}}) == ("tg:7", "1", "", "ar"))
check("واتساب: صورة تصل بنص فارغ",
      wa.parse({"entry": [{"changes": [{"value": {"messages": [
          {"id": "m1", "from": "966", "type": "image"}]}}]}]}) == [("wa:m1", "966", "966", "")])
check("واتساب: يُعرَّف المستخدم بالـBSUID ويُردّ على رقمه",
      wa.parse({"entry": [{"changes": [{"value": {"messages": [
          {"id": "m2", "from": "966", "from_user_id": "SA.123", "type": "text",
           "text": {"body": "سؤال"}}]}}]}]}) == [("wa:m2", "SA.123", "966", "سؤال")])
check("واتساب: صاحب اسم المستخدم بلا رقم يُردّ عليه بالـBSUID",
      wa.parse({"entry": [{"changes": [{"value": {"messages": [
          {"id": "m3", "from_user_id": "SA.456", "type": "text",
           "text": {"body": "سؤال"}}]}}]}]}) == [("wa:m3", "SA.456", "SA.456", "سؤال")])
check("واتساب: رسالة بلا أي معرّف تُتجاهل ولا توقف الباقي",
      [e[0] for e in wa.parse({"entry": [{"changes": [{"value": {"messages": [
          {"id": "m4", "type": "text", "text": {"body": "x"}},
          {"id": "m5", "from": "966", "type": "text", "text": {"body": "y"}}]}}]}]})]
      == ["wa:m5"])
check("ماسنجر: مرفق بلا نص يصل بنص فارغ",
      ms.parse({"entry": [{"messaging": [{"sender": {"id": "p"}, "message": {
          "mid": "x", "attachments": [{"type": "image"}]}}]}]}) == [("fb:x", "p", "")])
store.set_setting("daily_limit", "1")
brain.handle("Is there a tool for photos?", "telegram", "u-en-limit")
_limited = brain.handle("And for videos?", "telegram", "u-en-limit")
check("رسالة الحدّ اليومي بلغة السائل ولا تذكر العدد، والحدّ يبقى مطبَّقاً",
      "You have reached the daily question limit" in _limited and "limit of 1" not in _limited)
store.set_setting("daily_limit", "10")
sens_t = {"name": "X", "category_en": "Search", "summary_en": "s", "sensitive": 1,
          "caution": None, "link": "https://bad.example", "verification": "trained", "removed": 0}
rec = brain.tool_record(sens_t, "en")
check("سجلّ الأداة الحسّاسة بالإنجليزية: التحذير ومنع الرابط",
      "Mandatory warning" in rec and "direct link is forbidden" in rec
      and "bad.example" not in rec, rec)
check("درجة التحقق بالإنجليزية ليست حكم أمان",
      "not reviewed live" in rec and "safe" not in rec.lower().replace("unsafe", "")
      and "verified" not in rec.lower(), rec)
rm_t = {"name": "Y", "removed": 1, "removal_date": "2026-10-11", "domain": "evil.example",
        "removal_reason_ar": "سبب"}
rec = brain.tool_record(rm_t, "en")
check("سجلّ الأداة المُزالة بالإنجليزية", "removed from the guide on 2026-10-11" in rec
      and "forbidden" in rec and "evil.example" not in rec, rec)
twin_ar = {"type": "investigation", "meta": {"slug": "x", "lang": "ar"}}
twin_en = {"type": "investigation", "meta": {"slug": "x-en", "lang": "en"}}
only_ar = {"type": "investigation", "meta": {"slug": "no-english", "lang": "ar"}}
retrieve.warm()
check("لسؤال إنجليزي: النسخة الإنجليزية من التحقيق لا العربية",
      retrieve._in_language(twin_en, "en", retrieve._S)
      and not retrieve._in_language(twin_ar, "en", retrieve._S))
check("تحقيق بلا نسخة إنجليزية يبقى متاحاً لسؤال إنجليزي",
      retrieve._in_language(only_ar, "en", retrieve._S))
check("لسؤال عربي: النسخة العربية لا الإنجليزية",
      retrieve._in_language(twin_ar, "ar", retrieve._S)
      and not retrieve._in_language(twin_en, "ar", retrieve._S))

# ── ٥ج٢. اللغات الأخرى من ملفات الترجمة / 5c2. The other languages from the locale files ──
print("\n── اللغات الأخرى ──")
LOCALE_SAMPLES = {
    "ar": ["فرص", "السلام عليكم", "كيف أعرف مكان التقاط صورة؟"],
    "en": ["Hunchly", "How do I track a flight?", "Hello"],
    "pt-BR": ["Olá", "Como descubro onde uma foto foi tirada?", "Qual é a capital da França?"],
    "es": ["Hola", "¿Cómo averiguo dónde se tomó una foto?", "¿Qué es la herramienta Hunchly?"],
    "fr": ["Bonjour", "Comment savoir où une photo a été prise ?"],
    "sw": ["Habari", "Nawezaje kujua picha ilipigwa wapi?"],
    "hi": ["नमस्ते", "फ़ोटो कहाँ खींची गई, कैसे पता करूँ?"],
    "ur": ["تصویر کہاں لی گئی، میں کیسے جانوں؟"],
    "fa": ["چطور بفهمم عکسی کجا گرفته شده؟", "سلام خوبی"],
    "tr": ["Merhaba", "Bir fotoğrafın nerede çekildiğini nasıl bulurum?"],
    "id": ["Halo", "Bagaimana cara mengetahui di mana sebuah foto diambil?"],
}
en_keys = set(i18n.LOCALES["en"])
check("ملف ترجمة لكل لغة مدعومة، بمفاتيح en.json نفسها",
      set(i18n.LOCALES) == set(i18n.SUPPORTED_LANGUAGES) == set(LOCALE_SAMPLES)
      and all(set(loc) == en_keys for loc in i18n.LOCALES.values())
      and all((config.LOCALES_DIR / f"{c}.json").is_file() for c in i18n.SUPPORTED_LANGUAGES),
      {c: sorted(set(loc) ^ en_keys) for c, loc in i18n.LOCALES.items() if set(loc) != en_keys})
check("كل ملف يُبقي «فرص» والأوامر حرفياً ومتغيرات النصوص",
      all("فرص" in loc["out_of_scope"] and "فرص" in loc["welcome"]
          and "/subscribe" in loc["welcome_subscribe"] and "/unsubscribe" in loc["subscribed"]
          and "{limit}" not in loc["daily"] and "{wait}" in loc["daily"] and "{bot_name}" in loc["paused"]
          for loc in i18n.LOCALES.values()))
misses = [(lang, s, i18n.detect(s)) for lang, ss in LOCALE_SAMPLES.items() for s in ss
          if i18n.detect(s) != lang]
check("كشف اللغة على جمل من كل لغة، و«فرص» عربية و«Hunchly» إنجليزية", not misses, misses)
check("ما لا يُعرف إنجليزي، وبلا حروف عربي",
      i18n.detect("Привет, как дела?") == "en" and i18n.detect("123 ؟!") == "ar")
check("لغة الواجهة تُطابق الرمز المدعوم أو جزءه الأول، وإلا الإنجليزية",
      (i18n.from_hint("pt-br"), i18n.from_hint("en-GB"), i18n.from_hint("es_MX"),
       i18n.from_hint("de"), i18n.from_hint(None)) == ("pt-BR", "en", "es", "en", None))
check("اسم اللغة للنموذج، ولغة المصادر عربية للحرف العربي وإنجليزية لغيره",
      i18n.language_name("pt-BR") == "Portuguese (Brazil)" and i18n.language_name("ar") == "العربية"
      and i18n.language_name("en") == "English" and i18n.source_language("ur") == "ar"
      and i18n.source_language("fa") == "ar" and i18n.source_language("es") == "en")
g_pt = brain.messages(brain.handle("Olá", "whatsapp", "u-pt"))
g_es = brain.messages(brain.handle("Hola", "whatsapp", "u-es"))
check("«Olá» تُجاب بردّ التحية والترحيب بالبرتغالية البرازيلية",
      g_pt == ["Olá 👋", i18n.welcome("pt-BR", brain.daily_limit(), opener="")]
      and "O que posso fazer" in g_pt[1] and "Pax Memoria" in g_pt[1] and "/subscribe" in g_pt[1]
      and "What I can do" not in g_pt[1], g_pt[:1])
check("«Hola» تُجاب بردّ التحية والترحيب بالإسبانية",
      g_es == ["Hola 👋", i18n.welcome("es", brain.daily_limit(), opener="")]
      and "Lo que puedo hacer" in g_es[1], g_es[:1])
check("ردّ التحية بمثلها في اللغات الأخرى: Bom dia، Buenos días، Günaydın",
      brain.messages(brain.handle("Bom dia!", "whatsapp", "u-pt"))[0] == "Bom dia 👋"
      and brain.messages(brain.handle("Buenos días", "whatsapp", "u-es"))[0] == "Buenos días 👋"
      and brain.messages(brain.handle("Günaydın", "whatsapp", "u-tr"))[0] == "Günaydın 👋")
r_pt = brain.handle("Qual é a capital da França?", "telegram", "u-pt")
check("سؤال برتغالي خارج النطاق يُرفض من البوابة بالرفض البرتغالي، بلا نموذج",
      r_pt == i18n.msg("out_of_scope", "pt-BR") and r_pt.startswith("Desculpe")
      and "Bayan" in r_pt and "فرص" in r_pt and r_pt != config.OUT_OF_SCOPE_MESSAGE_EN, r_pt[:80])
check("الرسالة بلا نص بلغة الواجهة البرتغالية",
      brain.handle("", "telegram", "u-pt", "pt-br") == i18n.msg("text_only", "pt-BR")
      and brain.handle("", "telegram", "u-pt", "pt-br").startswith("Leio apenas texto"))
check("خلاصة الخصوصية بالفرنسية برابطها ومدة الحفظ",
      brain.handle("/privacy", "telegram", "u-fr", "fr").startswith("Politique de confidentialité de Bayan")
      and f"{config.MESSAGE_RETENTION_DAYS} jours" in brain.handle("/privacy", "telegram", "u-fr", "fr")
      and "/privacy" in brain.handle("/privacy", "telegram", "u-fr", "fr"))
store.set_setting("daily_limit", "1")
brain.handle("Quelles enquêtes avez-vous sur le Yémen ?", "telegram", "u-fr-limit")
r_fr = brain.handle("Et sur la Syrie ?", "telegram", "u-fr-limit")
check("رسالة الحدّ اليومي بالفرنسية، بالمدة ودون العدد",
      r_fr.startswith("Vous avez atteint la limite quotidienne de questions") and " 1 " not in r_fr and "heure" in r_fr
      and config.SITE_URL in r_fr, r_fr[:80])
store.set_setting("daily_limit", "10")
check("المدة بالساعات بلغتها: المثنى العربي، وعدد في غيرها",
      i18n.hours(7200, "ar") == "ساعتين" and i18n.hours(7200, "tr") == "2 saat"
      and i18n.hours(40000, "ar") == "12 ساعة" and i18n.hours(40000, "es") == "12 horas"
      and i18n.hours(100, "pt-BR") == "menos de uma hora")
check("الإيقاف المؤقت والخطأ بالسواحلية من ملفها، وباسم بيان اللاتيني",
      i18n.msg("paused", "sw").startswith("Bayan amesimamishwa") and config.SITE_URL in i18n.msg("paused", "sw")
      and i18n.msg("error", "sw") == i18n.LOCALES["sw"]["error"])
check("لغة غير مدعومة في msg تُعامل إنجليزية",
      i18n.msg("rate", "xx") == i18n.msg("rate", "en") and i18n.welcome("xx", 5) == i18n.welcome(None, 5))
# اللوحة بكل اللغات المدعومة / The dashboard in every supported language
dash_en = set(i18n.LOCALES["en"]["dashboard"])
check("قسم «dashboard» في كل ملف ترجمة بمفاتيح الإنجليزية نفسها",
      all(set(loc["dashboard"]) == dash_en for loc in i18n.LOCALES.values()) and len(dash_en) > 300,
      {c: sorted(set(loc.get("dashboard", {})) ^ dash_en)[:5] for c, loc in i18n.LOCALES.items()
       if set(loc.get("dashboard", {})) != dash_en})
check("متغيرات نصوص اللوحة متطابقة في كل لغة",
      all(set(re.findall(r"\{\w+\}", loc["dashboard"][k])) == set(re.findall(r"\{\w+\}", i18n.LOCALES["en"]["dashboard"][k]))
          for loc in i18n.LOCALES.values() for k in dash_en))
r_pt = client.get("/admin?lang=pt-BR")
pt_dash = i18n.LOCALES["pt-BR"]["dashboard"]
check("اللوحة تُعرض بالبرتغالية البرازيلية من اليسار",
      r_pt.status_code == 200 and '<html lang="pt-BR" dir="ltr"' in r_pt.text
      and pt_dash["nav_home"] in r_pt.text and pt_dash["logout"] in r_pt.text
      and "Dashboard" not in r_pt.text.split("<nav>")[1].split("</nav>")[0]
      and f"{server.dashboard.LANG_COOKIE}=pt-BR" in r_pt.headers.get("set-cookie", ""),
      (r_pt.status_code, r_pt.headers.get("set-cookie")))
r_ur = client.get("/admin?lang=ur")
check("اللوحة تُعرض بالأردية من اليمين",
      '<html lang="ur" dir="rtl"' in r_ur.text and i18n.LOCALES["ur"]["dashboard"]["nav_home"] in r_ur.text
      and 'class="brand">بيان' in r_ur.text)
check("قائمة اللغات تسرد كل لغة باسمها، والمختارة معلَّمة",
      all(f'<option value="{c}" lang="{c}"' in r_ur.text and i18n.LOCALES[c]["language"]["native"] in r_ur.text
          for c in i18n.SUPPORTED_LANGUAGES)
      and '<option value="ur" lang="ur" selected>' in r_ur.text and '<select name="lang"' in r_ur.text
      and '<form method="get" action="/admin" class="langform">' in r_ur.text)
check("الكوكي يثبّت اللغة، ولغة غير مدعومة في الرابط تُهمل، وبلا كوكي الإنجليزية",
      '<html lang="ur"' in client.get("/admin").text
      and '<html lang="ur"' in client.get("/admin?lang=xx").text
      and '<html lang="en" dir="ltr"' in client.get("/admin", cookies={server.dashboard.LANG_COOKIE: "xx"}).text)
r_role = client.get("/admin/role?lang=es")
check("صفحة «دور بيان» بالإسبانية: الواجهة مترجمة والحقول عربية وإنجليزية",
      r_role.status_code == 200 and i18n.LOCALES["es"]["dashboard"]["nav_role"] in r_role.text
      and 'name="refusal_ar"' in r_role.text and 'name="refusal_en"' in r_role.text
      and "Refusal message" in r_role.text and i18n.LOCALES["es"]["dashboard"]["lang_go"] in r_role.text)
check("صفحة الخصوصية العامة تبقى بالعربية والإنجليزية",
      client.get("/privacy").status_code == 200 and 'section lang="en"' in client.get("/privacy").text)
client.get("/admin?lang=ar")  # يعيد كوكي العربية لما بعده / restores the Arabic cookie

# ── ٥د. استدعاء النموذج دون شبكة / The model call, offline ─────────
# يُعترض الطلب قبل أن يغادر الجهاز: شكله، ثم معالجة كل حالة توقّف.
# The request is intercepted before it leaves the machine: its shape, then
# how each stop reason is handled.
print("\n── استدعاء النموذج ──")
import anthropic  # noqa: E402
import httpx2  # noqa: E402

sent = []
reply = {}


def fake_api(request):
    sent.append(request)
    body = {"id": "msg_test", "type": "message", "role": "assistant",
            "model": config.ANSWER_MODEL, "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5}}
    body.update(reply)
    return httpx2.Response(200, json=body)


brain._client = anthropic.Anthropic(
    api_key="test", max_retries=0,
    http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(fake_api)))
reply.update(content=[{"type": "text", "text": "Hunchly أداة توثيق. راجع github.com/AstraaDev"}],
             stop_reason="end_turn")
res = brain.answer("ما هي أداة Hunchly؟", "admin", "console")
req = json.loads(sent[-1].content)
check("الطلب بلا temperature ولا top_p ولا top_k",
      not {"temperature", "top_p", "top_k"} & set(req), sorted(req))
check("عمق التفكير في output_config", req.get("output_config") == {"effort": config.ANSWER_EFFORT})
check("max_tokens يتسع للتفكير", req.get("max_tokens") == config.MAX_OUTPUT_TOKENS >= 4000)
check("تعليمات النظام مخزّنة مؤقتاً",
      req["system"][0].get("cache_control") == {"type": "ephemeral"})
check("البديل التلقائي مفعّل برأسه",
      req.get("fallbacks") == "default"
      and "server-side-fallback-2026-07-01" in sent[-1].headers.get("anthropic-beta", ""))
check("إجابة عادية تمرّ، والطبقة ٤ تحذف الرابط الممنوع",
      res["outcome"] == "answered" and "AstraaDev" not in res["text"], res["text"])

check("المصادر مرقّمة في السياق المرسل", 'رقم="1"' in req["messages"][-1]["content"])
reply.update(content=[{"type": "text", "text": "Hunchly es una herramienta de documentación.\n[SOURCES: 1]"}],
             stop_reason="end_turn")
res_es = brain.answer("¿Qué es la herramienta Hunchly?", "admin", "console")
req_es = json.loads(sent[-1].content)["messages"][-1]["content"]
check("سؤال إسباني: وسم <لغة_الإجابة> يحمل اسم اللغة، والمصادر بالإنجليزية",
      "<لغة_الإجابة>Spanish</لغة_الإجابة>" in req_es and res_es["lang"] == "es"
      and res_es["outcome"] == "answered" and "Name: Hunchly" in req_es
      and "Verification grade:" in req_es and "درجة التحقق:" not in req_es,
      (res_es["lang"], res_es["outcome"], req_es[:300]))
check("تعليمات النظام تأمر بالإجابة بأي لغة يسمّيها الوسم وبالترجمة الأمينة",
      "أيّاً كانت" in brain.SYSTEM_PROMPT and "البرتغالية" in brain.SYSTEM_PROMPT
      and "بأمانة" in brain.SYSTEM_PROMPT and "كل اللغات" in brain.SYSTEM_PROMPT)
check("بلا سطر مصادر: صفحة الدليل لسؤال عن أداة",
      res["sources"] == [f"{config.SITE_URL}/osint-tools"], res["sources"])

reply.update(content=[{"type": "text", "text":
             "كشفت صور الأقمار الصناعية حجم السيول في الحديدة.\n[SOURCES: 1, 99]"}],
             stop_reason="end_turn")
config.VOYAGE_API_KEY = ""
res = brain.answer("ما حجم السيول في محافظة الحديدة اليمنية؟", "admin", "console")
check("المصادر هي ما ذكره النموذج فقط، والرقم غير الموجود يُهمل",
      res["sources"] == ["https://paxmemoria.org/investigations/x"], res["sources"])
check("سطر [SOURCES] لا يصل إلى السائل", "SOURCES" not in res["text"], res["text"])

# ── النظرة العامة على الدليل / The guide overview ──
from app import overview  # noqa: E402
req = json.loads(sent[-1].content)
view = req["system"][1]["text"] if len(req["system"]) > 1 else ""
check("النظرة العامة كتلة ثانية مخزّنة مؤقتاً في تعليمات النظام",
      req["system"][1].get("cache_control") == {"type": "ephemeral"}
      and 'موضوع="بيان"' in view and 'موضوع="الدليل"' in view, view[:300])
check("النظرة العامة تعدّ الأدوات المتاحة والمُزالة وتسرد التصنيفات بأعدادها",
      "في الدليل 3 أدوات متاحة" in view and "أُزيلت منه 2 أداة" in view
      and "- محركات البحث (Search): 2" in view, view)
check("قائمة التحقيقات فيها رابط كل تحقيق", "https://paxmemoria.org/investigations/x" in view, view)
check("وملخص كل تحقيق كما نُشر", "ملخصه: صور الأقمار الصناعية تكشف حجم الكارثة." in view, view)
check("وفقرة «من نحن» من صفحة الموقع بلا رأس مقطعها",
      'موضوع="باكس ميموريا"' in view and "منظمة دولية غير ربحية مسجلة في السويد." in view
      and "القسم: من نحن" not in view, view[:400])
check("تاريخ النشر يُقرأ بالعربية والإنجليزية للترتيب",
      overview._when("نُشر في 15 تشرين الأول/أكتوبر 2025").isoformat() == "2025-10-15"
      and overview._when("Published August 9, 2026").isoformat() == "2026-08-09"
      and overview._when("بلا تاريخ").year == 1)
reply.update(content=[{"type": "text", "text": "في الدليل 3 أدوات.\n[SOURCES: 0]"}],
             stop_reason="end_turn")
res = brain.answer("ما حجم السيول في محافظة الحديدة اليمنية؟", "admin", "console")
check("الاستناد إلى النظرة العامة يعطي صفحة الدليل مصدراً",
      res["sources"] == [f"{config.SITE_URL}/osint-tools"], res["sources"])
reply.update(content=[{"type": "text", "text": "أحدث تحقيقاتنا عن السيول.\n[SOURCES: 100]"}],
             stop_reason="end_turn")
res = brain.answer("ما حجم السيول في محافظة الحديدة اليمنية؟", "admin", "console")
check("الاستناد إلى قائمة التحقيقات يعطي صفحة التحقيقات مصدراً",
      res["sources"] == [f"{config.SITE_URL}/investigations"], res["sources"])
reply.update(content=[{"type": "text", "text": "منظمة غير ربحية.\n[SOURCES: 200]"}],
             stop_reason="end_turn")
res = brain.answer("ما حجم السيول في محافظة الحديدة اليمنية؟", "admin", "console")
check("الاستناد إلى «من نحن» يعطي صفحة «من نحن» مصدراً",
      res["sources"] == [f"{config.SITE_URL}/about"], res["sources"])
reply.update(content=[{"type": "text", "text": "أنا بيان، أجيب عن أربعة أشياء.\n[SOURCES: 300]"}],
             stop_reason="end_turn")
res = brain.answer("ما حجم السيول في محافظة الحديدة اليمنية؟", "admin", "console")
check("الاستناد إلى نظرة بيان عن نفسه لا يعطي رابطاً، ويبقى الجواب بلا سطر مصدر",
      res["sources"] == [] and "🔗" not in res["text"]
      and 'رقم="300" موضوع="بيان"' in brain.guide_overview(), (res["sources"], res["text"]))

# ── التصحيحات المعتمدة في الاسترجاع / Approved corrections in retrieval ──
# المتجهات المزيّفة كيس كلمات: صياغة تشارك معظم الكلمات قريبة، وغيرها بعيدة
# The fake vectors are a bag of words: a wording that shares most words is
# close, and others are far
config.VOYAGE_API_KEY = "test"
fq = "ما قوائم الأدوات في الدليل؟"
vec, model = retrieve.embed_correction(fq)
cid = store.save_correction(fq, "في الدليل تصنيفات كثيرة، وكل أداة تُعرف بالبحث عنها.",
                            "", True, vec, model)


def matches(q):
    return [c["id"] for c in retrieve.match_corrections(q, retrieve._query_vector(q))]


check("السؤال نفسه يطابق تصحيحه", matches(fq) == [cid])
check("صياغة قريبة تطابق بالمتجهات", matches("ما قوائم الأدوات المتوفرة في الدليل؟") == [cid])
check("سؤال مختلف لا يطابق", matches("ما أدوات تتبع الطيران؟") == [])
reply.update(content=[{"type": "text", "text": "في الدليل تصنيفات كثيرة.\n[SOURCES: 1]"}],
             stop_reason="end_turn")
res = brain.answer("ما قوائم الأدوات المتوفرة في الدليل؟", "admin", "console")
ctx = json.loads(sent[-1].content)["messages"][-1]["content"]
check("التصحيح المطابق أول المصادر، ويجيز السؤال من البوابة",
      res["outcome"] == "answered" and '<تصحيح_معتمد رقم="1">' in ctx
      and "الإجابة المعتمدة" in ctx, res["outcome"])
check("مصدر تصحيح بلا رابط هو صفحة الدليل",
      res["sources"] == [f"{config.SITE_URL}/osint-tools"], res["sources"])
store.save_correction(fq, "x", "", False, vec, model, cid)
check("التصحيح المعطّل لا يُستعمل", matches(fq) == [])
store.save_correction(fq, "x", "", True, vec, "model-from-before", cid)
check("متجه من نموذج سابق لا يُقارن، والسؤال نفسه يبقى مطابقاً",
      matches(fq) == [cid] and matches("ما قوائم الأدوات المتوفرة في الدليل؟") == [])
check("إعادة توليد متجهات التصحيحات بعد تغيّر النموذج",
      retrieve.refresh_correction_vectors() == 1
      and matches("ما قوائم الأدوات المتوفرة في الدليل؟") == [cid])
store.delete_correction(cid)
# ── الفرص: الجزء الثالث / Opportunities: the third part ──
from app import opportunities  # noqa: E402
LIST = """قائمة الفرص المتاحة لهذا الأسبوع:

1. زمالة الصحافة الاستقصائية | اليمن (آخر موعد 15 نوفمبر)
   https://yhms-ye.org/investigative-fellowship/

2. شفافية مصايد الأسماك
   https://informedstories.org/en/earth/opportunities/fisheries-transparency-virtual-workshop/

3. Earth Care Awards https://earthcareawards.com/communicators-for-climate-action/

بالتوفيق."""
parsed = opportunities.parse_list(LIST)
check("القائمة تُقسَّم إلى ثلاث فرص برابطها",
      len(parsed) == 3 and parsed[0]["url"].startswith("https://yhms-ye.org")
      and parsed[2]["url"].startswith("https://earthcareawards.com"), parsed)
store.save_opportunity_week(2026, 44, parsed[:2])
store.save_opportunity_week(2026, 45, [parsed[2]])
check("الأسابيع محفوظة وأحدثها أولاً",
      [(w["week"], w["n"]) for w in store.opportunity_weeks()] == [(45, 1), (44, 2)])
check("سؤال بلا نيّة فرصة لا يُرجع فرصاً", opportunities.match("ما أدوات تتبع الطيران؟") == [])
m = opportunities.match("هل توجد زمالة للصحفيين في اليمن؟")
check("«زمالة ... اليمن» تجد زمالة اليمن أولاً",
      m and "اليمن" in m[0]["title"] and m[0]["week"] == 44, m)
check("سؤال عام عن الفرص يعيد أحدث أسبوع أولاً",
      opportunities.match("ما الفرص المتاحة؟")[0]["week"] == 45)
res = retrieve.search("هل توجد زمالة للصحفيين في اليمن؟")
ctx, ctx_urls = brain.build_context(res, "ar")
check("الفرصة تدخل سياق النموذج برابطها وتجيز السؤال من البوابة",
      res["has_any"] and res["confidence"] >= 0.6 and "<فرصة" in ctx
      and "https://yhms-ye.org" in ctx, ctx[:200])
check("موضوع سؤال الزمالة «الفرص»", brain.topic_of(res, "answered") == ("opportunities", ""))
store.save_opportunity_week(2026, 46, [parsed[1]])
store.save_opportunity_week(2026, 47, [parsed[1]])
store.save_opportunity_week(2026, 48, [parsed[1]])
store.save_opportunity_week(2026, 49, [parsed[1]])
check("البحث في آخر 4 أسابيع فقط",
      all(o["week"] >= 46 for o in store.recent_opportunities(config.OPPORTUNITY_WEEKS)))
for w in (44, 45, 46, 47, 48, 49):
    store.delete_opportunity_week(2026, w)
# قوائم الفرص الأسبوعية: بلا رقم أحدث أسبوع، وبرقم ذلك الأسبوع
w1 = store.save_correction("فرص الأسبوع 9", "قائمة 9", "", True, None, None)
w2 = store.save_correction("فرص الأسبوع 45", "قائمة 45", "", True, None, None)
w3 = store.save_correction("فرص الأسبوع 10", "قائمة 10", "", True, None, None)
old = store.save_correction("فرص", "قديمة", "", True, None, None)
first = lambda q: (matches(q) or [None])[0]
check("«فرص» تعيد أحدث أسبوع لا الأحدث تعديلاً", first("فرص") == w2)
check("«فرص هذا الأسبوع» تعيد أحدث أسبوع", first("فرص هذا الأسبوع") == w2)
check("الأسبوع المسمّى برقمه يعيد قائمته", first("فرص الأسبوع 10") == w3)
check("الرقم بالهندية يُطبَّع", first("فرص الأسبوع ٩") == w1)
check("«فرص٤٥» دون مسافة تعيد قائمة الأسبوع 45", first("فرص٤٥") == w2)
check("«فرص 10» و«الفرص 10» و«فرص الأسبوع10» تعيد الأسبوع 10",
      first("فرص 10") == w3 and first("الفرص 10") == w3 and first("فرص الأسبوع10") == w3)
check("رقم أسبوع بلا قائمة يعيد آخر قائمة منشورة", first("فرص33") == w2)
check("«فرص الأسبوع» بلا رقم تعيد آخر قائمة", first("فرص الأسبوع") == w2)
check("سؤال بلا علاقة بالفرص لا يُغيَّر", first("ما أدوات تتبع الطيران؟") is None)
for i in (w1, w2, w3, old):
    store.delete_correction(i)
config.VOYAGE_API_KEY = ""

ctx, urls = brain.build_context(
    {"tools": [], "category": None, "category_tools": [],
     "passages": [{"type": "tool", "url": "u", "meta": {},
                   "text": "الأداة: X\nدرجة التحقق في تدقيق OTVS: direct"}]}, "ar")
check("رمز درجة التحقق الخام يُستبدل بصياغته: متحقق من وجودها ووصفها، لا حكم أمان",
      "direct" not in ctx and "متحقق من وجودها ووصفها" in ctx and "لم تُجرَّب الأداة" in ctx
      and "آمنة" not in ctx, ctx)
ctx_en, _ = brain.build_context(
    {"tools": [], "category": None, "category_tools": [],
     "passages": [{"type": "tool", "url": "u", "meta": {},
                   "text": "درجة التحقق في تدقيق OTVS: direct"}]}, "en")
check("وبالإنجليزية: confirmed to exist، بلا safe ولا verified",
      "confirmed to exist and to match its description" in ctx_en
      and "not tried" in ctx_en and "safe" not in ctx_en.lower()
      and "verified" not in ctx_en.lower(), ctx_en)
check("القاعدة ١ تمنع «آمنة للاستخدام» وتشرح معنى الدرجة",
      "آمنة للاستخدام" in brain.SYSTEM_PROMPT and "safe to use" in brain.SYSTEM_PROMPT
      and "لم تُجرَّب" in brain.SYSTEM_PROMPT)
ctx, _ = brain.build_context(
    {"tools": [], "category": None, "category_tools": [],
     "passages": [{"type": "tool", "url": "u", "meta": {},
                   "text": "درجة التحقق في تدقيق OTVS: trained"}]}, "en")
check("وبالإنجليزية لسؤال إنجليزي", "not reviewed live" in ctx, ctx)
check("قاعدة البديل في التعليمات", "لا تسمِّ أي أداة أخرى بديلاً" in brain.SYSTEM_PROMPT)

reply.update(content=[], stop_reason="refusal",
             stop_details={"type": "refusal", "category": "cyber", "explanation": "x"})
res = brain.answer("How do I hack someone else's account with Hunchly?", "admin", "console")
check("رفض مصنِّف الأمان يصير «رفضه النموذج» بلغة السائل",
      res["outcome"] == "refused_model" and res["text"] == config.OUT_OF_SCOPE_MESSAGE_EN, res)
reply.pop("stop_details")

reply.update(content=[{"type": "text", "text": "Hunchly أداة "}], stop_reason="max_tokens")
res = brain.answer("ما هي أداة Hunchly؟", "admin", "console")
check("إجابة قُطعت عند الحدّ لا تُرسل ناقصة", res["outcome"] == "error", res)

config.ANSWER_FALLBACK = "off"
reply.update(content=[{"type": "text", "text": "Hunchly أداة توثيق صفحات."}], stop_reason="end_turn")
brain.answer("ما هي أداة Hunchly؟", "admin", "console")
req = json.loads(sent[-1].content)
check("ANSWER_FALLBACK=off: لا fallbacks ولا رأس beta",
      "fallbacks" not in req and "server-side-fallback" not in sent[-1].headers.get("anthropic-beta", ""))
config.ANSWER_FALLBACK = "default"
brain._client = None

# ── البديل التلقائي عبر Gemini عند توقف Claude / Automatic Gemini failover ──
gemini_sent = []
gemini_reply = {}


def fake_gemini(request):
    gemini_sent.append(request)
    return httpx.Response(200, json=gemini_reply)


def broken_claude(request):
    return httpx2.Response(503, json={"type": "error", "error": {"message": "overloaded"}})


brain._client = anthropic.Anthropic(
    api_key="test", max_retries=0,
    http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(broken_claude)))
config.GEMINI_API_KEY = "gem-secret-key"
brain.httpx.Client = lambda **kw: real_client(transport=httpx.MockTransport(fake_gemini), **kw)
gemini_reply.update(candidates=[{
    "finishReason": "STOP",
    "content": {"role": "model", "parts": [
        {"text": "تفكير داخلي", "thought": True},
        {"text": "Hunchly أداة توثيق من Gemini. راجع github.com/AstraaDev\n[SOURCES: 1]"},
    ]},
}])
res = brain.answer("ما هي أداة Hunchly؟", "admin", "console")
greq = json.loads(gemini_sent[-1].content)
check("عند توقف Claude (503) يستمر بيان عبر Gemini تلقائياً",
      res["outcome"] == "answered" and "من Gemini" in res["text"], res)
check("أجزاء التفكير الداخلي (thought) والروابط الممنوعة وسطر [SOURCES] لا تصل للسائل",
      "تفكير داخلي" not in res["text"] and "AstraaDev" not in res["text"]
      and "SOURCES" not in res["text"], res["text"])
check("مفتاح Gemini يُرسل في الترويسة x-goog-api-key لا في عنوان الطلب",
      gemini_sent[-1].headers.get("x-goog-api-key") == "gem-secret-key"
      and "gem-secret-key" not in str(gemini_sent[-1].url))
check("تعليمات النظام والنظرة العامة تُرسل إلى Gemini في system_instruction",
      len(greq["system_instruction"]["parts"]) == 2)

# ── المزوّد المحلي بواجهة OpenAI / The local OpenAI-compatible provider ──
local_sent = []
local_reply: dict = {}


def fake_local(request):
    if request.url.path.endswith("/chat/completions"):
        local_sent.append(request)
        if local_reply.get("down"):
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, json=local_reply)
    return fake_gemini(request)


brain.httpx.Client = lambda **kw: real_client(transport=httpx.MockTransport(fake_local), **kw)
old_model, old_key = config.ANSWER_MODEL, config.GEMINI_API_KEY
config.ANSWER_MODEL, config.LOCAL_LLM_MODEL, config.LOCAL_LLM_KEY = "local", "qwen-test", "k-local"
local_reply.update(choices=[{"finish_reason": "stop", "message": {
    "role": "assistant",
    "content": "<think>أفكر هنا</think>Hunchly أداة توثيق محلية.\n[SOURCES: 1]"}}])
res = brain.answer("ما هي أداة Hunchly؟", "admin", "console")
lreq = json.loads(local_sent[-1].content)
check("ANSWER_MODEL=local يسأل المزوّد المحلي ويجيب",
      res["outcome"] == "answered" and "أداة توثيق محلية" in res["text"], res)
check("أجزاء <think> وسطر [SOURCES] لا تصل للسائل",
      "أفكر" not in res["text"] and "SOURCES" not in res["text"], res["text"])
check("الطلب بصيغة OpenAI: system أولاً ثم المحادثة، والنموذج والمفتاح في مكانهما",
      lreq["model"] == "qwen-test" and lreq["messages"][0]["role"] == "system"
      and "المصادر" in lreq["messages"][-1]["content"] and lreq["stream"] is False
      and local_sent[-1].headers.get("authorization") == "Bearer k-local"
      and str(local_sent[-1].url).endswith("/v1/chat/completions"), lreq["messages"][0]["role"])
local_reply.clear()
local_reply.update(choices=[{"finish_reason": "stop", "message": {"content": "."}}])
n0 = len(local_sent)
check("تسخين النموذج المحلي يرسل تعليمات النظام برمز واحد",
      brain.warm_local() is True and len(local_sent) == n0 + 1
      and json.loads(local_sent[-1].content)["max_tokens"] == 1
      and json.loads(local_sent[-1].content)["messages"][0]["content"].startswith(brain.SYSTEM_PROMPT[:40]))
check("خادم بيان يسخّن المحلي فقط حين يُستعمل", hasattr(server, "_local_warm_loop") and server.LOCAL_WARM_MINUTES == 30)
local_reply.clear()
local_reply.update(choices=[{"finish_reason": "length", "message": {"content": "نص مقطوع"}}])
res = brain.answer("ما هي أداة Hunchly؟", "admin", "console")
check("قطع المزوّد المحلي عند الحدّ لا يُرسل ناقصاً", res["outcome"] == "error", res["outcome"])
local_reply.clear()
local_reply.update(choices=[{"finish_reason": "content_filter", "message": {"content": ""}}])
res = brain.answer("ما هي أداة Hunchly؟", "admin", "console")
check("رفض المزوّد المحلي يصير «رفضه النموذج»", res["outcome"] == "refused_model", res["outcome"])
local_reply.clear()
local_reply["down"] = True
gemini_reply.clear()
gemini_reply.update(candidates=[{"finishReason": "STOP", "content": {"role": "model", "parts": [
    {"text": "إجابة Gemini بديلة عن المحلي.\n[SOURCES: 1]"}]}}])
res = brain.answer("ما هي أداة Hunchly؟", "admin", "console")
check("توقف الخادم المحلي يحوّل إلى Gemini تلقائياً",
      res["outcome"] == "answered" and "بديلة عن المحلي" in res["text"], res)
config.GEMINI_API_KEY = ""
res = brain.answer("ما هي أداة Hunchly؟", "admin", "console")
check("بلا مفتاح Gemini يكون توقف المحلي خطأً صريحاً", res["outcome"] == "error", res["outcome"])
config.ANSWER_MODEL, config.GEMINI_API_KEY = old_model, old_key
config.LOCAL_LLM_MODEL = config.LOCAL_LLM_KEY = ""
local_reply.clear()

# ── المحلي لتعليقات فيسبوك وحدها / The local provider for Facebook comments only ──
# هنا Claude معطّل (503) ومفتاح Gemini مضبوط، فالمزوّد العام يجيب عبر Gemini
# Here Claude is broken (503) and Gemini has a key, so the general provider answers via Gemini
config.COMMENT_ANSWER_MODEL, config.LOCAL_LLM_MODEL = "local", "qwen-test"
local_reply.update(choices=[{"finish_reason": "stop", "message": {"content": "رد محلي على التعليق.\n[SOURCES: 1]"}}])
gemini_reply.clear()
gemini_reply.update(candidates=[{"finishReason": "STOP", "content": {"role": "model", "parts": [
    {"text": "رد Gemini للمحادثة.\n[SOURCES: 1]"}]}}])
n_local = len(local_sent)
reply = brain.handle_comment("بيان ما هي أداة Hunchly؟", "messenger", "fb-c1")
check("تعليق فيسبوك يُجاب من النموذج المحلي",
      reply and "رد محلي" in reply and len(local_sent) == n_local + 1, reply)
res = brain.answer("ما هي أداة Hunchly؟", "admin", "console")
check("المحادثات تبقى على المزوّد العام", "رد Gemini" in res["text"] and len(local_sent) == n_local + 1, res["text"])
local_reply.clear()
local_reply["down"] = True
reply = brain.handle_comment("بيان ما هي أداة Hunchly؟", "messenger", "fb-c2")
check("توقف المحلي يحوّل رد التعليق إلى المزوّد العام", reply and "رد Gemini" in reply, reply)
local_reply.clear()
local_reply.update(choices=[{"finish_reason": "stop", "message": {"content": "رد محلي على التعليق.\n[SOURCES: 1]"}}])
for q in ("«بيان ما هي أداة Hunchly؟»", "بيان، ما هي أداة Hunchly؟", "Bayan: what is Hunchly?"):
    reply = brain.handle_comment(q, "messenger", "fb-c3")
    check(f"الاسم يُلتقط مع علامة ملتصقة: {q[:12]}", reply and "رد محلي" in reply, reply)
check("تعليق لا يذكر بيان ولا يطابق تصحيحاً يُترك", brain.handle_comment("ما هي أداة Hunchly؟", "messenger", "fb-c4") is None)
# «فرصة» بالمفرد مثل «فرص»: تعليق يطلب القائمة بأي صيغة يُجاب بها
# «فرصة» (singular) like «فرص»: a comment asking for the list in any form gets it
from app import opportunities  # noqa: E402
from app.arabic import normalize_ar  # noqa: E402
wk = store.save_correction("فرص الأسبوع 46", "قائمة الأسبوع 46:\n1. زمالة تجريبية\nhttps://example.org/46",
                           "", True, None, None)
retrieve.warm()
singular = {q: brain.handle_comment(q, "messenger", f"fb-s{i}") for i, q in enumerate(("فرصة", "الفرصة", "فرصه"))}
check("تعليقات «فرصة» و«الفرصة» و«فرصه» تُجاب بقائمة الأسبوع",
      all(r and "قائمة الأسبوع 46" in r for r in singular.values()), {k: (v or "")[:30] for k, v in singular.items()})
check("«فرصة» تُعدّ نيّة فرصة في الاسترجاع أيضاً",
      retrieve._asked_weekly(normalize_ar("فرصة")) is not None and opportunities.wants_opportunity("فرصة"))
store.delete_correction(wk)
# أول فحص بعد الإقلاع: القديم يُعدّ مقروءاً، والحديث غير المسجّل يُجاب
# First poll after startup: old counts as seen, recent unrecorded gets answered
now = time.time()
batch = [("fb_comment:old1", "u-old", "old1", "فرص", now - 5 * 3600),
         ("fb_comment:new1", "u-new", "new1", "فرص", now - 10 * 60),
         ("fb_comment:new2", "u-new2", "new2", "بيان ما هي Hunchly؟", now - 2 * 60)]
first = server._new_comments(batch, first_poll=True, now=now)
check("عند الإقلاع يُردّ على ما وصل خلال آخر ساعة فقط",
      [c[1] for c in first] == ["new1", "new2"], first)
again = server._new_comments(batch + [("fb_comment:new3", "u3", "new3", "فرص", now)], first_poll=False, now=now)
check("الفحص التالي يردّ على الجديد وحده ولا يكرّر", [c[1] for c in again] == ["new3"], again)
check("التعليق القديم سُجّل مقروءاً دون ردّ", not store.first_time("fb_comment:old1"))
config.COMMENT_ANSWER_MODEL = config.LOCAL_LLM_MODEL = ""
local_reply.clear()
brain.httpx.Client = lambda **kw: real_client(transport=httpx.MockTransport(fake_gemini), **kw)

gemini_reply.clear()
gemini_reply.update(candidates=[{"finishReason": "SAFETY"}])
res = brain.answer("How do I hack someone else's account with Hunchly?", "admin", "console")
check("رفض الأمان في Gemini يصير «رفضه النموذج»",
      res["outcome"] == "refused_model" and res["text"] == config.OUT_OF_SCOPE_MESSAGE_EN, res)

gemini_reply.clear()
gemini_reply.update(candidates=[{"finishReason": "MAX_TOKENS",
                                 "content": {"parts": [{"text": "ناقص"}]}}])
res = brain.answer("ما هي أداة Hunchly؟", "admin", "console")
check("إجابة Gemini المقطوعة عند MAX_TOKENS لا تُرسل ناقصة", res["outcome"] == "error", res)

config.GEMINI_API_KEY = ""
brain.httpx.Client = real_client
brain._client = None

# ── ٥هـ. الخصوصية / Privacy ─────────────────────────────────────
print("\n── الخصوصية ──")
import logging  # noqa: E402

with store.db() as c:
    c.execute("INSERT INTO messages(channel,user_id,role,content,ts) VALUES(?,?,?,?,?)",
              ("telegram", "u-old", "user", "سؤال قديم", time.time() - 31 * 86400))
    c.execute("INSERT INTO messages(channel,user_id,role,content,ts) VALUES(?,?,?,?,?)",
              ("telegram", "u-old", "user", "سؤال حديث", time.time() - 29 * 86400))
removed = store.purge_old_messages(30)
with store.db() as c:
    left = [r["content"] for r in c.execute(
        "SELECT content FROM messages WHERE user_id='u-old'").fetchall()]
check("الحذف التلقائي يزيل ما مضى عليه 30 يوماً ويبقي الأحدث",
      removed >= 1 and left == ["سؤال حديث"], (removed, left))
# أعداد الاستخدام تبقى بعد حذف الرسائل بلا نص ولا معرّفات
with store.db() as c:
    for uid, days_ago in (("cnt-a", 40), ("cnt-a", 40), ("cnt-b", 40)):
        c.execute("INSERT INTO messages(channel,user_id,role,content,ts) VALUES(?,?,?,?,?)",
                  ("cnt-test", uid, "user", "نص يُحذف", time.time() - days_ago * 86400))
store.purge_old_messages(30)
tot = store.usage_totals().get("cnt-test", {})
check("الأعداد تبقى بعد الحذف: 3 أسئلة ومستخدمان في اليوم",
      tot.get("questions") == 3 and tot.get("users") == 2, tot)
with store.db() as c:
    left = c.execute("SELECT COUNT(*) FROM messages WHERE user_id LIKE 'cnt-%'").fetchone()[0]
    cols = [r[1] for r in c.execute("PRAGMA table_info(usage_daily)").fetchall()]
check("الرسائل حُذفت وجدول الأعداد بلا نص ولا معرّفات",
      left == 0 and cols == ["day", "channel", "questions", "users"], (left, cols))
store.purge_old_messages(30)
check("إعادة الحذف لا تغيّر الأعداد", store.usage_totals()["cnt-test"]["questions"] == 3)
# ── مواضيع الأسئلة / Question topics ──
inv = {"type": "investigation", "meta": {"slug": "floods-hodeidah-yemen"}, "url": "u", "text": ""}
tool = {"type": "tool", "meta": {"category_en": "Geolocation"}, "url": "u", "text": ""}
base = {"tools": [], "category_tools": [], "category": None, "corrections": [], "opportunities": [], "passages": []}
check("رفض → بلا جواب", brain.topic_of({**base, "passages": [inv]}, "refused_gate") == ("unanswered", ""))
check("أداة بالاسم → الأدوات وتصنيفها",
      brain.topic_of({**base, "tools": [{"category_en": "Notes & Documentation"}]}, "answered")
      == ("tools", "Notes & Documentation"))
check("مقاطع تحقيق → التحقيقات وslug", brain.topic_of({**base, "passages": [inv, inv, tool]}, "answered")
      == ("investigations", "floods-hodeidah-yemen"))
check("مقاطع أدوات → الأدوات وتصنيفها", brain.topic_of({**base, "passages": [tool, inv]}, "answered")
      == ("tools", "Geolocation"))
check("تصحيح «فرص الأسبوع 44» → الفرص",
      brain.topic_of({**base, "corrections": [{"norm_question": "فرص الاسبوع 44"}]}, "answered")
      == ("opportunities", ""))
check("تصحيح عادي بلا مقاطع → أخرى",
      brain.topic_of({**base, "corrections": [{"norm_question": "ما اداة hunchly"}]}, "answered") == ("other", ""))
with store.db() as c:
    c.execute("ALTER TABLE messages DROP COLUMN topic")
    c.execute("ALTER TABLE messages DROP COLUMN detail")
store.init()
with store.db() as c:
    cols = {r[1] for r in c.execute("PRAGMA table_info(messages)").fetchall()}
check("الترقية تضيف عمودي الموضوع والتفصيل لقاعدة قائمة", {"topic", "detail"} <= cols, cols)
for d in (40, 40, 2):
    store.remember("tp-test", "tp-u", "user", "س", outcome="answered", topic="investigations",
                   detail="floods-hodeidah-yemen")
    with store.db() as c:
        c.execute("UPDATE messages SET ts=? WHERE channel='tp-test' AND ts > ?",
                  (time.time() - d * 86400, time.time() - 1))
store.remember("tp-test", "tp-u", "user", "س", outcome="refused_gate", topic="unanswered", detail="")
wk = store.topic_stats(time.time() - 7 * 86400)
check("مواضيع الأسبوع: تحقيق واحد وسؤال بلا جواب",
      wk.get("investigations", {}).get("questions") == 1 and wk.get("unanswered", {}).get("questions") == 1
      and wk["investigations"]["details"] == {"floods-hodeidah-yemen": 1}, wk)
store.purge_old_messages(30)
tot = store.topic_totals()
check("أعداد المواضيع تبقى بعد الحذف: 3 تحقيقات",
      tot.get("investigations", {}).get("questions") == 3
      and tot["investigations"]["details"].get("floods-hodeidah-yemen") == 3, tot)
with store.db() as c:
    c.execute("DELETE FROM messages WHERE channel='tp-test'")
    c.execute("DELETE FROM topic_daily")
with store.db() as c:
    check("الحذف الآمن مفعّل في القاعدة", c.execute("PRAGMA secure_delete").fetchone()[0] == 1)

store.set_setting("daily_limit", "2")
brain.handle("سؤال أول عن أداة", "telegram", "u-reset")
brain.handle("سؤال ثانٍ عن أداة", "telegram", "u-reset")
brain.handle("/reset", "telegram", "u-reset")
brain.handle("/start", "telegram", "u-reset")
check("حذف المحادثة لا يلغي حدّ الأسئلة اليومي",
      "الحدّ اليومي للأسئلة" in brain.handle("سؤال ثالث", "telegram", "u-reset"))
store.set_setting("daily_limit", "10")

pv = brain.handle("الخصوصية", "telegram", "u-p")
check("«الخصوصية» تعيد الرابط ومدة الحفظ بالعربية",
      "/privacy" in pv and "30 يوماً" in pv and "privacy policy" not in pv, pv)
check("/privacy بواجهة إنجليزية بالإنجليزية",
      "Bayan's privacy policy" in brain.handle("/privacy", "telegram", "u-p", "en"))
check("الترحيب يذكر سياسة الخصوصية", "/privacy" in brain.handle("/start", "telegram", "u-p", "ar"))

# ── الاشتراك في قائمة الفرص / Opportunities subscription ──
import asyncio  # noqa: E402
from app import broadcast, privacy as privacy_mod  # noqa: E402
r1 = brain.handle("/subscribe", "telegram", "u-sub", "ar")
check("/subscribe يسجّل المشترك ويؤكد بالعربية",
      store.is_subscribed("telegram", "u-sub") and "اشتركت" in r1 and "/unsubscribe" in r1, r1)
r1b = brain.handle("اشتراك", "telegram", "u-sub")
check("تكرار الاشتراك لا يضيف ثانية", "من قبل" in r1b and store.subscriber_counts().get("telegram") == 1, r1b)
r2 = brain.handle("subscribe", "whatsapp", "u-sub2")
check("الاشتراك على قناة بلا بث يُسجَّل ويوضّح ذلك بالإنجليزية",
      store.is_subscribed("whatsapp", "u-sub2") and "not enabled yet" in r2, r2)
r2b = brain.handle("/subscribe", "messenger", "u-sub3")
check("/subscribe بلا لغة معروفة يرد باللغتين", "سُجّل اشتراكك" in r2b and "is recorded" in r2b, r2b)
r3 = brain.handle("إلغاء الاشتراك", "telegram", "u-sub")
check("إلغاء الاشتراك", "أُلغي" in r3 and not store.is_subscribed("telegram", "u-sub"), r3)
check("إلغاء بلا اشتراك", "لست مشتركاً" in brain.handle("إلغاء الاشتراك", "telegram", "u-sub"))
check("الترحيب يذكر /subscribe", "/subscribe" in brain.handle("/start", "telegram", "u-p", "ar"))
check("سياسة الخصوصية تذكر الاشتراك وإلغاءه",
      privacy_mod.page().body.decode().count("/unsubscribe") == 4)
store.subscribe("telegram", "u-b1")
store.subscribe("telegram", "u-b2")
store.save_opportunity_week(2026, 45, [{"title": "زمالة", "url": "https://x.example/f"}])
sent = []


async def fake_send(uid, text):
    sent.append((uid, text))


real_tg = broadcast.SENDERS["telegram"]
broadcast.SENDERS["telegram"] = fake_send
res = asyncio.run(broadcast.send_week(2026, 45))
broadcast.SENDERS["telegram"] = real_tg
check("البثّ يصل مشتركي تيليغرام ويترك القنوات بلا بث",
      res == {"sent": 2, "failed": 0, "skipped": 2} and "https://x.example/f" in sent[0][1]
      and "/unsubscribe" in sent[0][1], (res, sent[:1]))
check("نتيجة البثّ محفوظة للوحة", '"week": 45' in store.setting("last_broadcast", ""))
check("أسبوع بلا قائمة لا يُبثّ", asyncio.run(broadcast.send_week(2026, 1)) == {"sent": 0, "failed": 0, "skipped": 0})
store.block("telegram", "u-b1", "x")
check("الحظر يلغي الاشتراك", not store.is_subscribed("telegram", "u-b1"))
store.unblock("telegram", "u-b1")
r = client.get("/admin/opportunities")
check("صفحة الفرص تعرض المشتركين وزر الإرسال ونتيجة آخر بثّ",
      "المشتركون في قائمة الفرص" in r.text and "أرسل للمشتركين" in r.text and "آخر بثّ: الأسبوع 45" in r.text)
with store.db() as c:
    c.execute("DELETE FROM subscribers")
# بلا مشتركين فلا يُرسل الزر شيئاً فعلياً / With no subscribers the button sends nothing real
r = client.post("/admin/opportunities/send", data={"year": "2026", "week": "45"}, follow_redirects=False)
check("زر الإرسال يبدأ البثّ ويعود للصفحة", r.status_code == 303 and "opp_sent" in r.headers["location"])
store.delete_opportunity_week(2026, 45)

# ── الفريق والدخول بحساب Google / Team and Google sign-in ──
from urllib.parse import parse_qs, urlsplit  # noqa: E402
from app import dashboard as dash  # noqa: E402
config.GOOGLE_CLIENT_ID, config.GOOGLE_CLIENT_SECRET = "cid", "sec"
config.PUBLIC_URL = "http://bayan.test"
config.ALLOWED_EMAIL_DOMAIN = "paxmemoria.org"
config.ADMIN_EMAILS = {"boss@paxmemoria.org"}
GOOGLE_USER: dict = {}


def google_api(request):
    if request.url.path == "/token":
        return httpx.Response(200, json={"access_token": "at"})
    return httpx.Response(200, json=GOOGLE_USER)


real_dash_async = dash.httpx.AsyncClient
dash.httpx.AsyncClient = lambda **kw: real_dash_async(transport=httpx.MockTransport(google_api), **kw)


def google_login(c, user: dict, state_override: str | None = None):
    GOOGLE_USER.clear()
    GOOGLE_USER.update(user)
    r = c.get("/admin/auth/google", follow_redirects=False)
    state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]
    return c.get(f"/admin/auth/google/callback?code=abc&state={state_override or state}",
                 follow_redirects=False)


anon = TestClient(server.app)
check("صفحة الدخول تعرض زر Google ونطاق المنظمة",
      "/admin/auth/google" in anon.get("/admin/login").text and "@paxmemoria.org" in anon.get("/admin/login").text)
r = anon.get("/admin/auth/google", follow_redirects=False)
check("البداية تحوّل إلى Google مع hd والحالة", r.status_code == 303 and "accounts.google.com" in r.headers["location"]
      and "hd=paxmemoria.org" in r.headers["location"] and "bayan_oauth" in r.cookies)
r = google_login(anon, {"email": "x@gmail.com", "email_verified": True, "name": "X"})
check("حساب من خارج النطاق يُرفض", "error=domain" in r.headers["location"], r.headers.get("location"))
r = google_login(anon, {"email": "new@paxmemoria.org", "email_verified": True, "hd": "paxmemoria.org", "name": "New"})
check("حساب من النطاق غير مضاف يُرفض", "error=unknown" in r.headers["location"], r.headers.get("location"))
r = google_login(anon, {"email": "boss@paxmemoria.org", "email_verified": True, "hd": "paxmemoria.org", "name": "Boss"},
                 state_override="wrong")
check("حالة خاطئة تُرفض", "error=google" in r.headers["location"], r.headers.get("location"))
r = google_login(anon, {"email": "boss@paxmemoria.org", "email_verified": True, "hd": "paxmemoria.org", "name": "Boss"})
boss = store.member_by_email("boss@paxmemoria.org")
check("العودة من Google صفحة هبوط من موقعنا تنتقل إلى اللوحة (كوكي Strict لا يُرسل في تحويلة من موقع آخر)",
      r.status_code == 200 and 'http-equiv="refresh" content="0; url=/admin"' in r.text
      and 'href="/admin"' in r.text and "bayan_admin" in r.cookies
      and "default-src 'none'" in r.headers.get("content-security-policy", ""), r.status_code)
check("بريد ADMIN_EMAILS يدخل مديراً ويُنشأ عضواً", r.status_code == 200
      and boss and boss["role"] == "admin" and boss["name"] == "Boss", boss)
r = anon.get("/admin?lang=ar")
check("الشريط الجانبي يعرض اسم العضو ودوره", r.status_code == 200 and "Boss" in r.text and "مدير" in r.text)
r = anon.post("/admin/team/add", data={"email": "ed@paxmemoria.org", "role": "editor", "name": ""}, follow_redirects=False)
check("المدير يضيف محرراً", "member_saved" in r.headers["location"] and store.member_by_email("ed@paxmemoria.org")["role"] == "editor")
r = anon.post("/admin/team/add", data={"email": "ed@gmail.com", "role": "editor"}, follow_redirects=False)
check("بريد من خارج النطاق لا يُضاف", "error=member" in r.headers["location"] and store.member_by_email("ed@gmail.com") is None)
anon.post("/admin/team/add", data={"email": "vw@paxmemoria.org", "role": "viewer"})
ed = TestClient(server.app)
google_login(ed, {"email": "ed@paxmemoria.org", "email_verified": True, "hd": "paxmemoria.org", "name": "Ed"})
check("المحرر يدخل ويرى الأسئلة", ed.get("/admin/messages").status_code == 200)
check("المحرر لا يفتح الفريق ولا الإعدادات",
      ed.get("/admin/team").status_code == 403 and ed.get("/admin/settings").status_code == 403)
r = ed.post("/admin/corrections/save", follow_redirects=False,
            data={"question": "ما أداة Hunchly؟", "answer": "توثّق الصفحات.", "url": "", "active": "1"})
fx = [c for c in store.corrections() if c["question"] == "ما أداة Hunchly؟"]
check("تصحيح المحرر يُنسب إليه ويظهر في القائمة",
      r.status_code == 303 and fx and fx[0]["author"] == "Ed" and "بواسطة Ed" in anon.get("/admin/corrections").text, fx and fx[0].get("author"))
for c in fx:
    store.delete_correction(c["id"])
vw = TestClient(server.app)
google_login(vw, {"email": "vw@paxmemoria.org", "email_verified": True, "hd": "paxmemoria.org", "name": "Vee"})
check("المشاهد يقرأ ولا يغيّر", vw.get("/admin/messages").status_code == 200
      and vw.post("/admin/corrections/save", data={"question": "س", "answer": "ج", "active": "1"}).status_code == 403)
me_id = boss["id"]
r = anon.post("/admin/team/update", data={"id": str(me_id), "role": "viewer"}, follow_redirects=False)
check("المدير لا يخفض دوره", "error=self" in r.headers["location"] and store.member(me_id)["role"] == "admin")
ed_id = store.member_by_email("ed@paxmemoria.org")["id"]
anon.post("/admin/team/update", data={"id": str(ed_id), "active": "0"})
check("تعطيل العضو يُسقط جلسته", not store.member(ed_id)["active"]
      and ed.get("/admin", follow_redirects=False).status_code == 303)
r = google_login(ed, {"email": "ed@paxmemoria.org", "email_verified": True, "hd": "paxmemoria.org", "name": "Ed"})
check("العضو المعطّل لا يدخل", "error=inactive" in r.headers["location"])
acts = [a["action"] for a in store.audit_log(50)]
check("سجلّ الإجراءات يحوي الدخول والإضافة والتصحيح والتعطيل",
      {"login", "member_add", "correction_add", "member_deactivate", "login_denied_unknown"} <= set(acts), acts[:12])
r = anon.get("/admin/team")
check("صفحة الفريق تعرض الأعضاء والسجلّ", "ed@paxmemoria.org" in r.text and "سجلّ الإجراءات" in r.text and "member_add" in r.text)
anon.post("/admin/team/delete", data={"id": str(ed_id)})
check("حذف عضو", store.member(ed_id) is None)
check("المالك بكلمة المرور ما زال يدخل مديراً",
      client.get("/admin/team").status_code == 200 and "المالك" in client.get("/admin").text)
# ── محادثة الفريق في «جرّب بيان» / The team conversation on "Try Bayan" ──
print("\n── محادثة الفريق ──")
team_sent, team_reply = [], {}


def team_api(request):
    team_sent.append(request)
    return httpx2.Response(200, json={
        "id": "msg_team", "type": "message", "role": "assistant", "model": config.ANSWER_MODEL,
        "stop_sequence": None, "usage": {"input_tokens": 10, "output_tokens": 5}, **team_reply})


brain._client = anthropic.Anthropic(
    api_key="test", max_retries=0,
    http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(team_api)))
old_daily = store.setting("daily_limit", "")
store.set_setting("daily_limit", "2")
week_ago = time.time() - 7 * 86400
before_stats = (store.usage_totals(), store.topic_totals(), store.topic_stats(week_ago),
                store.channel_stats(week_ago), store.outcome_stats(week_ago))
# السؤال المرفوض بالبوابة الذي جرّبه المالك أعلاه محفوظ في خيطه بشارته
# The gate-refused question the owner tried above is kept in the thread with its badge
r = client.get("/admin/try")
check("سؤال التجربة السابق في خيط المالك مع شارة الرفض",
      "ما هي عاصمة فرنسا؟" in r.text and "رفضته البوابة" in r.text)
store.clear_history("team", "owner")
check("خيط المالك فارغ بعد مسحه", "لا محادثة بعد" in client.get("/admin/try").text)
team_reply.update(content=[{"type": "text", "text": "Hunchly أداة توثيق الصفحات.\n[SOURCES: 1]"}],
                  stop_reason="end_turn")
r = client.post("/admin/try", data={"q": "ما هي أداة Hunchly؟", "action": "ask"})
check("السؤال الأول يُجاب ويظهر مع إجابته في الخيط",
      r.status_code == 200 and "ما هي أداة Hunchly؟" in r.text and "Hunchly أداة توثيق الصفحات." in r.text
      and "تفاصيل الاسترجاع" in r.text, r.status_code)
team_reply.update(content=[{"type": "text", "text": "نعم، وهي مجانية للصحفيين."}], stop_reason="end_turn")
r = client.post("/admin/try", data={"q": "هل أداة Hunchly مجانية؟", "action": "ask"})
req = json.loads(team_sent[-1].content)
check("السؤال الثاني يصل إلى النموذج مع الدورة الأولى سجلاً",
      len(req["messages"]) == 3 and req["messages"][0] == {"role": "user", "content": "ما هي أداة Hunchly؟"}
      and req["messages"][1]["role"] == "assistant" and "Hunchly أداة توثيق الصفحات." in req["messages"][1]["content"],
      [m["role"] for m in req["messages"]])
page_text = client.get("/admin/try").text
order = [page_text.find(t) for t in ("ما هي أداة Hunchly؟", "Hunchly أداة توثيق الصفحات.",
                                      "هل أداة Hunchly مجانية؟", "نعم، وهي مجانية للصحفيين.")]
check("الخيط يعود عند فتح الصفحة بدورتيه بالترتيب، الأحدث في الأسفل",
      all(i >= 0 for i in order) and order == sorted(order), order)
turns = store.thread("team", "owner", 20)
check("الدورتان محفوظتان بدوريهما ونتيجتهما وثقتهما",
      [t["role"] for t in turns] == ["user", "assistant"] * 2
      and all(t["outcome"] == "answered" and t["confidence"] is not None for t in turns)
      and turns[1]["retrieval"] and turns[1]["retrieval"]["passages"], turns and turns[1].get("retrieval"))
vw_page = vw.get("/admin/try?lang=en").text
check("عضو آخر يرى خيطاً فارغاً", "No conversation yet" in vw_page and "ما هي أداة Hunchly؟" not in vw_page)
team_reply.update(content=[{"type": "text", "text": "ردّ للمشاهد وحده."}], stop_reason="end_turn")
r = vw.post("/admin/try", data={"q": "ما هي أداة Hunchly؟", "action": "ask"})
check("المشاهد يحادث أيضاً، ومحادثته له وحده",
      r.status_code == 200 and "ردّ للمشاهد وحده." in r.text and "نعم، وهي مجانية للصحفيين." not in r.text
      and len(store.thread("team", "vw@paxmemoria.org", 20)) == 2
      and "ردّ للمشاهد وحده." not in client.get("/admin/try").text)
check("رسائل الفريق لا تظهر في صفحة الأسئلة",
      "هل أداة Hunchly مجانية؟" not in client.get("/admin/messages").text
      and all(q["channel"] != "team" for q in store.questions()))
check("رسائل الفريق لا تدخل في الإجماليات ولا المواضيع ولا أعداد القنوات",
      (store.usage_totals(), store.topic_totals(), store.topic_stats(week_ago),
       store.channel_stats(week_ago), store.outcome_stats(week_ago)) == before_stats
      and "team" not in store.usage_totals(), store.usage_totals())
r = client.post("/admin/try", data={"q": "سؤال ثالث عن Hunchly؟", "action": "ask"})
for i in range(2):
    brain.handle(f"سؤال {i}", "telegram", "u-cap")
check("الحدّ اليومي (2 هنا) يُطبَّق على القناة العامة لا على الفريق",
      "الحدّ اليومي للأسئلة" not in r.text and "سؤال ثالث عن Hunchly؟" in r.text
      and store.questions_since("team", "owner", time.time() - 86400) == []
      and "الحدّ اليومي للأسئلة" in brain.handle("ما هي أداة Hunchly؟", "telegram", "u-cap"))
r = client.post("/admin/try", data={"action": "new"})
check("«محادثة جديدة» تمسح الخيط",
      r.status_code == 200 and "لا محادثة بعد" in r.text and store.thread("team", "owner", 20) == []
      and store.history("team", "owner", 4) == [])
check("خيط المشاهد لم يتأثر", len(store.thread("team", "vw@paxmemoria.org", 20)) == 2)
with store.db() as c:
    c.execute("INSERT INTO messages(channel,user_id,role,content,ts) VALUES(?,?,?,?,?)",
              ("team", "vw@paxmemoria.org", "user", "قديم", time.time() - 31 * 86400))
store.purge_old_messages(30)
check("رسائل الفريق تخضع لمدة الحذف كغيرها",
      all(t["content"] != "قديم" for t in store.thread("team", "vw@paxmemoria.org", 20)))
store.clear_history("team", "vw@paxmemoria.org")
check("الإنجليزية في صفحة المحادثة", "New conversation" in client.get("/admin/try?lang=en").text
      and "No conversation yet" in client.get("/admin/try?lang=en").text)
client.get("/admin/try?lang=ar")
store.set_setting("daily_limit", old_daily)
brain._client = None

config.GOOGLE_CLIENT_ID = ""
check("بلا عميل Google تبقى صفحة الدخول بكلمة المرور وحدها", "/admin/auth/google" not in anon.get("/admin/login").text)
dash.httpx.AsyncClient = real_dash_async
config.PUBLIC_URL = ""
with store.db() as c:
    c.execute("DELETE FROM members")
    c.execute("DELETE FROM audit")

r = client.get("/privacy")
check("صفحة الخصوصية تعمل باللغتين",
      r.status_code == 200 and "سياسة الخصوصية لبيان" in r.text and "Bayan privacy policy" in r.text)
check("الصفحة تذكر مدة الحفظ والعنوان من الإعدادات",
      f"{config.MESSAGE_RETENTION_DAYS} يوماً" in r.text and config.PRIVACY_CONTACT in r.text)
check("صفحة الخصوصية بلا سكربت", "default-src 'none'" in r.headers.get("content-security-policy", ""))

captured = []


class Grab(logging.Handler):
    def emit(self, record):
        captured.append(record.getMessage())


grab = Grab()
logging.getLogger("brain").addHandler(grab)
brain.answer("كم سعر الذهب في سوق دمشق اليوم بالتحديد", "admin", "console")
logging.getLogger("brain").removeHandler(grab)
check("سجلّ الخادم لا يحوي نص السؤال", captured and not any("الذهب" in m for m in captured),
      captured)

# ── ٦. الفهرسة في الخلفية / 6. Background indexing ───────────────
print("\n── الفهرسة في الخلفية ──")
import threading  # noqa: E402

runs = []
gate = threading.Event()
real_run = ingest._run


def slow_run(pull):
    runs.append(pull)
    gate.wait(5)
    return True, "ok"


ingest._run = slow_run
first = ingest.start_background(pull=False)
second = ingest.start_background(pull=False)
third = ingest.start_background(pull=False)
check("إشارة أولى تبدأ، والتاليتان أثناءها تُدمجان في دورة واحدة",
      (first, second, third) == ("started", "queued", "queued"), (first, second, third))
gate.set()
for _ in range(50):
    if not ingest.running():
        break
    time.sleep(0.05)
check("دورتان فقط: الجارية، وواحدة بعدها تشمل آخر تعديل", len(runs) == 2, runs)
check("القفل يُحرَّر بعد آخر دورة", not ingest.running())

config.REINDEX_SECRET = "reindex-secret"
gate.clear()
r = client.post("/admin/reindex", headers={"X-Bayan-Secret": "reindex-secret"})
check("/admin/reindex يردّ فوراً بـ 202", r.status_code == 202 and r.json()["state"] == "started",
      r.text)
check("سرّ خاطئ يُرفض", client.post("/admin/reindex", headers={"X-Bayan-Secret": "x"})
      .status_code == 403)
gate.set()
for _ in range(50):
    if not ingest.running():
        break
    time.sleep(0.05)
ingest._run = real_run

# ── ٧. عزل مُستخرِج الموقع / 7. Isolating the site extractor ─────
print("\n── عزل المُستخرِج ──")
import shutil  # noqa: E402

if shutil.which("node"):
    site = TMP / "hostile-site"
    (site / "scripts").mkdir(parents=True)
    # مُستخرِج «معادٍ»: يحاول ما قد يحاوله تعديل خبيث في مستودع الموقع
    # A "hostile" extractor: it tries what a malicious edit in the site
    # repository might try
    (site / "scripts" / "export-bayan-knowledge.mjs").write_text("""
import { readFileSync, writeFileSync } from 'node:fs';
const probe = { key: process.env.ANTHROPIC_API_KEY ?? null };
try { readFileSync(process.argv[2] ?? '/etc/hosts'); probe.outside = 'read'; }
catch (e) { probe.outside = e.code; }
try { (await import('node:child_process')).execSync('id'); probe.child = 'ran'; }
catch (e) { probe.child = e.code; }
writeFileSync(new URL('../bayan-export/probe.json', import.meta.url), JSON.stringify(probe));
console.log('done');
""")
    old_repo, old_export = config.SITE_REPO, config.EXPORT_DIR
    config.SITE_REPO, config.EXPORT_DIR = site, site / "bayan-export"
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-should-never-leak"
    log_lines: list[str] = []
    ingest.run_extractor(log_lines)
    probe = json.loads((site / "bayan-export" / "probe.json").read_text())
    check("المُستخرِج لا يرى مفاتيح بيان", probe["key"] is None, probe)
    check("المُستخرِج لا يقرأ خارج مستودع الموقع", probe["outside"] == "ERR_ACCESS_DENIED", probe)
    check("المُستخرِج لا يشغّل أوامر", probe["child"] == "ERR_ACCESS_DENIED", probe)
    os.environ["ANTHROPIC_API_KEY"] = ""
    config.SITE_REPO, config.EXPORT_DIR = old_repo, old_export
else:
    print("  (node غير مثبّت هنا: يُختبر في صورة Docker)")

# ── ٧ب. سحب مستودع الموقع وتبديل الفرع / 7b. Pulling the site repository and switching branches ──
print("\n── سحب المستودع ──")
import subprocess  # noqa: E402

upstream = TMP / "upstream"
git = lambda *a, cwd=upstream: subprocess.run(  # noqa: E731
    ["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()
upstream.mkdir()
git("init", "-q", "-b", "main")
git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "main 1")
git("checkout", "-q", "-b", "feature")
git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "feature 1")
git("checkout", "-q", "main")
git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "main 2")
old = (config.SITE_REPO, config.SITE_REPO_URL, config.SITE_BRANCH)
config.SITE_REPO, config.SITE_REPO_URL = TMP / "clone", upstream.as_uri()
config.SITE_BRANCH = "feature"
ingest.sync_repo([])
check("النسخة الأولى من فرع مؤقت", git("log", "-1", "--format=%s", cwd=config.SITE_REPO) == "feature 1")
config.SITE_BRANCH = "main"
ingest.sync_repo([])
check("التبديل إلى main بعد نسخة من فرع آخر يعمل",
      git("log", "-1", "--format=%s", cwd=config.SITE_REPO) == "main 2")
config.SITE_REPO, config.SITE_REPO_URL, config.SITE_BRANCH = old

r = client.get("/", follow_redirects=False)
check("العنوان الجذر يحيل إلى موقع المنظمة",
      r.status_code == 302 and r.headers["location"] == config.SITE_URL)

# ── ٨. تيليغرام / 8. Telegram ────────────────────────────────────
print("\n── تيليغرام ──")
upd = {"update_id": 1, "message": {"chat": {"id": 5}, "text": "مرحبا"}}
check("بلا TELEGRAM_WEBHOOK_SECRET يُرفض كل تحديث",
      client.post("/webhooks/telegram", json=upd).status_code == 500)
config.TELEGRAM_WEBHOOK_SECRET = "tg-secret"
check("سرّ خاطئ يُرفض", client.post(
    "/webhooks/telegram", json=upd,
    headers={"X-Telegram-Bot-Api-Secret-Token": "nope"}).status_code == 403)

# ── تنسيق القنوات / Channel formatting ──────────────────────────
print("\n── تنسيق القنوات ──")
import asyncio  # noqa: E402

from app.channels import fmt  # noqa: E402
from app.channels import telegram as tg  # noqa: E402

R, L = fmt.RLM, fmt.LRM
md = "### أدوات\n- **FlightAware**: <تتبّع> & __رحلات__"
check("تيليغرام: عريض حقيقي، والرموز مهرّبة",
      fmt.to_telegram_html(md)
      == f"{R}<b>أدوات</b>\n\n{R}<b>FlightAware</b>\n{R}&lt;تتبّع&gt; &amp; <b>رحلات</b>",
      fmt.to_telegram_html(md))
ar = ("هذه أدوات الدليل لتتبّع الرحلات الجوية:\n"
      "- **رصد الحرائق:** تظهر النار كبقع برتقالية.\n"
      "- **FlightAware**: يتتبّع الرحلات الجوية حول العالم.\n"
      "**مفرق ماوية** منطقة في الحوبان.\n\n🔗 المصدر:\nhttps://paxmemoria.org/x/")
check("العنوان الفرعي في سطر مستقل وتحته التفاصيل، وكل سطر عربي من اليمين",
      fmt.to_whatsapp(ar) == (
          f"{R}هذه أدوات الدليل لتتبّع الرحلات الجوية:\n\n"
          f"{R}*رصد الحرائق*\n{R}تظهر النار كبقع برتقالية.\n\n"
          f"{R}*FlightAware*\n{R}يتتبّع الرحلات الجوية حول العالم.\n"
          f"{R}*مفرق ماوية* منطقة في الحوبان.\n\n{R}🔗 المصدر:\n"
          f"{R}https://paxmemoria.org/x/{L}"), fmt.to_whatsapp(ar))
check("بند مرقّم يبقى رقمه في عنوانه",
      fmt.to_plain("Steps:\n1. **Check the date:** compare it.")
      == "Steps:\n\n1. Check the date\ncompare it.", fmt.to_plain("Steps:\n1. **Check the date:** compare it."))
check("الرسالة الإنجليزية تبقى من اليسار بلا علامات",
      R not in fmt.to_plain("Use **FlightAware**: it tracks flights. المصدر"))
check("واتساب: نجمة واحدة", fmt.to_whatsapp("**FlightAware** و**Flightradar24**")
      == "*FlightAware* و*Flightradar24*")
check("ماسنجر: بلا تنسيق", fmt.to_plain("### عنوان\n**FlightAware**") == "عنوان\nFlightAware")

tg_calls = []


def tg_api(request):
    body = json.loads(request.content)
    tg_calls.append(body)
    if body.get("parse_mode") == "HTML" and "رفض" in body["text"]:
        return httpx.Response(400, json={"ok": False, "description": "can't parse entities"})
    return httpx.Response(200, json={"ok": True})


real_async = httpx.AsyncClient
tg.httpx.AsyncClient = lambda **kw: real_async(transport=httpx.MockTransport(tg_api), **kw)
asyncio.run(tg.send("5", "**مرحبا**"))
check("تيليغرام يُرسل بوضع HTML", tg_calls[-1].get("parse_mode") == "HTML"
      and tg_calls[-1]["text"] == f"{R}<b>مرحبا</b>", tg_calls[-1])
import app.channels.messenger as msgr  # noqa: E402
like_calls = []
tg_client = msgr.httpx.AsyncClient
msgr.httpx.AsyncClient = lambda **kw: real_async(
    transport=httpx.MockTransport(lambda r: like_calls.append(str(r.url)) or httpx.Response(200, json={"success": True})), **kw)
msgr.config.MESSENGER_PAGE_TOKEN = "t"
asyncio.run(msgr.like_comment("123_456"))
check("الإعجاب بالتعليق يُرسل إلى likes بتعليقه", like_calls and "/123_456/likes" in like_calls[-1], like_calls)
msgr.httpx.AsyncClient = lambda **kw: real_async(
    transport=httpx.MockTransport(lambda r: httpx.Response(403, json={"error": {}})), **kw)
asyncio.run(msgr.like_comment("123_456"))
check("فشل الإعجاب لا يرفع خطأً", True)
msgr.httpx.AsyncClient = tg_client
asyncio.run(tg.send("5", "**رفض** هنا"))
check("رفض التنسيق يعيد الرسالة نصاً عادياً",
      "parse_mode" not in tg_calls[-1] and tg_calls[-1]["text"] == f"{R}رفض هنا", tg_calls[-1])
asyncio.run(wa.sender("966500000001")("SA.123", "**مرحبا**"))
check("واتساب يردّ على الرقم في to", tg_calls[-1].get("to") == "966500000001"
      and "recipient" not in tg_calls[-1] and tg_calls[-1]["text"]["body"] == f"{R}*مرحبا*",
      tg_calls[-1])
asyncio.run(wa.sender("SA.456")("SA.456", "نص"))
check("واتساب يردّ على الـBSUID في recipient", tg_calls[-1].get("recipient") == "SA.456"
      and "to" not in tg_calls[-1], tg_calls[-1])
tg.httpx.AsyncClient = real_async

# ── السلامة الرقمية: الجزء الرابع من مصدرين مفتوحين / Digital safety: the fourth part ──
print("\n── السلامة الرقمية ──")
from app import safety  # noqa: E402

SIAB_URL = "https://securityinabox.org/ar/passwords/2fa/"
SIAB_PARA = "الاستيثاق بمُعاملين يضيف مُعاملاً للاستيثاق إلى نظام الولوج. " * 5
SIAB_HTML = f"""<html><body><nav id="top-nav"><a href="/ar">القائمة</a></nav>
<main id="content"><ul class="breadcrumbs"><li><a href="/ar">الرئيسية</a></li></ul>
<div class="d-none" id="search-breadcrumbs">كلمات السرّ › الاستيثاق</div>
<h1 class="title">الاستيثاق بمعاملين</h1><p class="meta">روجِع 28 March 2024</p>
<div id="toc"><h2>الفهرس</h2><ul><li><a href="#a">كيفية الاستخدام</a></li></ul></div>
<p>{SIAB_PARA}&#x639;ن الاستيثاق.</p><h2>كيفية الاستخدام</h2>
<ul><li>خطوة <strong>أولى</strong></li><li>خطوة ثانية</li></ul>
<details><summary>تفصيل مطويّ</summary><p>نص التفصيل.</p></details><img src="x.png" alt>
</main><footer id="footer">CC BY-SA</footer></body></html>"""
recs = safety.parse_siab(SIAB_HTML, SIAB_URL)
text = "\n".join(r["text"] for r in recs)
check("صفحة Security in a Box تُقرأ من <main>", recs and recs[0]["title"] == "الاستيثاق بمعاملين",
      recs[:1])
check("تاريخ المراجعة من سطر «روجِع»", recs and recs[0]["meta"]["date"] == "28 March 2024")
check("المعرّف والرابط والرخصة في meta",
      recs and recs[0]["id"] == "safety:siab:passwords/2fa:0" and recs[0]["url"] == SIAB_URL
      and recs[0]["meta"]["licence"] == "CC BY-SA 4.0" and recs[0]["type"] == "safety"
      and recs[0]["lang"] == "ar", recs[:1])
check("مسار التنقّل والفهرس والتذييل خارج النص",
      "الرئيسية" not in text and "الفهرس" not in text and "CC BY-SA" not in text
      and "القائمة" not in text, text)
check("العناوين والقوائم والتفاصيل والكيانات في النص",
      "## كيفية الاستخدام" in text and "- خطوة أولى" in text and "- خطوة ثانية" in text
      and "تفصيل مطويّ" in text and "نص التفصيل." in text and "عن الاستيثاق." in text, text)
en_recs = safety.parse_siab(SIAB_HTML.replace(SIAB_PARA, "Signal protects your calls end to end. " * 8),
                            "https://securityinabox.org/ar/tools/signal/")
check("صفحة /ar/ لم تُترجم تُوسم إنجليزية من حروفها",
      recs[0]["lang"] == "ar" and en_recs and en_recs[0]["lang"] == "en", en_recs[:1])
check("صفحة قسم بلا متن لا تُفهرس",
      safety.parse_siab('<main id="content"><h1 class="title">كلمات السرّ</h1></main>',
                        "https://securityinabox.org/ar/passwords/") == [])
sitemap = "".join(f"<loc>{u}</loc>" for u in (
    "https://securityinabox.org/ar/", "https://securityinabox.org/ar/404/",
    "https://securityinabox.org/ar/about/how/", "https://securityinabox.org/ar/blog/x/",
    "https://securityinabox.org/ar/disclaimer/", "https://securityinabox.org/en/passwords/2fa/",
    "https://securityinabox.org/ar/passwords/2fa/", "https://securityinabox.org/ar/guide/riseup/",
))
check("من sitemap تُؤخذ الصفحات العربية الإرشادية وحدها",
      safety.siab_urls(sitemap) == ["https://securityinabox.org/ar/passwords/2fa/",
                                    "https://securityinabox.org/ar/guide/riseup/"],
      safety.siab_urls(sitemap))

long = "جملة أولى. " * 30
first = "فقرة أولى طويلة بما يكفي. " * 3
parts = safety.chunk_blocks([first, "## عنوان", "فقرة ثانية.", long], limit=120)
check("العنوان بعد مقطع امتلأ نصفه يبدأ مقطعاً ويبقى مع ما بعده",
      parts[0] == first.strip() and parts[1].startswith("## عنوان\nفقرة ثانية."), parts[:2])
check("العنوان بعد مقطع قصير يُضمّ إليه",
      safety.chunk_blocks(["فقرة.", "## عنوان", "فقرة ثانية."], limit=120)
      == ["فقرة.\n## عنوان\nفقرة ثانية."])
check("الفقرة الطويلة تُقسَم عند نهايات الجمل دون تجاوز الحدّ",
      all(len(p) <= 120 for p in parts) and "".join(parts).count("جملة أولى") == 30,
      [len(p) for p in parts])

DFAK_MD = """---
layout: topic
title: "لا أستطيع الولوج إلى حسابي"
language: ar
summary: "هل تواجهين صعوبة في الولوج&nbsp;إلى حسابك؟"
date: 2023-06-29
permalink: topics/account-access-issues
sidebar: >
  <h3>المزيد</h3>

  <ul><li>سطر</li></ul>
---

# لا أستطيع الولوج إلى حسابي

يستعمل أفراد المجتمع المدني الحسابات بكثافة [[1]](#note-1) و&nbsp;انظر [دليل الاستخدام](https://example.org/x).
<!--- قالب للمحرّرين
- Yes
-->

## Workflow

### Password-Typo

#### هل تحتوي كلمة السر على خطأ مطبعي؟

> جرِّبي كتابة كلمة السرِّ في مُحرِّر نصوص **صافية**.
>
> - [فيسبوك](https://www.facebook.com/help/1)
> - [إنستَگرام
>   للمساعدة](https://help.instagram.com/2)

##### Options

- [نعم](#resolved_end)
- [لا](#account-disabled)

### account-disabled

#### الحساب معطل

اتّبعوا آليات التظلّم.
"""
fields, body = safety.front_matter(DFAK_MD)
check("حقول الواجهة تُقرأ، والقيمة متعددة الأسطر تُلحق بمفتاحها",
      fields["permalink"] == "topics/account-access-issues" and fields["date"] == "2023-06-29"
      and fields["title"] == "لا أستطيع الولوج إلى حسابي" and "<h3>المزيد</h3>" in fields["sidebar"]
      and "<ul><li>سطر</li></ul>" in fields["sidebar"], fields)
blocks = safety.md_blocks(body)
check("عنوان الصفحة ومراسي المسار وقوائم Options تُسقَط",
      not any(b.startswith("## Workflow") or "Password-Typo" in b or "account-disabled" in b
              or "resolved_end" in b or b == "- نعم" or b == "- لا" for b in blocks), blocks)
check("العناوين العربية والاقتباسات والروابط والتعليقات تُنظَّف",
      "## هل تحتوي كلمة السر على خطأ مطبعي؟" in blocks and "## الحساب معطل" in blocks
      and "جرِّبي كتابة كلمة السرِّ في مُحرِّر نصوص صافية." in blocks
      and "- فيسبوك" in blocks and "- إنستَگرام للمساعدة" in blocks
      and "اتّبعوا آليات التظلّم." in blocks
      and any(b.startswith("يستعمل أفراد المجتمع المدني الحسابات بكثافة 1 و انظر دليل الاستخدام.")
              for b in blocks)
      and not any("قالب" in b or "](" in b or "<" in b for b in blocks), blocks)

dfak_dir = TMP / "dfak" / "content" / "ar"
(dfak_dir / "topics").mkdir(parents=True)
(dfak_dir / "organisations").mkdir()
(dfak_dir / "contact-methods").mkdir()
(dfak_dir / "topics" / "account-access-issues.md").write_text(DFAK_MD, encoding="utf-8")
(dfak_dir / "organisations" / "FLD.md").write_text("""---
language: ar
layout: organisation
name: Front Line Defenders
website: https://www.frontlinedefenders.org/emergency-contact
hours: emergency 24/7
response_time: نفس اليوم
---

منظَّمة دوليَّة تقدِّم دعمًا سريعًا للمدافعين عن حقوق الإنسان.
""", encoding="utf-8")
(dfak_dir / "about.md").write_text("---\nlayout: page\ntitle: About\npermalink: about\n---\n\nعن العدّة.\n",
                                   encoding="utf-8")
(dfak_dir / "contact-methods" / "email.md").write_text(
    "---\nlayout: contact-method\ntitle: البريد\npermalink: /ar/contact-methods/email.md\n---\n\nنص.\n",
    encoding="utf-8")
drecs = safety.read_dfak(TMP / "dfak")
topic = [r for r in drecs if r["meta"]["slug"] == "topics/account-access-issues"]
org = [r for r in drecs if r["meta"]["slug"] == "support/FLD"]
check("ملفات content/ar تُقرأ: موضوع ومنظمة، لا «عن» ولا وسائل الاتصال",
      len(drecs) == len(topic) + len(org) and topic and org, [r["id"] for r in drecs])
check("الموضوع: الرابط من permalink، الملخص أولاً، التاريخ والرخصة في meta",
      topic[0]["url"] == "https://digitalfirstaid.org/ar/topics/account-access-issues/"
      and topic[0]["text"].startswith("لا أستطيع الولوج إلى حسابي\nهل تواجهين صعوبة في الولوج إلى حسابك؟")
      and topic[0]["meta"]["date"] == "2023-06-29" and topic[0]["meta"]["licence"] == "CC BY 4.0"
      and topic[0]["meta"]["source"] == "Digital First Aid Kit", topic[0])
check("منظمة الدعم: اسمها وموقعها وساعاتها، ورابطها صفحة الدعم",
      org[0]["title"] == "Front Line Defenders" and org[0]["url"] == "https://digitalfirstaid.org/ar/support/"
      and "منظمة دعم: Front Line Defenders" in org[0]["text"]
      and "الموقع: https://www.frontlinedefenders.org/emergency-contact" in org[0]["text"]
      and "ساعات العمل: emergency 24/7" in org[0]["text"] and "زمن الاستجابة: نفس اليوم" in org[0]["text"]
      and "دعمًا سريعًا" in org[0]["text"], org[0]["text"])

# الدورة: الجلب الفاشل يُبقي النسخة السابقة، والناجح يحفظها، وبلا سحب تُقرأ وحدها
# The cycle: a failed fetch keeps the previous copy, a successful one saves it,
# and without pull only the copy is read
cached = recs[:1] + drecs[:1]
config.SAFETY_PATH.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in cached) + "\n",
                              encoding="utf-8")
real_sources, real_fetch_siab, real_fetch_dfak = config.SAFETY_SOURCES, safety.fetch_siab, safety.fetch_dfak
config.SAFETY_SOURCES = {"siab", "dfak"}
got = safety.collect([], pull=False)
check("بلا سحب تُقرأ النسخة المحفوظة", [c["id"] for c in got] == [c["id"] for c in cached])
config.SAFETY_SOURCES = {"dfak"}
check("SAFETY_SOURCES يحصر المصادر", [c["id"] for c in safety.collect([], pull=False)] == [drecs[0]["id"]])
config.SAFETY_SOURCES = set()
check("SAFETY_SOURCES فارغاً يعطّل الجزء", safety.collect([], pull=True) == [])
config.SAFETY_SOURCES = {"siab", "dfak"}


def down(*a, **k):
    raise RuntimeError("503 Service Unavailable")


safety.fetch_siab = safety.fetch_dfak = down
log_lines = []
mtime = config.SAFETY_PATH.stat().st_mtime_ns
got = safety.collect(log_lines, pull=True)
check("تعطّل المصدرين يُبقي النسخة السابقة ويُسجَّل",
      [c["id"] for c in got] == [c["id"] for c in cached]
      and sum("503" in line and "أُبقي على 1 مقطع" in line for line in log_lines) == 2
      and config.SAFETY_PATH.stat().st_mtime_ns == mtime, log_lines)
safety.fetch_siab = lambda log, client: recs
safety.fetch_dfak = down
got = safety.collect(log_lines, pull=True)
check("مصدر ناجح ومصدر معطّل: الناجح جديد والمعطّل من النسخة، وتُحفظ النسخة",
      [c["id"] for c in got] == [c["id"] for c in recs] + [drecs[0]["id"]]
      and [c["id"] for c in safety.collect([], pull=False)] == [c["id"] for c in got], got)
safety.fetch_siab, safety.fetch_dfak = real_fetch_siab, real_fetch_dfak

# الفهرسة تضمّ المقاطع، والاسترجاع يجدها، والسياق يسمّي المصدر والرخصة والتاريخ
# Indexing includes the chunks, retrieval finds them, and the context names
# the source, licence and date
config.VOYAGE_API_KEY = "test"
embed.embed = fake_vectors
okk, detail = ingest.run(pull=False)
n_safety = len(recs) + 1
check("الفهرسة بلا سحب تضمّ مقاطع السلامة من النسخة",
      okk and store.counts().get("safety") == n_safety and f"{n_safety} سلامة رقمية" in detail, detail)
retrieve.warm()
r = retrieve.search("كيف أفعّل الاستيثاق بمعاملين لحماية حسابي؟")
hit = [p for p in r["passages"] if p["type"] == "safety"]
check("الاسترجاع يجد مقطع السلامة", hit, [(p["type"], p["title"]) for p in r["passages"]])
ctx, urls = brain.build_context({**r, "passages": hit[:1], "corrections": [], "opportunities": [],
                                 "tools": [], "category_tools": [], "category": None}, "ar")
check("السياق يسمّي المصدر ورخصته وتاريخ المراجعة ورابط الصفحة",
      ctx.startswith('<سلامة_رقمية رقم="1" المصدر="Security in a Box" الرخصة="CC BY-SA 4.0">')
      and "المصدر: عدّة الأمان (Security in a Box، Front Line Defenders) | الرخصة: CC BY-SA 4.0"
      in ctx and "روجِعت الصفحة: 28 March 2024" in ctx and urls[1] == SIAB_URL, ctx[:300])
check("سطر المصدر يحمل اسم المصدر ورخصته بعد الرابط، والرخصة ليست مطلوبة في النص",
      brain.source_lines([SIAB_URL, f"{config.SITE_URL}/osint-tools"], {"passages": hit[:1]})
      == [f"{SIAB_URL} — Security in a Box, CC BY-SA 4.0", f"{config.SITE_URL}/osint-tools"]
      and "لا تكتب الرخصة في النص" in brain.SYSTEM_PROMPT)
check("موضوع السؤال «السلامة الرقمية» باسم مصدره",
      brain.topic_of({"passages": hit[:1], "tools": [], "category_tools": []}, "answered")
      == ("safety", "Security in a Box") and "safety" in brain.TOPICS)
check("تعليمات النظام والرفض تذكر الجزء الرابع ومصدريه",
      "<سلامة_رقمية>" in brain.SYSTEM_PROMPT and "CC BY-SA 4.0" in brain.SYSTEM_PROMPT
      and "أربعة أشياء" in config.OUT_OF_SCOPE_MESSAGE and "الجنوب العالمي" in config.OUT_OF_SCOPE_MESSAGE
      and "four things" in config.OUT_OF_SCOPE_MESSAGE_EN and "Global South" in config.OUT_OF_SCOPE_MESSAGE_EN
      and "Digital First Aid Kit" in config.OUT_OF_SCOPE_MESSAGE_EN)
r = client.get("/admin")
check("اللوحة تعدّ مقاطع السلامة الرقمية",
      r.status_code == 200 and f"السلامة الرقمية: {n_safety}" in r.text, r.status_code)
config.SAFETY_SOURCES = real_sources

# ── مفاتيح API من اللوحة، للمدير وحده / API keys from the dashboard, admin only ──
print("\n── مفاتيح API من اللوحة ──")
from app import keys  # noqa: E402

old_key, old_client_obj = config.ANTHROPIC_API_KEY, brain._client
client.get("/admin?lang=ar")
r = client.post("/admin/keys/set", follow_redirects=False,
                data={"name": "ANTHROPIC_API_KEY", "value": "sk-ant-test-1234567890abcd"})
check("المدير يحفظ مفتاحاً فيعمل فوراً ويُعاد بناء العميل",
      "key_saved" in r.headers["location"] and config.ANTHROPIC_API_KEY == "sk-ant-test-1234567890abcd"
      and brain._client is None, r.headers.get("location"))
page_text = client.get("/admin/settings").text
check("اللوحة تعرض آخر أربعة أحرف فقط ومصدر المفتاح",
      "••••abcd" in page_text and "sk-ant-test" not in page_text and "من اللوحة" in page_text
      and "مفاتيح API" in page_text)
old_pub = config.PUBLIC_URL
config.PUBLIC_URL = "https://bayan.test"
r = client.post("/admin/keys/set", follow_redirects=False,
                data={"name": "GOOGLE_CLIENT_ID", "value": "123-abc.apps.googleusercontent.com"})
client.post("/admin/keys/set", data={"name": "GOOGLE_CLIENT_SECRET", "value": "GOCSPX-test-secret-1234"})
check("معرّف عميل Google وسرّه يُضبطان من اللوحة فيظهر زر الدخول بحساب Google فوراً",
      "key_saved" in r.headers["location"] and config.GOOGLE_CLIENT_ID.endswith("googleusercontent.com")
      and dash.google_enabled() and "auth/google" in TestClient(server.app).get("/admin/login").text,
      (r.headers.get("location"), dash.google_enabled()))
client.post("/admin/keys/clear", data={"name": "GOOGLE_CLIENT_ID"})
client.post("/admin/keys/clear", data={"name": "GOOGLE_CLIENT_SECRET"})
check("مسحهما يعيد قيم .env ويخفي الزر", config.GOOGLE_CLIENT_ID == keys.ENV_VALUES["GOOGLE_CLIENT_ID"]
      and not dash.google_enabled()
      and "auth/google" not in TestClient(server.app).get("/admin/login").text)
config.PUBLIC_URL = old_pub
acts = store.audit_log(20)
check("القيمة في القاعدة، وفي سجلّ الإجراءات اسم المفتاح لا قيمته",
      store.api_keys()[0]["value"] == "sk-ant-test-1234567890abcd"
      and any(a["action"] == "key_set" and a.get("target") == "ANTHROPIC_API_KEY" for a in acts)
      and not any("1234567890abcd" in json.dumps(a, ensure_ascii=False) for a in acts), acts[:3])
r = client.post("/admin/keys/set", data={"name": "ANTHROPIC_API_KEY", "value": "has space key"},
                follow_redirects=False)
check("مفتاح فيه مسافة يُرفض", "error=key" in r.headers["location"])
r = client.post("/admin/keys/set", data={"name": "TELEGRAM_BOT_TOKEN", "value": "123456:ABCDEFGH"},
                follow_redirects=False)
check("مفتاح ليس في القائمة (يحتاج إعادة تشغيل) يُرفض",
      "error=key" in r.headers["location"] and len(store.api_keys()) == 1)
config.GOOGLE_CLIENT_ID, config.GOOGLE_CLIENT_SECRET = "cid", "sec"
config.PUBLIC_URL = "http://bayan.test"
dash.httpx.AsyncClient = lambda **kw: real_dash_async(transport=httpx.MockTransport(google_api), **kw)
store.add_member("keys-viewer@paxmemoria.org", "viewer", "KV")
viewer = TestClient(server.app)
google_login(viewer, {"email": "keys-viewer@paxmemoria.org", "email_verified": True,
                      "hd": "paxmemoria.org", "name": "KV"})
dash.httpx.AsyncClient = real_dash_async
config.PUBLIC_URL = ""
check("المشاهد يقرأ ولا يحفظ مفاتيح، ولا يرى صفحة الإعدادات",
      viewer.get("/admin/messages").status_code == 200
      and viewer.post("/admin/keys/set", data={"name": "GEMINI_API_KEY", "value": "AIza-test-123456"}).status_code == 403
      and viewer.get("/admin/settings").status_code == 403 and len(store.api_keys()) == 1,
      (viewer.get("/admin/messages").status_code, viewer.get("/admin/settings").status_code))
config.GOOGLE_CLIENT_ID = config.GOOGLE_CLIENT_SECRET = ""
config.ANTHROPIC_API_KEY = "from-env"
check("عند الإقلاع تُطبَّق المفاتيح المحفوظة فوق .env",
      keys.apply_saved() == 1 and config.ANTHROPIC_API_KEY == "sk-ant-test-1234567890abcd")
r = client.post("/admin/keys/clear", data={"name": "ANTHROPIC_API_KEY"}, follow_redirects=False)
check("المسح يعيد قيمة .env ويُسجَّل",
      "key_cleared" in r.headers["location"] and config.ANTHROPIC_API_KEY == keys.ENV_VALUES["ANTHROPIC_API_KEY"]
      and store.api_keys() == [] and any(a["action"] == "key_clear" for a in store.audit_log(5)))
config.ANTHROPIC_API_KEY, brain._client = old_key, old_client_obj

# ── دور بيان من اللوحة، للمدير وحده / Bayan's role from the dashboard, admin only ──
print("\n── دور بيان ──")
from app import role  # noqa: E402

r = client.get("/admin/role")
check("صفحة «دور بيان» للمدير: أقسامها الخمسة ومعاينة التعليمات",
      r.status_code == 200
      and all(k in r.text for k in ("scope_ar", 'name="rules"', "refusal_en", "welcome_ar", "paused_en"))
      and "نطاقك:" in r.text, r.status_code)
check("المشاهد لا يفتح «دور بيان» ولا يحفظ فيه",
      viewer.get("/admin/role").status_code == 403
      and viewer.post("/admin/role/save", data={"section": "rules", "rules": "x"}).status_code == 403)
r = client.post("/admin/role/save", follow_redirects=False,
                data={"section": "rules", "rules": "لا تذكر أسعار الأدوات.\r\nاختم بشكر."})
live = brain.system_prompt()
check("قواعد الفريق تُلحق بالتعليمات الفعلية ولا تمسّ الافتراضية",
      "role_saved" in r.headers["location"] and "لا تذكر أسعار الأدوات.\nاختم بشكر." in live
      and "قواعد إضافية من فريق" in live and "قواعد إضافية" not in brain.SYSTEM_PROMPT
      and live.startswith(brain.SYSTEM_PROMPT), r.headers.get("location"))
r = client.post("/admin/role/save", follow_redirects=False,
                data={"section": "refusal", "refusal_ar": "خارج نطاقي. اسألني عن الدليل.",
                      "refusal_en": "Outside my scope. Ask me about the guide."})
check("نص الرفض الجديد يُستعمل فوراً باللغتين",
      "role_saved" in r.headers["location"]
      and i18n.msg("out_of_scope", "ar") == "خارج نطاقي. اسألني عن الدليل."
      and i18n.msg("out_of_scope", "en") == "Outside my scope. Ask me about the guide.")
check("تعديل الرفض من اللوحة لا يمسّ اللغات الأخرى، وصفحة الدور تقول ذلك",
      i18n.msg("out_of_scope", "pt-BR").startswith("Desculpe")
      and brain.handle("Qual é a capital da França?", "telegram", "u-pt-role").startswith("Desculpe")
      and "app/locales" in client.get("/admin/role").text)
check("الصفحة تعلّم المعدَّل، والنص الأطول من الحدّ يُرفض",
      "معدَّل من اللوحة" in client.get("/admin/role").text
      and "error=role" in client.post("/admin/role/save", follow_redirects=False,
                                      data={"section": "rules", "rules": "x" * 4001}).headers["location"])
config.TEAM_RULES, config.OUT_OF_SCOPE_MESSAGE = "", "من .env"
check("عند الإقلاع تُطبَّق النصوص المحفوظة فوق .env",
      role.apply_saved() == 3 and config.TEAM_RULES.startswith("لا تذكر")
      and config.OUT_OF_SCOPE_MESSAGE.startswith("خارج نطاقي"))
client.post("/admin/role/save", data={"section": "refusal", "reset": "1"})
client.post("/admin/role/save", data={"section": "rules", "reset": "1"})
check("إعادة الافتراضي تعيد نصوص الكود وتعليمات النظام وتُسجَّل",
      i18n.msg("out_of_scope", "ar") == role.DEFAULTS["refusal_ar"]
      and i18n.msg("out_of_scope", "en") == role.DEFAULTS["refusal_en"]
      and brain.system_prompt() == brain.SYSTEM_PROMPT
      and any(a["action"] == "role_reset" for a in store.audit_log(8))
      and any(a["action"] == "role_saved" and a.get("target") == "rules" for a in store.audit_log(20)))
# اسم بيان وأسلوب الردّ من الصفحة نفسها / The bot's name and the response style from the same page
r = client.post("/admin/role/save", follow_redirects=False,
                data={"section": "name", "name_ar": "نور", "name_en": "Noor"})
check("اسم البوت الجديد يدخل تعليمات النظام وعنوان اللوحة فوراً",
      "role_saved" in r.headers["location"] and "أنت «نور»" in brain.system_prompt()
      and "أنت «بيان»" in brain.SYSTEM_PROMPT and 'class="brand">Noor' in client.get("/admin?lang=en").text
      and 'class="brand">نور' in client.get("/admin?lang=ar").text, r.headers.get("location"))
check("الاسم الأطول من 40 حرفاً أو على سطرين يُرفض ولا يُحفظ",
      "error=role_name" in client.post("/admin/role/save", follow_redirects=False,
                                       data={"section": "name", "name_ar": "ن" * 41, "name_en": "Noor"}
                                       ).headers["location"]
      and "error=role_name" in client.post("/admin/role/save", follow_redirects=False,
                                           data={"section": "name", "name_ar": "نور", "name_en": "No\nor"}
                                           ).headers["location"]
      and config.BOT_NAME == "نور" and config.BOT_NAME_EN == "Noor")
r = client.post("/admin/role/save", follow_redirects=False,
                data={"section": "style", "tone": "friendly", "length": "short"})
live = brain.system_prompt()
check("النبرة الودودة والطول القصير يغيّران قسم «الأسلوب» في التعليمات الفعلية فقط",
      "role_saved" in r.headers["location"] and "بصيغة المخاطب" in live and "جملة إلى ثلاث جمل" in live
      and "من جملتين إلى ست" not in live and "بصيغة المخاطب" not in brain.SYSTEM_PROMPT
      and "من جملتين إلى ست" in brain.SYSTEM_PROMPT and live.count("## الأسلوب") == 1,
      r.headers.get("location"))
check("اختيار غير معروف في الأسلوب يُرفض",
      "error=role_choice" in client.post("/admin/role/save", follow_redirects=False,
                                         data={"section": "style", "tone": "shouting", "length": "short"}
                                         ).headers["location"]
      and config.RESPONSE_TONE == "friendly")
r = client.get("/admin/role?lang=en")
check("صفحة «دور بيان» تعرض القوائم بالاختيار المحفوظ والاسم في حقل سطر واحد",
      '<select id="tone" name="tone">' in r.text and '<option value="friendly" selected>' in r.text
      and '<option value="short" selected>' in r.text and '<option value="formal">' in r.text
      and 'name="name_en"' in r.text and 'value="Noor"' in r.text
      and r.text.count("Edited here") >= 4)
config.BOT_NAME, config.BOT_NAME_EN = "بيان", "Bayan"
config.RESPONSE_TONE, config.RESPONSE_LENGTH = "formal", "medium"
check("عند الإقلاع تُطبَّق الاسم والنبرة والطول المحفوظة فوق .env",
      role.apply_saved() == 4 and config.BOT_NAME == "نور" and config.BOT_NAME_EN == "Noor"
      and config.RESPONSE_TONE == "friendly" and config.RESPONSE_LENGTH == "short")
client.post("/admin/role/save", data={"section": "name", "reset": "1"})
client.post("/admin/role/save", data={"section": "style", "reset": "1"})
check("إعادة الافتراضي تعيد الاسم والأسلوب وتعليمات النظام الافتراضية",
      config.BOT_NAME == role.DEFAULTS["name_ar"] and config.RESPONSE_TONE == "formal"
      and config.RESPONSE_LENGTH == "medium" and brain.system_prompt() == brain.SYSTEM_PROMPT
      and 'class="brand">Bayan' in client.get("/admin?lang=en").text)
client.get("/admin?lang=ar")  # ?lang= يثبّت كوكي اللغة؛ نعيد العربية لما بعده / restores the Arabic cookie

# ── مصادر الفريق من اللوحة / Team sources from the dashboard ──
print("\n── مصادر الفريق ──")
import io  # noqa: E402
import zipfile  # noqa: E402
from app import sources  # noqa: E402

config.VOYAGE_API_KEY = "test"
embed.embed = fake_vectors
real_getaddrinfo = sources.socket.getaddrinfo


def fake_getaddrinfo(host, port, *a, **k):
    ip = {"localhost": "127.0.0.1", "127.0.0.1": "127.0.0.1", "10.0.0.5": "10.0.0.5",
          "192.168.1.1": "192.168.1.1", "169.254.1.1": "169.254.1.1"}.get(host, "93.184.216.34")
    return [(2, 1, 6, "", (ip, 0))]


sources.socket.getaddrinfo = fake_getaddrinfo
NOTE = ("سياسة باكس ميموريا في التحقق من الصور: نعتمد ثلاث خطوات، البحث العكسي ثم مقارنة "
        "المعالم ثم تحديد الوقت بالظلال. ") * 3
r = client.post("/admin/sources/note", data={"title": "سياسة التحقق من الصور", "text": NOTE},
                follow_redirects=False)
srcs = store.team_sources()
check("إضافة ملاحظة من اللوحة تُفهرس فوراً بمتجهاتها دون إعادة فهرسة كاملة",
      "msg=src_added" in r.headers["location"] and len(srcs) == 1 and srcs[0]["kind"] == "note"
      and store.counts().get("team", 0) >= 1 and store.embedded_count() == store.chunk_count(),
      (r.headers.get("location"), store.counts()))
note_id = srcs[0]["id"]
res = retrieve.search("ما سياسة التحقق من الصور بالظلال؟")
hit = [p for p in res["passages"] if p["type"] == "team"]
check("الاسترجاع يجد الملاحظة بعد إعادة التحميل التلقائي",
      hit and hit[0]["meta"]["source"] == "سياسة التحقق من الصور",
      [(p["type"], p["title"]) for p in res["passages"]])
ctx, urls = brain.build_context({**res, "passages": hit[:1], "corrections": [], "opportunities": [],
                                 "tools": [], "category_tools": [], "category": None}, "ar")
check("سياق الملاحظة بوسم مصدر_الفريق وعنوانها، وبلا رابط عام",
      ctx.startswith('<مصدر_الفريق رقم="1" العنوان="سياسة التحقق من الصور">')
      and "مستند أضافه فريق" in ctx and "(ملاحظة)" in ctx and urls[1] == "", ctx[:200])
check("موضوع السؤال «مصادر الفريق» بعنوان المستند",
      brain.topic_of({"passages": hit[:1], "tools": [], "category_tools": []}, "answered")
      == ("team", "سياسة التحقق من الصور") and "team" in brain.TOPICS
      and "<مصدر_الفريق>" in brain.SYSTEM_PROMPT)
r = client.post("/admin/sources/note", data={"title": "", "text": "قصير"}, follow_redirects=False)
check("ملاحظة بلا عنوان أو بنص قصير تُرفض", "error=text" in r.headers["location"])
check("المشاهد يقرأ الصفحة ولا يضيف",
      viewer.get("/admin/sources").status_code == 200
      and viewer.post("/admin/sources/note", data={"title": "x", "text": NOTE}).status_code == 403)
page_text = client.get("/admin/sources").text
check("الصفحة تعرض المصدر ونوعه وعدد مقاطعه ومن أضافه",
      "سياسة التحقق من الصور" in page_text and "ملاحظة" in page_text and "المالك" in page_text
      and "مصادر الفريق:" in client.get("/admin").text)

rejected = []
for bad in ("ftp://example.org/x", "http://localhost/x", "http://127.0.0.1/x", "http://10.0.0.5/x",
            "http://192.168.1.1/", "http://169.254.1.1/", "javascript:alert(1)", "http:///", "x"):
    try:
        sources.check_url(bad)
    except ValueError:
        rejected.append(bad)
check("الروابط المحلية والخاصة وغير http تُرفض قبل الجلب", len(rejected) == 9, rejected)

PAGE = {"text": ("<html><head><title>دليل التوثيق</title></head><body><nav>قائمة التنقّل</nav>"
                 "<main><h1>خطوات التوثيق</h1><p>" + "احفظ الصفحة بتاريخها وبصمتها الرقمية. " * 5
                 + "</p></main><footer>تذييل</footer></body></html>")}
def make_pdf(text: str) -> bytes:
    """ملف PDF صغير صحيح البنية (جدول xref محسوب) بصفحة فيها سطر نص.
    A small well-formed PDF (computed xref table) with one line of text."""
    body = f"BT /F1 18 Tf 20 100 Td ({text}) Tj ET".encode()
    objs = [b"<</Type/Catalog/Pages 2 0 R>>", b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 400 144]/Contents 4 0 R"
            b"/Resources<</Font<</F1 5 0 R>>>>>>",
            b"<</Length " + str(len(body)).encode() + b">>stream\n" + body + b"\nendstream",
            b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<</Size {len(objs) + 1}/Root 1 0 R>>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


PDF = make_pdf("Bayan PDF test document for the team sources page of the dashboard")


def fake_site(request):
    if request.url.path == "/redirect":
        return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
    if request.url.path == "/pdf":
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=PDF)
    return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text=PAGE["text"])


real_src_client = sources.httpx.Client
sources.httpx.Client = lambda **kw: real_src_client(transport=httpx.MockTransport(fake_site), **kw)
r = client.post("/admin/sources/url", data={"url": "http://docs.example.org/guide"}, follow_redirects=False)
u = [s for s in store.team_sources() if s["kind"] == "url"]
u_text = store.team_source(u[0]["id"])["text"] if u else ""
check("رابط صفحة يُجلب ويُستخرج نصه من <main> دون التنقّل والتذييل",
      "msg=src_added" in r.headers["location"] and u and u[0]["title"] == "دليل التوثيق"
      and "قائمة التنقّل" not in u_text and "تذييل" not in u_text
      and u_text.startswith("## خطوات التوثيق"), (r.headers.get("location"), u_text[:80]))
res = retrieve.search("كيف أحفظ الصفحة ببصمتها الرقمية؟")
hit = [p for p in res["passages"] if p["type"] == "team" and p["meta"].get("kind") == "url"]
_, urls = brain.build_context({**res, "passages": hit[:1], "corrections": [], "opportunities": [],
                               "tools": [], "category_tools": [], "category": None}, "ar")
check("سطر المصدر لرابط الفريق هو رابطه", hit and urls[1] == "http://docs.example.org/guide", urls)
r = client.post("/admin/sources/url", data={"url": "http://docs.example.org/redirect"}, follow_redirects=False)
check("تحويلة إلى عنوان محلي تُرفض", "error=url" in r.headers["location"] and len(store.team_sources()) == 2)
r = client.post("/admin/sources/url", data={"url": "http://docs.example.org/pdf"}, follow_redirects=False)
pdf_src = [s for s in store.team_sources() if s["origin"].endswith("/pdf")]
check("رابط PDF يُقرأ نصه", "msg=src_added" in r.headers["location"] and pdf_src
      and "Bayan PDF test document" in store.team_source(pdf_src[0]["id"])["text"],
      r.headers.get("location"))


def team_chunk_texts(source_id):
    with store.db() as conn:
        return [row["text"] for row in conn.execute(
            "SELECT text FROM chunks WHERE ext_id LIKE ?", (f"team:{source_id}:%",)).fetchall()]


PAGE["text"] = PAGE["text"].replace("احفظ الصفحة", "أرشف الصفحة")
r = client.post("/admin/sources/sync", data={"id": str(u[0]["id"])}, follow_redirects=False)
check("المزامنة تلتقط التغيير وتعيد فهرسة مقاطع المصدر وحده",
      "msg=src_synced" in r.headers["location"]
      and "أرشف الصفحة" in store.team_source(u[0]["id"])["text"]
      and all("أرشف" in t for t in team_chunk_texts(u[0]["id"])) and team_chunk_texts(note_id),
      r.headers.get("location"))
r = client.post("/admin/sources/sync", data={"id": str(u[0]["id"])}, follow_redirects=False)
check("بلا تغيير: لا إعادة فهرسة", "msg=src_same" in r.headers["location"])
sources.httpx.Client = lambda **kw: real_src_client(
    transport=httpx.MockTransport(lambda req: httpx.Response(503)), **kw)
n_chunks = len(team_chunk_texts(u[0]["id"]))
r = client.post("/admin/sources/sync", data={"id": str(u[0]["id"])}, follow_redirects=False)
check("تعذّر الجلب يُسجَّل في حال المصدر وتبقى مقاطعه",
      "error=fetch" in r.headers["location"] and store.team_source(u[0]["id"])["status"] == "error"
      and len(team_chunk_texts(u[0]["id"])) == n_chunks
      and "تعذّرت المزامنة" in client.get("/admin/sources").text)
check("sync_all يعدّ الروابط والمتعذّر منها",
      sources.sync_all() == {"changed": 0, "failed": 2, "total": 2}, sources.sync_all())
sources.httpx.Client = real_src_client

MD = ("# دليل الأرشفة\n\nالأرشفة تحفظ الصفحة كما كانت وقت التوثيق.\n\n" * 3).encode()
r = client.post("/admin/sources/file", files={"file": ("دليل الأرشفة.md", MD, "text/markdown")},
                follow_redirects=False)
f_md = [s for s in store.team_sources() if s["origin"] == "دليل الأرشفة.md"]
check("ملف Markdown يُرفع ويُحفظ نصه لا الملف، وعنوانه من اسمه",
      "msg=src_added" in r.headers["location"] and f_md and f_md[0]["title"] == "دليل الأرشفة"
      and store.team_source(f_md[0]["id"])["text"].startswith("## دليل الأرشفة"),
      r.headers.get("location"))
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("word/document.xml",
               '<w:document><w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>سياسة '
               'الاقتباس</w:t></w:r></w:p><w:p><w:r><w:t>ننقل الاقتباس كما ورد &amp; نذكر مصدره دائماً. '
               'ولا نحذف منه شيئاً.</w:t></w:r></w:p></w:body></w:document>')
r = client.post("/admin/sources/file", files={"file": ("policy.docx", buf.getvalue(),
                                                       "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
                follow_redirects=False)
f_docx = [s for s in store.team_sources() if s["origin"] == "policy.docx"]
check("ملف Word يُقرأ بعناوينه وفقراته",
      "msg=src_added" in r.headers["location"] and f_docx
      and store.team_source(f_docx[0]["id"])["text"] ==
      "## سياسة الاقتباس\n\nننقل الاقتباس كما ورد & نذكر مصدره دائماً. ولا نحذف منه شيئاً.",
      store.team_source(f_docx[0]["id"])["text"] if f_docx else r.headers.get("location"))
r = client.post("/admin/sources/file", files={"file": ("virus.exe", b"MZ" * 100, "application/octet-stream")},
                follow_redirects=False)
check("نوع ملف غير مدعوم يُرفض", "error=type" in r.headers["location"])
try:
    sources.extract("big.txt", b"a" * (sources.MAX_UPLOAD + 1))
    big_ok = False
except ValueError as exc:
    big_ok = str(exc) == "big"
check("ملف أكبر من الحدّ يُرفض", big_ok)
check("المشاهد لا يرفع ملفاً",
      viewer.post("/admin/sources/file", files={"file": ("a.md", MD, "text/markdown")}).status_code == 403)

n_team = store.counts().get("team", 0)
okk, detail = ingest.run(pull=False)
check("الفهرسة الكاملة تعيد مصادر الفريق من جدولها",
      okk and store.counts().get("team", 0) == n_team and "مصادر الفريق:" in detail, detail[-200:])
r = client.post("/admin/sources/delete", data={"id": str(note_id)}, follow_redirects=False)
check("الحذف يزيل المصدر ومقاطعه ويُسجَّل",
      "msg=src_deleted" in r.headers["location"] and store.team_source(note_id) is None
      and not team_chunk_texts(note_id)
      and any(a["action"] == "source_delete" for a in store.audit_log(5))
      and any(a["action"] == "source_add" and a.get("target") == f"note:{note_id}" for a in store.audit_log(40)))
sources.socket.getaddrinfo = real_getaddrinfo

# ── معاينة السيناريوهات في صفحة الدور / Scenario preview on the role page ──
print("\n── معاينة السيناريوهات ──")
r = client.get("/admin/role")
check("صفحة الدور تعرض نموذج المعاينة بكل السيناريوهات",
      "/admin/role/preview" in r.text and all(f'value="{s["key"]}"' in r.text for s in role.SCENARIOS)
      and "ولّد مثالاً" in r.text)
r = client.post("/admin/role/preview", data={"scenario": "greeting", "lang": "ar"})
check("معاينة التحية: رسالتان، ردّ التحية ثم الترحيب، بلا نموذج",
      r.status_code == 200 and "وعليكم السلام ورحمة الله وبركاته" in r.text
      and "ما أستطيع فعله" in r.text and "رسالة 2" in r.text, r.status_code)
r = client.post("/admin/role/preview", data={"scenario": "paused", "lang": "en"})
check("معاينة الإيقاف بالإنجليزية", r.status_code == 200 and "is paused for now" in r.text)
before_q = len(store.questions())
r = client.post("/admin/role/preview", data={"scenario": "out_of_scope", "lang": "ar"})
check("معاينة سؤال خارج النطاق تمرّ بالبوابة وتعرض نص الرفض ولا تُسجَّل",
      r.status_code == 200 and "أربعة أشياء" in r.text and "رفضته البوابة" in r.text
      and len(store.questions()) == before_q, r.status_code)
check("سيناريو غير معروف يُرفض، والمشاهد لا يعاين",
      "error=scen" in client.post("/admin/role/preview", data={"scenario": "x"},
                                  follow_redirects=False).headers["location"]
      and viewer.post("/admin/role/preview", data={"scenario": "greeting"}).status_code == 403)

# ── الدردشة على الموقع / The website chat ──
print("\n── الدردشة على الموقع ──")
from app import web  # noqa: E402

old_origins, old_pub = config.WEB_CHAT_ORIGINS, config.PUBLIC_URL
config.WEB_CHAT_ORIGINS = {"https://site.test", "https://www.site.test"}
config.PUBLIC_URL = "https://bayan.test"
store.set_setting("web_chat", "1")
web.reset_limits()
site = TestClient(server.app)
ORIGIN = {"Origin": "https://site.test"}
SID = "a1b2c3d4e5f6a7b8c9d0e1f2"

r = site.get("/widget.js")
check("widget.js يُقدَّم سكربتاً بنقطة الإرسال ونصوص اللغات كلها",
      r.status_code == 200 and r.headers["content-type"].startswith("application/javascript")
      and "__BAYAN_CONFIG__" not in r.text and "https://bayan.test/chat" in r.text
      and all(f'"{c}"' in r.text for c in i18n.SUPPORTED_LANGUAGES) and "</script" not in r.text,
      r.headers.get("content-type"))
check("الفقاعة ترتفع فوق شريط ثابت أسفل الصفحة (مثل شريط الكوكيز) ولا تغطّيه",
      "elementsFromPoint" in r.text and "--lift" in r.text and "var(--lift,0px)" in r.text)
cfg = web.widget_config()
check("نصوص الودجت بأسماء البوت والمنظمة لكل لغة، والعربية والفارسية والأردية من اليمين",
      config.BOT_NAME in cfg["strings"]["ar"]["intro"] and config.BOT_NAME_EN in cfg["strings"]["pt-BR"]["intro"]
      and "{" not in cfg["strings"]["fa"]["intro"] and set(cfg["rtl"]) == {"ar", "fa", "ur"}
      and cfg["privacy"] == "https://bayan.test/privacy",
      cfg["rtl"])
check("ملفات اللغات كلها فيها قسم الودجت بمفاتيح الإنجليزية نفسها",
      all(set(i18n.LOCALES[c]["widget"]) == set(i18n.LOCALES["en"]["widget"]) for c in i18n.SUPPORTED_LANGUAGES))

r = site.options("/chat", headers={**ORIGIN, "Access-Control-Request-Method": "POST"})
check("طلب CORS المسبق من موقع مسموح يُقبل برأسه",
      r.status_code == 204 and r.headers.get("access-control-allow-origin") == "https://site.test")
check("طلب CORS من موقع آخر يُرفض",
      site.options("/chat", headers={"Origin": "https://evil.test"}).status_code == 403)
check("سؤال بلا Origin أو من موقع آخر يُرفض",
      site.post("/chat", json={"session": SID, "message": "Olá"}).status_code == 403
      and site.post("/chat", json={"session": SID, "message": "Olá"},
                    headers={"Origin": "https://evil.test"}).status_code == 403)

r = site.post("/chat", json={"session": SID, "message": "Olá", "lang": "pt-BR"}, headers=ORIGIN)
msgs = r.json().get("messages", [])
check("تحية بالبرتغالية: ردّ التحية ثم الترحيب بلا أوامر القنوات، برأس CORS",
      r.status_code == 200 and len(msgs) == 2 and msgs[0] == "Olá 👋"
      and "/subscribe" not in msgs[1] and "/privacy" not in msgs[1]
      and r.headers.get("access-control-allow-origin") == "https://site.test", (r.status_code, msgs[:1]))
from app.channels import fmt as _fmt  # noqa: E402
_w = _fmt.to_web("- **عنوان:** نص التفصيل\n## قسم")
check("الخط العريض يبقى **نص** للودجت والعنوان في سطره، بلا علامات اتجاه",
      "**عنوان**\nنص التفصيل" in _w and "**قسم**" in _w and "\u200f" not in _w
      and "\u200f" not in "".join(msgs), _w)
check("معرّف محادثة غير صالح أو سؤال فارغ يُرفض",
      site.post("/chat", json={"session": "short", "message": "hi"}, headers=ORIGIN).status_code == 400
      and site.post("/chat", json={"session": SID, "message": "  "}, headers=ORIGIN).status_code == 400
      and site.post("/chat", content=b"not json", headers={**ORIGIN, "Content-Type": "application/json"}).status_code == 400)
long_q = "س" * (config.MAX_QUESTION_CHARS + 200)
site.post("/chat", json={"session": SID + "x", "message": long_q}, headers=ORIGIN)
web_q = [q for q in store.questions() if q.get("channel") == "web"]
check("أسئلة الموقع تُسجَّل على قناة web بمعرّف المحادثة، والطويل يُقصّ",
      web_q and all(len(q["content"]) <= config.MAX_QUESTION_CHARS for q in web_q), len(web_q))
check("قناة الموقع في اللوحة: اسمها في الأسئلة وحالها وزرّها في الإعدادات",
      "Website" in client.get("/admin/messages?lang=en&channel=web").text
      and 'name="web_chat"' in client.get("/admin/settings?lang=en").text
      and "/widget.js" in client.get("/admin/settings?lang=en").text)

web.reset_limits()
old_burst = config.WEB_IP_BURST
config.WEB_IP_BURST = 3
codes = [site.post("/chat", json={"session": SID, "message": "Hello"}, headers=ORIGIN).status_code
         for _ in range(4)]
r = site.post("/chat", json={"session": SID, "message": "Hola"}, headers=ORIGIN)
check("حدّ العنوان: الرابع يُرفض بـ 429 ورسالة الحدّ بلغة السائل",
      codes == [200, 200, 200, 429] and r.status_code == 429
      and r.json()["messages"] == [i18n.msg("rate", "es")], (codes, r.json()))
config.WEB_IP_BURST = old_burst
web.reset_limits()
check("العنوان من X-Forwarded-For (آخره) خلف وكيل محلي فقط",
      web.client_ip("172.17.0.1", "1.2.3.4, 5.6.7.8") == "5.6.7.8"
      and web.client_ip("127.0.0.1", "9.9.9.9") == "9.9.9.9"
      and web.client_ip("8.8.4.4", "1.2.3.4") == "8.8.4.4")
t0 = 1_000_000.0
config.WEB_IP_DAILY, old_daily = 2, config.WEB_IP_DAILY
check("الحدّ اليومي للعنوان في الذاكرة، ويُفتح بعد 24 ساعة",
      web.ip_allowed("8.8.8.8", t0) and web.ip_allowed("8.8.8.8", t0 + 700)
      and not web.ip_allowed("8.8.8.8", t0 + 1400) and web.ip_allowed("8.8.8.8", t0 + 86400 + 800))
config.WEB_IP_DAILY = old_daily
web.reset_limits()

store.set_setting("web_chat", "0")
r = site.post("/chat", json={"session": SID, "message": "Hello"}, headers=ORIGIN)
check("القناة مطفأة من اللوحة: الودجت فارغ والأسئلة ترفض بـ 503",
      r.status_code == 503 and "switched off" in site.get("/widget.js").text
      and "__bayanChat" not in site.get("/widget.js").text)
store.set_setting("web_chat", "1")
check("WEB_CHAT_ORIGINS الافتراضي من SITE_URL ونسخة www، و none يعطّل",
      config._web_origins() == {config.SITE_URL.rstrip("/"),
                                config.SITE_URL.rstrip("/").replace("://", "://www.", 1)}
      or config.SITE_URL.startswith("https://www."))
os.environ["WEB_CHAT_ORIGINS"] = "none"
check("قيمة none تعطّل القناة", config._web_origins() == set())
os.environ.pop("WEB_CHAT_ORIGINS")

print("\n── لغة الودجت حسب البلد ──")
from app import geo  # noqa: E402


class _FakeGeo:
    TABLE = {"5.0.0.1": "BR", "5.0.0.2": "SY", "5.0.0.3": "SE", "5.0.0.4": "KE"}

    def get(self, ip):
        cc = self.TABLE.get(ip)
        return {"country": {"iso_code": cc}} if cc else None

    def close(self):
        pass


old_reader = geo._reader
geo._reader = _FakeGeo()
check("البلد ← اللغة: البرازيل برتغالية، سوريا عربية، كينيا سواحلية، السويد بلا لغة",
      geo.language("5.0.0.1") == "pt-BR" and geo.language("5.0.0.2") == "ar"
      and geo.language("5.0.0.4") == "sw" and geo.language("5.0.0.3") is None)
check("عنوان خاص أو غير صالح بلا بلد", geo.country("10.0.0.5") is None and geo.country("nope") is None)
check("كل لغة في جدول البلدان لغة مدعومة",
      set(geo.COUNTRY_LANG.values()) <= set(i18n.SUPPORTED_LANGUAGES))
# عميل الاختبار ليس وكيلاً محلياً، فيُؤخذ العنوان من الترويسة هنا
# The test client is not a local proxy, so the address comes from the header here
real_client_ip = web.client_ip
web.client_ip = lambda host, xff: xff or "?"
r = site.get("/lang", headers={**ORIGIN, "X-Forwarded-For": "5.0.0.1"})
check("/lang يعيد لغة البلد بلا تخزين مؤقت وبـ CORS",
      r.status_code == 200 and r.json() == {"lang": "pt-BR"}
      and r.headers.get("access-control-allow-origin") == "https://site.test"
      and "no-store" in r.headers.get("cache-control", ""), r.text)
check("/lang يرفض موقعاً غير مسموح",
      site.get("/lang", headers={"Origin": "https://evil.test"}).status_code == 403)
r = site.get("/lang", headers={**ORIGIN, "X-Forwarded-For": "5.0.0.3"})
check("بلد بلا لغة هنا: null فتبقى لغة الصفحة", r.json() == {"lang": None})
web.client_ip = real_client_ip
before = len(store.questions_since("web", "geo-none", time.time() - 86400))
check("/lang لا يُحفظ سؤالاً", before == 0)
w = site.get("/widget.js").text
check("الودجت يطلب لغة البلد ويقدّم لغة الصفحة إن غيّرها الزائر",
      "https://bayan.test/lang" in w and "geoLang" in w and "pageTouched = true" in w)
config.GEO_LANG = False
check("GEO_LANG=0 يطفئ اللغة حسب البلد",
      geo.language("5.0.0.1") is None and '"geo": ""' in site.get("/widget.js").text)
config.GEO_LANG = True
check("أشهر التنزيل: الحالي ثم السابق، ويناير يعود إلى ديسمبر",
      geo._months(__import__("datetime").date(2027, 1, 3)) == ["2027-01", "2026-12"])
check("بلا ملف القاعدة: لا لغة ولا خطأ", (lambda: (setattr(geo, "_reader", None), geo.language("5.0.0.1"))[1])() is None)
geo._reader = old_reader
config.WEB_CHAT_ORIGINS, config.PUBLIC_URL = old_origins, old_pub

embed.embed = real_embed
print(f"\nالنتيجة: {ok}/{ok + fail}")
sys.exit(0 if fail == 0 else 1)
