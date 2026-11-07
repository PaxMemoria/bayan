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
r = client.get("/admin")
check("نظرة عامة تعمل", r.status_code == 200 and "نظرة عامة" in r.text)
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
check("قيمة لغة غير معروفة لا تُقبل", 'dir="rtl"' in client.get("/admin?lang=fr").text)

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
      all("الحدّ المسموح" not in r for r in replies[:3]))
check("الرابع يتلقى رسالة الحدّ ومتى يعود",
      "الحدّ المسموح، وهو 3" in replies[3] and "بعد" in replies[3], replies[3])
check("رسالة الحدّ لا تُحسب سؤالاً",
      len(store.questions_since("telegram", "u-limit", time.time() - 86400)) == 3)
check("/start يعمل بعد بلوغ الحدّ",
      brain.handle("/start", "telegram", "u-limit") == i18n.welcome(None, brain.daily_limit()))
check("مستخدم آخر لا يتأثر", "الحدّ المسموح" not in brain.handle("سؤال", "telegram", "u-other"))
check("المعرّف نفسه في قناة أخرى لا يتأثر",
      "الحدّ المسموح" not in brain.handle("سؤال", "whatsapp", "u-limit"))
store.set_setting("daily_limit", "0")
check("0 يعني بلا حدّ", "الحدّ المسموح" not in brain.handle("سؤال", "telegram", "u-limit"))
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
check("الترحيب يذكر الحدّ اليومي كما في اللوحة",
      f"حدّ الأسئلة: {brain.daily_limit()} في كل 24 ساعة" in w_ar)
before = len(store.questions_since("whatsapp", "u-greet", time.time() - 86400))
g_ar = brain.handle("مرحباً!", "whatsapp", "u-greet")
g_en = brain.handle("Hello 👋", "whatsapp", "u-greet")
check("تحية عربية: ترحيب بالعربية", "أهلاً" in g_ar and "Hello" not in g_ar)
check("تحية إنجليزية: ترحيب بالإنجليزية", "Hello" in g_en and "أهلاً" not in g_en)
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
check("رسالة الحدّ اليومي بلغة السائل",
      "You have reached the limit of 1" in brain.handle("And for videos?", "telegram", "u-en-limit"))
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
check("سؤال بلا علاقة بالفرص لا يُغيَّر", first("ما أدوات تتبع الطيران؟") is None)
for i in (w1, w2, w3, old):
    store.delete_correction(i)
config.VOYAGE_API_KEY = ""

ctx, urls = brain.build_context(
    {"tools": [], "category": None, "category_tools": [],
     "passages": [{"type": "tool", "url": "u", "meta": {},
                   "text": "الأداة: X\nدرجة التحقق في تدقيق OTVS: direct"}]}, "ar")
check("رمز درجة التحقق الخام يُستبدل بصياغته",
      "direct" not in ctx and "روجِعت بدليل مباشر" in ctx, ctx)
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
with store.db() as c:
    check("الحذف الآمن مفعّل في القاعدة", c.execute("PRAGMA secure_delete").fetchone()[0] == 1)

store.set_setting("daily_limit", "2")
brain.handle("سؤال أول عن أداة", "telegram", "u-reset")
brain.handle("سؤال ثانٍ عن أداة", "telegram", "u-reset")
brain.handle("/reset", "telegram", "u-reset")
brain.handle("/start", "telegram", "u-reset")
check("حذف المحادثة لا يلغي حدّ الأسئلة اليومي",
      "الحدّ المسموح" in brain.handle("سؤال ثالث", "telegram", "u-reset"))
store.set_setting("daily_limit", "10")

pv = brain.handle("الخصوصية", "telegram", "u-p")
check("«الخصوصية» تعيد الرابط ومدة الحفظ بالعربية",
      "/privacy" in pv and "30 يوماً" in pv and "privacy policy" not in pv, pv)
check("/privacy بواجهة إنجليزية بالإنجليزية",
      "Bayan's privacy policy" in brain.handle("/privacy", "telegram", "u-p", "en"))
check("الترحيب يذكر سياسة الخصوصية", "/privacy" in brain.handle("/start", "telegram", "u-p", "ar"))

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

embed.embed = real_embed
print(f"\nالنتيجة: {ok}/{ok + fail}")
sys.exit(0 if fail == 0 else 1)
