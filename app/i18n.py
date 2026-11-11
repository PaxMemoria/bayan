"""اللغات: كشف لغة السؤال، ورسائل بيان الثابتة من ملفات الترجمة.

كل لغة ملف JSON واحد في app/locales (ar.json، en.json، pt-BR.json…) يحمل
كل نص يصل الجمهور: الرفض والترحيب والإيقاف المؤقت والحدّ اليومي وردود
التحية وخلاصة الخصوصية. العربية والإنجليزية هما الأصل، وبقية اللغات ترجمة
عنهما. لإضافة لغة: ملف جديد باسم رمزها، ثم رمزها في SUPPORTED_LANGUAGES،
والكلمات الدالة عليها في _MARKERS إن كانت بالحرف اللاتيني. ما ينقص من ملف
يُؤخذ من الإنجليزية.

كشف اللغة بلا مكتبات: الحرف أولاً (عربي، فارسي/أردو بحروفهما الخاصة،
ديفاناغاري)، ثم للحرف اللاتيني كلمات شائعة وحروف مميزة لكل لغة، والإنجليزية
لما لم يُعرف. حرفان عربيان أو أكثر يجعلان السؤال عربياً مهما طال اسم أداة
لاتيني فيه («ما هي أداة Google Earth Pro؟»)، واسم أداة وحده إنجليزي.

Languages: detect the question's language, and Bayan's fixed messages from
the translation files.

Each language is one JSON file in app/locales (ar.json, en.json,
pt-BR.json, ...) holding every text the public gets: the refusal, welcome,
paused and daily-limit texts, the greeting replies and the privacy gist.
Arabic and English are the originals; the other languages are translations
of them. To add a language: a new file named after its code, its code in
SUPPORTED_LANGUAGES, and its marker words in _MARKERS if it uses the Latin
script. Whatever a file lacks is taken from English.

Detection without libraries: the script first (Arabic, Persian/Urdu by
their own letters, Devanagari), then for the Latin script common words and
distinctive characters per language, and English for anything unknown.
Two or more Arabic letters make a question Arabic however long a Latin
tool name in it («ما هي أداة Google Earth Pro؟»), and a bare tool name
is English.
"""
import re

from . import config
from .arabic import normalize_ar

# رمز كل لغة مدعومة؛ الترتيب هو ترتيب الحسم عند تعادل الكلمات الدالة
# Every supported language's code; the order breaks ties between marker words
SUPPORTED_LANGUAGES = ("ar", "en", "pt-BR", "es", "fr", "sw", "hi", "ur", "fa", "tr", "id")
FALLBACK = "en"

LOCALES: dict[str, dict] = {code: config.load_locale(code) for code in SUPPORTED_LANGUAGES}


def language_name(lang: str) -> str:
    """اسم اللغة كما يُكتب للنموذج في <لغة_الإجابة>: «العربية» و"English" وبقية
    اللغات باسمها الإنجليزي ("Portuguese (Brazil)").
    The language's name as written for the model in <لغة_الإجابة>: «العربية»,
    "English", and the others by their English name ("Portuguese (Brazil)")."""
    if lang == "ar":
        return "العربية"
    return LOCALES.get(lang, LOCALES[FALLBACK])["language"]["name"]


def script_of(lang: str) -> str:
    return LOCALES.get(lang, LOCALES[FALLBACK])["language"].get("script", "latin")


def source_language(lang: str) -> str:
    """لغة المصادر التي تُسترجع وتُكتب بها سجلات الأدوات: العربية للغات الحرف
    العربي، والإنجليزية لغيرها؛ النموذج يترجم منها إلى لغة الإجابة.
    The language the sources are retrieved and the tool records written in:
    Arabic for Arabic-script languages, English for the rest; the model
    translates from it into the answer language."""
    return "ar" if script_of(lang) == "arabic" else "en"


# ───────────────────────────────────────────────── كشف اللغة / Detection
_ARABIC = re.compile(r"[ء-يٱ-ۓ]")
# حروف لا تستعملها العربية: الأردو أولاً (حروفها الخاصة)، ثم الفارسية
# Letters Arabic does not use: Urdu first (its own letters), then Persian
_URDU = re.compile(r"[ےٹڈڑںھہ]")
_PERSIAN = re.compile(r"[پچژگکی]")
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_LATIN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ɏ]")
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

