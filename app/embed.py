"""المتجهات — ضرورية عملياً، راجع «لماذا المتجهات ضرورية» في README.

مزوّدان (EMBED_PROVIDER):
  local  : voyage-4-nano على الخادم نفسه (الافتراضي). لا يغادر السؤال الخادم.
  voyage : خدمة Voyage عبر MongoDB Atlas.

Vectors: necessary in practice; see "Why vectors are necessary" in the
README.

Two providers (EMBED_PROVIDER):
  local  : voyage-4-nano on the server itself (the default). The question
           never leaves the server.
  voyage : the Voyage service through MongoDB Atlas.
"""
import logging
import time

import httpx

from . import config, nano

log = logging.getLogger("embed")

# المقطع العربي يستهلك رموزاً أكثر مما يوحي طوله، فتُقسَم دفعات الخدمة بعدد
# الأحرف إلى جانب عدد المقاطع، لتبقى كل دفعة تحت حدّ الرموز لكل طلب.
# An Arabic passage uses more tokens than its length suggests, so batches
# for the service are split by character count as well as by passage
# count, to keep each batch under the per-request token limit.
BATCH_TEXTS = 128
BATCH_CHARS = 120_000
RETRY_STATUS = {429, 500, 502, 503, 504}


class EmbedError(RuntimeError):
    """فشل توليد المتجهات.
    Generating the vectors failed."""


def unavailable_reason(lang: str = "ar") -> str:
    """لماذا لا تتوفر المتجهات، أو نص فارغ إن كانت متوفرة.
    Why vectors are unavailable, or an empty string if they are available."""
    en = lang == "en"
    if config.EMBED_PROVIDER == "local":
        if config.EMBED_MODEL != "voyage-4-nano":
            if en:
                return f"The local provider only runs voyage-4-nano, not {config.EMBED_MODEL}"
            return f"المزوّد المحلي يشغّل voyage-4-nano وحده، لا {config.EMBED_MODEL}"
        return nano.missing(config.LOCAL_MODEL_DIR, lang)
    if config.EMBED_PROVIDER == "voyage":
        if config.VOYAGE_API_KEY:
            return ""
        return "VOYAGE_API_KEY is not set" if en else "VOYAGE_API_KEY غير مضبوط"
    if en:
        return f"Unknown EMBED_PROVIDER value: {config.EMBED_PROVIDER}"
    return f"قيمة EMBED_PROVIDER غير معروفة: {config.EMBED_PROVIDER}"


def enabled() -> bool:
    return not unavailable_reason()


def model_id() -> str:
    """ما يُخزَّن مع الفهرس: متجهات نموذج أو أبعاد مختلفة لا تُقارَن.
    What is stored with the index: vectors from a different model or
    dimensions cannot be compared."""
    return f"{config.EMBED_MODEL}@{config.EMBED_DIM}"


def preload() -> None:
    """تحميل النموذج المحلي عند الإقلاع، كي لا ينتظر أول سائل تحميله.
    Load the local model at startup, so the first asker does not wait for
    it to load."""
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

    One vector per text, in the same order, or None if vectors are unavailable.

    Raises EmbedError on failure. retries applies to the service only:
    indexing needs all six attempts, and a live question passes retries=1
    so the asker does not wait.
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
