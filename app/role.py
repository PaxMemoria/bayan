"""دور بيان من اللوحة، للمدير وحده.

ما كان يُغيَّر بتعديل الكود أو .env وإعادة التشغيل صار يُحرَّر من صفحة
«دور بيان»: اسم بيان باللغتين، ونطاقه (السطر الثاني من تعليمات النظام)،
وقواعد إضافية من الفريق تُلحق بالتعليمات، وأسلوب الردّ (النبرة والطول)،
ونصوص الرفض والترحيب والإيقاف المؤقت باللغتين.
يُحفظ في جدول الإعدادات بمفاتيح role:…، ويتقدّم على قيمة .env، ويُطبَّق
فوراً؛ والحقل الفارغ يعني العودة إلى الافتراضي. كل حفظ يُسجَّل في سجلّ
الإجراءات باسم الحقل.

Bayan's role from the dashboard, for the admin only.

What used to need a code or .env change and a restart is edited on the
"Bayan's role" page: Bayan's name in both languages, its scope (the second
line of the system instructions), extra team rules appended to the
instructions, the response style (tone and length), and the refusal, welcome
and paused texts in both languages. Saved in the settings
table under role:… keys, taking precedence over the .env value and applied
at once; an empty field means back to the default. Every save goes to the
audit log with the field's name.
"""
from . import config, store

MAX_CHARS = 4000
MAX_NAME_CHARS = 40

