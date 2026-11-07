"""الاسترجاع بمسارين.

الأدوات قاعدة بيانات، فسؤال «ما أدوات تحليل صور الأقمار الصناعية؟» يُجاب
بتصفية على حقل التصنيف تعيد القائمة كاملة ومرتّبة — لا ببحث نصي يعيد
ستة مقاطع متفرقة. وسؤال «كيف أتحقق من تاريخ صورة؟» سؤال معنى، فيذهب
للمسار الدلالي. المساران يعملان معاً ويتغذّى النموذج من ناتجهما.

Retrieval along two paths.

Tools are a database, so a question like
«ما أدوات تحليل صور الأقمار الصناعية؟» ("What tools analyze satellite
images?") is answered by filtering on the category field, which returns
the full list in order, not by a text search that returns six scattered
passages. A question like «كيف أتحقق من تاريخ صورة؟» ("How do I verify
the date of a photo?") is a question of meaning, so it goes to the
semantic path. The two paths run together and the model is fed with
their output.
"""
import json
import logging
import math
import re
import threading
from collections import Counter

import numpy as np

from . import config, embed, i18n, overview, store
from .arabic import fts_query, normalize_ar, tokens, weighted_overlap

log = logging.getLogger("retrieve")
_lock = threading.Lock()

# صيغ تدل على طلب قائمة لا تعريف أداة بعينها
# Phrasings that point to a request for a list, not for a definition of
# one specific tool
LIST_INTENT = re.compile(
    r"\b(ادوات|اداه|قائمه|قائمة|ماهي|ما هي|اقترح|افضل|انواع|وش|شنو|كل ال)\b"
)
# درجة ثقة ثابتة للمطابقة المنظّمة: المطابقة هنا يقينية لا تقديرية
# Fixed confidence for a structured match: the match here is certain, not
# an estimate
STRUCTURED_CONFIDENCE = 0.95
# أنواع المقاطع التي لها نسختان بلغتين (slug الإنجليزية = العربية + "-en")
# Passage types that come in two language versions (English slug = Arabic + "-en")
TWIN_TYPES = ("investigation", "about")


class _State:
    """كل ما يُحمَّل من الفهرس إلى الذاكرة، يُستبدل دفعة واحدة.

    الاستبدال الذرّي يمنع سؤالاً يصل أثناء إعادة التحميل من قراءة مصفوفة
    متجهات جديدة مع معرّفات قديمة.

    Everything loaded from the index into memory, replaced all at once.

    The atomic swap stops a question that arrives during a reload from
    reading a new vector matrix with old IDs.
    """

    def __init__(self) -> None:
        self.version: str | None = None
        self.matrix = np.zeros((0, config.EMBED_DIM), dtype=np.float32)
        self.ids: list[int] = []
        self.vector_note = ""
        self.vector_note_en = ""
        self.categories: list[dict] = []
        self.tool_names: list[tuple[str, str]] = []  # (norm_name, name)
        self.idf: dict[str, float] = {}
        self.idf_unseen = 1.0
        # All investigations, in both languages
        self.inv_slugs: set[str] = set()  # كل التحقيقات بلغتيها
        self.banned: list[str] = []
        self.allowed: set[str] = set()
        self.overview = ""


_S = _State()


def norm_link(value: str) -> str:
    """صيغة موحّدة لرابط أو نطاق، لمقارنة ما يكتبه النموذج بالدليل.
    A normalized form of a link or domain, to compare what the model writes
    with the guide."""
    v = re.sub(r"^[a-z]+://", "", (value or "").strip().lower())
    return re.sub(r"^www\.", "", v).rstrip("/")


