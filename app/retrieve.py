"""الاسترجاع بمسارين.

الأدوات قاعدة بيانات، فسؤال «ما أدوات تحليل صور الأقمار الصناعية؟» يُجاب
بتصفية على حقل التصنيف تعيد القائمة كاملة ومرتّبة — لا ببحث نصي يعيد
ستة مقاطع متفرقة. وسؤال «كيف أتحقق من تاريخ صورة؟» سؤال معنى، فيذهب
للمسار الدلالي. المساران يعملان معاً ويتغذّى النموذج من ناتجهما.
"""
import logging
import math
import re
import threading
from collections import Counter

import numpy as np

from . import config, embed, store
from .arabic import fts_query, normalize_ar, tokens, weighted_overlap

log = logging.getLogger("retrieve")
_lock = threading.Lock()

# صيغ تدل على طلب قائمة لا تعريف أداة بعينها
LIST_INTENT = re.compile(
    r"\b(ادوات|اداه|قائمه|قائمة|ماهي|ما هي|اقترح|افضل|انواع|وش|شنو|كل ال)\b"
)
# درجة ثقة ثابتة للمطابقة المنظّمة: المطابقة هنا يقينية لا تقديرية
STRUCTURED_CONFIDENCE = 0.95


class _State:
    """كل ما يُحمَّل من الفهرس إلى الذاكرة، يُستبدل دفعة واحدة.

    الاستبدال الذرّي يمنع سؤالاً يصل أثناء إعادة التحميل من قراءة مصفوفة
    متجهات جديدة مع معرّفات قديمة.
    """

    def __init__(self) -> None:
        self.version: str | None = None
        self.matrix = np.zeros((0, config.EMBED_DIM), dtype=np.float32)
        self.ids: list[int] = []
        self.vector_note = ""
        self.categories: list[dict] = []
        self.tool_names: list[tuple[str, str]] = []  # (norm_name, name)
        self.idf: dict[str, float] = {}
        self.idf_unseen = 1.0
        self.banned: list[str] = []
        self.allowed: set[str] = set()


_S = _State()


def norm_link(value: str) -> str:
    """صيغة موحّدة لرابط أو نطاق، لمقارنة ما يكتبه النموذج بالدليل."""
    v = re.sub(r"^[a-z]+://", "", (value or "").strip().lower())
    return re.sub(r"^www\.", "", v).rstrip("/")


def warm() -> None:
    """تحميل المتجهات وجداول البحث — عند الإقلاع وكلما تغيّر الفهرس."""
    global _S
    with _lock:
        s = _State()
        s.version = store.index_version()

        matrix, ids = store.load_embeddings()
        built_with = store.setting("index_embed_model", "")
        reason = embed.unavailable_reason()
        if reason:
            s.vector_note = reason
        elif not ids:
            s.vector_note = "الفهرس بلا متجهات، أعد الفهرسة"
        elif built_with != embed.model_id() or matrix.shape[1] != config.EMBED_DIM:
            s.vector_note = (
                f"الفهرس مبني بـ {built_with or 'إعداد سابق'} والإعداد الحالي "
                f"{embed.model_id()}، أعد الفهرسة"
            )
        else:
            s.matrix, s.ids = matrix, ids
        if s.vector_note:
            log.warning("البحث الدلالي معطّل: %s", s.vector_note)

        s.categories = store.categories()
        with store.db() as conn:
            s.tool_names = [
                (r["norm_name"], r["name"]) for r in conn.execute(
                    "SELECT norm_name, name FROM tools WHERE LENGTH(norm_name) >= 4"
                ).fetchall()
            ]
            texts = [r["norm_text"] for r in
                     conn.execute("SELECT norm_text FROM chunks").fetchall()]
        s.idf = _build_idf(texts)
        # كلمة لا ترد في أي مقطع أندر من أندر كلمة موجودة: log(n)
        s.idf_unseen = math.log(max(len(texts), 2))

        banned, allowed = store.link_rules()
        s.banned = sorted({norm_link(b) for b in banned if norm_link(b)},
                          key=len, reverse=True)
        s.allowed = {norm_link(a) for a in allowed}
        _S = s


def ensure_fresh() -> None:
    """يعيد التحميل إن تغيّر الفهرس منذ آخر تحميل (فهرسة من عملية أخرى)."""
    if store.index_version() != _S.version:
        warm()


def status() -> dict:
    return {"vectors": len(_S.ids), "vector_note": _S.vector_note}


def link_rules() -> tuple[list[str], set[str]]:
    return _S.banned, _S.allowed


def _build_idf(texts: list[str]) -> dict[str, float]:
    """وزن ندرة كل كلمة في قاعدة المعرفة، لاستعماله بلا متجهات."""
    df: Counter = Counter()
    for t in texts:
        df.update(set(tokens(t)))
    n = max(len(texts), 1)
    return {w: max(math.log(n / (1 + c)), 0.0) for w, c in df.items()}