# الأقسام والحقول: (العربية، الإنجليزية) لكل تسمية، والسمة في config التي يحلّ محلها.
# كل حقل (المفتاح، السمة، التسمية، الإضافة): التسمية "ar" أو "en" للنصوص باللغتين،
# أو (العربية، الإنجليزية) لحقل باسم خاص. نوع القسم "kind": نص متعدد الأسطر
# (الافتراضي، الإضافة عدد الأسطر)، أو "line" سطر واحد (الإضافة أقصى عدد حروف)،
# أو "select" اختيار من قائمة (الإضافة الخيارات: (القيمة، (العربية، الإنجليزية))).
# Sections and fields: (Arabic, English) for each label, and the config
# attribute it replaces. Each field is (key, attribute, label, extra): the label
# is "ar" or "en" for texts in both languages, or (Arabic, English) for a field
# with a name of its own. The section's "kind": a multi-line text (the default,
# extra = rows), "line" for a single line (extra = max characters), or "select"
# for a choice from a list (extra = the options: (value, (Arabic, English))).
SECTIONS: list[dict] = [
    {
        "key": "name",
        "kind": "line",
        "title": ("اسم بيان", "Bot name"),
        "help": ("اسم البوت كما يظهر في تعليمات النظام وفي عنوان اللوحة وحين يُنادى في "
                 "المجموعات، بالعربية وبالإنجليزية. من حرف إلى 40 حرفاً في سطر واحد. "
                 "النصوص الافتراضية للرفض والترحيب والإيقاف المؤقت تذكر الاسم الأصلي، فمن "
                 "يغيّر الاسم يعدّلها أيضاً في أقسامها أدناه.",
                 "The bot's name as it appears in the system instructions, in the dashboard "
                 "title and when it is called in groups, in Arabic and in English. One to 40 "
                 "characters on one line. The default refusal, welcome and paused texts "
                 "mention the original name, so whoever renames the bot also edits them in "
                 "their sections below."),
        "fields": [("name_ar", "BOT_NAME", "ar", MAX_NAME_CHARS),
                   ("name_en", "BOT_NAME_EN", "en", MAX_NAME_CHARS)],
    },
    {
        "key": "scope",
        "title": ("نطاق بيان", "Bayan's scope"),
        "help": ("السطر الذي يعرّف بيان بحدود عمله في تعليمات النظام، ويُذكر بالعربية "
                 "للنموذج وبالإنجليزية في التعريف بالبوت. سطر أو سطران.",
                 "The line that tells Bayan the limits of its work in the system "
                 "instructions, in Arabic for the model and in English where the bot "
                 "is described. One or two lines."),
        "fields": [("scope_ar", "SCOPE_DESCRIPTION", "ar", 3),
                   ("scope_en", "SCOPE_DESCRIPTION_EN", "en", 3)],
    },
    {
        "key": "rules",
        "title": ("قواعد إضافية من الفريق", "Extra team rules"),
        "help": ("تُلحق بتعليمات النظام تحت عنوان «قواعد إضافية من الفريق» وتسري مع "
                 "القواعد الثابتة ولا تُلغيها: لا معرفة عامة، ولا روابط لأدوات حسّاسة. "
                 "اكتب القواعد بالعربية، كل قاعدة في سطر، مثل: «لا تذكر أسعار الأدوات».",
                 "Appended to the system instructions under an \"extra team rules\" "
                 "heading; they apply alongside the fixed rules and cannot override "
                 "them: no general knowledge, no links to sensitive tools. Write the "
                 "rules in Arabic, one per line, such as «لا تذكر أسعار الأدوات»."),
        "fields": [("rules", "TEAM_RULES", "ar", 8)],
    },
    {
        "key": "style",
        "kind": "select",
        "title": ("أسلوب الردّ", "Response style"),
        "help": ("النبرة والطول في قسم «الأسلوب» من تعليمات النظام. الافتراضي: فصحى مبسطة "
                 "وإنجليزية واضحة، من جملتين إلى ست. بقية القواعد (لا معرفة عامة، لا أحكام "
                 "أمان، الأرقام الغربية) تسري كما هي مع كل اختيار.",
                 "The tone and length in the \"style\" section of the system instructions. "
                 "The default: simplified fusha and plain English, two to six sentences. "
                 "The other rules (no general knowledge, no safety verdicts, Western digits) "
                 "apply unchanged with every choice."),
        "fields": [
            ("tone", "RESPONSE_TONE", ("النبرة", "Tone"),
             [("formal", ("رسمية: فصحى مبسطة", "Formal: simplified fusha / plain English")),
              ("friendly", ("ودودة: مباشرة بصيغة المخاطب", "Friendly: direct, addressing the asker"))]),
            ("length", "RESPONSE_LENGTH", ("الطول", "Length"),
             [("short", ("قصير: جملة إلى ثلاث", "Short: one to three sentences")),
              ("medium", ("متوسط: من جملتين إلى ست", "Medium: two to six sentences")),
              ("long", ("طويل: حتى عشر جمل", "Long: up to ten sentences"))]),
        ],
    },
    {
        "key": "refusal",
        "title": ("رسالة الرفض", "Refusal message"),
        "help": ("ما يصل السائل حين يكون سؤاله خارج النطاق. الحقلان للعربية والإنجليزية "
                 "وحدهما؛ بقية اللغات تقرأ نصّها من ملفات الترجمة في app/locales ولا "
                 "يغيّرها التعديل هنا.",
                 "What the asker gets when the question is outside the scope. The two "
                 "fields are for Arabic and English only; the other languages read their "
                 "text from the translation files in app/locales, and an edit here does "
                 "not change them."),
        "fields": [("refusal_ar", "OUT_OF_SCOPE_MESSAGE", "ar", 10),
                   ("refusal_en", "OUT_OF_SCOPE_MESSAGE_EN", "en", 10)],
    },
    {
        "key": "welcome",
        "title": ("رسالة الترحيب", "Welcome message"),
        "help": ("بعد /start أو تحية. يُضاف إليها تلقائياً سطر «أهلاً بك» أو ردّ التحية، "
                 "وحدّ الأسئلة اليومي، ورابطا الاشتراك والخصوصية. بالعربية والإنجليزية "
                 "وحدهما؛ بقية اللغات على نص ملفاتها في app/locales.",
                 "After /start or a greeting. The opening line or greeting reply, the "
                 "daily limit and the subscribe and privacy lines are added automatically. "
                 "Arabic and English only; the other languages keep the text of their "
                 "files in app/locales."),
        "fields": [("welcome_ar", "WELCOME_MESSAGE_AR", "ar", 14),
                   ("welcome_en", "WELCOME_MESSAGE_EN", "en", 14)],
    },
    {
        "key": "paused",
        "title": ("رسالة الإيقاف المؤقت", "Paused message"),
        "help": ("ما يصل السائل حين يكون بيان متوقفاً من الإعدادات. بالعربية والإنجليزية "
                 "وحدهما؛ بقية اللغات على نص ملفاتها في app/locales.",
                 "What the asker gets while Bayan is paused from Settings. Arabic and "
                 "English only; the other languages keep the text of their files in "
                 "app/locales."),
        "fields": [("paused_ar", "PAUSED_MESSAGE", "ar", 3),
                   ("paused_en", "PAUSED_MESSAGE_EN", "en", 3)],
    },
]
FIELDS: dict[str, str] = {f: attr for s in SECTIONS for f, attr, _, _ in s["fields"]}
KINDS: dict[str, str] = {f: s.get("kind", "text") for s in SECTIONS for f, _, _, _ in s["fields"]}
# قيم حقول الاختيار المسموحة / The allowed values of the select fields
OPTIONS: dict[str, list[str]] = {f: [v for v, _ in extra] for s in SECTIONS
                                 if s.get("kind") == "select" for f, _, _, extra in s["fields"]}
# الافتراضي: ما قرأه config من .env أو من الكود عند الإقلاع
# The default: what config read from .env or the code at startup
DEFAULTS: dict[str, str] = {f: getattr(config, attr) for f, attr in FIELDS.items()}


def _key(field: str) -> str:
    return f"role:{field}"


