"""نظرة عامة على المنظمة والدليل والتحقيقات، تُبنى من الفهرس عند كل تحميل له.

البحث يعطي النموذج مقاطع قليلة، فلا يرى منها الدليل كله: كم أداة فيه، وما
تصنيفاته، وما أحدث التحقيقات. هذه النظرة تجيب عن تلك الأسئلة العامة، وتُرسل
في تعليمات النظام المخزّنة مؤقتاً، فلا تزيد كلفة كل سؤال إلا قليلاً.

An overview of the organization, the guide and the investigations, built
from the index every time it is loaded.

Search gives the model a few passages, so it never sees the guide as a
whole: how many tools it holds, its categories, the latest investigations.
This overview answers those general questions, and it is sent in the cached
system instructions, so it adds little to the cost of each question.
"""
import json
import re
from datetime import date

from . import config, store

# رقما النظرة العامة في سطر [SOURCES]، بعيدان عن أرقام المصادر المسترجعة
# The overview's numbers in the [SOURCES] line, far from the retrieved
# sources' numbers
GUIDE_NO, INVESTIGATIONS_NO, ABOUT_NO = 0, 100, 200

_MONTHS = {
    "يناير": 1, "كانون الثاني": 1, "فبراير": 2, "شباط": 2, "مارس": 3, "آذار": 3,
    "أبريل": 4, "نيسان": 4, "مايو": 5, "أيار": 5, "يونيو": 6, "حزيران": 6,
    "يوليو": 7, "تموز": 7, "أغسطس": 8, "آب": 8, "سبتمبر": 9, "أيلول": 9,
    "أكتوبر": 10, "تشرين الأول": 10, "نوفمبر": 11, "تشرين الثاني": 11,
    "ديسمبر": 12, "كانون الأول": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}


def _when(text: str | None) -> date:
    """تاريخ النشر من نصه («نُشر في 9 آب/أغسطس 2026» أو «Published August 9,
    2026») للترتيب وحده. ما لا يُقرأ يأتي في آخر القائمة.
    The publication date from its text, for sorting only. Whatever cannot be
    read goes to the end of the list."""
    t = (text or "").lower()
    year = re.search(r"\b(19|20)\d{2}\b", t)
    day = re.search(r"\b(\d{1,2})\b", t)
    month = next((n for name, n in sorted(_MONTHS.items(), key=lambda x: -len(x[0]))
                  if name in t), None)
    if not (year and month):
        return date.min
    try:
        return date(int(year.group(0)), month, int(day.group(1)) if day else 1)
    except ValueError:
        return date.min


def _dek(title: str | None, text: str) -> str:
    """ملخص التحقيق كما نُشر، من رأس مقطعه الأول («العنوان — الملخص»).
    The investigation's standfirst as published, from the head of its first
    passage ("Title — standfirst")."""
    head = (text or "").split("\n", 1)[0]
    prefix = f"{title} — "
    return head[len(prefix):].strip()[:400] if title and head.startswith(prefix) else ""


def _about(rows) -> str:
    """صفحة «من نحن» العربية كاملة كما في الموقع: أقسامها بالترتيب، كل قسم
    باسمه ثم نصّه. صغيرة، فتُرسل كلها، فلا تتوقف إجابة سؤال عن المنظمة على
    ترتيب البحث.
    The whole Arabic About page as on the site: its sections in order, each
    with its name and then its text. It is small, so all of it is sent, and
    an answer about the organization never depends on how search ranks it."""
    parts = sorted(
        (json.loads(r["meta"]).get("position", 0), r["text"]) for r in rows
        if json.loads(r["meta"]).get("slug") == "about"
    )
    out = []
    for _, text in parts:
        head, _, body = text.partition("\n\n")
        section = head.split("\n")[-1].removeprefix("القسم:").strip()
        out.append(f"{section}:\n{body.strip()}" if section and "\n" in head
                   else body.strip() or head.strip())
    return "\n\n".join(out)[:5000]


