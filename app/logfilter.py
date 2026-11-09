"""حجب الأسرار عن سجلّ الطلبات.

يطبع uvicorn سطراً لكل طلب فيه المسار بسلسلة الاستعلام كاملة. مساران
يحملان سراً في الاستعلام: رجوع Google بعد الدخول (code وstate، يُستبدل
الرمز خلال ثوانٍ لكنه لا ينبغي أن يصل إلى السجلّ أصلاً)، والتحقق من
webhook ميتا (hub.verify_token). هذا المرشّح يُركَّب على مسجّل
uvicorn.access ويستبدل سلسلة الاستعلام في هذين المسارين بـ «?…» ويترك
بقية الطلبات كما هي. رمز تيليغرام ليس مساراً عندنا بل جزء من عنوان واجهة
تيليغرام التي نناديها، ويعالَج بإسكات مسجّل httpx في main.py.

Keeping secrets out of the access log.

uvicorn prints a line per request with the path and its full query string.
Two paths carry a secret in the query: the Google sign-in callback (code
and state; the code is exchanged within seconds but should not reach the
log at all) and the Meta webhook verification (hub.verify_token). This
filter is installed on the uvicorn.access logger and replaces the query
string of those paths with "?…", leaving every other request untouched.
The Telegram token is not a route of ours but part of the Telegram API
address we call, handled by silencing the httpx logger in main.py.
"""
import logging

# المسارات التي تحمل سراً في سلسلة الاستعلام (بادئات)
# Paths whose query string carries a secret (prefixes)
SECRET_QUERY_PATHS = ("/admin/auth/google/callback", "/webhooks/meta")
REDACTED = "?…"


class RedactQueryFilter(logging.Filter):
    """يستبدل سلسلة الاستعلام في سجلّ uvicorn.access للمسارات السرّية.

    سجلّ uvicorn يحمل args = (العميل، الطريقة، المسار مع الاستعلام،
    إصدار HTTP، الحالة)؛ يُستبدل العنصر الثالث في نسخة من الصفّ.

    Replaces the query string in uvicorn.access records for secret paths.

    The uvicorn record carries args = (client, method, path with query,
    HTTP version, status); the third element is replaced in a copy of the
    tuple.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            path = args[2]
            if "?" in path and path.startswith(SECRET_QUERY_PATHS):
                record.args = (*args[:2], path.split("?", 1)[0] + REDACTED, *args[3:])
        return True


def install() -> None:
    """يركّب المرشّح على uvicorn.access مرة واحدة / Installs the filter on uvicorn.access once."""
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, RedactQueryFilter) for f in logger.filters):
        logger.addFilter(RedactQueryFilter())
