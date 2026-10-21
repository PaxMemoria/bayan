"""طبقة التخزين: SQLite واحدة تحمل المعرفة والأدوات والمحادثات."""
import json
import sqlite3
import time
from contextlib import contextmanager

import numpy as np

from . import config

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
    ts         REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(channel, user_id, ts);
CREATE INDEX IF NOT EXISTS idx_messages_outcome ON messages(outcome, ts);

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

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
    USING fts5(norm_text, content='', tokenize="unicode61 remove_diacritics 2");
"""


@contextmanager
def db():
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)


# ──────────────────────────────────────────────────── الفهرسة
def reset_index() -> None:
    with db() as conn:
        conn.executescript(
            "DROP TABLE IF EXISTS chunks_fts;"
            "DELETE FROM chunks;"
            "DELETE FROM tools;"
            "DELETE FROM sqlite_sequence WHERE name IN ('chunks','tools');"
        )
        conn.executescript(SCHEMA)


def add_chunks(rows: list[dict]) -> None:
    with db() as conn:
        for r in rows:
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


TOOL_COLS = (
    "name", "norm_name", "category_ar", "category_en", "norm_category",
    "summary_ar", "summary_en", "link", "domain", "verification",
    "sensitive", "caution", "removed", "removal_type_ar",
    "removal_reason_ar", "removal_date", "replacement", "url",
)


def add_tools(rows: list[dict]) -> None:
    marks = ",".join("?" * len(TOOL_COLS))
    with db() as conn:
        conn.executemany(
            f"INSERT INTO tools({','.join(TOOL_COLS)}) VALUES({marks})",
            [tuple(r.get(c) for c in TOOL_COLS) for r in rows],
        )


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


# ──────────────────────────────────────────── الأدوات: بحث منظّم
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


# ──────────────────────────────────────────────────── المحادثات
def history(channel: str, user_id: str, turns: int) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE channel=? AND user_id=? "
            "ORDER BY id DESC LIMIT ?",
            (channel, user_id, turns * 2),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def remember(
    channel: str, user_id: str, role: str, content: str,
    outcome: str | None = None, confidence: float | None = None,
    sources: list[str] | None = None,
) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO messages(channel,user_id,role,content,outcome,"
            "confidence,sources,ts) VALUES(?,?,?,?,?,?,?,?)",
            (
                channel, user_id, role, content, outcome, confidence,
                json.dumps(sources or [], ensure_ascii=False), time.time(),
            ),
        )
        conn.execute(
            "DELETE FROM messages WHERE channel=? AND user_id=? AND id NOT IN "
            "(SELECT id FROM messages WHERE channel=? AND user_id=? "
            "ORDER BY id DESC LIMIT 40)",
            (channel, user_id, channel, user_id),
        )


def clear_history(channel: str, user_id: str) -> None:
    with db() as conn:
        conn.execute(
            "DELETE FROM messages WHERE channel=? AND user_id=?", (channel, user_id)
        )


# ──────────────────────────────────────────────────────── الحدود
def is_blocked(channel: str, user_id: str) -> bool:
    with db() as conn:
        return conn.execute(
            "SELECT 1 FROM blocked WHERE channel=? AND user_id=?", (channel, user_id)
        ).fetchone() is not None


def rate_ok(channel: str, user_id: str) -> bool:
    now = time.time()
    cutoff = now - config.RATE_LIMIT_WINDOW
    with db() as conn:
        conn.execute("DELETE FROM hits WHERE ts < ?", (now - 3600,))
        n = conn.execute(
            "SELECT COUNT(*) c FROM hits WHERE channel=? AND user_id=? AND ts > ?",
            (channel, user_id, cutoff),
        ).fetchone()["c"]
        if n >= config.RATE_LIMIT_MESSAGES:
            return False
        conn.execute(
            "INSERT INTO hits(channel,user_id,ts) VALUES(?,?,?)", (channel, user_id, now)
        )
    return True


def first_time(event_id: str) -> bool:
    now = time.time()
    with db() as conn:
        conn.execute("DELETE FROM seen_events WHERE ts < ?", (now - 86400,))
        try:
            conn.execute(
                "INSERT INTO seen_events(event_id, ts) VALUES(?,?)", (event_id, now)
            )
            return True
        except sqlite3.IntegrityError:
            return False


# ────────────────────────────────────────────── سجلّ الفهرسة
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


def last_run() -> dict | None:
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM ingest_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


# ───────────────────────────────────────────── إعدادات اللوحة
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