def _n(n: int, few: str, many: str) -> str:
    """العدد ومعدوده: «5 أدوات» من 3 إلى 10، و«598 أداة» و«54 تصنيفاً» فيما عداها.
    A number and its counted noun, with the Arabic plural for 3 to 10 and the
    singular otherwise."""
    return f"{n} {few if 3 <= n % 100 <= 10 else many}"


def build() -> str:
    with store.db() as conn:
        n = conn.execute(
            "SELECT SUM(removed=0) avail, SUM(removed=0 AND sensitive=1) sens, "
            "SUM(removed=1) removed FROM tools"
        ).fetchone()
        rows = conn.execute(
            "SELECT title, url, meta, text FROM chunks WHERE type='investigation'"
        ).fetchall()
        about = conn.execute(
            "SELECT text, meta FROM chunks WHERE type='about'"
        ).fetchall()
    cats = store.categories()
    if not (n and n["avail"]):
        return ""

    stories: dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: json.loads(r["meta"]).get("position", 0)):
        m = json.loads(r["meta"])
        stories.setdefault(m.get("slug", ""), {
            "title": r["title"], "url": r["url"], "date": m.get("date"),
            "author": m.get("author"), "dek": _dek(r["title"], r["text"]),
        })
    lines = []
    bases = sorted({s.removesuffix("-en") for s in stories if s},
                   key=lambda b: _when((stories.get(b) or stories[b + "-en"])["date"]),
                   reverse=True)
    for base in bases:
        ar, en = stories.get(base), stories.get(base + "-en")
        main = ar or en
        line = f"- {main['title']}"
        if main["date"]:
            line += f" | {main['date']}"
        if main["author"]:
            line += f" | إعداد: {main['author']}"
        line += f" | {main['url']}"
        if ar and en:
            line += f" | بالإنجليزية: {en['title']} | {en['url']}"
        if main["dek"]:
            line += f"\n  ملخصه: {main['dek']}"
        lines.append(line)

    site = config.SITE_URL
    cat_lines = "\n".join(
        f"  - {c['category_ar']} ({c['category_en']}): {c['n']}" for c in cats
    )
    who = _about(about)
    org = (f'<نظرة_عامة رقم="{ABOUT_NO}" موضوع="{config.ORG_NAME}">\n'
           f"- صفحة «من نحن»: {site}/about\n{who}\n</نظرة_عامة>\n\n" if who else "")
    return org + f"""<نظرة_عامة رقم="{GUIDE_NO}" موضوع="الدليل">
- صفحة الدليل: {site}/osint-tools، وفيها خانة بحث بالاسم أو الوصف.
- في الدليل {_n(n['avail'], 'أدوات', 'أداة')} متاحة في {_n(len(cats), 'تصنيفات', 'تصنيفاً')}، منها {_n(n['sens'] or 0, 'أدوات', 'أداة')} حسّاسة تُفتح بحذر. وأُزيلت منه {_n(n['removed'] or 0, 'أدوات', 'أداة')} لم تعد موصى بها.
- يصف الدليل كل أداة كما كانت في آخر تدقيق.
- لا يذكر الدليل لكل أداة إن كانت مجانية أو مدفوعة، لكن معظم أدواته مجانية ومتاحة للاستخدام. وقد تتغيّر الأسعار وشروط الاستخدام، فالمرجع فيها صفحة الأداة نفسها وسياسة المنصة التي تعمل عليها.
- التصنيفات وعدد الأدوات المتاحة في كل منها:
{cat_lines}
</نظرة_عامة>

<نظرة_عامة رقم="{INVESTIGATIONS_NO}" موضوع="التحقيقات">
- صفحة التحقيقات: {site}/investigations
- التحقيقات المنشورة من الأحدث إلى الأقدم ({_n(len(bases), 'تحقيقات', 'تحقيقاً')}):
{chr(10).join(lines)}
</نظرة_عامة>"""
