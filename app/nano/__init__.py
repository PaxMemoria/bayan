"""voyage-4-nano على خادم بيان نفسه: سؤال الجمهور لا يغادر الخادم.

النموذج مفتوح الأوزان (Apache 2.0)، ويشترك في فضاء متجهات واحد مع بقية
عائلة voyage-4، فيمكن لاحقاً فهرسة نصوص الموقع العامة بنموذج أكبر عبر
الخدمة مع بقاء متجهات الأسئلة محلية.

الكود في modeling.py منقول من المراجعة المثبّتة أدناه، والأوزان تُنزَّل
بالمراجعة نفسها ويُتحقَّق من بصمتها (scripts/fetch_model.py). لا يُنفَّذ
أي كود من الشبكة، والخادم يعمل دون اتصال بـ Hugging Face.

torch و transformers يُستوردان عند أول استعمال فقط.

voyage-4-nano on Bayan's own server: questions from the public do not
leave the server.

The model has open weights (Apache 2.0) and shares one vector space with
the rest of the voyage-4 family, so the site's public texts could later
be indexed with a larger model through the service while the question
vectors stay local.

The code in modeling.py is copied from the pinned revision below, and
the weights are downloaded at the same revision and checked against
their hash (scripts/fetch_model.py). No code from the network is run,
and the server works without a connection to Hugging Face.

torch and transformers are imported only on first use.
"""
import threading
from pathlib import Path

REPO = "voyageai/voyage-4-nano"
REVISION = "433ece5e27a1611e9360dd7134ecaaf79fb3681d"
WEIGHTS_SHA256 = "3dae0c63c81dcab79ac213af331940a1bf2b8a53ec8646be878552890291ad30"
FILES = (
    "config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json",
    "vocab.json", "merges.txt", "LICENSE.txt", "NOTICE.txt",
)
PROMPTS = {
    "query": "Represent the query for retrieving supporting documents: ",
    "document": "Represent the document for retrieval: ",
}
MAX_TOKENS = 2048
# دفعة صغيرة تُبقي ذروة الذاكرة أثناء الفهرسة منخفضة، وتترك الأسئلة الحيّة
# تمرّ بين دفعة وأخرى بدل أن تنتظر الفهرسة كلها.
# A small batch keeps peak memory low during indexing, and lets live
# questions through between batches instead of waiting for the whole
# indexing run.
BATCH = 8

_lock = threading.Lock()
_loaded: tuple | None = None  # (tokenizer, model, path)


def missing(path: Path, lang: str = "ar") -> str:
    """سبب عدم توفّر النموذج، أو نص فارغ إن كان جاهزاً.
    Why the model is unavailable, or an empty string if it is ready."""
    import importlib.util

    en = lang == "en"
    if importlib.util.find_spec("torch") is None:
        return "torch is not installed" if en else "مكتبة torch غير مثبّتة"
    absent = [f for f in FILES if not (path / f).exists()]
    if absent:
        if en:
            return (f"The local model is missing from {path} (no {absent[0]}). "
                    "Run scripts/fetch_model.py")
        return (f"النموذج المحلي غير موجود في {path} (ينقصه {absent[0]}). "
                "شغّل scripts/fetch_model.py")
    rev = (path / "REVISION").read_text().strip() if (path / "REVISION").exists() else ""
    if rev != REVISION:
        if en:
            return (f"The model in {path} is not from the pinned revision. "
                    "Run scripts/fetch_model.py")
        return f"النموذج في {path} ليس من المراجعة المثبّتة. شغّل scripts/fetch_model.py"
    return ""


def load(path: Path, threads: int = 0):
    global _loaded
    with _lock:
        if _loaded and _loaded[2] == path:
            return _loaded
        import torch
        from transformers import AutoTokenizer

        from .modeling import Qwen3BidirectionalModel

        if threads:
            torch.set_num_threads(threads)
        tok = AutoTokenizer.from_pretrained(str(path), local_files_only=True)
        model = Qwen3BidirectionalModel.from_pretrained(
            str(path), local_files_only=True, dtype=torch.float32,
            attn_implementation="sdpa",
        ).eval()
        _loaded = (tok, model, path)
        return _loaded


def encode(texts: list[str], input_type: str, dim: int, path: Path,
           threads: int = 0) -> list[list[float]]:
    """متجه لكل نص بالترتيب نفسه، مقصوص إلى dim ومطبَّع.

    النموذج مدرَّب بأسلوب Matryoshka، فأوائل أبعاده متجه صالح بذاته.

    One vector per text, in the same order, truncated to dim and normalized.

    The model is trained Matryoshka-style, so its first dimensions are a
    valid vector on their own.
    """
    import torch

    tok, model, _ = load(path, threads)
    prompt = PROMPTS[input_type]
    order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
    out: list[list[float] | None] = [None] * len(texts)
    for start in range(0, len(order), BATCH):
        idx = order[start:start + BATCH]
        inputs = tok([prompt + texts[i] for i in idx], return_tensors="pt",
                     padding=True, truncation=True, max_length=MAX_TOKENS)
        with _lock, torch.no_grad():
            hidden = model(**inputs).last_hidden_state
        mask = inputs["attention_mask"].unsqueeze(-1).float()
        vecs = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
        vecs = torch.nn.functional.normalize(vecs[:, :dim], p=2, dim=1)
        for j, i in enumerate(idx):
            out[i] = vecs[j].tolist()
    return out  # type: ignore[return-value]
