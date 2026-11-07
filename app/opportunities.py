"""الفرص: الجزء الثالث من قاعدة بيان، موزّعة بالأسابيع.

تُلصَق قائمة الأسبوع من اللوحة، فتُقسَّم إلى فرصة لكل بند، وتُحفظ برقم أسبوعها
(ISO). يبحث بيان فيها حين يسأل السائل عن زمالة أو منحة أو جائزة أو تدريب،
وفي آخر OPPORTUNITY_WEEKS أسابيع فقط حتى لا يقترح فرصاً مضى وقتها.

Opportunities: the third part of Bayan's knowledge, split by week.

The week's list is pasted in the dashboard, split into one opportunity per
item and saved with its ISO week number. Bayan searches them when the asker
wants a fellowship, grant, award or training, and only in the last
OPPORTUNITY_WEEKS weeks so it does not suggest ones whose time has passed.
"""
import re

from . import config, store
from .arabic import normalize_ar, tokens

_ITEM = re.compile(r"^\s*(\d{1,3})\s*[.)\-–]\s*(.+?)\s*$")
_URL = re.compile(r"https?://\S+")

# كلمات تدلّ على أن السائل يريد فرصة، لا أداة ولا تحقيقاً
# Words that show the asker wants an opportunity, not a tool or an investigation
_INTENT = {normalize_ar(w) for w in (
    "فرصة", "فرص", "الفرص", "زمالة", "زمالات", "الزمالات", "منحة", "منح", "المنح",
    "جائزة", "جوائز", "الجوائز", "تدريب", "تدريبات", "ورشة", "ورش", "مسابقة",
    "مسابقات", "تقديم", "التقديم", "للتقديم", "ترشح", "الترشح", "دورة", "دورات",
    "ماجستير", "منحه", "opportunity", "opportunities", "fellowship", "fellowships",
    "grant", "grants", "scholarship", "scholarships", "award", "awards",
    "training", "workshop", "apply", "application", "deadline",
)}
_GENERIC = {normalize_ar(w) for w in ("فرص", "الفرص", "فرصة", "الاسبوع", "هذا", "المتاحة")}


def parse_list(text: str) -> list[dict]:
    """يقسّم قائمة مرقّمة إلى بنود {title, url}. البند: سطر «1. العنوان» ثم رابط
    في السطر نفسه أو الذي يليه. ما سوى ذلك (العنوان والتحية) يُهمَل.
    Splits a numbered list into {title, url} items. An item is a «1. Title» line
    with a link on the same line or the next one. Anything else is ignored."""
    items: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _ITEM.match(line)
        url = _URL.search(line)
        if m and not (url and line.startswith(url.group(0))):
            title = _URL.sub("", m.group(2)).strip(" |-–:")
            items.append({"title": title, "url": url.group(0) if url else ""})
        elif url and items and not items[-1]["url"]:
            items[-1]["url"] = url.group(0)
    return [i for i in items if i["title"] and i["url"]]


def wants_opportunity(question: str) -> bool:
    return bool(_INTENT & set(normalize_ar(question).replace("؟", " ").replace("?", " ").split()))


def match(question: str) -> list[dict]:
    """فرص آخر الأسابيع التي تلائم السؤال، الأوفق أولاً. تُشترط نيّة فرصة في السؤال.
    كلمة عامة مثل «فرص» تُرجع أحدث الفرص؛ وكلمات أخرى (اليمن، صحافة) ترتّب بالتداخل.
    Opportunities from the latest weeks that fit the question, best first. The
    question must show opportunity intent. A generic word such as «فرص» returns
    the newest; other words (Yemen, journalism) rank by overlap."""
    if not wants_opportunity(question):
        return []
    rows = store.recent_opportunities(config.OPPORTUNITY_WEEKS)
    if not rows:
        return []
    words = {w for w in tokens(question) if w not in _INTENT and w not in _GENERIC}
    scored = []
    for r in rows:
        title = set(tokens(r["title"]))
        hits = len(words & title)
        scored.append((hits, r["year"], r["week"], -r["position"], r))
    if words and any(s[0] for s in scored):
        scored = [s for s in scored if s[0]]
    scored.sort(key=lambda s: (-s[0], -s[1], -s[2], -s[3]))
    return [s[4] for s in scored[: config.OPPORTUNITIES_PER_QUESTION]]
