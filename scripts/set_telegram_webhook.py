"""ربط بوت تيليغرام بالخادم.  التشغيل: python scripts/set_telegram_webhook.py

Connect the Telegram bot to the server.  Run: python scripts/set_telegram_webhook.py
"""
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import config  # noqa: E402

if not config.TELEGRAM_BOT_TOKEN or not config.PUBLIC_URL:
    sys.exit("اضبط TELEGRAM_BOT_TOKEN و PUBLIC_URL في .env")

url = f"{config.PUBLIC_URL.rstrip('/')}/webhooks/telegram"
payload = {"url": url, "allowed_updates": ["message"], "drop_pending_updates": True}
if config.TELEGRAM_WEBHOOK_SECRET:
    payload["secret_token"] = config.TELEGRAM_WEBHOOK_SECRET

r = httpx.post(
    f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/setWebhook",
    json=payload,
    timeout=30,
)
print(r.status_code, r.text)
info = httpx.get(
    f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getWebhookInfo",
    timeout=30,
)
print(info.json())