# كلمات شائعة لكل لغة لاتينية الحرف. كلمة تظهر في لغتين تُحسب لهما معاً، والحسم
# عند التعادل بالحروف المميزة ثم بترتيب SUPPORTED_LANGUAGES.
# Common words per Latin-script language. A word shared by two languages
# counts for both; ties go to the distinctive characters, then to the order
# of SUPPORTED_LANGUAGES.
_MARKERS: dict[str, set[str]] = {
    "en": {"the", "what", "is", "are", "how", "do", "does", "can", "i", "you", "to", "for",
           "of", "and", "in", "on", "with", "tool", "tools", "which", "where", "when",
           "hello", "hi", "hey", "thanks", "please", "this", "that", "it", "my", "me",
           "your", "find", "photo", "photos", "video", "about", "there", "have", "has",
           "was", "were", "be", "an", "or", "not", "by", "from", "any", "who", "why",
           "good", "morning", "evening"},
    "pt-BR": {"olá", "ola", "oi", "bom", "boa", "dia", "tarde", "noite", "você", "vocês",
              "não", "sim", "como", "qual", "quais", "onde", "quando", "para", "com", "uma",
              "um", "o", "os", "as", "é", "são", "por", "ferramenta", "ferramentas",
              "posso", "pode", "obrigado", "obrigada", "quero", "preciso", "e", "em", "do",
              "da", "dos", "das", "na", "nos", "nas", "há", "tem", "têm", "muito", "mais",
              "esse", "essa", "isso", "saber", "eu", "nós", "ajuda", "existe", "foto",
              "fotos", "vídeo", "investigação", "investigações", "sobre", "alguma",
              "algum", "tirada", "descobrir", "localizar", "está", "aqui", "isto"},
    "es": {"hola", "qué", "cómo", "cuál", "cuáles", "dónde", "cuándo", "para", "con", "una",
           "un", "el", "la", "los", "las", "es", "son", "por", "herramienta", "herramientas",
           "puedo", "puede", "usted", "gracias", "quiero", "necesito", "buenos", "buenas",
           "días", "tardes", "noches", "y", "en", "del", "al", "hay", "tiene", "tienen",
           "si", "sí", "muy", "más", "ese", "esa", "esto", "eso", "saber", "yo",
           "nosotros", "ayuda", "existe", "foto", "fotos", "vídeo", "investigación",
           "investigaciones", "sobre", "alguna", "algún", "tomada", "averiguar",
           "ubicar", "está", "aquí", "ustedes", "tienes"},
    "fr": {"bonjour", "bonsoir", "salut", "merci", "le", "la", "les", "des", "une", "un",
           "est", "sont", "comment", "quel", "quelle", "quels", "quelles", "où", "quand",
           "pour", "avec", "vous", "je", "nous", "sur", "dans", "pas", "outil", "outils",
           "quoi", "qui", "que", "ce", "cette", "ces", "il", "elle", "et", "ou", "du",
           "au", "aux", "être", "avez", "puis", "s'il", "plaît", "savoir", "photo",
           "photos", "vidéo", "enquête", "enquêtes", "avoir", "y", "à", "trouver",
           "prise", "été", "voudrais", "peux", "peut", "aide"},
    "tr": {"merhaba", "selam", "günaydın", "nasıl", "ne", "bir", "için", "ve", "bu", "mi",
           "mı", "mu", "mü", "nedir", "araç", "aracı", "araçlar", "var", "ile", "hangi",
           "nerede", "ben", "siz", "lütfen", "teşekkürler", "yardım", "edebilir",
           "misiniz", "fotoğraf", "fotoğrafın", "video", "araştırma", "araştırmalar",
           "hakkında", "çekildiğini", "bulurum", "nasil", "da", "de", "ya", "şey",
           "bana", "size", "iyi", "akşamlar", "günler"},
    "id": {"halo", "hai", "apa", "bagaimana", "yang", "dan", "ini", "itu", "saya", "anda",
           "untuk", "dengan", "tidak", "bisa", "alat", "cara", "dari", "adalah", "selamat",
           "pagi", "siang", "sore", "malam", "terima", "kasih", "di", "ke", "ada", "mana",
           "kapan", "foto", "video", "investigasi", "tentang", "mengetahui", "diambil",
           "tolong", "mohon", "bantu", "kami", "kalian", "atau", "juga", "sebuah",
           "sudah", "belum", "apakah", "berapa"},
    "sw": {"habari", "jambo", "hujambo", "shikamoo", "mambo", "karibu", "asante", "tafadhali",
           "nini", "ni", "na", "ya", "wa", "kwa", "za", "la", "vipi", "gani", "je", "zana",
           "kifaa", "picha", "video", "uchunguzi", "kuhusu", "nawezaje", "unaweza",
           "ninaweza", "kujua", "ilipigwa", "wapi", "lini", "mimi", "wewe", "sisi", "hii",
           "hiyo", "ile", "ipi", "zipi", "mna", "kuna", "iko", "yako", "yangu", "yetu",
           "nzuri", "salama", "kupata"},
}
# حروف لا تكاد تظهر إلا في لغة واحدة: وزنها كلمتان
# Characters that hardly appear outside one language: worth two words
_LETTERS: dict[str, str] = {
    "pt-BR": "ãõçÃÕÇ", "es": "ñ¿¡Ñ", "fr": "œŒ", "tr": "ğışİĞŞ",
}


