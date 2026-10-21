"""تطبيع النص العربي — ضروري لنجاح البحث النصي.

بدونه، "الاستثمار" و"الإستثمار" و"الاستثمـار" تُعامل ككلمات مختلفة.
"""
import re
import unicodedata

_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭ]")
_TATWEEL = "ـ"
# الحروف العربية فقط. النطاق العربي العام يشمل علامات الترقيم
# «؟» و«،» و«؛»، فإدراجها كان يجعل "فرنسا؟" كلمة لا تطابق
# "فرنسا" أبداً — خطأ كان يفسد كل استرجاع لسؤال منتهٍ بعلامة.
_ARABIC_LETTERS = "\u0621-\u063A\u0641-\u064A\u0671-\u06D3"
_NON_WORD = re.compile(rf"[^\w{_ARABIC_LETTERS}]+", re.UNICODE)
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")

# كلمات وظيفية تُحذف من استعلام البحث فقط (لا من النص المخزّن)
STOPWORDS = {
    "من", "الى", "على", "في", "عن", "مع", "هل", "ما", "ماذا", "متى", "اين",
    "كيف", "لماذا", "من", "هذا", "هذه", "ذلك", "تلك", "التي", "الذي", "الذين",
    "كان", "كانت", "يكون", "هو", "هي", "هم", "ان", "انه", "او", "و", "ثم",
    "قد", "كل", "بعض", "غير", "بين", "عند", "لدي", "اريد", "ممكن", "لو",
    "سمحت", "شكرا", "يرجى", "رجاء", "اعطني", "اخبرني", "وش", "شنو", "ايش",
    "the", "a", "an", "of", "in", "on", "to", "is", "are", "what", "how",
    "and", "or", "for", "about", "please", "tell", "me",
}


def normalize_ar(text: str) -> str:
    """توحيد شكل الحروف والأرقام وإزالة التشكيل."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = _DIACRITICS.sub("", text)
    text = text.replace(_TATWEEL, "")
    text = re.sub("[إأآٱا]", "ا", text)
    text = text.replace("ى", "ي").replace("ئ", "ي")
    text = text.replace("ؤ", "و").replace("ة", "ه")
    text = text.translate(_DIGITS)
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def tokens(text: str) -> list[str]:
    """تقطيع نص مطبّع إلى كلمات دلالية."""
    parts = [p for p in _NON_WORD.split(normalize_ar(text)) if p]
    return [p for p in parts if len(p) > 1 and p not in STOPWORDS]


def fts_query(question: str) -> str:
    """تحويل سؤال المستخدم إلى استعلام FTS5 آمن."""
    toks = tokens(question)[:16]
    if not toks:
        return ""
    return " OR ".join(f'"{t}"' for t in toks)


def weighted_overlap(question: str, passage: str, idf: dict[str, float]) -> float:
    """تداخل موزون بندرة الكلمات — بديل احتياطي للعتبة حين لا تتوفر متجهات.

    التداخل غير الموزون يضلّل: سؤال من كلمتين تطابق إحداهما كلمة شائعة
    يعطي 0.5 فيتجاوز العتبة. الوزن بالندرة يجعل مطابقة كلمة شائعة مثل
    "الحكومة" شبه عديمة الأثر، ومطابقة كلمة نادرة حاسمة.
    """
    q = tokens(question)
    if not q:
        return 0.0
    p = set(tokens(passage))
    total = sum(idf.get(t, 1.0) for t in q)
    if total <= 0:
        return 0.0
    hit = sum(idf.get(t, 1.0) for t in q if t in p)
    return hit / total
