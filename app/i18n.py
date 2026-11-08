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
        "text_only": {
            "ar": "أقرأ النص فقط، ولا أستطيع فحص الصور أو الفيديو أو الصوت أو الملفات.\n"
                  "اكتب سؤالك نصاً عن أداة في دليلنا أو عن أحد تحقيقاتنا.",
            "en": "I read text only, and can't check photos, video, audio or files.\n"
                  "Type your question about a tool in our guide or one of our "
                  "investigations.",
        },
        "reset": {"ar": "حُذفت محادثتك المحفوظة، وبدأت محادثة جديدة. اكتب سؤالك.",
                  "en": "Your saved conversation was deleted and a new one started. "
                        "Ask your question."},
        "subscribed": {
            "ar": "اشتركت في قائمة الفرص الأسبوعية، وستصلك هنا كل أسبوع حين تُنشر.\n"
                  "لإلغاء الاشتراك في أي وقت اكتب /unsubscribe",
            "en": "You are subscribed to the weekly opportunities list. It will reach "
                  "you here every week when it is published.\n"
                  "To unsubscribe at any time, send /unsubscribe",
        },
        "subscribed_later": {
            "ar": "سُجّل اشتراكك في قائمة الفرص الأسبوعية. الإرسال على هذه القناة لم "
                  "يُفعَّل بعد، وستصلك القائمة حين يُفعَّل. حتى ذلك الحين اكتب «فرص» في "
                  "أي وقت لتصلك آخر قائمة.\nلإلغاء الاشتراك اكتب /unsubscribe",
            "en": "Your subscription to the weekly opportunities list is recorded. "
                  "Sending on this channel is not enabled yet, and the list will reach "
                  "you once it is. Until then, write \"فرص\" at any time to get the "
                  "latest list.\nTo unsubscribe, send /unsubscribe",
        },
        "already_subscribed": {
            "ar": "أنت مشترك في قائمة الفرص الأسبوعية من قبل. لإلغاء الاشتراك اكتب /unsubscribe",
            "en": "You are already subscribed to the weekly opportunities list. "
                  "To unsubscribe, send /unsubscribe",
        },
        "unsubscribed": {
            "ar": "أُلغي اشتراكك، ولن تصلك قائمة الفرص بعد الآن. للاشتراك مجدداً اكتب /subscribe",
            "en": "You are unsubscribed, and the opportunities list will no longer be "
                  "sent to you. To subscribe again, send /subscribe",
        },
        "not_subscribed": {
            "ar": "لست مشتركاً في قائمة الفرص. للاشتراك اكتب /subscribe",
            "en": "You are not subscribed to the opportunities list. To subscribe, "
                  "send /subscribe",
        },
        "broadcast_footer": {
            "ar": "وصلتك هذه القائمة لأنك مشترك. لإلغاء الاشتراك اكتب /unsubscribe",
            "en": "You received this list because you subscribed. To unsubscribe, "
                  "send /unsubscribe",
        },
    }


# ردّ التحية بمثلها، بالنص بعد التطبيع (أ←ا، ة←ه). ما ليس هنا يُجاب بـ«أهلاً وسهلاً».
# A greeting answered in kind, keyed by the normalized text (أ to ا, ة to ه).
# Anything else gets "أهلاً وسهلاً".
GREETING_REPLIES = {
    "السلام عليكم": "وعليكم السلام ورحمة الله وبركاته 👋",
    "سلام": "وعليكم السلام 👋",
    "صباح الخير": "صباح النور 👋",
    "مساء الخير": "مساء النور 👋",
    "good morning": "Good morning 👋",
    "good evening": "Good evening 👋",
}
OPENERS = {"ar": "أهلاً بك 👋", "en": "Hello 👋"}


def greeting_reply(key: str, lang: str) -> str:
    """الرسالة الأولى بعد تحية: مثلها إن عُرفت، وإلا ترحيب عام بلغتها.
    The first message after a greeting: in kind if known, else a general
    welcome in its language."""
    return GREETING_REPLIES.get(key) or ("Hello 👋" if lang == "en" else "أهلاً وسهلاً 👋")


def welcome(lang: str | None, limit: int, opener: str | None = None) -> str:
    """الترحيب بلغة السائل، أو باللغتين إن لم تُعرف لغته. opener السطر الأول:
    None يعني «أهلاً بك» بلغته، و"" يعني بلا سطر أول (جاء ردّ التحية قبله).
    The welcome in the asker's language, or in both if it is not known. opener
    is the first line: None means "أهلاً بك" in its language, and "" means no
    first line (the greeting reply came before it)."""
    def one(code: str) -> str:
        base = config.WELCOME_MESSAGE_EN if code == "en" else config.WELCOME_MESSAGE_AR
        first = OPENERS[code] if opener is None else opener
        if first:
            base = f"{first}\n\n{base}"
        lines = []
        if limit > 0:
            lines.append(f"Limit: {limit} questions every 24 hours." if code == "en"
                         else f"حدّ الأسئلة: {limit} في كل 24 ساعة.")
        lines.append("Weekly opportunities list: /subscribe" if code == "en"
                     else "الاشتراك في قائمة الفرص الأسبوعية: /subscribe")
        lines.append("Privacy policy: /privacy" if code == "en" else "سياسة الخصوصية: /privacy")
        return base + "\n" + "\n".join(lines)
    if lang in ("ar", "en"):
        return one(lang)
    return f"{one('ar')}\n\n{one('en')}"


def privacy(lang: str | None) -> str:
    """رابط سياسة الخصوصية وخلاصتها، بلغة السائل أو باللغتين.
    The privacy policy link and its gist, in the asker's language or both."""
    url = f"{(config.PUBLIC_URL or config.SITE_URL).rstrip('/')}/privacy"
    days = config.MESSAGE_RETENTION_DAYS
    ar = (f"سياسة خصوصية بيان: {url}\n"
          f"نحفظ أسئلتك وإجاباتها مدة {days} يوماً ثم نحذفها تلقائياً. "
          "اكتب /reset لحذف محادثتك الآن.")
    en = (f"Bayan's privacy policy: {url}\n"
          f"We keep your questions and answers for {days} days, then delete them "
          "automatically. Send /reset to delete your conversation now.")
    if lang == "ar":
        return ar
    if lang == "en":
        return en
    return f"{ar}\n\n{en}"


def from_hint(hint: str | None) -> str | None:
    """لغة واجهة السائل كما ترسلها القناة (تيليغرام: language_code).
    The asker's interface language as the channel sends it (Telegram:
    language_code)."""
    if not hint:
        return None
    return "ar" if hint.lower().startswith("ar") else "en"


def msg(key: str, lang: str, **kw) -> str:
    text = _messages()[key]["en" if lang == "en" else "ar"]
    return text.format(**kw) if kw else text


def both(key: str) -> str:
    """الرسالة باللغتين، لما لا لغة له مثل الأوامر.
    The message in both languages, for input with no language, such as commands."""
    m = _messages()[key]
    return f"{m['ar']}\n\n{m['en']}"
