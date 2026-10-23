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
    f"دليل أدوات المصادر المفتوحة والتحقيقات المنشورة في {ORG_NAME}",
)
SCOPE_DESCRIPTION_EN = os.getenv(
    "SCOPE_DESCRIPTION_EN",
    f"{ORG_NAME_EN}'s open-source tools guide and published investigations",
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
META_GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v21.0")

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
HISTORY_TURNS = int(os.getenv("HISTORY_TURNS", "4"))
MAX_QUESTION_CHARS = int(os.getenv("MAX_QUESTION_CHARS", "600"))
