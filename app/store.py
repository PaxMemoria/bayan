"""طبقة التخزين: SQLite واحدة تحمل المعرفة والأدوات والمحادثات.

The storage layer: one SQLite database that holds the knowledge, the tools
and the conversations.
"""
import json
import sqlite3
import time
from contextlib import contextmanager

import numpy as np

from . import config
from .arabic import normalize_ar

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ext_id    TEXT,
    type      TEXT NOT NULL,          -- tool | tool_removed | investigation
    title     TEXT,
    url       TEXT NOT NULL,
    text      TEXT NOT NULL,
    norm_text TEXT NOT NULL,
    meta      TEXT NOT NULL DEFAULT '{}',
    embedding BLOB
);
CREATE INDEX IF NOT EXISTS idx_chunks_type ON chunks(type);

-- الأدوات قاعدة بيانات لا نصوص: تُستعلَم بالتصنيف والاسم مباشرة،
-- إلى جانب وجودها في chunks للبحث الدلالي.
CREATE TABLE IF NOT EXISTS tools (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    norm_name     TEXT NOT NULL,
    category_ar   TEXT,
    category_en   TEXT,
    norm_category TEXT,
    summary_ar    TEXT,
    summary_en    TEXT,
    link          TEXT,
    domain        TEXT,
    verification  TEXT,
    sensitive     INTEGER NOT NULL DEFAULT 0,
    caution       TEXT,
    removed       INTEGER NOT NULL DEFAULT 0,
    removal_type_ar   TEXT,
    removal_reason_ar TEXT,
    removal_date  TEXT,
    replacement   TEXT,
    url           TEXT
);
CREATE INDEX IF NOT EXISTS idx_tools_cat ON tools(norm_category);
CREATE INDEX IF NOT EXISTS idx_tools_name ON tools(norm_name);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    channel    TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    -- حقول التشخيص التي تغذّي لوحة بيان
    outcome    TEXT,      -- answered | refused_gate | refused_model | tool_list
    confidence REAL,
    sources    TEXT,
    topic      TEXT,      -- الجزء الذي أُجيب منه / the part answered from (brain.TOPICS)
    detail     TEXT,      -- تفصيله: slug تحقيق أو تصنيف أدوات / its detail: an investigation slug or a tool category
    ts         REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(channel, user_id, ts);
CREATE INDEX IF NOT EXISTS idx_messages_outcome ON messages(outcome, ts);
CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(ts);