def warm() -> None:
    """تحميل المتجهات وجداول البحث — عند الإقلاع وكلما تغيّر الفهرس.
    Load the vectors and the search tables, at startup and whenever the
    index changes."""
    global _S
    with _lock:
        s = _State()
        s.version = store.index_version()

        matrix, ids = store.load_embeddings()
        built_with = store.setting("index_embed_model", "")
        reason = embed.unavailable_reason()
        if reason:
            s.vector_note = reason
            s.vector_note_en = embed.unavailable_reason("en")
        elif not ids:
            s.vector_note = "الفهرس بلا متجهات، أعد الفهرسة"
            s.vector_note_en = "The index has no vectors; reindex"
        elif built_with != embed.model_id() or matrix.shape[1] != config.EMBED_DIM:
            s.vector_note = (
                f"الفهرس مبني بـ {built_with or 'إعداد سابق'} والإعداد الحالي "
                f"{embed.model_id()}، أعد الفهرسة"
            )
            s.vector_note_en = (
                f"The index was built with {built_with or 'an earlier setting'} and "
                f"the current setting is {embed.model_id()}; reindex"
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
            s.inv_slugs = {
                json.loads(r["meta"]).get("slug", "") for r in conn.execute(
                    "SELECT DISTINCT meta FROM chunks WHERE type IN ('investigation', 'about')"
                ).fetchall()
            }
        s.idf = _build_idf(texts)
        # كلمة لا ترد في أي مقطع أندر من أندر كلمة موجودة: log(n)
        # A word found in no passage is rarer than the rarest word present: log(n)
        s.idf_unseen = math.log(max(len(texts), 2))

        banned, allowed = store.link_rules()
        s.banned = sorted({norm_link(b) for b in banned if norm_link(b)},
                          key=len, reverse=True)
        s.allowed = {norm_link(a) for a in allowed}
        s.overview = overview.build()
        _S = s


def ensure_fresh() -> None:
    """يعيد التحميل إن تغيّر الفهرس منذ آخر تحميل (فهرسة من عملية أخرى).
    Reload if the index changed since the last load (indexing from another
    process)."""
    if store.index_version() != _S.version:
        warm()


def status() -> dict:
    return {"vectors": len(_S.ids), "vector_note": _S.vector_note,
            "vector_note_en": _S.vector_note_en}


def link_rules() -> tuple[list[str], set[str]]:
    return _S.banned, _S.allowed


def guide_overview() -> str:
    """النظرة العامة على الدليل والتحقيقات (overview.py)، كما بُنيت من الفهرس
    الحالي.
    The overview of the guide and the investigations (overview.py), as built
    from the current index."""
    return _S.overview


def _build_idf(texts: list[str]) -> dict[str, float]:
    """وزن ندرة كل كلمة في قاعدة المعرفة، لاستعماله بلا متجهات.
    The rarity weight of each word in the knowledge base, for use without
    vectors."""
    df: Counter = Counter()
    for t in texts:
        df.update(set(tokens(t)))
    n = max(len(texts), 1)
    return {w: max(math.log(n / (1 + c)), 0.0) for w, c in df.items()}


# ───────────────────────────────────── المسار المنظّم / Structured path
def match_category(question: str) -> dict | None:
    """أطول تصنيف يرد اسمه (عربياً أو إنجليزياً) داخل السؤال.
    The longest category whose name (in Arabic or English) appears in the
    question."""
    q = normalize_ar(question)
    best = None
    for cat in _S.categories:
        for label in (cat["norm_category"], normalize_ar(cat["category_en"] or "")):
            if len(label) >= 4 and label in q:
                if best is None or len(label) > best[0]:
                    best = (len(label), cat)
    return best[1] if best else None


def match_tool_names(question: str, limit: int = 3) -> list[dict]:
    """أدوات يرد اسمها حرفياً في السؤال — الأطول اسماً أولاً.
    Tools whose name appears literally in the question, longest name first."""
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
    """ناتج المسار المنظّم: أدوات بالاسم و/أو قائمة تصنيف.
    Output of the structured path: tools by name and/or a category list."""
    result = {"tools": [], "category": None, "category_tools": []}

    result["tools"] = match_tool_names(question)

    cat = match_category(question)
    # لا نُخرج قائمة تصنيف كاملة إلا إذا بدا السؤال طلب قائمة، وإلا
    # فسؤال عن أداة واحدة في تصنيف ما يُغرق بقائمة لا يريدها السائل.
    # Only return a full category list when the question looks like a request
    # for a list. Otherwise a question about one tool in some category would
    # be flooded with a list the asker does not want.
    if cat and (LIST_INTENT.search(normalize_ar(question)) or not result["tools"]):
        tools = store.tools_in_category(cat["norm_category"], config.MAX_TOOLS_LISTED)
        if tools:
            result["category"] = cat
            result["category_tools"] = tools
    return result


# ───────────────────────────────────── المسار الدلالي / Semantic path
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


def _query_vector(question: str) -> np.ndarray | None:
    """متجه السؤال مُطبَّعاً، يُحسب مرة للبحث وللتصحيحات معاً، أو None.
    The question's normalized vector, computed once for both the search and
    the corrections, or None."""
    if not embed.enabled():
        return None
    try:
        vecs = embed.embed([question], input_type="query", retries=1)
    except Exception:  # noqa: BLE001 — تعطّل Voyage لا يُسكت بيان
        # A Voyage outage does not silence Bayan
        log.exception("تعذّر متجه السؤال — البحث اللفظي وحده لهذا السؤال")
        return None
    if not vecs:
        return None
    q = np.asarray(vecs[0], dtype=np.float32)
    return q / (np.linalg.norm(q) or 1.0)


def _vector(q: np.ndarray | None, limit: int, s: _State) -> tuple[list[int], dict[int, float]]:
    if q is None or s.matrix.shape[0] == 0 or len(q) != s.matrix.shape[1]:
        return [], {}
    sims = s.matrix @ q
    top = np.argsort(-sims)[:limit]
    return [s.ids[i] for i in top], {s.ids[i]: float(sims[i]) for i in top}


def _in_language(p: dict, lang: str, s: _State) -> bool:
    """تحقيق له نسخة بلغة السؤال لا يُعرض بلغته الأخرى.

    كي لا يأخذ التحقيق نفسه خانتين من المقاطع الستة، بالعربية وبالإنجليزية.
    slug النسخة الإنجليزية هو slug العربية مع "-en".

    An investigation that has a version in the question's language is not
    shown in its other language.

    This keeps the same investigation from taking two of the six passage
    slots, once in Arabic and once in English. The slug of the English
    version is the Arabic slug plus "-en".
    """
    if p["type"] not in TWIN_TYPES:
        return True
    plang = p["meta"].get("lang", "ar")
    if plang == lang:
        return True
    slug = p["meta"].get("slug", "")
    twin = f"{slug}-en" if plang == "ar" else slug.removesuffix("-en")
    return twin not in s.inv_slugs


def semantic(question: str, lang: str = "ar",
             q: np.ndarray | None = None) -> tuple[list[dict], float, bool]:
    """-> (مقاطع، ثقة، هل استُعملت المتجهات). q متجه السؤال إن حُسب سلفاً.
    -> (passages, confidence, whether vectors were used). q is the
    question's vector if it was already computed."""
    s = _S
    lex = _fts(question, config.CANDIDATES)
    if q is None:
        q = _query_vector(question)
    vec, sims = _vector(q, config.CANDIDATES, s)

    scores: dict[int, float] = {}
    for ranked in (lex, vec):
        for rank, cid in enumerate(ranked):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (60 + rank)
    if not scores:
        return [], 0.0, bool(sims)

    ordered = sorted(scores, key=scores.get, reverse=True)[: config.CANDIDATES]
    rows = store.get_chunks(ordered)
    passages = [rows[cid] for cid in ordered
                if cid in rows and _in_language(rows[cid], lang, s)][: config.TOP_K]
    if not passages:
        return [], 0.0, bool(sims)

    if sims:
        confidence = max(sims.get(p["id"], 0.0) for p in passages)
    else:
        # بلا متجهات: تداخل موزون بالندرة، مُعاير إلى مقياس العتبة نفسه
        # Without vectors: overlap weighted by rarity, rescaled to the same scale
        # as the threshold
        raw = max(weighted_overlap(question, p["text"], s.idf, s.idf_unseen)
                  for p in passages)
        confidence = raw * (config.MIN_RELEVANCE / config.LEXICAL_THRESHOLD)
    return passages, float(confidence), bool(sims)


# ───────────────────────────────────── الواجهة الموحّدة / Unified interface
def search(question: str, lang: str | None = None) -> dict:
    """يُرجع ناتج المسارين ودرجة ثقة واحدة.
    Return the output of both paths and a single confidence score."""
    ensure_fresh()
    lang = lang or i18n.detect(question)
    struct = structured(question)
    q = _query_vector(question)
    passages, confidence, used_vectors = semantic(question, lang, q)
    fixes = match_corrections(question, q)

    if struct["tools"] or struct["category_tools"]:
        confidence = max(confidence, STRUCTURED_CONFIDENCE)
    # تصحيح معتمد مطابق يجيز السؤال من البوابة بقدر شبهه
    # A matching approved correction lets the question through the gate, by
    # its similarity
    if fixes:
        confidence = max(confidence, fixes[0]["similarity"])

    return {
        "passages": passages,
        "confidence": confidence,
        "used_vectors": used_vectors,
        "corrections": fixes,
        **struct,
        "has_any": bool(passages or struct["tools"] or struct["category_tools"] or fixes),
    }


# ──────────────────────────────────────── التصحيحات المعتمدة / Approved corrections
# قوائم الفرص الأسبوعية: تصحيح لكل أسبوع سؤاله «فرص الأسبوع 45». السؤال العام
# عن الفرص بلا رقم يعيد أحدث أسبوع، وبرقم يعيد ذلك الأسبوع.
# Weekly opportunity lists: one correction per week, its question «فرص الأسبوع 45».
# A general question about opportunities without a number returns the latest
# week, and with a number returns that week.
_WEEKLY_Q = re.compile(r"^فرص(?: هذا)? الاسبوع (\d{1,2})$")
_OPPORTUNITY_WORDS = {"فرص", "الفرص"}


def _latest_weekly(norm_q: str) -> dict | None:
    """تصحيح أحدث أسبوع إن كان السؤال عاماً عن الفرص بلا رقم أسبوع، وإلا None.
    The latest week's correction if the question is a general one about
    opportunities with no week number, otherwise None."""
    if not _OPPORTUNITY_WORDS & set(norm_q.split()) or re.search(r"\d", norm_q):
        return None
    weekly = [(int(m.group(1)), c) for c in store.corrections(active_only=True)
              if (m := _WEEKLY_Q.match(c["norm_question"] or ""))]
    return max(weekly, key=lambda w: w[0])[1] if weekly else None


def match_corrections(question: str, q: np.ndarray | None) -> list[dict]:
    """التصحيحات المعتمدة التي يشبه سؤالُها سؤالَ السائل، الأقرب أولاً.

    السؤال نفسه بعد التطبيع يطابق دائماً. وبالمتجهات يطابق ما بلغ شبهه
    CORRECTION_MIN_SIMILARITY، إن وُلّد متجه التصحيح بنموذج المتجهات الحالي.

    The approved corrections whose question resembles the asker's, closest
    first.

    The same question, once normalized, always matches. With vectors, a
    correction matches when its similarity reaches CORRECTION_MIN_SIMILARITY,
    provided its vector was produced with the current embedding model.
    """
    norm_q, model = normalize_ar(question), embed.model_id()
    norm_words = set(norm_q.split())
    found = []
    for c in store.corrections(active_only=True):
        v = c.pop("vector")
        nq = c["norm_question"]
        if (
            nq == norm_q
            or (nq and " " not in nq and len(nq) >= 3 and nq in norm_words)
            or (len(nq) >= 8 and nq in norm_q)
        ):
            sim = 1.0
        elif (q is not None and v is not None and c["embed_model"] == model
              and len(v) == len(q)):
            sim = float(v @ q / (np.linalg.norm(v) or 1.0))
        else:
            continue
        if sim >= config.CORRECTION_MIN_SIMILARITY:
            found.append({**c, "similarity": sim})
    # عند التعادل يتقدّم التصحيح الأطول سؤالاً (الأخصّ)، ثم الأحدث تعديلاً
    # On a tie the correction with the longer (more specific) question goes first,
    # then the most recently edited
    found.sort(key=lambda c: (-c["similarity"], -len(c["norm_question"] or "")))
    if latest := _latest_weekly(norm_q):
        latest.pop("vector", None)
        found = [{**latest, "similarity": 1.0}] + [c for c in found if c["id"] != latest["id"]]
    return found[: config.CORRECTIONS_PER_QUESTION]


def embed_correction(question: str) -> tuple[list[float] | None, str | None]:
    """(متجه سؤال التصحيح، النموذج الذي ولّده)، أو (None، None) إن تعذّر،
    فيطابق التصحيح عندها السؤال نفسه وحده حتى يُولَّد متجهه.
    (the correction question's vector, the model that produced it), or
    (None, None) if that fails, in which case the correction matches only the
    same question until its vector is produced."""
    if not embed.enabled():
        return None, None
    try:
        vecs = embed.embed([question], input_type="query", retries=3)
    except Exception:  # noqa: BLE001
        log.exception("تعذّر متجه سؤال التصحيح")
        return None, None
    return (vecs[0], embed.model_id()) if vecs else (None, None)


def refresh_correction_vectors() -> int:
    """يولّد متجه كل تصحيح بلا متجه أو بمتجه من نموذج سابق، ويعيد عددها.
    Produces the vector of every correction with none, or with one from an
    earlier model, and returns how many."""
    if not embed.enabled():
        return 0
    model, n = embed.model_id(), 0
    for c in store.corrections():
        if c["vector"] is None or c["embed_model"] != model:
            vec, used = embed_correction(c["question"])
            if vec is not None:
                store.set_correction_vector(c["id"], vec, used)
                n += 1
    return n
