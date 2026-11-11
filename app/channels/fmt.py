"""تنسيق الإجابة لكل قناة.

النموذج يكتب الخط العريض بصيغة Markdown (‎**نص**)، والقنوات لا تفهمها كما
هي: تيليغرام يعرض النجوم حرفياً ما لم يُطلب منه تنسيق، وواتساب يعرف نجمة
واحدة، وماسنجر لا يعرف أي تنسيق.

وفي القنوات كلها: العنوان الفرعي يُفصل في سطر مستقل فوق تفاصيله، والرسالة
العربية تُعرض من اليمين إلى اليسار في كل سطر.

Formatting the answer for each channel.

The model writes bold in Markdown (**text**), which the channels do not
understand as it is: Telegram shows the asterisks literally unless told to
parse formatting, WhatsApp uses a single asterisk, and Messenger supports no
formatting at all.

On every channel, a subheading is put on its own line above its details,
and an Arabic message is displayed right to left on every line.
"""
import html
import re

_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_UNDERLINE_BOLD = re.compile(r"__(.+?)__", re.S)
_HEADING = re.compile(r"^#{1,6}\s*(.+?)\s*#*\s*$", re.M)
# بند يبدأ بعنوان فرعي عريض تليه نقطتان، والنقطتان داخل العريض أو بعده:
# «- **رصد الحرائق:** التفاصيل» أو «1. **FlightAware**: التفاصيل».
# An item that opens with a bold subheading followed by a colon, inside or
# after the bold: "- **Fire detection:** details" or "1. **FlightAware**: details".
_LEAD_IN = re.compile(
    r"^[ \t]*(?:[-•*][ \t]+|(?P<num>\d+[.)])[ \t]+)?\*\*(?:"
    r"(?P<h1>[^*\n]+?)[ \t]*[:：]\*\*|(?P<h2>[^*\n]+?)\*\*[ \t]*[:：])"
    r"[ \t]*(?P<body>\S.*)$"
)
_ARABIC = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿ]")
_LATIN = re.compile(r"[A-Za-z]")
_URL = re.compile(r"https?://\S+")
RLM, LRM = "‏", "‎"


def _normalise(text: str) -> str:
    """العناوين وصيغة __نص__ تصير **نص**، كي يعالج الباقي حالة واحدة.
    Headings and __text__ become **text**, so the rest handles one form."""
    text = _HEADING.sub(r"**\1**", text)
    return _UNDERLINE_BOLD.sub(r"**\1**", text)


def _layout(text: str) -> str:
    """العنوان الفرعي في سطر مستقل، وتفاصيله في السطر الذي تحته، وسطر
    فارغ يفصله عمّا قبله.
    A subheading on its own line, its details on the line below, and a
    blank line separating it from what comes before."""
    out: list[str] = []
    for line in text.split("\n"):
        m = _LEAD_IN.match(line)
        if not m:
            out.append(line)
            continue
        if out and out[-1].strip():
            out.append("")
        head = (m["h1"] or m["h2"]).strip()
        num = f"{m['num']} " if m["num"] else ""
        out += [f"**{num}{head}**", m["body"].strip()]
    return "\n".join(out)


def _rtl(text: str) -> str:
    """رسالة عربية تُعرض من اليمين إلى اليسار في كل سطر.

    تيليغرام وواتساب يحددان اتجاه كل سطر بأول حرف فيه، فسطر عربي يبدأ
    باسم أداة لاتيني أو برابط يُعرض من اليسار. علامة RLM غير المرئية في
    أول كل سطر تجعله من اليمين، وعلامة LRM بعد الرابط الذي يشغل سطراً
    كاملاً تُبقي آخر حرف منه في مكانه. العربية تُعرف بأن حروفها أكثر من
    اللاتينية خارج الروابط.

    An Arabic message is displayed right to left on every line.

    Telegram and WhatsApp set each line's direction from its first letter,
    so an Arabic line that starts with a Latin tool name or a link is shown
    left to right. An invisible RLM at the start of each line makes it
    right to left, and an LRM after a link that fills a whole line keeps
    its last character in place. A message counts as Arabic when it has
    more Arabic letters than Latin ones outside links.
    """
    bare = _URL.sub("", text)
    if len(_ARABIC.findall(bare)) <= len(_LATIN.findall(bare)):
        return text
    lines = []
    for line in text.split("\n"):
        if not line.strip():
            lines.append(line)
        elif _URL.fullmatch(line.strip()):
            lines.append(RLM + line.strip() + LRM)
        else:
            lines.append(RLM + line)
    return "\n".join(lines)


def _prepare(text: str) -> str:
    return _rtl(_layout(_normalise(text)))


def to_telegram_html(text: str) -> str:
    """HTML لوضع parse_mode=HTML في تيليغرام، بعد تهريب كل ما عداه.
    HTML for Telegram's parse_mode=HTML, with everything else escaped."""
    escaped = html.escape(_prepare(text), quote=False)
    return _BOLD.sub(r"<b>\1</b>", escaped)


def to_whatsapp(text: str) -> str:
    """واتساب: الخط العريض بنجمة واحدة.
    WhatsApp: bold uses a single asterisk."""
    return _BOLD.sub(r"*\1*", _prepare(text))


def to_plain(text: str) -> str:
    """بلا أي تنسيق، لماسنجر ولما يرفضه تيليغرام.
    No formatting at all, for Messenger and for whatever Telegram rejects."""
    return _BOLD.sub(r"\1", _prepare(text))


def to_web(text: str) -> str:
    """للدردشة على الموقع: العناوين الفرعية في أسطرها، والخط العريض يبقى ‎**نص**
    ليعرضه الودجت عريضاً بنفسه، وبلا علامات الاتجاه (المتصفح يضبطه بـ dir=auto).
    For the website chat: subheadings on their own lines, bold kept as **text**
    for the widget to render, and no direction marks (the browser handles
    direction with dir=auto)."""
    return _layout(_normalise(text))