CREATE TABLE IF NOT EXISTS hits (
    channel TEXT NOT NULL,
    user_id TEXT NOT NULL,
    ts      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hits ON hits(channel, user_id, ts);

CREATE TABLE IF NOT EXISTS blocked (
    channel TEXT NOT NULL,
    user_id TEXT NOT NULL,
    reason  TEXT,
    ts      REAL NOT NULL,
    PRIMARY KEY (channel, user_id)
);

-- أوقات الأسئلة لحدّ الأسئلة اليومي، منفصلة عن المحادثة كي لا يلغي حذفُ
-- المحادثة (/reset) الحدَّ. تُحذف بعد 24 ساعة.
-- Question times for the daily limit, kept apart from the conversation so
-- deleting it (/reset) does not reset the limit. Deleted after 24 hours.
CREATE TABLE IF NOT EXISTS asked (
    channel TEXT NOT NULL,
    user_id TEXT NOT NULL,
    ts      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_asked ON asked(channel, user_id, ts);

-- الفرص: بند لكل فرصة، موزّعة بالأسابيع، وتبقى بعد كل فهرسة (ليست في chunks).
-- Opportunities: one row each, split by week, kept across reindexing (not in chunks).
CREATE TABLE IF NOT EXISTS opportunities (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    year     INTEGER NOT NULL,
    week     INTEGER NOT NULL,       -- رقم أسبوع ISO / ISO week number
    position INTEGER NOT NULL,       -- ترتيبها في القائمة / order in the list
    title    TEXT NOT NULL,
    url      TEXT NOT NULL,
    UNIQUE (year, week, position)
);

-- أعداد الاستخدام اليومية فقط: لا نصوص ولا معرّفات. تبقى بعد حذف الرسائل.
-- Daily usage counts only: no text and no identifiers. They outlive the messages.
CREATE TABLE IF NOT EXISTS usage_daily (
    day       TEXT NOT NULL,      -- YYYY-MM-DD (UTC)
    channel   TEXT NOT NULL,
    questions INTEGER NOT NULL,
    users     INTEGER NOT NULL,   -- مستخدمون مختلفون في ذلك اليوم / distinct users that day
    PRIMARY KEY (day, channel)
);

-- مواضيع الأسئلة اليومية، أعداد فقط بلا نصوص ولا معرّفات. تبقى بعد حذف الرسائل.
-- Daily question topics, counts only with no text and no identifiers. They outlive the messages.
CREATE TABLE IF NOT EXISTS topic_daily (
    day       TEXT NOT NULL,
    topic     TEXT NOT NULL,
    detail    TEXT NOT NULL DEFAULT '',
    questions INTEGER NOT NULL,
    PRIMARY KEY (day, topic, detail)
);

-- المشتركون في قائمة الفرص الأسبوعية: معرّف القناة ووقت الاشتراك، حتى يُلغى.
-- Subscribers to the weekly opportunities list: the channel identifier and the
-- time of subscribing, until they unsubscribe.
CREATE TABLE IF NOT EXISTS subscribers (
    channel TEXT NOT NULL,
    user_id TEXT NOT NULL,
    ts      REAL NOT NULL,
    PRIMARY KEY (channel, user_id)
);

-- الفريق: من يدخل اللوحة بحساب Google من النطاق، ودوره. لا كلمات مرور هنا.
-- The team: who signs in to the dashboard with a Google account from the
-- domain, and their role. No passwords here.
CREATE TABLE IF NOT EXISTS members (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    email      TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL DEFAULT '',
    role       TEXT NOT NULL,          -- admin | editor | viewer
    active     INTEGER NOT NULL DEFAULT 1,
    created    REAL NOT NULL,
    last_login REAL
);

-- سجلّ إجراءات الفريق في اللوحة: من فعل ماذا ومتى. لا نصوص أسئلة ولا معرّفات جمهور.
-- The team's actions in the dashboard: who did what, when. No question text
-- and no audience identifiers.
CREATE TABLE IF NOT EXISTS audit (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts     REAL NOT NULL,
    member TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT
);

CREATE TABLE IF NOT EXISTS seen_events (
    event_id TEXT PRIMARY KEY,
    ts       REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS ingest_runs (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    started  REAL NOT NULL,
    finished REAL,
    ok       INTEGER,
    chunks   INTEGER,
    tools    INTEGER,
    detail   TEXT
);

-- إعدادات قابلة للتحرير من اللوحة دون إعادة تشغيل الخادم.
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- مفاتيح API المحفوظة من اللوحة (app/keys.py): تتقدّم على .env. القيمة لا تُعرض.
-- API keys saved from the dashboard (app/keys.py): they take precedence over
-- .env. The value is never displayed.
CREATE TABLE IF NOT EXISTS api_keys (
    name    TEXT PRIMARY KEY,
    value   TEXT NOT NULL,
    updated REAL NOT NULL,
    by      TEXT
);

-- مصادر الفريق (app/sources.py): ملاحظات وروابط وملفات يضيفها الفريق من اللوحة.
-- يُحفظ النص المستخرَج لا الملف، وتُبنى منه مقاطع من نوع team في الفهرس.
-- Team sources (app/sources.py): notes, links and files the team adds from
-- the dashboard. The extracted text is kept, not the file, and chunks of
-- type team are built from it in the index.
CREATE TABLE IF NOT EXISTS team_sources (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    kind     TEXT NOT NULL,            -- note | url | file
    title    TEXT NOT NULL,
    origin   TEXT NOT NULL DEFAULT '', -- الرابط أو اسم الملف / the URL or the file name
    text     TEXT NOT NULL,
    status   TEXT NOT NULL DEFAULT 'ok',
    error    TEXT NOT NULL DEFAULT '',
    added_by TEXT NOT NULL DEFAULT '',
    added    REAL NOT NULL,
    synced   REAL NOT NULL
);

-- تقييم الفريق لإجابة بيان على سؤال، برقم رسالة السؤال. يُحذف مع الرسالة.
-- The team's rating of Bayan's answer to a question, keyed by the question's
-- message number. Deleted together with the message.
CREATE TABLE IF NOT EXISTS ratings (
    message_id INTEGER PRIMARY KEY,
    rating     INTEGER NOT NULL,   -- 1 جيدة / good، -1 تحتاج تصحيحاً / needs fixing
    reason     TEXT,
    note       TEXT,
    ts         REAL NOT NULL
);

-- إجابات معتمدة يكتبها الفريق بكلماته. لا تحوي معرّف مستخدم، ولا تُحذف مع
-- الرسائل ولا مع إعادة الفهرسة. embedding متجه السؤال، و embed_model النموذج
-- الذي ولّده.
-- Approved answers the team writes in its own words. They hold no user ID,
-- and are deleted neither with the messages nor by reindexing. embedding is
-- the question's vector, and embed_model the model that produced it.
CREATE TABLE IF NOT EXISTS corrections (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    question    TEXT NOT NULL,
    norm_question TEXT NOT NULL,
    answer      TEXT NOT NULL,
    url         TEXT,
    active      INTEGER NOT NULL DEFAULT 1,
    embedding   BLOB,
    embed_model TEXT,
    created     REAL NOT NULL,
    updated     REAL NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
    USING fts5(norm_text, content='', tokenize="unicode61 remove_diacritics 2");
"""


@contextmanager
def db():
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    # المحذوف يُكتب فوقه أصفاراً، فلا يبقى نص سؤال محذوف في ملف القاعدة
    # Deleted content is overwritten with zeros, so a deleted question's text
    # does not linger in the database file
    conn.execute("PRAGMA secure_delete=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def _migrate(conn) -> None:
    """أعمدة أُضيفت بعد إنشاء القاعدة: CREATE TABLE IF NOT EXISTS لا يضيفها لجدول قائم.
    Columns added after the database was created: CREATE TABLE IF NOT EXISTS does
    not add them to an existing table."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()}
    for col in ("topic", "detail", "retrieval"):
        if col not in cols:
            conn.execute(f"ALTER TABLE messages ADD COLUMN {col} TEXT")
    for table in ("corrections", "ratings"):
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if "author" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN author TEXT")


# ──────────────────────────────────────────────────── الفهرسة / Indexing
TOOL_COLS = (
    "name", "norm_name", "category_ar", "category_en", "norm_category",
    "summary_ar", "summary_en", "link", "domain", "verification",
    "sensitive", "caution", "removed", "removal_type_ar",
    "removal_reason_ar", "removal_date", "replacement", "url",
)


def replace_index(tools: list[dict], chunks: list[dict], embed_model: str) -> None:
    """يستبدل الفهرس كله في معاملة واحدة.

    إن فشل أي جزء يبقى الفهرس السابق كما هو: إعادة فهرسة فاشلة لا تترك
    بيان بقاعدة معرفة فارغة. المعرّفات لا يُعاد ترقيمها، فمقطع من فهرس
    قديم ما زال في ذاكرة عملية أخرى لا يشير خطأً إلى مقطع جديد.

    Replace the whole index in a single transaction.

    If any part fails, the previous index stays as it was: a failed reindex
    does not leave Bayan with an empty knowledge base. IDs are not
    renumbered, so a passage from an old index that is still in another
    process's memory does not point by mistake to a new passage.
    """
    marks = ",".join("?" * len(TOOL_COLS))
    with db() as conn:
        conn.execute("DELETE FROM chunks")
        conn.execute("DELETE FROM tools")
        conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('delete-all')")
        conn.executemany(
            f"INSERT INTO tools({','.join(TOOL_COLS)}) VALUES({marks})",
            [tuple(r.get(c) for c in TOOL_COLS) for r in tools],
        )
        for r in chunks:
            emb = r.get("embedding")
            blob = np.asarray(emb, dtype=np.float32).tobytes() if emb is not None else None
            cur = conn.execute(
                "INSERT INTO chunks(ext_id,type,title,url,text,norm_text,meta,embedding) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    r.get("ext_id"), r["type"], r.get("title"), r["url"],
                    r["text"], r["norm_text"],
                    json.dumps(r.get("meta", {}), ensure_ascii=False), blob,
                ),
            )
            conn.execute(
                "INSERT INTO chunks_fts(rowid, norm_text) VALUES(?,?)",
                (cur.lastrowid, r["norm_text"]),
            )
        # كل عملية (الخادم، أو فهرسة من سطر الأوامر) تقارن هذا الرقم بما
        # حمّلته في ذاكرتها، فتعيد التحميل دون إعادة تشغيل.
        # Every process (the server, or indexing from the command line) compares
        # this number with what it loaded into memory, so it reloads without a
        # restart.
        for key, value in (("index_version", repr(time.time())),
                           ("index_embed_model", embed_model)):
            conn.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )


def index_version() -> str:
    return setting("index_version", "")


def counts() -> dict:
    with db() as conn:
        rows = conn.execute(
            "SELECT type, COUNT(*) c FROM chunks GROUP BY type"
        ).fetchall()
        tools = conn.execute(
            "SELECT COUNT(*) c, SUM(removed) r, SUM(sensitive) s FROM tools"
        ).fetchone()
    out = {r["type"]: r["c"] for r in rows}
    out["_chunks"] = sum(out.values())
    out["_tools"] = tools["c"] or 0
    out["_tools_removed"] = tools["r"] or 0
    out["_tools_sensitive"] = tools["s"] or 0
    return out


def chunk_count() -> int:
    with db() as conn:
        return conn.execute("SELECT COUNT(*) c FROM chunks").fetchone()["c"]


def embedded_count() -> int:
    with db() as conn:
        return conn.execute(
            "SELECT COUNT(*) c FROM chunks WHERE embedding IS NOT NULL"
        ).fetchone()["c"]


def load_embeddings() -> tuple[np.ndarray, list[int]]:
    with db() as conn:
        rows = conn.execute(
            "SELECT id, embedding FROM chunks WHERE embedding IS NOT NULL ORDER BY id"
        ).fetchall()
    if not rows:
        return np.zeros((0, config.EMBED_DIM), dtype=np.float32), []
    ids = [r["id"] for r in rows]
    mat = np.vstack(
        [np.frombuffer(r["embedding"], dtype=np.float32) for r in rows]
    ).astype(np.float32)
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms, ids


def get_chunks(ids: list[int]) -> dict[int, dict]:
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    with db() as conn:
        rows = conn.execute(
            f"SELECT id,type,title,url,text,meta FROM chunks WHERE id IN ({marks})", ids
        ).fetchall()
    return {
        r["id"]: {
            "id": r["id"], "type": r["type"], "title": r["title"],
            "url": r["url"], "text": r["text"], "meta": json.loads(r["meta"]),
        }
        for r in rows
    }


# ──────────────────────────────────────── الأدوات: بحث منظّم / Tools: structured search
def categories() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT category_ar, category_en, norm_category, COUNT(*) n "
            "FROM tools WHERE removed=0 AND category_ar IS NOT NULL "
            "GROUP BY norm_category ORDER BY n DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def tools_in_category(norm_category: str, limit: int) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM tools WHERE norm_category=? AND removed=0 "
            "ORDER BY (verification='direct') DESC, sensitive ASC, name LIMIT ?",
            (norm_category, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def tool_by_name(norm_name: str) -> dict | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM tools WHERE norm_name=? ORDER BY removed ASC LIMIT 1",
            (norm_name,),
        ).fetchone()
    return dict(row) if row else None


def tools_name_like(fragment: str, limit: int = 5) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM tools WHERE norm_name LIKE ? ORDER BY removed ASC, "
            "LENGTH(norm_name) LIMIT ?",
            (f"%{fragment}%", limit),
        ).fetchall()
    return [dict(r) for r in rows]


def link_rules() -> tuple[list[str], list[str]]:
    """(روابط ونطاقات ممنوعة، روابط مسموحة) لكل أدوات الدليل.

    الممنوع: رابط أو نطاق كل أداة حسّاسة أو مُزالة. المسموح: روابط
    الأدوات العادية، ليُستثنى منها ما يشترك في بادئة مع رابط ممنوع.

    (banned links and domains, allowed links) for every tool in the guide.

    Banned: the link or domain of every sensitive or removed tool. Allowed:
    the links of ordinary tools, so that those sharing a prefix with a
    banned link can be exempted.
    """
    with db() as conn:
        rows = conn.execute(
            "SELECT link, domain, (removed=1 OR sensitive=1) banned FROM tools"
        ).fetchall()
    banned = [v for r in rows if r["banned"] for v in (r["link"], r["domain"]) if v]
    allowed = [r["link"] for r in rows if not r["banned"] and r["link"]]
    return banned, allowed


# ──────────────────────────────────────────────────── المحادثات / Conversations
# قناة الفريق: محادثة كل عضو مع بيان من صفحة «جرّب بيان». رسائلها تُحفظ كغيرها
# (وتخضع لمدة الحذف نفسها)، لكنها ليست من الجمهور، فتُستبعد من صفحة الأسئلة
# والأعداد والمواضيع بالشرط PUBLIC أدناه
# The team channel: each member's conversation with Bayan from the "Try Bayan"
# page. Its messages are saved like the others (and purged on the same
# schedule), but they are not from the public, so the PUBLIC condition below
# leaves them out of the questions page, the counts and the topics
TEAM_CHANNEL = "team"
PUBLIC = f"channel != '{TEAM_CHANNEL}'"


def history(channel: str, user_id: str, turns: int) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE channel=? AND user_id=? "
            "ORDER BY id DESC LIMIT ?",
            (channel, user_id, turns * 2),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def thread(channel: str, user_id: str, turns: int) -> list[dict]:
    """آخر turns دورة من محادثة واحدة بكل حقولها، الأقدم أولاً، لعرضها كخيط.
    The last turns of one conversation with all their fields, oldest first,
    to show as a thread."""
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE channel=? AND user_id=? ORDER BY id DESC LIMIT ?",
            (channel, user_id, turns * 2),
        ).fetchall()
    out = []
    for r in reversed(rows):
        d = dict(r)
        d["sources"] = json.loads(d["sources"] or "[]")
        d["retrieval"] = json.loads(d["retrieval"] or "null")
        out.append(d)
    return out


