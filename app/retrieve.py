"""الاسترجاع بمسارين.

الأدوات قاعدة بيانات، فسؤال «ما أدوات تحليل صور الأقمار الصناعية؟» يُجاب
بتصفية على حقل التصنيف تعيد القائمة كاملة ومرتّبة — لا ببحث نصي يعيد
ستة مقاطع متفرقة. وسؤال «كيف أتحقق من تاريخ صورة؟» سؤال معنى، فيذهب
للمسار الدلالي. المساران يعملان معاً ويتغذّى النموذج من ناتجهما.
"""
import re
import threading

import numpy as np

from . import config, embed, store
from .arabic import fts_query, normalize_ar, tokens, weighted_overlap

_lock = threading.Lock()
_matrix: np.ndarray | None = None
_ids: list[int] = []
_categories: list[dict] = []
_tool_names: list[tuple[str, str]] = []  # (norm_name, name)
_idf: dict[str, float] = {}

# صيغ تدل على طلب قائمة لا تعريف أداة بعينها
LIST_INTENT = re.compile(
    r"\b(ادوات|اداه|قائمه|قائمة|ماهي|ما هي|اقترح|افضل|انواع|وش|شنو|كل ال)\b"
)
# درجة ثقة ثابتة للمطابقة المنظّمة: المطابقة هنا يقينية لا تقديرية
STRUCTURED_CONFIDENCE = 0.95


def warm() -> None:
    """تحميل المتجهات وجداول البحث — عند الإقلاع وبعد كل فهرسة."""
    global _matrix, _ids, _categories, _tool_names
    with _lock:
        _matrix, _ids = store.load_embeddings()
        _categories = store.categories()
        with store.db() as conn:
            rows = conn.execute(
                "SELECT norm_name, name FROM tools WHERE LENGTH(norm_name) >= 4"
            ).fetchall()
        with store.db() as conn:
            texts = [r["norm_text"] for r in
                     conn.execute("SELECT norm_text FROM chunks").fetchall()]
        _tool_names = [(r["norm_name"], r["name"]) for r in rows]
        _idf = _build_idf(texts)


def _build_idf(texts: list[str]) -> dict[str, float]:
    """وزن ندرة كل كلمة في قاعدة المعرفة، لاستعماله بلا متجهات."""
    import math
    from collections import Counter

    df: Counter = Counter()
    for t in texts:
        df.update(set(tokens(t)))
    n = max(len(texts), 1)
    return {w: math.log(n / (1 + c)) for w, c in df.items()}


# ───────────────────────────────────── المسار المنظّم
def match_category(question: str) -> dict | None:
    """أطول تصنيف يرد اسمه (عربياً أو إنجليزياً) داخل السؤال."""
    q = normalize_ar(question)
    best = None
    for cat in _categories:
        for label in (cat["norm_category"], normalize_ar(cat["category_en"] or "")):
            if len(label) >= 4 and label in q:
                if best is None or len(label) > best[0]:
                    best = (len(label), cat)
    return best[1] if best else None


def match_tool_names(question: str, limit: int = 3) -> list[dict]:
    """أدوات يرد اسمها حرفياً في السؤال — الأطول اسماً أولاً."""
    q = normalize_ar(question)
    hits = [(len(n), name) for n, name in _tool_names if n in q]
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


def _vector(question: str, limit: int) -> tuple[list[int], dict[int, float]]:
    if _matrix is None or _matrix.shape[0] == 0:
        return [], {}
    vecs = embed.embed([question], input_type="query")
    if not vecs:
        return [], {}
    q = np.asarray(vecs[0], dtype=np.float32)
    sims = _matrix @ (q / (np.linalg.norm(q) or 1.0))
    top = np.argsort(-sims)[:limit]
    return [_ids[i] for i in top], {_ids[i]: float(sims[i]) for i in top}


def semantic(question: str) -> tuple[list[dict], float]:
    lex = _fts(question, config.CANDIDATES)
    vec, sims = _vector(question, config.CANDIDATES)

    scores: dict[int, float] = {}
    for ranked in (lex, vec):
        for rank, cid in enumerate(ranked):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (60 + rank)
    if not scores:
        return [], 0.0

    ordered = sorted(scores, key=scores.get, reverse=True)[: config.TOP_K]
    rows = store.get_chunks(ordered)
    passages = [rows[cid] for cid in ordered if cid in rows]
    if not passages:
        return [], 0.0

    if sims:
        confidence = max(sims.get(p["id"], 0.0) for p in passages)
    else:
        # بلا متجهات: تداخل موزون بالندرة، مُعاير إلى مقياس العتبة نفسه
        raw = max(weighted_overlap(question, p["text"], _idf) for p in passages)
        confidence = raw * (config.MIN_RELEVANCE / config.LEXICAL_THRESHOLD)
    return passages, float(confidence)


# ───────────────────────────────────── الواجهة الموحّدة
def search(question: str) -> dict:
    """يُرجع ناتج المسارين ودرجة ثقة واحدة."""
    struct = structured(question)
    passages, confidence = semantic(question)

    if struct["tools"] or struct["category_tools"]:
        confidence = max(confidence, STRUCTURED_CONFIDENCE)

    return {
        "passages": passages,
        "confidence": confidence,
        **struct,
        "has_any": bool(passages or struct["tools"] or struct["category_tools"]),
    }
