"""ملف بيان في تيليغرام: الوصف والنبذة وقائمة الأوامر، بالعربية والإنجليزية.

التشغيل:  python scripts/set_telegram_profile.py
من واجهته عربية يرى النصوص العربية، والباقون الإنجليزية. التوكن يُقرأ من
‎.env ولا يُطبع.

Bayan's Telegram profile: the description, the about text and the commands
menu, in Arabic and English.

Run:  python scripts/set_telegram_profile.py
Users whose interface is Arabic see the Arabic texts; everyone else sees
the English. The token is read from .env and never printed.
"""
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config  # noqa: E402

TEXT = {
    "en": {
        "description": (
            "Bayan is Pax Memoria's automated assistant. It answers questions only "
            "about the open-source tools in our guide and our published "
            "investigations, and cites the source of each answer. It does not check "
            "photos or links, and does not answer anything else. Ask in Arabic or "
            "English."
        ),
        "short": ("Pax Memoria's assistant for its open-source tools guide and "
                  "published investigations. paxmemoria.org"),
        "commands": {
            "start": "Start and see what Bayan can do",
            "help": "What Bayan can and can't do",
            "reset": "Start a new conversation",
        },
    },
    "ar": {
        "description": (
            "بيان مساعد آلي من باكس ميموريا. يجيب عن أدوات المصادر المفتوحة في "
            "دليلنا وعن تحقيقاتنا المنشورة فقط، ويذكر لكل إجابة مصدرها. لا يفحص "
            "الصور أو الروابط، ولا يجيب عن أي موضوع آخر. اكتب سؤالك بالعربية أو "
            "بالإنجليزية."
        ),
        "short": ("مساعد باكس ميموريا لدليل أدوات المصادر المفتوحة والتحقيقات "
                  "المنشورة. paxmemoria.org"),
        "commands": {
            "start": "ابدأ وتعرّف إلى ما يستطيعه بيان",
            "help": "ما يستطيعه بيان وما لا يستطيعه",
            "reset": "ابدأ محادثة جديدة",
        },
    },
}

if not config.TELEGRAM_BOT_TOKEN:
    sys.exit("TELEGRAM_BOT_TOKEN is not set in .env")

# حدود تيليغرام / Telegram's limits
for lang, t in TEXT.items():
    assert len(t["description"]) <= 512, f"{lang} description too long"
    assert len(t["short"]) <= 120, f"{lang} about text too long"


def call(method: str, **payload) -> dict:
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{method}"
    data = httpx.post(url, json=payload, timeout=30).json()
    if not data.get("ok"):
        sys.exit(f"{method} failed: {data.get('description')}")
    return data


for lang, t in TEXT.items():
    # الإنجليزية افتراضية لكل لغة غير العربية
    # English is the default for every language other than Arabic
    scope = {} if lang == "en" else {"language_code": "ar"}
    call("setMyDescription", description=t["description"], **scope)
    call("setMyShortDescription", short_description=t["short"], **scope)
    call("setMyCommands", commands=[{"command": c, "description": d}
                                    for c, d in t["commands"].items()], **scope)

# ما يعرضه تيليغرام الآن / What Telegram now shows
for lang, scope in (("default (English)", {}), ("ar", {"language_code": "ar"})):
    d = call("getMyDescription", **scope)["result"]["description"]
    s = call("getMyShortDescription", **scope)["result"]["short_description"]
    cmds = call("getMyCommands", **scope)["result"]
    print(f"\n[{lang}]")
    print(f"description ({len(d)} chars): {d}")
    print(f"about ({len(s)} chars): {s}")
    print("commands: " + " | ".join(f"/{c['command']}: {c['description']}" for c in cmds))