def remember(
    channel: str, user_id: str, role: str, content: str,
    outcome: str | None = None, confidence: float | None = None,
    sources: list[str] | None = None,
    topic: str | None = None, detail: str | None = None,
    retrieval: dict | None = None,
) -> None:
    """retrieval: ملخّص الاسترجاع لإجابة في قناة الفريق، لعرضه مع الخيط لاحقاً.
    retrieval: the retrieval summary of a team-channel answer, to show with
    the thread later."""
    with db() as conn:
        conn.execute(
            "INSERT INTO messages(channel,user_id,role,content,outcome,"
            "confidence,sources,topic,detail,retrieval,ts) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                channel, user_id, role, content, outcome, confidence,
                json.dumps(sources or [], ensure_ascii=False), topic, detail,
                json.dumps(retrieval, ensure_ascii=False) if retrieval is not None else None,
                time.time(),
            ),
        )
        conn.execute(
            "DELETE FROM messages WHERE channel=? AND user_id=? AND id NOT IN "
            "(SELECT id FROM messages WHERE channel=? AND user_id=? "
            "ORDER BY id DESC LIMIT 40)",
            (channel, user_id, channel, user_id),
        )


def record_question(channel: str, user_id: str) -> None:
    """يسجّل وقت سؤال لحدّ الأسئلة اليومي، ويحذف ما مضى عليه يوم.
    Records a question's time for the daily limit, and deletes entries older
    than a day."""
    now = time.time()
    with db() as conn:
        conn.execute("DELETE FROM asked WHERE ts < ?", (now - 86400,))
        conn.execute("INSERT INTO asked(channel,user_id,ts) VALUES(?,?,?)",
                     (channel, user_id, now))


