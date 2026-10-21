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

VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY", "")
# تغيير النموذج يستلزم إعادة الفهرسة: متجهات نموذجين لا تُقارَن، فيُعطَّل
# البحث الدلالي حتى تُعاد الفهرسة بالنموذج الجديد.
EMBED_MODEL = os.getenv("EMBED_MODEL", "voyage-4")
EMBED_DIM = int(os.getenv("EMBED_DIM", "1024"))

# ───────────────────────────────── الاسترجاع
TOP_K = int(os.getenv("TOP_K", "6"))
CANDIDATES = int(os.getenv("CANDIDATES", "25"))
# القيمة الابتدائية للعتبة. تُعدَّل بعد ذلك من اللوحة دون إعادة تشغيل،
# وقيمة اللوحة تتقدّم على هذه. عايِرها بـ scripts/calibrate.py.
MIN_RELEVANCE = float(os.getenv("MIN_RELEVANCE", "0.30"))
# بلا متجهات تصبح الثقة تداخلاً لفظياً موزوناً بالندرة — مقياس مختلف
# يحتاج عتبة أعلى، تُعاير داخلياً إلى مقياس MIN_RELEVANCE نفسه.
LEXICAL_THRESHOLD = float(os.getenv("LEXICAL_THRESHOLD", "0.60"))
# أقصى عدد أدوات تُعرض في إجابة تصنيف واحد
MAX_TOOLS_LISTED = int(os.getenv("MAX_TOOLS_LISTED", "12"))

# ───────────────────────────────── الهوية
BOT_NAME = os.getenv("BOT_NAME", "بيان")
ORG_NAME = os.getenv("ORG_NAME", "باكس ميموريا")
SITE_URL = os.getenv("SITE_URL", "https://paxmemoria.org")
SCOPE_DESCRIPTION = os.getenv(
    "SCOPE_DESCRIPTION",
    f"دليل أدوات المصادر المفتوحة والتحقيقات المنشورة في {ORG_NAME}",
)
OUT_OF_SCOPE_MESSAGE = os.getenv(
    "OUT_OF_SCOPE_MESSAGE",
    "أعتذر، سؤالك خارج ما أعرفه.\n"
    f"أنا {BOT_NAME}، مخصص للإجابة عن دليل أدوات المصادر المفتوحة "
    f"والتحقيقات المنشورة في {ORG_NAME} فقط.\n"
    "جرّب سؤالاً عن أداة أو تصنيف أدوات، أو عن أحد تحقيقاتنا.",
)
WELCOME_MESSAGE = os.getenv(
    "WELCOME_MESSAGE",
    f"أهلاً بك 👋\n\nأنا {BOT_NAME}، مساعد {ORG_NAME}.\n"
    "أجيب عن سؤالين فقط:\n"
    "• أدوات المصادر المفتوحة في دليلنا — ما هي، ولأي غرض، وتحذيراتها\n"
    "• تحقيقاتنا المنشورة — ماذا وثّقت وكيف\n\n"
    "اكتب سؤالك مباشرة.",
)
PAUSED_MESSAGE = os.getenv(
    "PAUSED_MESSAGE",
    f"{BOT_NAME} متوقف مؤقتاً.\n"
    f"دليل الأدوات والتحقيقات متاحان على {SITE_URL}",
)
ERROR_MESSAGE = "حدث خلل مؤقت. حاول بعد قليل من فضلك."
# بيان يعمل بالعربية. الأسئلة بلغات أخرى تُجاب بالعربية.
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
HISTORY_TURNS = int(os.getenv("HISTORY_TURNS", "4"))
MAX_QUESTION_CHARS = int(os.getenv("MAX_QUESTION_CHARS", "600"))
