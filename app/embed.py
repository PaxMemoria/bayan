"""متجهات Voyage AI — اختيارية لكن موصى بها بشدة."""
import httpx

from . import config

ENDPOINT = "https://api.voyageai.com/v1/embeddings"


def enabled() -> bool:
    return bool(config.VOYAGE_API_KEY)


def embed(texts: list[str], input_type: str = "document") -> list[list[float]] | None:
    if not enabled() or not texts:
        return None
    out: list[list[float]] = []
    with httpx.Client(timeout=90) as client:
        for i in range(0, len(texts), 96):
            batch = texts[i : i + 96]
            r = client.post(
                ENDPOINT,
                headers={"Authorization": f"Bearer {config.VOYAGE_API_KEY}"},
                json={
                    "input": batch,
                    "model": config.EMBED_MODEL,
                    "input_type": input_type,
                },
            )
            r.raise_for_status()
            data = sorted(r.json()["data"], key=lambda d: d["index"])
            out.extend(d["embedding"] for d in data)
    return out