def questions_since(channel: str, user_id: str, since: float) -> list[float]:
    """أوقات أسئلة المستخدم منذ since، الأقدم أولاً.
    Times of the user's questions at or after since, oldest first."""
    with db() as conn:
        rows = conn.execute(
            "SELECT ts FROM asked WHERE channel=? AND user_id=? AND ts >= ? ORDER BY ts",
            (channel, user_id, since),
        ).fetchall()
    return [r["ts"] for r in rows]


def save_opportunity_week(year: int, week: int, items: list[dict]) -> int:
    """يستبدل فرص أسبوع بقائمته الجديدة، ويعيد عددها.
    Replaces a week's opportunities with its new list, and returns how many."""
    with db() as conn:
        conn.execute("DELETE FROM opportunities WHERE year=? AND week=?", (year, week))
        conn.executemany(
            "INSERT INTO opportunities(year,week,position,title,url) VALUES(?,?,?,?,?)",
            [(year, week, i, it["title"], it["url"]) for i, it in enumerate(items, 1)],
        )
    return len(items)


def delete_opportunity_week(year: int, week: int) -> None:
    with db() as conn:
        conn.execute("DELETE FROM opportunities WHERE year=? AND week=?", (year, week))


def opportunity_weeks() -> list[dict]:
    """الأسابيع المحفوظة وعدد فرص كل منها، الأحدث أولاً.
    The saved weeks and the number of opportunities in each, newest first."""
    with db() as conn:
        rows = conn.execute(
            "SELECT year, week, COUNT(*) n FROM opportunities "
            "GROUP BY year, week ORDER BY year DESC, week DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def recent_opportunities(weeks: int) -> list[dict]:
    """فرص آخر weeks أسابيع محفوظة (لا آخر weeks أسابيع تقويمية).
    The opportunities of the last `weeks` saved weeks (not calendar weeks)."""
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM opportunities WHERE (year, week) IN "
            "(SELECT year, week FROM opportunities GROUP BY year, week "
            " ORDER BY year DESC, week DESC LIMIT ?) ORDER BY year DESC, week DESC, position",
            (max(weeks, 1),),
        ).fetchall()
    return [dict(r) for r in rows]


def opportunity_week_items(year: int, week: int) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM opportunities WHERE year=? AND week=? ORDER BY position",
            (year, week),
        ).fetchall()
    return [dict(r) for r in rows]


def _rollup_usage(conn) -> None:
    """يحفظ أعداد الأيام المكتملة (قبل اليوم UTC) من الرسائل الموجودة. لا يُنقص عدداً
    محفوظاً: يومٌ قُطع نصفه بالحذف يبقى بأكبر عدّين.
    Saves the counts of completed days (before today, UTC) from the messages still
    present. It never lowers a saved count: a day half-deleted keeps the larger."""
    conn.execute(
        "INSERT INTO usage_daily(day, channel, questions, users) "
        "SELECT date(ts,'unixepoch'), channel, COUNT(*), COUNT(DISTINCT user_id) "
        f"FROM messages WHERE role='user' AND {PUBLIC} AND date(ts,'unixepoch') < date('now') "
        "GROUP BY 1, 2 "
        "ON CONFLICT(day, channel) DO UPDATE SET "
        "questions=MAX(questions, excluded.questions), users=MAX(users, excluded.users)"
    )
    conn.execute(
        "INSERT INTO topic_daily(day, topic, detail, questions) "
        "SELECT date(ts,'unixepoch'), topic, COALESCE(detail, ''), COUNT(*) "
        f"FROM messages WHERE role='user' AND {PUBLIC} AND topic IS NOT NULL "
        "AND date(ts,'unixepoch') < date('now') GROUP BY 1, 2, 3 "
        "ON CONFLICT(day, topic, detail) DO UPDATE SET "
        "questions=MAX(questions, excluded.questions)"
    )


