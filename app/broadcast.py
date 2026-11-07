"""بثّ قائمة الفرص الأسبوعية إلى المشتركين.

يُرسل نص قائمة الأسبوع كما حُفظ في تصحيح «فرص الأسبوع N» (وإلا يُبنى من بنودها)
إلى كل مشترك على قناة مفعّلة في BROADCAST_CHANNELS. القنوات غير المفعّلة تُترك
وتُعدّ، ولا يُرسل إليها شيء. النتيجة تُحفظ في الإعدادات لتعرضها اللوحة.

Broadcasting the weekly opportunities list to subscribers.

Sends the week's list as saved in the «فرص الأسبوع N» correction (otherwise
built from its items) to every subscriber on a channel enabled in
BROADCAST_CHANNELS. Channels not enabled are skipped and counted, and nothing
is sent to them. The result is saved in the settings for the dashboard.
"""
import asyncio
import json
import logging
import time

from . import config, i18n, store
from .arabic import normalize_ar
from .channels import messenger, telegram, whatsapp

log = logging.getLogger("broadcast")

SENDERS = {"telegram": telegram.send, "whatsapp": whatsapp.send, "messenger": messenger.send}


def week_text(year: int, week: int) -> str | None:
    """نص قائمة الأسبوع: التصحيح المعتمد إن وُجد، وإلا بنودها المحفوظة، وإلا None.
    The week's list text: the approved correction if there is one, otherwise
    its saved items, otherwise None."""
    norm = normalize_ar(f"فرص الأسبوع {week}")
    for c in store.corrections(active_only=True):
        if c["norm_question"] == norm:
            return c["answer"]
    items = store.opportunity_week_items(year, week)
    if not items:
        return None
    return "\n\n".join(f"{i}. {it['title']}\n{it['url']}" for i, it in enumerate(items, 1))


async def send_week(year: int, week: int) -> dict:
    """يبثّ قائمة الأسبوع ويعيد {sent, failed, skipped}. sent عدد محاولات الإرسال
    التي لم ترفع خطأً؛ رفض المنصة لرسالة يظهر في سجلّ قناتها.
    Broadcasts the week's list and returns {sent, failed, skipped}. sent counts
    the send attempts that raised no error; a platform rejecting a message shows
    in its channel's log."""
    counts = {"sent": 0, "failed": 0, "skipped": 0}
    text = week_text(year, week)
    if text is None:
        log.warning("لا قائمة للأسبوع %d/%d، لم يُبثّ شيء", week, year)
        return counts
    body = text.rstrip() + "\n\n" + i18n.both("broadcast_footer")
    for sub in store.subscribers():
        send = SENDERS.get(sub["channel"])
        if sub["channel"] not in config.BROADCAST_CHANNELS or send is None:
            counts["skipped"] += 1
            continue
        try:
            await send(sub["user_id"], body)
            counts["sent"] += 1
        except Exception:  # noqa: BLE001
            log.exception("فشل بثّ الفرص على %s", sub["channel"])
            counts["failed"] += 1
        # مهلة قصيرة بين الرسائل احتراماً لحدود المنصات
        # A short pause between messages, for the platforms' rate limits
        await asyncio.sleep(0.05)
    store.set_setting("last_broadcast", json.dumps(
        {"year": year, "week": week, "ts": time.time(), **counts}, ensure_ascii=False))
    log.info("بُثّت قائمة الأسبوع %d: أُرسل %d، فشل %d، تُرك %d",
             week, counts["sent"], counts["failed"], counts["skipped"])
    return counts
