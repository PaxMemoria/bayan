"""المتجهات — ضرورية عملياً، راجع «لماذا المتجهات ضرورية» في README.

مزوّدان (EMBED_PROVIDER):
  local  : voyage-4-nano على الخادم نفسه (الافتراضي). لا يغادر السؤال الخادم.
  voyage : خدمة Voyage عبر MongoDB Atlas.
"""
import logging
import time

import httpx

from . import config, nano

log = logging.getLogger("embed")

# المقطع العربي يستهلك رموزاً أكثر مما يوحي طوله، فتُقسَم دفعات الخدمة بعدد
# الأحرف إلى جانب عدد المقاطع، لتبقى كل دفعة تحت حدّ الرموز لكل طلب.
BATCH_TEXTS = 128
BATCH_CHARS = 120_000
RETRY_STATUS = {429, 500, 502, 503, 504}


class EmbedError(RuntimeError):
    """فشل توليد المتجهات."""


def unavailable_reason() -> str:
    """لماذا لا تتوفر المتجهات، أو نص فارغ إن كانت متوفرة."""
    if config.EMBED_PROVIDER == "local":
        if config.EMBED_MODEL != "voyage-4-nano":
            return f"المزوّد المحلي يشغّل voyage-4-nano وحده، لا {config.EMBED_MODEL}"
        return nano.missing(config.LOCAL_MODEL_DIR)
    if config.EMBED_PROVIDER == "voyage":
        return "" if config.VOYAGE_API_KEY else "VOYAGE_API_KEY غير مضبوط"
    return f"قيمة EMBED_PROVIDER غير معروفة: {config.EMBED_PROVIDER}"


def enabled() -> bool:
    return not unavailable_reason()


def model_id() -> str:
    """ما يُخزَّن مع الفهرس: متجهات نموذج أو أبعاد مختلفة لا تُقارَن."""
    return f"{config.EMBED_MODEL}@{config.EMBED_DIM}"


def preload() -> None:
    """تحميل النموذج المحلي عند الإقلاع، كي لا ينتظر أول سائل تحميله."""
    if config.EMBED_PROVIDER != "local" or not enabled():
        return
    t0 = time.time()
    try:
        nano.load(config.LOCAL_MODEL_DIR, config.EMBED_THREADS)
        log.info("حُمّل voyage-4-nano في %.1f ث", time.time() - t0)
    except Exception:  # noqa: BLE001
        log.exception("تعذّر تحميل النموذج المحلي")


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
    payload = {"input": batch, "model": config.EMBED_MODEL, "input_type": input_type}
    if config.EMBED_MODEL.startswith("voyage-4"):
        payload["output_dimension"] = config.EMBED_DIM
    last = ""
    for attempt in range(retries + 1):
        try:
            r = client.post(
                config.VOYAGE_ENDPOINT,
                headers={"Authorization": f"Bearer {config.VOYAGE_API_KEY}"},
                json=payload,
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
        hint = (". تجاوزتَ حدّ المعدل: الحساب بلا وسيلة دفع محدود بثلاثة طلبات"
                " و10 آلاف رمز في الدقيقة، وهذا لا يكفي لفهرسة بيان. راجع"
                " وسيلة الدفع في حساب MongoDB Atlas ثم أعد الفهرسة.")
    raise EmbedError(f"تعذّر توليد المتجهات: {last}{hint}")


def embed(texts: list[str], input_type: str = "document",
          retries: int = 6) -> list[list[float]] | None:
    """متجه لكل نص بالترتيب نفسه، أو None إن لم تتوفر المتجهات.

    يرفع EmbedError عند الفشل. retries للخدمة وحدها: الفهرسة تحتاج
    المحاولات الست، والسؤال الحيّ يمرّر retries=1 كي لا ينتظر السائل.
    """
    if not enabled() or not texts:
        return None
    if config.EMBED_PROVIDER == "local":
        try:
            return nano.encode(texts, input_type, config.EMBED_DIM,
                               config.LOCAL_MODEL_DIR, config.EMBED_THREADS)
        except Exception as e:  # noqa: BLE001
            raise EmbedError(f"تعذّر النموذج المحلي: {e}") from e
    out: list[list[float]] = []
    with httpx.Client(timeout=90) as client:
        for batch in _batches(texts):
            out.extend(_post(client, batch, input_type, retries))
    return out
