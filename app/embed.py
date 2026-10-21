"""متجهات Voyage AI — ضرورية عملياً، راجع «لماذا المتجهات ضرورية» في README."""
import logging
import time

import httpx

from . import config

log = logging.getLogger("embed")

ENDPOINT = "https://api.voyageai.com/v1/embeddings"

# المقطع العربي يستهلك رموزاً أكثر مما يوحي طوله، فتُقسَم الدفعات بعدد
# الأحرف إلى جانب عدد المقاطع، لتبقى كل دفعة تحت حدّ الرموز لكل طلب.
BATCH_TEXTS = 128
BATCH_CHARS = 120_000
RETRY_STATUS = {429, 500, 502, 503, 504}


class EmbedError(RuntimeError):
    """فشل توليد المتجهات بعد استنفاد المحاولات."""


def enabled() -> bool:
    return bool(config.VOYAGE_API_KEY)


def _batches(texts: list[str]):
    batch: list[str] = []
    size = 0
    for t in texts:
        if batch and (len(batch) >= BATCH_TEXTS or size + len(t) > BATCH_CHARS):
            yield batch
            batch, size = [], 0
        batch.append(t)
        size += len(t)
    if batch:
        yield batch


def _post(client: httpx.Client, batch: list[str], input_type: str,
          retries: int) -> list[list[float]]:
    last = ""
    for attempt in range(retries + 1):
        try:
            r = client.post(
                ENDPOINT,
                headers={"Authorization": f"Bearer {config.VOYAGE_API_KEY}"},
                json={"input": batch, "model": config.EMBED_MODEL,
                      "input_type": input_type},
            )
        except httpx.TransportError as e:
            last = f"خطأ اتصال: {e}"
            wait = 2.0 ** attempt
        else:
            if r.status_code == 200:
                data = sorted(r.json()["data"], key=lambda d: d["index"])
                return [d["embedding"] for d in data]
            if r.status_code not in RETRY_STATUS:
                raise EmbedError(f"Voyage {r.status_code}: {r.text[:300]}")
            last = f"Voyage {r.status_code}: {r.text[:200]}"
            try:
                wait = float(r.headers.get("retry-after", ""))
            except ValueError:
                wait = 2.0 ** (attempt + 1)
        if attempt == retries:
            break
        wait = min(wait, 60.0)
        log.warning("%s — إعادة المحاولة بعد %.0f ث", last, wait)
        time.sleep(wait)

    hint = ""
    if "429" in last:
        hint = (". حساب Voyage بلا وسيلة دفع محدود بثلاثة طلبات و10 آلاف رمز"
                " في الدقيقة، وهذا لا يكفي لفهرسة بيان. أضف وسيلة دفع في"
                " dashboard.voyageai.com ثم أعد الفهرسة.")
    raise EmbedError(f"تعذّر توليد المتجهات: {last}{hint}")


def embed(texts: list[str], input_type: str = "document",
          retries: int = 6) -> list[list[float]] | None:
    """متجه لكل نص بالترتيب نفسه، أو None إن لم يُضبط المفتاح.

    يرفع EmbedError عند الفشل. الفهرسة تحتاج المحاولات الست (حتى دقيقة
    بين كل منها)؛ السؤال الحيّ يمرّر retries=1 كي لا ينتظر السائل.
    """
    if not enabled() or not texts:
        return None
    out: list[list[float]] = []
    with httpx.Client(timeout=90) as client:
        for batch in _batches(texts):
            out.extend(_post(client, batch, input_type, retries))
    return out
