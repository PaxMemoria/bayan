"""مفاتيح API من اللوحة، للمدير وحده.

المفتاح المحفوظ من اللوحة يتقدّم على قيمة .env، فيبدّل المدير مفتاحاً
منتهياً دون دخول إلى الخادم. يُحفظ في قاعدة بيان (الجدول api_keys) على
الخادم نفسه الذي يحمل .env، فلا يزيد التعرّض عمّا هو؛ ولا يُعرض في اللوحة
بعد حفظه إلا آخر أربعة أحرف. كل حفظ أو مسح يُسجَّل في سجلّ الإجراءات باسم
المفتاح لا بقيمته.

ليست هنا مفاتيح يحتاج تغييرها إلى إعادة تشغيل (رمز تيليغرام يسجَّل webhook
عند الإقلاع، وسرّ Meta يُستعمل في التحقق من التوقيع): تبقى في .env.

API keys from the dashboard, for the admin only.

A key saved from the dashboard takes precedence over the .env value, so the
admin can replace an expired key without logging in to the server. It is
kept in Bayan's database (the api_keys table) on the same server that holds
.env, so the exposure does not grow; and after saving only its last four
characters are shown. Every save or clear goes to the audit log with the
key's name, never its value.

Keys whose change needs a restart are not here (the Telegram token registers
the webhook at startup, and the Meta app secret verifies signatures): they
stay in .env.
"""
import os
import re
import time

from . import brain, config, store

# المفاتيح المتاحة من اللوحة: (العربية، الإنجليزية)، وما يُعاد ضبطه بعد التغيير
# The keys available from the dashboard: (Arabic, English), and what is reset
# after a change
KEYS: dict[str, dict] = {
    "ANTHROPIC_API_KEY": {
        "label": ("مفتاح Claude (Anthropic)", "Claude (Anthropic) API key"),
        "apply": brain.reset_client,
    },
    "GEMINI_API_KEY": {"label": ("مفتاح Gemini", "Gemini API key")},
    "VOYAGE_API_KEY": {"label": ("مفتاح Voyage (المتجهات)", "Voyage API key (vectors)")},
    "LOCAL_LLM_KEY": {"label": ("مفتاح النموذج المحلي", "Local model key")},
    "MESSENGER_PAGE_TOKEN": {
        "label": ("رمز صفحة فيسبوك (ماسنجر والتعليقات)",
                  "Facebook page token (Messenger and comments)"),
    },
    "WHATSAPP_TOKEN": {"label": ("رمز واتساب", "WhatsApp token")},
}
MAX_LEN = 1024
_VALID = re.compile(r"^[\x21-\x7e]{8,%d}$" % MAX_LEN)

# قيم .env كما قرأها config عند الإقلاع، ليعود إليها المفتاح حين يُمسح من اللوحة
# The .env values as config read them at startup, for a key to fall back to
# when cleared from the dashboard
ENV_VALUES: dict[str, str] = {name: getattr(config, name, "") for name in KEYS}


def valid(value: str) -> bool:
    """مفتاح: أحرف ASCII مطبوعة بلا مسافات، من 8 أحرف. A key: printable ASCII
    without spaces, 8 characters or more."""
    return bool(_VALID.match(value))


def _apply(name: str, value: str) -> None:
    setattr(config, name, value)
    hook = KEYS[name].get("apply")
    if hook:
        hook()


def apply_saved() -> int:
    """عند الإقلاع: المفاتيح المحفوظة في القاعدة تحلّ محل قيم .env.
    At startup: the keys saved in the database replace the .env values."""
    n = 0
    for row in store.api_keys():
        if row["name"] in KEYS and row["value"]:
            _apply(row["name"], row["value"])
            n += 1
    return n


def set_key(name: str, value: str, by: str) -> None:
    if name not in KEYS or not valid(value):
        raise ValueError(name)
    store.set_api_key(name, value, by)
    _apply(name, value)
    store.audit(by, "key_set", name)


def clear_key(name: str, by: str) -> None:
    if name not in KEYS:
        raise ValueError(name)
    store.clear_api_key(name)
    _apply(name, ENV_VALUES.get(name) or os.getenv(name, ""))
    store.audit(by, "key_clear", name)


def mask(value: str) -> str:
    """آخر أربعة أحرف فقط، أو لا شيء للمفاتيح القصيرة.
    The last four characters only, or nothing for short keys."""
    return f"••••{value[-4:]}" if len(value) >= 12 else "••••"


def status() -> list[dict]:
    """حال كل مفتاح للعرض: من اللوحة أو من .env أو غير مضبوط، بلا قيمته.
    Each key's state for display: from the dashboard, from .env, or not set,
    without its value."""
    saved = {r["name"]: r for r in store.api_keys()}
    out = []
    for name, spec in KEYS.items():
        row = saved.get(name)
        env = ENV_VALUES.get(name, "")
        if row and row["value"]:
            source, value = "dashboard", row["value"]
        elif env:
            source, value = "env", env
        else:
            source, value = "none", ""
        out.append({
            "name": name, "label": spec["label"], "source": source,
            "mask": mask(value) if value else "",
            "updated": row["updated"] if row else None,
            "by": row["by"] if row else "",
        })
    return out


def now() -> float:
    return time.time()
