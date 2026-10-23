"""اللغتان: كشف لغة السؤال، ورسائل بيان الثابتة بالعربية والإنجليزية.

القاعدة: حرفان عربيان أو أكثر في السؤال يجعلانه عربياً، وإلا فالحروف
اللاتينية تجعله إنجليزياً. أسماء الأدوات لاتينية في الغالب، فسؤال مثل
«ما هي أداة Google Earth Pro؟» يبقى عربياً مهما طال الاسم. وأي لغة أخرى
تُجاب بالعربية، لغة بيان الأولى.

Two languages: detect the question's language, and Bayan's fixed messages
in Arabic and English.

The rule: two or more Arabic letters in the question make it Arabic;
otherwise, Latin letters make it English. Tool names are mostly in Latin
letters, so a question like «ما هي أداة Google Earth Pro؟» ("What is the
Google Earth Pro tool?") stays Arabic however long the name is. Any other
language is answered in Arabic, Bayan's first language.
"""
import re

from . import config

_ARABIC = re.compile(r"[ء-يٱ-ۓ]")
_LATIN = re.compile(r"[A-Za-z]")


def detect(text: str) -> str:
    """'ar' أو 'en'.
    'ar' or 'en'."""
    if len(_ARABIC.findall(text or "")) >= 2:
        return "ar"
    return "en" if len(_LATIN.findall(text or "")) >= 2 else "ar"


def hours(seconds: float, lang: str) -> str:
    """المدة بالساعات مقرّبة إلى الأعلى، كي لا يعود السائل قبل موعده.
    The duration in hours, rounded up, so the asker does not come back too
    early."""
    if seconds < 3600:
        return "less than an hour" if lang == "en" else "أقل من ساعة"
    n = int(-(-seconds // 3600))
    if lang == "en":
        return "1 hour" if n == 1 else f"{n} hours"
    if n == 1:
        return "ساعة"
    if n == 2:
        return "ساعتين"
    return f"{n} ساعات" if n <= 10 else f"{n} ساعة"


def _messages() -> dict[str, dict[str, str]]:
    return {
        "out_of_scope": {"ar": config.OUT_OF_SCOPE_MESSAGE,
                         "en": config.OUT_OF_SCOPE_MESSAGE_EN},
        "paused": {"ar": config.PAUSED_MESSAGE, "en": config.PAUSED_MESSAGE_EN},
        "error": {"ar": config.ERROR_MESSAGE, "en": config.ERROR_MESSAGE_EN},
        "rate": {
            "ar": "أرسلت رسائل كثيرة خلال وقت قصير. انتظر دقيقة ثم أعد المحاولة.",
            "en": "You sent many messages in a short time. Please wait a minute "
                  "and try again.",
        },
        "daily": {
            "ar": "بلغت أسئلتك في آخر 24 ساعة الحدّ المسموح، وهو {limit}.\n"
                  "يمكنك أن تسأل مجدداً بعد {wait}.\n"
                  "دليل الأدوات والتحقيقات متاحان دائماً على {site}",
            "en": "You have reached the limit of {limit} questions in the last "
                  "24 hours.\nYou can ask again in {wait}.\n"
                  "The tools guide and the investigations are always at {site}",
        },
        "sources": {"ar": "🔗 المصدر:", "en": "🔗 Source:"},
    }


def msg(key: str, lang: str, **kw) -> str:
    text = _messages()[key]["en" if lang == "en" else "ar"]
    return text.format(**kw) if kw else text


def both(key: str) -> str:
    """الرسالة باللغتين، لما لا لغة له مثل الأوامر.
    The message in both languages, for input with no language, such as commands."""
    m = _messages()[key]
    return f"{m['ar']}\n\n{m['en']}"