def _topic_tree(rows) -> dict:
    """{موضوع: {"questions": n, "details": {تفصيل: n}}}"""
    out: dict[str, dict] = {}
    for r in rows:
        t = out.setdefault(r["topic"], {"questions": 0, "details": {}})
        t["questions"] += r["n"]
        if r["detail"]:
            t["details"][r["detail"]] = t["details"].get(r["detail"], 0) + r["n"]
    return out


def topic_stats(since: float) -> dict:
    """مواضيع الأسئلة منذ since من الرسائل الموجودة.
    Question topics since `since`, from the messages still present."""
    with db() as conn:
        rows = conn.execute(
            f"SELECT topic, COALESCE(detail,'') detail, COUNT(*) n FROM messages "
            f"WHERE role='user' AND {PUBLIC} AND topic IS NOT NULL AND ts >= ? GROUP BY 1, 2",
            (since,),
        ).fetchall()
    return _topic_tree(rows)


def topic_totals() -> dict:
    """مواضيع الأسئلة منذ البداية: الأيام المحفوظة مع اليوم الجاري.
    Question topics since the start: the saved days plus today."""
    with db() as conn:
        _rollup_usage(conn)
        rows = conn.execute(
            "SELECT topic, detail, SUM(n) n FROM ("
            "SELECT topic, detail, questions n FROM topic_daily "
            "UNION ALL SELECT topic, COALESCE(detail,''), COUNT(*) FROM messages "
            f"WHERE role='user' AND {PUBLIC} AND topic IS NOT NULL AND date(ts,'unixepoch') >= date('now') "
            "GROUP BY 1, 2) GROUP BY 1, 2"
        ).fetchall()
    return _topic_tree(rows)


def investigation_titles() -> dict[str, str]:
    """عنوان كل تحقيق مفهرس بحسب slug، لعرض تفصيل الموضوع باسمه.
    Each indexed investigation's title by slug, to show a topic detail by name."""
    with db() as conn:
        rows = conn.execute(
            "SELECT title, meta FROM chunks WHERE type='investigation'"
        ).fetchall()
    out: dict[str, str] = {}
    for r in rows:
        slug = json.loads(r["meta"] or "{}").get("slug")
        if slug and r["title"] and slug not in out:
            out[slug] = r["title"]
    return out


def usage_totals() -> dict:
    """الإجمالي منذ البداية: الأيام المحفوظة مع اليوم الجاري. المستخدمون هنا مجموع
    المستخدمين اليوميين (من تكرر في يومين يُحسب مرتين)، لأن المعرّفات لا تُحفظ.
    All-time totals: the saved days plus today. Users here is the sum of daily
    users (someone seen on two days counts twice), because identifiers are not kept."""
    with db() as conn:
        _rollup_usage(conn)
        rows = conn.execute(
            "SELECT channel, SUM(questions) q, SUM(users) u, MIN(day) first "
            "FROM (SELECT day, channel, questions, users FROM usage_daily "
            "UNION ALL SELECT date(ts,'unixepoch'), channel, COUNT(*), COUNT(DISTINCT user_id) "
            f"FROM messages WHERE role='user' AND {PUBLIC} AND date(ts,'unixepoch') >= date('now') "
            "GROUP BY 1, 2) GROUP BY channel"
        ).fetchall()
    return {r["channel"]: {"questions": r["q"], "users": r["u"], "first": r["first"]}
            for r in rows}


def purge_old_messages(days: int) -> int:
    """يحذف الأسئلة والإجابات الأقدم من days يوماً، ويعيد عددها. تُحفظ أعدادها أولاً.
    Deletes questions and answers older than days, and returns how many. Their
    counts are saved first."""
    with db() as conn:
        _rollup_usage(conn)
    if days <= 0:
        return 0
    with db() as conn:
        n = conn.execute(
            "DELETE FROM messages WHERE ts < ?", (time.time() - days * 86400,)
        ).rowcount
        _drop_orphan_ratings(conn)
        return n


def clear_history(channel: str, user_id: str) -> None:
    with db() as conn:
        conn.execute(
            "DELETE FROM messages WHERE channel=? AND user_id=?", (channel, user_id)
        )
        _drop_orphan_ratings(conn)


def _drop_orphan_ratings(conn) -> None:
    """تقييم رسالة حُذفت يُحذف معها.
    The rating of a deleted message is deleted with it."""
    conn.execute("DELETE FROM ratings WHERE message_id NOT IN (SELECT id FROM messages)")


# ──────────────────────────────────────────────────────── الحدود / Limits
def is_blocked(channel: str, user_id: str) -> bool:
    with db() as conn:
        return conn.execute(
            "SELECT 1 FROM blocked WHERE channel=? AND user_id=?", (channel, user_id)
        ).fetchone() is not None


def rate_ok(channel: str, user_id: str) -> bool:
    return throttle(channel, user_id, config.RATE_LIMIT_MESSAGES,
                    config.RATE_LIMIT_WINDOW)


def throttle(channel: str, key: str, limit: int, window: int) -> bool:
    """يسجّل محاولة ويُرجع False إن تجاوزت limit خلال window ثانية.
    Record an attempt and return False if it goes over limit within window seconds."""
    now = time.time()
    with db() as conn:
        conn.execute("DELETE FROM hits WHERE ts < ?", (now - 3600,))
        n = conn.execute(
            "SELECT COUNT(*) c FROM hits WHERE channel=? AND user_id=? AND ts > ?",
            (channel, key, now - window),
        ).fetchone()["c"]
        if n >= limit:
            return False
        conn.execute(
            "INSERT INTO hits(channel,user_id,ts) VALUES(?,?,?)", (channel, key, now)
        )
    return True


def block(channel: str, user_id: str, reason: str) -> None:
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO blocked(channel,user_id,reason,ts) VALUES(?,?,?,?)",
            (channel, user_id, reason, time.time()),
        )
        # المحظور لا تصله قائمة الفرص / A blocked user gets no opportunities list
        conn.execute("DELETE FROM subscribers WHERE channel=? AND user_id=?", (channel, user_id))