# ───────────────────────────────────── المسار المنظّم
def match_category(question: str) -> dict | None:
    """أطول تصنيف يرد اسمه (عربياً أو إنجليزياً) داخل السؤال."""
    q = normalize_ar(question)
    best = None
    for cat in _S.categories:
        for label in (cat["norm_category"], normalize_ar(cat["category_en"] or "")):
            if len(label) >= 4 and label in q:
                if best is None or len(label) > best[0]:
                    best = (len(label), cat)
    return best[1] if best else None


def match_tool_names(question: str, limit: int = 3) -> list[dict]:
    """أدوات يرد اسمها حرفياً في السؤال — الأطول اسماً أولاً."""
    q = normalize_ar(question)
    hits = [(len(n), name) for n, name in _S.tool_names if n in q]
    hits.sort(reverse=True)
    out, seen = [], set()
    for _, name in hits[: limit * 2]:
        rec = store.tool_by_name(normalize_ar(name))
        if rec and rec["name"] not in seen:
            seen.add(rec["name"])
            out.append(rec)
        if len(out) >= limit:
            break
    return out


def structured(question: str) -> dict:
    """ناتج المسار المنظّم: أدوات بالاسم و/أو قائمة تصنيف."""
    result = {"tools": [], "category": None, "category_tools": []}

    result["tools"] = match_tool_names(question)

    cat = match_category(question)
    # لا نُخرج قائمة تصنيف كاملة إلا إذا بدا السؤال طلب قائمة، وإلا
    # فسؤال عن أداة واحدة في تصنيف ما يُغرق بقائمة لا يريدها السائل.
    if cat and (LIST_INTENT.search(normalize_ar(question)) or not result["tools"]):
        tools = store.tools_in_category(cat["norm_category"], config.MAX_TOOLS_LISTED)
        if tools:
            result["category"] = cat
            result["category_tools"] = tools
    return result


# ───────────────────────────────────── المسار الدلالي
def _fts(question: str, limit: int) -> list[int]:
    q = fts_query(question)
    if not q:
        return []
    with store.db() as conn:
        try:
            rows = conn.execute(
                "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? "
                "ORDER BY bm25(chunks_fts) LIMIT ?",
                (q, limit),
            ).fetchall()
        except Exception:
            return []
    return [r["rowid"] for r in rows]


def _vector(question: str, limit: int, s: _State) -> tuple[list[int], dict[int, float]]:
    if s.matrix.shape[0] == 0:
        return [], {}
    try:
        vecs = embed.embed([question], input_type="query", retries=1)
    except Exception:  # noqa: BLE001 — تعطّل Voyage لا يُسكت بيان
        log.exception("تعذّر متجه السؤال — البحث اللفظي وحده لهذا السؤال")
        return [], {}
    if not vecs or len(vecs[0]) != s.matrix.shape[1]:
        return [], {}
    q = np.asarray(vecs[0], dtype=np.float32)
    sims = s.matrix @ (q / (np.linalg.norm(q) or 1.0))
    top = np.argsort(-sims)[:limit]
    return [s.ids[i] for i in top], {s.ids[i]: float(sims[i]) for i in top}


def semantic(question: str) -> tuple[list[dict], float, bool]:
    """-> (مقاطع، ثقة، هل استُعملت المتجهات)"""
    s = _S
    lex = _fts(question, config.CANDIDATES)
    vec, sims = _vector(question, config.CANDIDATES, s)

    scores: dict[int, float] = {}
    for ranked in (lex, vec):
        for rank, cid in enumerate(ranked):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (60 + rank)
    if not scores:
        return [], 0.0, bool(sims)

    ordered = sorted(scores, key=scores.get, reverse=True)[: config.TOP_K]
    rows = store.get_chunks(ordered)
    passages = [rows[cid] for cid in ordered if cid in rows]
    if not passages:
        return [], 0.0, bool(sims)

    if sims:
        confidence = max(sims.get(p["id"], 0.0) for p in passages)
    else:
        # بلا متجهات: تداخل موزون بالندرة، مُعاير إلى مقياس العتبة نفسه
        raw = max(weighted_overlap(question, p["text"], s.idf, s.idf_unseen)
                  for p in passages)
        confidence = raw * (config.MIN_RELEVANCE / config.LEXICAL_THRESHOLD)
    return passages, float(confidence), bool(sims)


# ───────────────────────────────────── الواجهة الموحّدة
def search(question: str) -> dict:
    """يُرجع ناتج المسارين ودرجة ثقة واحدة."""
    ensure_fresh()
    struct = structured(question)
    passages, confidence, used_vectors = semantic(question)

    if struct["tools"] or struct["category_tools"]:
        confidence = max(confidence, STRUCTURED_CONFIDENCE)

    return {
        "passages": passages,
        "confidence": confidence,
        "used_vectors": used_vectors,
        **struct,
        "has_any": bool(passages or struct["tools"] or struct["category_tools"]),
    }