def detect(text: str) -> str:
    """رمز اللغة من SUPPORTED_LANGUAGES. بلا حروف أصلاً: العربية، لغة بيان الأولى.
    The language code from SUPPORTED_LANGUAGES. With no letters at all:
    Arabic, Bayan's first language."""
    text = text or ""
    if len(_ARABIC.findall(text)) >= 2:
        if _URDU.search(text):
            return "ur"
        if _PERSIAN.search(text):
            return "fa"
        return "ar"
    if len(_DEVANAGARI.findall(text)) >= 2:
        return "hi"
    if len(_LATIN.findall(text)) < 2:
        return "ar" if not _WORD.search(text) else FALLBACK
    words = [w.lower() for w in _WORD.findall(text)]
    scores: dict[str, float] = {}
    for lang, markers in _MARKERS.items():
        score = sum(1 for w in words if w in markers)
        score += 2 * sum(1 for ch in text if ch in _LETTERS.get(lang, ""))
        if score:
            scores[lang] = score
    if not scores:
        return FALLBACK
    best = max(scores.values())
    for lang in SUPPORTED_LANGUAGES:
        if scores.get(lang) == best:
            return lang
    return FALLBACK


def from_hint(hint: str | None) -> str | None:
    """لغة واجهة السائل كما ترسلها القناة (تيليغرام: language_code مثل "pt-br"
    أو "en-GB"): الرمز المدعوم المطابق، أو المطابق بجزئه الأول، وإلا الإنجليزية.
    The asker's interface language as the channel sends it (Telegram:
    language_code such as "pt-br" or "en-GB"): the matching supported code,
    or the one matching its first part, else English."""
    if not hint:
        return None
    hint = hint.strip().lower()
    for code in SUPPORTED_LANGUAGES:
        if hint == code.lower():
            return code
    primary = hint.split("-")[0].split("_")[0]
    for code in SUPPORTED_LANGUAGES:
        if code.lower().split("-")[0] == primary:
            return code
    return FALLBACK


# ───────────────────────────────────────────────── النصوص / The texts
def _text(key: str, lang: str) -> str:
    loc = LOCALES.get(lang) or LOCALES[FALLBACK]
    return loc.get(key) or LOCALES[FALLBACK][key]


def _names(lang: str) -> dict[str, str]:
    """اسم بيان والمنظمة بالحرف المناسب للغة: العربي للغات الحرف العربي، وإلا
    الإنجليزي. The bot's and the organisation's names in the script that fits
    the language: Arabic for Arabic-script languages, English otherwise."""
    if script_of(lang) == "arabic":
        return {"bot_name": config.BOT_NAME, "org_name": config.ORG_NAME,
                "site_url": config.SITE_URL}
    return {"bot_name": config.BOT_NAME_EN, "org_name": config.ORG_NAME_EN,
            "site_url": config.SITE_URL}


# النصوص التي تُحرَّر من صفحة «دور بيان» بالعربية والإنجليزية: التعديل هناك يسري
# على لغته وحدها، وبقية اللغات تبقى على نص ملفها.
# The texts edited on the "Bayan's role" page in Arabic and English: an edit
# there applies to its language alone; the other languages keep their file's text.
_EDITABLE: dict[str, tuple[str, str]] = {
    "out_of_scope": ("OUT_OF_SCOPE_MESSAGE", "OUT_OF_SCOPE_MESSAGE_EN"),
    "welcome": ("WELCOME_MESSAGE_AR", "WELCOME_MESSAGE_EN"),
    "paused": ("PAUSED_MESSAGE", "PAUSED_MESSAGE_EN"),
    "error": ("ERROR_MESSAGE", "ERROR_MESSAGE_EN"),
}


def _message(key: str, lang: str) -> str:
    if key in _EDITABLE and lang in ("ar", "en"):
        return getattr(config, _EDITABLE[key][1 if lang == "en" else 0])
    text = _text(key, lang)
    if key in _EDITABLE:
        text = text.format(**_names(lang))
    return text


def msg(key: str, lang: str, **kw) -> str:
    """رسالة ثابتة بلغة السائل؛ لغة غير مدعومة تُعامل إنجليزية.
    A fixed message in the asker's language; an unsupported language is
    treated as English."""
    lang = lang if lang in LOCALES else FALLBACK
    text = _message(key, lang)
    return text.format(**kw) if kw else text