# ──────────────────────────────────────────────── الفريق / Team members
ROLES = ("admin", "editor", "viewer")


def members() -> list[dict]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM members ORDER BY created").fetchall()
    return [dict(r) for r in rows]


def member(member_id: int) -> dict | None:
    with db() as conn:
        r = conn.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone()
    return dict(r) if r else None


def member_by_email(email: str) -> dict | None:
    with db() as conn:
        r = conn.execute("SELECT * FROM members WHERE email=?", (email.lower(),)).fetchone()
    return dict(r) if r else None


def add_member(email: str, role: str, name: str = "") -> int:
    """يضيف عضواً أو يعيد رقمه إن كان موجوداً. / Adds a member, or returns the
    existing one's id."""
    if role not in ROLES:
        raise ValueError(role)
    with db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO members(email,name,role,active,created) VALUES(?,?,?,1,?)",
            (email.lower(), name, role, time.time()),
        )
        return conn.execute(
            "SELECT id FROM members WHERE email=?", (email.lower(),)
        ).fetchone()["id"]


def set_member(member_id: int, role: str | None = None, active: bool | None = None,
               name: str | None = None) -> None:
    with db() as conn:
        if role is not None:
            if role not in ROLES:
                raise ValueError(role)
            conn.execute("UPDATE members SET role=? WHERE id=?", (role, member_id))
        if active is not None:
            conn.execute("UPDATE members SET active=? WHERE id=?", (int(active), member_id))
        if name is not None:
            conn.execute("UPDATE members SET name=? WHERE id=?", (name, member_id))


def delete_member(member_id: int) -> None:
    with db() as conn:
        conn.execute("DELETE FROM members WHERE id=?", (member_id,))


def touch_login(member_id: int, name: str) -> None:
    with db() as conn:
        conn.execute("UPDATE members SET last_login=?, name=? WHERE id=?",
                     (time.time(), name, member_id))


def audit(member_name: str, action: str, target: str | None = None) -> None:
    """يسجّل إجراءً في اللوحة. target وصف قصير (رقم تصحيح، بريد عضو)، لا نص سؤال.
    Records a dashboard action. target is a short label (a correction id, a
    member's email), never question text."""
    with db() as conn:
        conn.execute("INSERT INTO audit(ts,member,action,target) VALUES(?,?,?,?)",
                     (time.time(), member_name, action, target))
        conn.execute("DELETE FROM audit WHERE id NOT IN "
                     "(SELECT id FROM audit ORDER BY id DESC LIMIT 2000)")


def audit_log(limit: int = 100) -> list[dict]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


# ──────────────────────────────────── المشتركون في الفرص / Opportunities subscribers
def subscribe(channel: str, user_id: str) -> bool:
    """يسجّل الاشتراك ويعيد True إن كان جديداً.
    Records the subscription and returns True if it is new."""
    with db() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO subscribers(channel,user_id,ts) VALUES(?,?,?)",
            (channel, user_id, time.time()),
        )
        return cur.rowcount > 0


def unsubscribe(channel: str, user_id: str) -> bool:
    """يلغي الاشتراك ويعيد True إن كان قائماً.
    Removes the subscription and returns True if there was one."""
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM subscribers WHERE channel=? AND user_id=?", (channel, user_id)
        )
        return cur.rowcount > 0


def is_subscribed(channel: str, user_id: str) -> bool:
    with db() as conn:
        return conn.execute(
            "SELECT 1 FROM subscribers WHERE channel=? AND user_id=?", (channel, user_id)
        ).fetchone() is not None


def subscribers() -> list[dict]:
    with db() as conn:
        rows = conn.execute("SELECT channel, user_id FROM subscribers ORDER BY ts").fetchall()
    return [dict(r) for r in rows]


def subscriber_counts() -> dict[str, int]:
    with db() as conn:
        rows = conn.execute(
            "SELECT channel, COUNT(*) n FROM subscribers GROUP BY channel"
        ).fetchall()
    return {r["channel"]: r["n"] for r in rows}


def unblock(channel: str, user_id: str) -> None:
    with db() as conn:
        conn.execute(
            "DELETE FROM blocked WHERE channel=? AND user_id=?", (channel, user_id)
        )


def blocked_list() -> list[dict]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM blocked ORDER BY ts DESC").fetchall()
    return [dict(r) for r in rows]


def first_time(event_id: str) -> bool:
    now = time.time()
    with db() as conn:
        conn.execute(
            "DELETE FROM seen_events WHERE ts < ? AND event_id NOT LIKE 'fb_comment:%'",
            (now - 86400,),
        )
        try:
            conn.execute(
                "INSERT INTO seen_events(event_id, ts) VALUES(?,?)", (event_id, now)
            )
            return True
        except sqlite3.IntegrityError:
            return False


# ────────────────────────────────────────────── سجلّ الفهرسة / Indexing log
def start_run() -> int:
    with db() as conn:
        return conn.execute(
            "INSERT INTO ingest_runs(started) VALUES(?)", (time.time(),)
        ).lastrowid


def finish_run(run_id: int, ok: bool, chunks: int, tools: int, detail: str) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE ingest_runs SET finished=?, ok=?, chunks=?, tools=?, detail=? "
            "WHERE id=?",
            (time.time(), int(ok), chunks, tools, detail[:4000], run_id),
        )


def close_interrupted_runs() -> int:
    """عند الإقلاع: كل دورة فهرسة لم تنتهِ قطعتها إعادة تشغيل، فتُغلق فاشلة
    بدل أن تبقى «جارية» إلى الأبد. الفهرس السابق لم يُمسّ. تعيد عددها.
    At startup: every indexing run that never finished was cut off by a
    restart, so it is closed as failed instead of staying "running" forever.
    The previous index was not touched. Returns how many."""
    with db() as conn:
        return conn.execute(
            "UPDATE ingest_runs SET finished=?, ok=0, detail=TRIM(COALESCE(detail, '') "
            "|| ' انقطعت بإعادة تشغيل الخادم، والفهرس السابق بقي يعمل. / Interrupted "
            "by a server restart; the previous index stayed in use.') "
            "WHERE finished IS NULL",
            (time.time(),),
        ).rowcount


