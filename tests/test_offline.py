"""اختبارات لا تحتاج مستودع الموقع ولا أي مفتاح.  التشغيل: python tests/test_offline.py

تبني فهرساً صغيراً في مجلد مؤقت، وتحاكي Voyage، وتختبر ما يحمي بيان حين
يُضاف المفتاح أو يتعطّل، ثم أمان اللوحة.
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
    "VOYAGE_API_KEY": "", "ANTHROPIC_API_KEY": "", "ADMIN_PASSWORD": "",
    "SESSION_SECRET": "", "TELEGRAM_WEBHOOK_SECRET": "", "PUBLIC_URL": "",
})
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import brain, config, embed, ingest, retrieve, store  # noqa: E402
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
]
CHUNKS = [
    {"id": "tool:0", "type": "tool", "title": "Hunchly", "url": "https://paxmemoria.org/osint-tools",
     "text": "الأداة: Hunchly\nتوثّق كل صفحة تزورها أثناء البحث مع التوقيت."},
    {"id": "tool-removed:0", "type": "tool_removed", "title": "Discord Multi-Tool",
     "url": "https://paxmemoria.org/osint-tools",
     "text": "الأداة: Discord Multi-Tool\nأُزيلت.\nنطاقها السابق (لا يُفتح): github.com/AstraaDev"},
    {"id": "inv:x:0", "type": "investigation", "title": "تحقيق السيول",
     "url": "https://paxmemoria.org/investigations/x",
     "text": "كشفت صور الأقمار الصناعية حجم السيول في محافظة الحديدة اليمنية."},
]
pathlib.Path(os.environ["TOOLS_PATH"]).write_text(json.dumps(TOOLS, ensure_ascii=False))
pathlib.Path(os.environ["KNOWLEDGE_PATH"]).write_text(
    "\n".join(json.dumps(c, ensure_ascii=False) for c in CHUNKS))


def fake_vectors(texts, input_type="document", retries=6):
    """متجهات حتمية من كلمات النص: تكفي لاختبار المسار لا لجودته."""
    out = []
    for t in texts:
        v = [0.0] * config.EMBED_DIM
        for w in t.split():
            v[hash(w) % config.EMBED_DIM] += 1.0
        out.append(v)
    return out


real_embed = embed.embed

# ── ٠. المزوّد المحلي: ما يمنعه من العمل يُعلَن بسببه ────────────────
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
config.EMBED_PROVIDER, config.EMBED_MODEL = "voyage", "voyage-4"

# ── ١. Voyage: إعادة المحاولة ورسالة حساب بلا وسيلة دفع ─────────────
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
embed.time.sleep = real_sleep

# ── ٢. الفهرسة: الفشل لا يمسح الفهرس ──────────────────────────────
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
r = retrieve.search("كيف تبدو السيول في اليمن من الفضاء؟")
check("البحث يعيد التحميل تلقائياً ويستعمل المتجهات", r["used_vectors"],
      retrieve.status())

# ── ٣. المتجهات: تعطّل Voyage وتغيّر النموذج ──────────────────────
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

# ── ٤. الطبقة ٤ على فهرس الاختبار ─────────────────────────────────
print("\n── مرشّح الروابط ──")
t, n = brain.strip_forbidden("حمّلها من github.com/AstraaDev/tool أو https://cse.google.com/cse.")
check("نطاق مُزال ورابط حسّاس يُحذفان", n == 2 and "AstraaDev" not in t and "cse.google" not in t, t)
t, n = brain.strip_forbidden("ابحث عبر https://cse.google.com/cse?cx=123:abc")
check("رابط عادي يشترك في البادئة يبقى", n == 0, t)

# ── ٥. اللوحة ────────────────────────────────────────────────────
print("\n── اللوحة ──")
# المتجهات المزيّفة تقرّب أي سؤال من أي مقطع، فتُطفأ هنا ليبقى رفض البوابة حتمياً
config.VOYAGE_API_KEY = ""
retrieve.warm()
client = TestClient(server.app)
r = client.get("/admin", follow_redirects=False)
check("بلا كلمة مرور: اللوحة معطّلة", r.status_code == 503)

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
store.remember("whatsapp", "966500000001", "user", "<script>alert(1)</script> ما أدوات Hunchly؟",
               outcome="refused_gate", confidence=0.21, sources=[])
store.remember("whatsapp", "966500000001", "assistant", "رد <b>تجريبي</b>")

r = client.post("/admin/login", data={"password": "correct horse battery"}, follow_redirects=False)
check("كلمة المرور الصحيحة تفتح جلسة", r.status_code == 303 and "bayan_admin" in r.cookies)
r = client.get("/admin")
check("نظرة عامة تعمل", r.status_code == 200 and "نظرة عامة" in r.text)
check("ترويسة CSP تمنع كل سكربت", "default-src 'none'" in r.headers.get("content-security-policy", ""))
r = client.get("/admin/messages")
check("الأسئلة تُعرض", "ما أدوات Hunchly" in r.text)
check("نص الجمهور مُهرَّب", "<script>alert" not in r.text and "&lt;script&gt;" in r.text)
check("رقم الهاتف لا يظهر في اللوحة", "966500000001" not in r.text)
check("/admin/status بعد الدخول يعمل", client.get("/admin/status").status_code == 200)

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

# ── ٥ب. حدّ الأسئلة اليومي ───────────────────────────────────────
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
      brain.handle("/start", "telegram", "u-limit") == config.WELCOME_MESSAGE)
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

# ── ٦. الفهرسة في الخلفية ────────────────────────────────────────
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

# ── ٧. عزل مُستخرِج الموقع ───────────────────────────────────────
print("\n── عزل المُستخرِج ──")
import shutil  # noqa: E402

if shutil.which("node"):
    site = TMP / "hostile-site"
    (site / "scripts").mkdir(parents=True)
    # مُستخرِج «معادٍ»: يحاول ما قد يحاوله تعديل خبيث في مستودع الموقع
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

# ── ٨. تيليغرام ──────────────────────────────────────────────────
print("\n── تيليغرام ──")
upd = {"update_id": 1, "message": {"chat": {"id": 5}, "text": "مرحبا"}}
check("بلا TELEGRAM_WEBHOOK_SECRET يُرفض كل تحديث",
      client.post("/webhooks/telegram", json=upd).status_code == 500)
config.TELEGRAM_WEBHOOK_SECRET = "tg-secret"
check("سرّ خاطئ يُرفض", client.post(
    "/webhooks/telegram", json=upd,
    headers={"X-Telegram-Bot-Api-Secret-Token": "nope"}).status_code == 403)

embed.embed = real_embed
print(f"\nالنتيجة: {ok}/{ok + fail}")
sys.exit(0 if fail == 0 else 1)
