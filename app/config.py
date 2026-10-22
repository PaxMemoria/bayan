"""إعدادات بيان — تُقرأ من متغيرات البيئة (.env)."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "knowledge.db"

# ───────────────────────────────── مصدر المعرفة
# نسخة للقراءة فقط من مستودع الموقع، يسحبها هذا الخادم بنفسه.
# لا يحمل مستودع الموقع أياً من أسرار بيان.
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
REINDEX_SECRET = os.getenv("REINDEX_SECRET", "")

# ───────────────────────────────── النماذج
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANSWER_MODEL = os.getenv("ANSWER_MODEL", "claude-sonnet-5-5")
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "900"))

# ───────────────────────────────── المتجهات
# local  : voyage-4-nano على الخادم نفسه، فلا يغادر سؤال الجمهور الخادم.
# voyage : خدمة Voyage عبر MongoDB Atlas، وتحتاج VOYAGE_API_KEY.
EMBED_PROVIDER = os.getenv("EMBED_PROVIDER", "local").strip().lower()
# تغيير النموذج أو الأبعاد يستلزم إعادة الفهرسة: يُعطَّل البحث الدلالي حتى
# تُعاد الفهرسة، لأن متجهات إعدادين مختلفين لا تُقارَن.
EMBED_MODEL = os.getenv(
    "EMBED_MODEL", "voyage-4-nano" if EMBED_PROVIDER == "local" else "voyage-4"
)
EMBED_DIM = int(os.getenv("EMBED_DIM", "1024"))
LOCAL_MODEL_DIR = Path(
    os.getenv("LOCAL_MODEL_DIR", DATA_DIR / "models" / "voyage-4-nano")
)
# أنوية المعالج للنموذج المحلي. 0 يترك القرار لـ torch.
EMBED_THREADS = int(os.getenv("EMBED_THREADS", "0"))

VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY", "")
# المفاتيح التي تُنشأ في MongoDB Atlas تعمل على هذا العنوان. مفتاح قديم من
# منصة Voyage نفسها يعمل على https://api.voyageai.com/v1/embeddings
VOYAGE_ENDPOINT = os.getenv("VOYAGE_ENDPOINT", "https://ai.mongodb.com/v1/embeddings")

# ───────────────────────────────── الاسترجاع
TOP_K = int(os.getenv("TOP_K", "6"))
CANDIDATES = int(os.getenv("CANDIDATES", "25"))
# القيمة الابتدائية للعتبة. تُعدَّل بعد ذلك من اللوحة دون إعادة تشغيل،
# وقيمة اللوحة تتقدّم على هذه. 0.30 معايَرة لـ voyage-4-nano بـ1024 بُعداً
# على 36 سؤالاً؛ أعد المعايرة بـ scripts/calibrate.py عند تغيير النموذج.
MIN_RELEVANCE = float(os.getenv("MIN_RELEVANCE", "0.30"))
# بلا متجهات تصبح الثقة تداخلاً لفظياً موزوناً بالندرة — مقياس مختلف
# يحتاج عتبة أعلى، تُعاير داخلياً إلى مقياس MIN_RELEVANCE نفسه.
LEXICAL_THRESHOLD = float(os.getenv("LEXICAL_THRESHOLD", "0.60"))
# أقصى عدد أدوات تُعرض في إجابة تصنيف واحد
MAX_TOOLS_LISTED = int(os.getenv("MAX_TOOLS_LISTED", "12"))

# ───────────────────────────────── الهوية
# بيان يجيب بلغة السائل: العربية أو الإنجليزية (app/i18n.py). لكل رسالة
# ثابتة نسختان، والترحيب يجمعهما لأن من يضغط «ابدأ» لم يكتب شيئاً بعد.
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
WELCOME_MESSAGE_AR = (
    f"أهلاً بك 👋\n\nأنا {BOT_NAME}، مساعد {ORG_NAME}.\n"
    "أجيب عن موضوعين فقط:\n"
    "• أدوات المصادر المفتوحة في دليلنا: ما هي، ولأي غرض، وتحذيراتها\n"
    "• تحقيقاتنا المنشورة: ماذا وثّقت وكيف\n\n"
    "اكتب سؤالك مباشرة، بالعربية أو بالإنجليزية."
)
WELCOME_MESSAGE_EN = (
    f"Hello 👋\n\nI'm {BOT_NAME_EN}, {ORG_NAME_EN}'s assistant.\n"
    "I answer questions on two topics only:\n"
    "• The open-source tools in our guide: what they are, what they are for, "
    "and their warnings\n"
    "• Our published investigations: what they documented and how\n\n"
    "Just type your question, in Arabic or English."
)
WELCOME_MESSAGE = os.getenv(
    "WELCOME_MESSAGE", f"{WELCOME_MESSAGE_AR}\n\n{WELCOME_MESSAGE_EN}"
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

# ───────────────────────────────── القنوات
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")

META_APP_SECRET = os.getenv("META_APP_SECRET", "")
META_VERIFY_TOKEN = os.getenv("META_VERIFY_TOKEN", "")
META_GRAPH_VERSION = os.getenv("META_GRAPH_VERSION", "v21.0")

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
MESSENGER_PAGE_TOKEN = os.getenv("MESSENGER_PAGE_TOKEN", "")

PUBLIC_URL = os.getenv("PUBLIC_URL", "")

# ───────────────────────────────── اللوحة والحدود
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
SESSION_SECRET = os.getenv("SESSION_SECRET", "")

RATE_LIMIT_MESSAGES = int(os.getenv("RATE_LIMIT_MESSAGES", "12"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))
# أقصى عدد أسئلة للمستخدم الواحد في أي 24 ساعة متتالية، في كل قناة. 0 بلا حدّ.
# يُعدَّل من اللوحة دون إعادة تشغيل، وقيمة اللوحة تتقدّم على هذه.
DAILY_LIMIT = int(os.getenv("DAILY_LIMIT", "10"))
HISTORY_TURNS = int(os.getenv("HISTORY_TURNS", "4"))
MAX_QUESTION_CHARS = int(os.getenv("MAX_QUESTION_CHARS", "600"))