def last_run() -> dict | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM ingest_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


# ───────────────────────────────────────────── إعدادات اللوحة / Dashboard settings
def setting(key: str, default: str) -> str:
    with db() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def clear_setting(key: str) -> None:
    with db() as conn:
        conn.execute("DELETE FROM settings WHERE key=?", (key,))


# ─────────────────────────────────────── مفاتيح API من اللوحة / Dashboard API keys
def api_keys() -> list[dict]:
    with db() as conn:
        rows = conn.execute("SELECT name, value, updated, by FROM api_keys ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def set_api_key(name: str, value: str, by: str) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO api_keys(name,value,updated,by) VALUES(?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET value=excluded.value, updated=excluded.updated, "
            "by=excluded.by",
            (name, value, time.time(), by),
        )


def clear_api_key(name: str) -> None:
    with db() as conn:
        conn.execute("DELETE FROM api_keys WHERE name=?", (name,))


# ───────────────────────────────────────── مصادر الفريق / Team sources
def team_sources() -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT id, kind, title, origin, LENGTH(text) chars, status, error, added_by, "
            "added, synced FROM team_sources ORDER BY added DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def team_source(source_id: int) -> dict | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM team_sources WHERE id=?", (source_id,)).fetchone()
    return dict(row) if row else None


def add_team_source(kind: str, title: str, origin: str, text: str, by: str) -> int:
    now = time.time()
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO team_sources(kind,title,origin,text,added_by,added,synced) "
            "VALUES(?,?,?,?,?,?,?)", (kind, title, origin, text, by, now, now),
        )
        return cur.lastrowid


def update_team_source(source_id: int, text: str | None, status: str, error: str = "",
                       title: str | None = None) -> None:
    """بعد مزامنة: النص الجديد إن تغيّر، وحال المزامنة. text=None يُبقي النص.
    After a sync: the new text if it changed, and the sync state. text=None
    keeps the text."""
    with db() as conn:
        if text is not None:
            conn.execute("UPDATE team_sources SET text=?, synced=? WHERE id=?",
                         (text, time.time(), source_id))
        if title:
            conn.execute("UPDATE team_sources SET title=? WHERE id=?", (title, source_id))
        conn.execute("UPDATE team_sources SET status=?, error=? WHERE id=?",
                     (status, error[:400], source_id))


def delete_team_source(source_id: int) -> None:
    with db() as conn:
        conn.execute("DELETE FROM team_sources WHERE id=?", (source_id,))


def _bump_index_version(conn) -> None:
    conn.execute(
        "INSERT INTO settings(key,value) VALUES('index_version',?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (repr(time.time()),),
    )


def add_chunks(chunks: list[dict]) -> int:
    """يضيف مقاطع إلى الفهرس القائم دون استبداله (مصدر فريق جديد)، ويرفع رقم
    الإصدار فتعيد كل عملية التحميل.
    Adds chunks to the existing index without replacing it (a new team
    source), and bumps the version so every process reloads."""
    with db() as conn:
        for r in chunks:
            emb = r.get("embedding")
            blob = np.asarray(emb, dtype=np.float32).tobytes() if emb is not None else None
            cur = conn.execute(
                "INSERT INTO chunks(ext_id,type,title,url,text,norm_text,meta,embedding) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (r.get("ext_id"), r["type"], r.get("title"), r["url"], r["text"],
                 r["norm_text"], json.dumps(r.get("meta", {}), ensure_ascii=False), blob),
            )
            conn.execute("INSERT INTO chunks_fts(rowid, norm_text) VALUES(?,?)",
                         (cur.lastrowid, r["norm_text"]))
        _bump_index_version(conn)
    return len(chunks)


def delete_chunks(ext_prefix: str) -> int:
    """يحذف مقاطع معرّفها الخارجي يبدأ بـ ext_prefix (مثل «team:7:»).
    Deletes the chunks whose external id starts with ext_prefix (such as
    «team:7:»)."""
    with db() as conn:
        rows = conn.execute(
            "SELECT id, norm_text FROM chunks WHERE ext_id LIKE ? ESCAPE '\\'",
            (ext_prefix.replace("%", "\\%").replace("_", "\\_") + "%",),
        ).fetchall()
        # جدول FTS بلا محتوى: الحذف بأمر 'delete' مع النص الأصلي، لا DELETE
        # A contentless FTS table: deletion is the 'delete' command with the
        # original text, not DELETE
        for r in rows:
            conn.execute(
                "INSERT INTO chunks_fts(chunks_fts, rowid, norm_text) VALUES('delete', ?, ?)",
                (r["id"], r["norm_text"]),
            )
        if rows:
            marks = ",".join("?" * len(rows))
            conn.execute(f"DELETE FROM chunks WHERE id IN ({marks})", [r["id"] for r in rows])
        _bump_index_version(conn)
    return len(rows)


# ──────────────────────────────────────────────── استعلامات اللوحة / Dashboard queries
def outcome_stats(since: float) -> dict[str, int]:
    with db() as conn:
        rows = conn.execute(
            f"SELECT outcome, COUNT(*) c FROM messages "
            f"WHERE role='user' AND {PUBLIC} AND ts >= ? GROUP BY outcome",
            (since,),
        ).fetchall()
    return {r["outcome"] or "": r["c"] for r in rows}


def channel_stats(since: float) -> dict[str, dict]:
    with db() as conn:
        rows = conn.execute(
            f"SELECT channel, COUNT(*) c, COUNT(DISTINCT user_id) u FROM messages "
            f"WHERE role='user' AND {PUBLIC} AND ts >= ? GROUP BY channel",
            (since,),
        ).fetchall()
    return {r["channel"]: {"questions": r["c"], "users": r["u"]} for r in rows}


