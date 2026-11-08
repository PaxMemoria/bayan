"""إعدادات بيان — تُقرأ من متغيرات البيئة (.env).

Bayan's settings, read from environment variables (.env).
"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "knowledge.db"

# ───────────────────────────────── مصدر المعرفة / Knowledge source
# نسخة للقراءة فقط من مستودع الموقع، يسحبها هذا الخادم بنفسه.
# لا يحمل مستودع الموقع أياً من أسرار بيان.
# A read-only copy of the site repository, which this server pulls itself.
# The site repository holds none of Bayan's secrets.
SITE_REPO = Path(os.getenv("SITE_REPO", DATA_DIR / "paxmemoria-site"))
SITE_REPO_URL = os.getenv(
    "SITE_REPO_URL", "https://github.com/PaxMemoria/paxmemoria-site.git"
)
SITE_BRANCH = os.getenv("SITE_BRANCH", "main")
EXPORT_DIR = SITE_REPO / "bayan-export"
KNOWLEDGE_PATH = Path(os.getenv("KNOWLEDGE_PATH", EXPORT_DIR / "knowledge.jsonl"))
TOOLS_PATH = Path(os.getenv("TOOLS_PATH", EXPORT_DIR / "tools.json"))

# سرّ الإشارة التي يرسلها workflow الموقع لطلب إعادة الفهرسة.
# هذا هو السرّ الوحيد الذي يملكه مستودع الموقع، وأقصى ضرر تسريبه
# إعادة فهرسة غير لازمة.
# Secret for the signal the site workflow sends to request reindexing.
# This is the only secret the site repository holds, and the worst harm
# from leaking it is an unnecessary reindex.
REINDEX_SECRET = os.getenv("REINDEX_SECRET", "")

# ───────────────────────────────── النماذج / Models
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANSWER_MODEL = os.getenv("ANSWER_MODEL", "claude-sonnet-5-5")
# التفكير تكيّفي في نماذج الجيل الحالي، ورموزه تُحسب من max_tokens، فالحدّ
# أعلى من طول الإجابة نفسها كي لا تُقطع.
# Thinking is adaptive on current models and its tokens count against
# max_tokens, so the cap is well above the answer's own length.
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "4000"))
# عمق التفكير: low أو medium أو high. لا temperature: أُزيلت من الواجهة في
# 21 تشرين الأول/أكتوبر 2026، والنماذج الحالية لا تقبل إلا القيم الافتراضية.
# medium لأن القواعد التحريرية صارمة، و low أرخص إن ثبت أنها تكفي.
# Thinking depth: low, medium or high. No temperature: the API removed it
# on 21 October 2026 and current models accept only the defaults. medium
# because the editorial rules are strict; low is cheaper if it holds up.
ANSWER_EFFORT = os.getenv("ANSWER_EFFORT", "medium")
# إن رفض مصنِّف الأمان سؤالاً، تُعيده واجهة Anthropic على نموذج بديل
# (fallbacks: "default"). في Sonnet 5.5 يُعاد رفض فئتي cyber و frontier_llm
# فقط، فيحمي أسئلة الأمن الرقمي المشروعة عن أدوات الدليل. "off" يعطّله.
# If a safety classifier declines a question, the API reruns it on a
# fallback model (fallbacks: "default"). On Sonnet 5.5 only the cyber and
# frontier_llm categories are retried, which protects legitimate security
# questions about the guide's tools. "off" disables it.
ANSWER_FALLBACK = os.getenv("ANSWER_FALLBACK", "default").strip().lower()
# بديل تلقائي عند توقف Claude (أو مزوّد أساسي إن لم يُضبط مفتاح Anthropic
# أو ضُبط ANSWER_MODEL على نموذج gemini-*). المفتاح يُرسل في الترويسة
# x-goog-api-key فلا يظهر في عنوان الطلب ولا في السجلّات.
# Automatic fallback when Claude is unavailable (or primary provider if
# ANTHROPIC_API_KEY is unset or ANSWER_MODEL is set to a gemini-* model).
# The key is sent in the x-goog-api-key header so it never appears in the
# request URL or logs.
# مزوّد محلي بواجهة متوافقة مع OpenAI (llama.cpp server أو Ollama أو vLLM)، يُستعمل
# أساسياً حين ANSWER_MODEL=local. بلا تكلفة لكل سؤال، لكنه يحتاج خادماً يحمل النموذج.
# إن تعذّر، يُحوَّل إلى Gemini إن كان له مفتاح. LOCAL_LLM_KEY اختياري.
# A local provider with an OpenAI-compatible API (llama.cpp server, Ollama or
# vLLM), used as primary when ANSWER_MODEL=local. No cost per question, but it
# needs a server that holds the model. If it fails, Gemini takes over when it
# has a key. LOCAL_LLM_KEY is optional.
LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "http://127.0.0.1:8080/v1").rstrip("/")
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "")
LOCAL_LLM_KEY = os.getenv("LOCAL_LLM_KEY", "")
# مهلة الاستدعاء المحلي. الطلب الأول بعد الإقلاع يقرأ طلب بيان كاملاً (نحو 7 آلاف
# رمز) على المعالج فيستغرق دقائق؛ لذلك يُسخَّن النموذج عند الإقلاع، وتبقى المهلة
# طويلة لأن ردود التعليقات لا ينتظرها أحد على الشاشة.
# The local call's timeout. The first request after start-up reads Bayan's
# whole prompt (about 7,000 tokens) on the CPU and takes minutes; hence the
# warm-up at start-up, and a long timeout, since nobody waits on screen for a
# comment reply.
LOCAL_LLM_TIMEOUT = int(os.getenv("LOCAL_LLM_TIMEOUT", "900"))
# مزوّد الردود الخاصة على تعليقات فيسبوك وحدها: local، أو gemini-…، أو فارغ فيُستعمل
# المزوّد العام. الرد على التعليق لا ينتظره أحد على الشاشة، فيحتمل بطء النموذج
# المحلي (نحو دقيقة ونصف على الخادم)، والمحادثات تبقى على المزوّد العام.
# The provider for private replies to Facebook comments only: local, gemini-…,
# or empty for the general provider. Nobody waits on screen for a comment
# reply, so it can bear the local model's slowness (about a minute and a half
# on the server), while chats stay on the general provider.
COMMENT_ANSWER_MODEL = os.getenv("COMMENT_ANSWER_MODEL", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_ENDPOINT = os.getenv(
    "GEMINI_ENDPOINT", "https://generativelanguage.googleapis.com/v1beta/models"
)

# ───────────────────────────────── المتجهات / Vectors
# local  : voyage-4-nano على الخادم نفسه، فلا يغادر سؤال الجمهور الخادم.
# voyage : خدمة Voyage عبر MongoDB Atlas، وتحتاج VOYAGE_API_KEY.
# local  : voyage-4-nano on the server itself, so questions from the
#          public never leave the server.
# voyage : the Voyage service through MongoDB Atlas; needs VOYAGE_API_KEY.
EMBED_PROVIDER = os.getenv("EMBED_PROVIDER", "local").strip().lower()
# تغيير النموذج أو الأبعاد يستلزم إعادة الفهرسة: يُعطَّل البحث الدلالي حتى
# تُعاد الفهرسة، لأن متجهات إعدادين مختلفين لا تُقارَن.
# Changing the model or the dimensions requires reindexing: semantic search
# is disabled until the index is rebuilt, because vectors from two
# different settings cannot be compared.
EMBED_MODEL = os.getenv(
    "EMBED_MODEL", "voyage-4-nano" if EMBED_PROVIDER == "local" else "voyage-4"
)
EMBED_DIM = int(os.getenv("EMBED_DIM", "1024"))
LOCAL_MODEL_DIR = Path(
    os.getenv("LOCAL_MODEL_DIR", DATA_DIR / "models" / "voyage-4-nano")
)
# أنوية المعالج للنموذج المحلي. 0 يترك القرار لـ torch.
# CPU cores for the local model. 0 leaves the choice to torch.
EMBED_THREADS = int(os.getenv("EMBED_THREADS", "0"))

VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY", "")
# المفاتيح التي تُنشأ في MongoDB Atlas تعمل على هذا العنوان. مفتاح قديم من
# منصة Voyage نفسها يعمل على https://api.voyageai.com/v1/embeddings
# Keys created in MongoDB Atlas work with this address. An older key from
# the Voyage platform itself works with https://api.voyageai.com/v1/embeddings
VOYAGE_ENDPOINT = os.getenv("VOYAGE_ENDPOINT", "https://ai.mongodb.com/v1/embeddings")

# ───────────────────────────────── الاسترجاع / Retrieval
TOP_K = int(os.getenv("TOP_K", "6"))
CANDIDATES = int(os.getenv("CANDIDATES", "25"))
# القيمة الابتدائية للعتبة. تُعدَّل بعد ذلك من اللوحة دون إعادة تشغيل،
# وقيمة اللوحة تتقدّم على هذه. 0.30 معايَرة لـ voyage-4-nano بـ1024 بُعداً
# على 36 سؤالاً؛ أعد المعايرة بـ scripts/calibrate.py عند تغيير النموذج.
# Initial value of the threshold. After that it is changed from the
# dashboard without a restart, and the dashboard value takes precedence
# over this one. 0.30 is calibrated for voyage-4-nano at 1024 dimensions
# on 36 questions; recalibrate with scripts/calibrate.py when the model
# changes.
MIN_RELEVANCE = float(os.getenv("MIN_RELEVANCE", "0.30"))
# بلا متجهات تصبح الثقة تداخلاً لفظياً موزوناً بالندرة — مقياس مختلف
# يحتاج عتبة أعلى، تُعاير داخلياً إلى مقياس MIN_RELEVANCE نفسه.
# Without vectors, confidence becomes word overlap weighted by rarity, a
# different measure that needs a higher threshold. It is rescaled
# internally to the same scale as MIN_RELEVANCE.
LEXICAL_THRESHOLD = float(os.getenv("LEXICAL_THRESHOLD", "0.60"))
# أقصى عدد أدوات تُعرض في إجابة تصنيف واحد
# Maximum number of tools listed in one category answer
MAX_TOOLS_LISTED = int(os.getenv("MAX_TOOLS_LISTED", "12"))
# التصحيح المعتمد يُرسل للنموذج حين يشبه سؤاله سؤالَ السائل بهذا القدر على
# الأقل. 0.75 معايَرة لـ voyage-4-nano: صياغات أخرى للسؤال نفسه بين 0.65 و
# 0.96، وأسئلة متقاربة الموضوع مختلفة المعنى لم تتجاوز 0.70.
# An approved correction is sent to the model when its question is at least
# this similar to the asker's. 0.75 is calibrated for voyage-4-nano: other
# wordings of the same question scored 0.65 to 0.96, and questions on a close
# topic with a different meaning never went above 0.70.
CORRECTION_MIN_SIMILARITY = float(os.getenv("CORRECTION_MIN_SIMILARITY", "0.75"))
# أقصى عدد تصحيحات تُرسل مع سؤال واحد
# Maximum number of corrections sent with one question
CORRECTIONS_PER_QUESTION = int(os.getenv("CORRECTIONS_PER_QUESTION", "2"))

# ───────────────────────────────── الهوية / Identity
# بيان يجيب بلغة السائل: العربية أو الإنجليزية (app/i18n.py). لكل رسالة
# ثابتة نسختان، والترحيب يجمعهما لأن من يضغط «ابدأ» لم يكتب شيئاً بعد.
# Bayan answers in the asker's language: Arabic or English (app/i18n.py).
# Each fixed message has two versions, and the welcome combines both,
# because someone who presses «ابدأ» (Start) has not written anything yet.
BOT_NAME = os.getenv("BOT_NAME", "بيان")
BOT_NAME_EN = os.getenv("BOT_NAME_EN", "Bayan")
ORG_NAME = os.getenv("ORG_NAME", "باكس ميموريا")
ORG_NAME_EN = os.getenv("ORG_NAME_EN", "Pax Memoria")
SITE_URL = os.getenv("SITE_URL", "https://paxmemoria.org")
SCOPE_DESCRIPTION = os.getenv(
    "SCOPE_DESCRIPTION",
    f"دليل أدوات المصادر المفتوحة والتحقيقات المنشورة في {ORG_NAME}، والتعريف بـ{ORG_NAME} نفسها",
)
SCOPE_DESCRIPTION_EN = os.getenv(
    "SCOPE_DESCRIPTION_EN",
    f"{ORG_NAME_EN}'s open-source tools guide and published investigations, and {ORG_NAME_EN} itself",
)
OUT_OF_SCOPE_MESSAGE = os.getenv(
    "OUT_OF_SCOPE_MESSAGE",
    "أعتذر، سؤالك خارج ما أعرفه.\n"
    f"أنا {BOT_NAME}، مخصص للإجابة عن دليل أدوات المصادر المفتوحة "
    f"والتحقيقات المنشورة في {ORG_NAME} فقط.\n"
    "جرّب سؤالاً عن أداة أو تصنيف أدوات، أو عن أحد تحقيقاتنا.",
)
OUT_OF_SCOPE_MESSAGE_EN = os.getenv(
    "OUT_OF_SCOPE_MESSAGE_EN",
    "Sorry, your question is outside what I know.\n"
    f"I'm {BOT_NAME_EN}, and I only answer questions about {ORG_NAME_EN}'s "
    "open-source tools guide and its published investigations.\n"
    "Try asking about a tool, a category of tools, or one of our investigations.",
)
# الترحيب بلغة السائل، ويقول ما يستطيع بيان فعله وما لا يستطيع. سطر حدّ
# الأسئلة اليومي يُضاف عند العرض لأن الحدّ يتغيّر من اللوحة (app/i18n.py).
# The welcome is in the asker's language and says what Bayan can and cannot
# do. The daily-limit line is added when shown, since the limit is changed
# from the dashboard (app/i18n.py).
WELCOME_MESSAGE_AR = os.getenv(
    "WELCOME_MESSAGE_AR",
    f"أهلاً بك 👋\n\nأنا {BOT_NAME}، مساعد {ORG_NAME}.\n\n"
    "ما أستطيع فعله:\n"
    "• أعرّفك بأدوات المصادر المفتوحة في دليلنا: ما هي، ولأي غرض، وتحذيراتها، "
    "ورابطها حين يُسمح بإعطائه.\n"
    "• أقترح أدوات لمهمة ما، مثل معرفة مكان التقاط صورة أو تتبّع رحلة طائرة.\n"
    "• أجيب عن تحقيقاتنا المنشورة: ماذا وثّقت وكيف، مع رابط التحقيق.\n\n"
    "ما لا أستطيع فعله:\n"
    "• الإجابة عن أي موضوع خارج الدليل والتحقيقات، كالأخبار والسياسة والصحة.\n"
    "• فحص صورة أو فيديو أو رابط ترسله إليّ، أو البحث في الإنترنت. أقرأ النص فقط.\n"
    "• إبداء رأي أو تقدير لم يرد في تحقيقاتنا.\n"
    "• المساعدة في أي عمل قد يؤذي أحداً، كاختراق الحسابات.\n\n"
    "اكتب سؤالك بالعربية أو بالإنجليزية.",
)
WELCOME_MESSAGE_EN = os.getenv(
    "WELCOME_MESSAGE_EN",
    f"Hello 👋\n\nI'm {BOT_NAME_EN}, {ORG_NAME_EN}'s assistant.\n\n"
    "What I can do:\n"
    "• Tell you about the open-source tools in our guide: what they are, what "
    "they are for, their warnings, and their link where sharing it is allowed.\n"
    "• Suggest tools for a task, such as finding where a photo was taken or "
    "tracking a flight.\n"
    "• Answer questions about our published investigations: what they "
    "documented and how, with a link to the investigation.\n\n"
    "What I can't do:\n"
    "• Answer anything outside the guide and the investigations, such as news, "
    "politics or health.\n"
    "• Check a photo, video or link you send me, or search the internet. I read "
    "text only.\n"
    "• Give opinions or estimates that our investigations do not contain.\n"
    "• Help with anything that could harm someone, such as breaking into "
    "accounts.\n\n"
    "Ask your question in Arabic or English.",
)
PAUSED_MESSAGE = os.getenv(
    "PAUSED_MESSAGE",
    f"{BOT_NAME} متوقف مؤقتاً.\n"
    f"دليل الأدوات والتحقيقات متاحان على {SITE_URL}",
)
PAUSED_MESSAGE_EN = os.getenv(
    "PAUSED_MESSAGE_EN",
    f"{BOT_NAME_EN} is paused for now.\n"
    f"The tools guide and the investigations are available at {SITE_URL}",
)
ERROR_MESSAGE = "حدث خلل مؤقت. حاول بعد قليل من فضلك."
ERROR_MESSAGE_EN = "Something went wrong for a moment. Please try again shortly."
SHOW_SOURCES = os.getenv("SHOW_SOURCES", "true").lower() == "true"

# ───────────────────────────────── القنوات / Channels
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")

META_APP_SECRET = os.getenv("META_APP_SECRET", "")
META_VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "")
# تطبيق Meta يستدعي الإصدارات التي صدرت بعد إنشائه فقط، فتطبيق جديد يرفض
# إصداراً قديماً. طابِقه مع الإصدار في صفحة API Setup في لوحة Meta.
# A Meta app can only call versions released after it was created, so a new
# app rejects an old one. Match it to the version on the API Setup page in
# Meta's dashboard.
META_GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v25.0")

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
MESSENGER_PAGE_TOKEN = os.getenv("MESSENGER_PAGE_TOKEN", "")

PUBLIC_URL = os.getenv("PUBLIC_URL", "")

# ───────────────────────────────── اللوحة والحدود / Dashboard and limits
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
SESSION_SECRET = os.getenv("SESSION_SECRET", "")

RATE_LIMIT_MESSAGES = int(os.getenv("RATE_LIMIT_MESSAGES", "12"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))
# أقصى عدد أسئلة للمستخدم الواحد في أي 24 ساعة متتالية، في كل قناة. 0 بلا حدّ.
# يُعدَّل من اللوحة دون إعادة تشغيل، وقيمة اللوحة تتقدّم على هذه.
# Maximum questions per user in any rolling 24 hours, in each channel.
# 0 means no limit. It is changed from the dashboard without a restart,
# and the dashboard value takes precedence over this one.
DAILY_LIMIT = int(os.getenv("DAILY_LIMIT", "10"))
# مدة حفظ الأسئلة والإجابات بالأيام، ثم تُحذف تلقائياً. سياسة الخصوصية
# المنشورة (/privacy) تذكر هذه المدة، فغيّرهما معاً.
# How many days questions and answers are kept before they are deleted
# automatically. The published privacy policy (/privacy) states this period,
# so change both together.
# الفرص: كم أسبوعاً يبحث فيها بيان، وكم فرصة يرسلها للنموذج
# Opportunities: how many weeks Bayan searches, and how many it sends the model
OPPORTUNITY_WEEKS = int(os.getenv("OPPORTUNITY_WEEKS", "4"))
OPPORTUNITIES_PER_QUESTION = int(os.getenv("OPPORTUNITIES_PER_QUESTION", "6"))
# الدخول إلى اللوحة بحساب Google من نطاق المنظمة. Google تتولى كلمات المرور
# والتحقق بخطوتين ومفاتيح المرور، وبيان يحفظ قائمة الفريق وأدواره فقط.
# ADMIN_EMAILS: بريد يدخل مديراً دون أن يضيفه أحد (للمدير الأول).
# Dashboard sign-in with a Google account from the organisation's domain.
# Google handles passwords, two-step verification and passkeys; Bayan keeps
# only the team list and its roles. ADMIN_EMAILS: addresses that sign in as
# admins without being added by anyone (for the first admin).
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
ALLOWED_EMAIL_DOMAIN = os.getenv("ALLOWED_EMAIL_DOMAIN", "paxmemoria.org").lower()
ADMIN_EMAILS = {
    a.strip().lower() for a in os.getenv("ADMIN_EMAILS", "").split(",") if a.strip()
}

# قنوات بثّ قائمة الفرص للمشتركين. تيليغرام يسمح بالرسائل الاستباقية بلا قيود؛
# واتساب يشترط قوالب رسائل معتمدة، وماسنجر إشعارات متكررة بموافقة Meta، فيُضافان
# هنا بعد الموافقة. الاشتراك نفسه يُسجَّل على كل القنوات.
# Channels that broadcast the opportunities list to subscribers. Telegram allows
# proactive messages freely; WhatsApp needs approved message templates and
# Messenger recurring notifications approved by Meta, so they are added here
# once approved. Subscribing itself is recorded on every channel.
BROADCAST_CHANNELS = {
    c.strip() for c in os.getenv("BROADCAST_CHANNELS", "telegram").split(",") if c.strip()
}
MESSAGE_RETENTION_DAYS = int(os.getenv("MESSAGE_RETENTION_DAYS", "30"))
PRIVACY_CONTACT = os.getenv("PRIVACY_CONTACT", "GDPR@paxmemoria.org")
HISTORY_TURNS = int(os.getenv("HISTORY_TURNS", "4"))
MAX_QUESTION_CHARS = int(os.getenv("MAX_QUESTION_CHARS", "600"))
