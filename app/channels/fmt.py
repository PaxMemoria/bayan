"""تنسيق الإجابة لكل قناة.

النموذج يكتب الخط العريض بصيغة Markdown (‎**نص**)، والقنوات لا تفهمها كما
هي: تيليغرام يعرض النجوم حرفياً ما لم يُطلب منه تنسيق، وواتساب يعرف نجمة
واحدة، وماسنجر لا يعرف أي تنسيق.

Formatting the answer for each channel.

The model writes bold in Markdown (**text**), which the channels do not
understand as it is: Telegram shows the asterisks literally unless told to
parse formatting, WhatsApp uses a single asterisk, and Messenger supports no
formatting at all.
"""
import html
import re

_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_UNDERLINE_BOLD = re.compile(r"__(.+?)__", re.S)
_HEADING = re.compile(r"^#{1,6}\s*(.+?)\s*#*\s*$", re.M)


def _normalise(text: str) -> str:
    """العناوين وصيغة __نص__ تصير **نص**، كي يعالج الباقي حالة واحدة.
    Headings and __text__ become **text**, so the rest handles one form."""
    text = _HEADING.sub(r"**\1**", text)
    return _UNDERLINE_BOLD.sub(r"**\1**", text)


def to_telegram_html(text: str) -> str:
    """HTML لوضع parse_mode=HTML في تيليغرام، بعد تهريب كل ما عداه.
    HTML for Telegram's parse_mode=HTML, with everything else escaped."""
    escaped = html.escape(_normalise(text), quote=False)
    return _BOLD.sub(r"<b>\1</b>", escaped)


def to_whatsapp(text: str) -> str:
    """واتساب: الخط العريض بنجمة واحدة.
    WhatsApp: bold uses a single asterisk."""
    return _BOLD.sub(r"*\1*", _normalise(text))


def to_plain(text: str) -> str:
    """بلا أي تنسيق، لماسنجر ولما يرفضه تيليغرام.
    No formatting at all, for Messenger and for whatever Telegram rejects."""
    return _BOLD.sub(r"\1", _normalise(text))