def questions(outcome: str = "", channel: str = "", before: int = 0,
              by_confidence: bool = False, limit: int = 50,
              rating: str = "") -> list[dict]:
    """أسئلة الجمهور مع ردّ بيان على كل منها وتقييمه، الأحدث أولاً.
    rating: up أو down أو none لتصفيتها بالتقييم.
    Questions from the public with Bayan's reply to each and its rating,
    newest first. rating: up, down or none to filter by rating."""
    where, args = ["u.role='user'", f"u.{PUBLIC}"], []
    if outcome:
        where.append("u.outcome=?")
        args.append(outcome)
    if rating in ("up", "down"):
        where.append("r.rating=?")
        args.append(1 if rating == "up" else -1)
    elif rating == "none":
        where.append("r.rating IS NULL")
    if channel:
        where.append("u.channel=?")
        args.append(channel)
    if before:
        where.append("u.id<?")
        args.append(before)
    order = "u.confidence DESC, u.id DESC" if by_confidence else "u.id DESC"
    with db() as conn:
        rows = conn.execute(
            "SELECT u.*, (SELECT a.content FROM messages a WHERE a.channel=u.channel "
            "AND a.user_id=u.user_id AND a.role='assistant' AND a.id>u.id "
            "ORDER BY a.id LIMIT 1) AS reply, "
            "r.rating AS rating, r.reason AS rating_reason, r.note AS rating_note, r.author AS rating_author "
            "FROM messages u LEFT JOIN ratings r ON r.message_id=u.id "
            f"WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ?",
            (*args, limit),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["sources"] = json.loads(d["sources"] or "[]")
        out.append(d)
    return out


def question_text(message_id: int) -> tuple[str, str | None] | None:
    """(نص السؤال، ردّ بيان عليه) برقم رسالة السؤال، لتعبئة نموذج التصحيح.
    (the question's text, Bayan's reply to it) by the question's message
    number, to fill in the correction form."""
    rows = [q for q in questions(before=message_id + 1, limit=1) if q["id"] == message_id]
    return (rows[0]["content"], rows[0].get("reply")) if rows else None


# ──────────────────────────────────────────────────── التقييم / Ratings
RATING_REASONS = ("wrong", "missing", "refused_wrongly", "should_refuse", "format", "other")


def set_rating(message_id: int, rating: int, reason: str = "", note: str = "",
               author: str | None = None) -> bool:
    """يحفظ تقييم إجابة السؤال، ويستبدل تقييماً سابقاً. False إن لم يوجد السؤال.
    Saves the rating of the question's answer, replacing an earlier one.
    False if the question does not exist."""
    with db() as conn:
        if not conn.execute("SELECT 1 FROM messages WHERE id=? AND role='user'",
                            (message_id,)).fetchone():
            return False
        conn.execute(
            "INSERT OR REPLACE INTO ratings (message_id, rating, reason, note, author, ts) "
            "VALUES (?,?,?,?,?,?)",
            (message_id, 1 if rating > 0 else -1,
             reason if reason in RATING_REASONS else None, note.strip() or None,
             author, time.time()),
        )
    return True


def clear_rating(message_id: int) -> None:
    with db() as conn:
        conn.execute("DELETE FROM ratings WHERE message_id=?", (message_id,))


def rating_stats(since: float) -> dict[str, int]:
    with db() as conn:
        rows = conn.execute(
            "SELECT r.rating, COUNT(*) n FROM ratings r JOIN messages m "
            "ON m.id=r.message_id WHERE m.ts >= ? GROUP BY r.rating", (since,)
        ).fetchall()
    return {"up" if r["rating"] > 0 else "down": r["n"] for r in rows}


# ──────────────────────────────────────── التصحيحات المعتمدة / Approved corrections
def _vector_blob(vector: list[float] | None) -> bytes | None:
    return np.asarray(vector, dtype=np.float32).tobytes() if vector is not None else None


def save_correction(question: str, answer: str, url: str | None, active: bool,
                    vector: list[float] | None, embed_model: str | None,
                    correction_id: int = 0, author: str | None = None) -> int:
    """يضيف تصحيحاً أو يعدّله (correction_id)، ويعيد رقمه.
    Adds a correction, or edits one (correction_id), and returns its number."""
    now = time.time()
    values = (question, normalize_ar(question), answer, url or None, int(active),
              _vector_blob(vector), embed_model if vector is not None else None, now, author)
    with db() as conn:
        if correction_id:
            conn.execute(
                "UPDATE corrections SET question=?, norm_question=?, answer=?, url=?, "
                "active=?, embedding=?, embed_model=?, updated=?, author=? WHERE id=?",
                (*values, correction_id),
            )
            return correction_id
        return conn.execute(
            "INSERT INTO corrections (question, norm_question, answer, url, active, "
            "embedding, embed_model, updated, author, created) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (*values, now),
        ).lastrowid


def set_correction_vector(correction_id: int, vector: list[float], embed_model: str) -> None:
    with db() as conn:
        conn.execute("UPDATE corrections SET embedding=?, embed_model=? WHERE id=?",
                     (_vector_blob(vector), embed_model, correction_id))


def delete_correction(correction_id: int) -> None:
    with db() as conn:
        conn.execute("DELETE FROM corrections WHERE id=?", (correction_id,))


def corrections(active_only: bool = False) -> list[dict]:
    """التصحيحات، الأحدث تعديلاً أولاً، مع متجه كل سؤال إن وُجد.
    The corrections, most recently edited first, with each question's vector
    if there is one."""
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM corrections"
            + (" WHERE active=1" if active_only else "") + " ORDER BY updated DESC"
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        blob = d.pop("embedding")
        d["vector"] = np.frombuffer(blob, dtype=np.float32) if blob else None
        out.append(d)
    return out


def correction(correction_id: int) -> dict | None:
    return next((c for c in corrections() if c["id"] == correction_id), None)


def message_owner(message_id: int) -> tuple[str, str] | None:
    with db() as conn:
        row = conn.execute(
            "SELECT channel, user_id FROM messages WHERE id=?", (message_id,)
        ).fetchone()
    return (row["channel"], row["user_id"]) if row else None