def apply_saved() -> int:
    """عند الإقلاع: النصوص المحفوظة تحلّ محل الافتراضية.
    At startup: the saved texts replace the defaults."""
    n = 0
    for field, attr in FIELDS.items():
        value = store.setting(_key(field), "")
        if value and (KINDS[field] != "select" or value in OPTIONS[field]):
            setattr(config, attr, value)
            n += 1
    return n


def save(field: str, value: str, by: str) -> None:
    """يحفظ نصاً ويطبّقه؛ الفارغ أو المطابق للافتراضي يعيد الافتراضي.
    Saves a text and applies it; empty or equal to the default restores the
    default."""
    if field not in FIELDS:
        raise ValueError(field)
    value = value.replace("\r\n", "\n").strip()
    kind = KINDS[field]
    if kind == "select":
        if value and value not in OPTIONS[field]:
            raise ValueError("choice")
    elif kind == "line":
        if len(value) > MAX_NAME_CHARS or "\n" in value:
            raise ValueError("name")
    elif len(value) > MAX_CHARS:
        raise ValueError("too long")
    attr = FIELDS[field]
    if not value or value == DEFAULTS[field]:
        store.clear_setting(_key(field))
        setattr(config, attr, DEFAULTS[field])
        store.audit(by, "role_reset", field)
    else:
        store.set_setting(_key(field), value)
        setattr(config, attr, value)
        store.audit(by, "role_saved", field)


# معاينة السيناريوهات: سؤال نموذجي لكل حالة، يُجاب بالإعدادات الحالية كما لو
# جاء من قناة، دون أن يُسجَّل. الحالتان الثابتتان (التحية والإيقاف) بلا نموذج.
# Scenario preview: a sample question per case, answered with the current
# settings as if it came from a channel, without being logged. The two static
# cases (greeting and paused) need no model.
SCENARIOS: list[dict] = [
    {"key": "greeting", "label": ("تحية أولى", "A first greeting"),
     "q": ("السلام عليكم", "Hello"), "static": True},
    {"key": "out_of_scope", "label": ("سؤال خارج النطاق", "An out-of-scope question"),
     "q": ("ما أفضل مطعم في ستوكهولم؟", "What's the best restaurant in Stockholm?")},
    {"key": "tool", "label": ("سؤال عن أداة", "A tool question"),
     "q": ("ما هي أداة FotoForensics وهل هي آمنة؟", "What is FotoForensics and is it safe?")},
    {"key": "guide", "label": ("سؤال عن الدليل كله", "A question about the whole guide"),
     "q": ("ما الأدوات في الدليل؟", "What tools are in the guide?")},
    {"key": "investigation", "label": ("سؤال عن التحقيقات", "An investigations question"),
     "q": ("ما تحقيقاتكم عن اليمن؟", "What investigations do you have on Yemen?")},
    {"key": "safety", "label": ("سؤال في السلامة الرقمية", "A digital-safety question"),
     "q": ("كيف أحمي حسابي بالاستيثاق بمعاملين؟",
           "How do I protect my account with two-factor authentication?")},
    {"key": "opportunities", "label": ("طلب الفرص «فرص»", "The opportunities request «فرص»"),
     "q": ("فرص", "فرص")},
    {"key": "about", "label": ("من أنتم؟", "Who are you?"),
     "q": ("من أنتم؟", "Who are you?")},
    {"key": "paused", "label": ("بيان متوقف مؤقتاً", "Bayan paused"), "q": ("", ""),
     "static": True},
]


def preview(key: str, lang: str) -> dict:
    """ردّ بيان على سيناريو بالإعدادات الحالية: {question, messages, outcome,
    confidence, sources}. ValueError لسيناريو غير معروف.
    Bayan's reply to a scenario with the current settings. ValueError for an
    unknown scenario."""
    from . import brain, i18n  # استيراد محلي: brain لا يستورد هذه الوحدة / local import

    scenario = next((s for s in SCENARIOS if s["key"] == key), None)
    if scenario is None:
        raise ValueError(key)
    lang = "en" if lang == "en" else "ar"
    question = scenario["q"][1 if lang == "en" else 0]
    if key == "greeting":
        reply = (i18n.greeting_reply(brain._greeting_key(question), lang) + brain.MESSAGE_BREAK
                 + i18n.welcome(lang, brain.daily_limit(), opener=""))
        return {"question": question, "messages": brain.messages(reply), "outcome": "",
                "confidence": None, "sources": []}
    if key == "paused":
        return {"question": "", "messages": [i18n.msg("paused", lang)], "outcome": "",
                "confidence": None, "sources": []}
    res = brain.answer(question, "admin", "preview")
    return {"question": question, "messages": brain.messages(res["text"]),
            "outcome": res["outcome"], "confidence": res["confidence"],
            "sources": res.get("sources") or []}


def current(field: str) -> tuple[str, bool]:
    """(النص الحالي، هل عُدّل من اللوحة). (the current text, whether it was
    edited from the dashboard)."""
    value = getattr(config, FIELDS[field])
    return value, value != DEFAULTS[field]