def both(key: str) -> str:
    """الرسالة بالعربية والإنجليزية، لما لا لغة له مثل الأوامر.
    The message in Arabic and English, for input with no language, such as
    commands."""
    return f"{msg(key, 'ar')}\n\n{msg(key, 'en')}"


def hours(seconds: float, lang: str) -> str:
    """المدة بالساعات مقرّبة إلى الأعلى، كي لا يعود السائل قبل موعده.
    The duration in hours, rounded up, so the asker does not come back too
    early."""
    if seconds < 3600:
        return msg("hour_less", lang)
    n = int(-(-seconds // 3600))
    if n == 1:
        return msg("hour_one", lang)
    if n == 2:
        return msg("hours_two", lang, n=n)
    return msg("hours_few" if n <= 10 else "hours_many", lang, n=n)


# ───────────────────────────────────────────────── التحية / Greetings
def greeting_key(text: str) -> str:
    """نص التحية بعد التطبيع (أ←ا، ة←ه، أحرف صغيرة، بلا ترقيم) للمقارنة.
    The greeting's text after normalization (أ to ا, ة to ه, lower case, no
    punctuation) for comparison."""
    return " ".join(normalize_ar(re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)).split())


# ردّ التحية بمثلها، بالنص بعد التطبيع، من كل اللغات معاً. ما ليس هنا يُجاب
# بترحيب اللغة العام («أهلاً وسهلاً»، "Hello"، "Olá").
# A greeting answered in kind, keyed by the normalized text, from every
# language together. Anything else gets the language's general greeting
# («أهلاً وسهلاً», "Hello", "Olá").
GREETING_REPLIES: dict[str, str] = {
    greeting_key(k): v for loc in LOCALES.values() for k, v in loc["greeting_replies"].items()
}
# كل التحيات التي تُجاب بالترحيب بدل الرفض / Every greeting answered with the
# welcome instead of the refusal
GREETINGS: set[str] = set(GREETING_REPLIES) | {
    greeting_key(g) for loc in LOCALES.values() for g in loc["greetings"]
}
OPENERS: dict[str, str] = {code: loc["opener"] for code, loc in LOCALES.items()}


def greeting_reply(key: str, lang: str) -> str:
    """الرسالة الأولى بعد تحية: مثلها إن عُرفت، وإلا ترحيب عام بلغتها.
    The first message after a greeting: in kind if known, else a general
    welcome in its language."""
    return GREETING_REPLIES.get(key) or msg("greeting", lang)


def welcome(lang: str | None, limit: int, opener: str | None = None,
            commands: bool = True) -> str:
    """الترحيب بلغة السائل، أو بالعربية والإنجليزية إن لم تُعرف لغته. opener
    السطر الأول: None يعني «أهلاً بك» بلغته، و"" يعني بلا سطر أول (جاء ردّ
    التحية قبله).
    The welcome in the asker's language, or in Arabic and English if it is not
    known. opener is the first line: None means "أهلاً بك" in its language,
    and "" means no first line (the greeting reply came before it).

    commands=False يحذف سطري /subscribe و/privacy، لقناة لا أوامر فيها (الموقع،
    وفيه رابط الخصوصية تحت النافذة). commands=False drops the /subscribe and
    /privacy lines, for a channel with no commands (the website, which shows
    the privacy link under the window)."""
    def one(code: str) -> str:
        base = msg("welcome", code)
        first = msg("opener", code) if opener is None else opener
        if first:
            base = f"{first}\n\n{base}"
        # الحدّ اليومي يُطبَّق ولا يُعلَن عدده / The daily limit applies but its
        # number is not announced
        lines = []
        if commands:
            lines.append(msg("welcome_subscribe", code))
            lines.append(msg("welcome_privacy", code))
        return base + ("\n" + "\n".join(lines) if lines else "")
    if lang in LOCALES:
        return one(lang)
    return f"{one('ar')}\n\n{one('en')}"


def privacy(lang: str | None) -> str:
    """رابط سياسة الخصوصية وخلاصتها، بلغة السائل أو بالعربية والإنجليزية.
    The privacy policy link and its gist, in the asker's language or in
    Arabic and English."""
    url = f"{(config.PUBLIC_URL or config.SITE_URL).rstrip('/')}/privacy"
    days = config.MESSAGE_RETENTION_DAYS

    def one(code: str) -> str:
        return msg("privacy_gist", code, url=url, days=days, **_names(code))
    if lang in LOCALES:
        return one(lang)
    return f"{one('ar')}\n\n{one('en')}"
