"""تنزيل voyage-4-nano بالمراجعة المثبّتة والتحقق من بصمة أوزانه.

التشغيل:  python scripts/fetch_model.py
يُشغَّل عند بناء صورة Docker، فيعمل الخادم بعدها دون اتصال بـ Hugging Face.
المجلد: LOCAL_MODEL_DIR، وإلا DATA_DIR/models/voyage-4-nano.

لا يعتمد على بقية app عمداً: تعديل الكود لا يُبطل طبقة النموذج في Docker
فلا يُعاد تنزيل 0.7 GB مع كل بناء.

Download voyage-4-nano at the pinned revision and check the hash of its
weights.

Run:  python scripts/fetch_model.py
It runs when the Docker image is built, so the server then works without
a connection to Hugging Face.
Folder: LOCAL_MODEL_DIR, otherwise DATA_DIR/models/voyage-4-nano.

It deliberately does not depend on the rest of app: a code change does
not invalidate the model layer in Docker, so 0.7 GB is not downloaded
again on every build.
"""
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
from app import nano  # noqa: E402

target = Path(
    os.getenv("LOCAL_MODEL_DIR")
    or Path(os.getenv("DATA_DIR", BASE / "data")) / "models" / "voyage-4-nano"
)

from huggingface_hub import snapshot_download  # noqa: E402

# بلا HF_HOME يُنزَّل إلى مجلد مؤقت يُحذف بعد النسخ، كي لا تتضاعف الصورة.
# Without HF_HOME, download to a temporary folder that is deleted after
# copying, so the image does not double in size.
cache = None if os.getenv("HF_HOME") else tempfile.mkdtemp(prefix="hf-")
try:
    src = Path(snapshot_download(nano.REPO, revision=nano.REVISION,
                                 allow_patterns=list(nano.FILES), cache_dir=cache))
    target.mkdir(parents=True, exist_ok=True)
    for f in nano.FILES:
        shutil.copyfile(src / f, target / f)
finally:
    if cache:
        shutil.rmtree(cache, ignore_errors=True)

digest = hashlib.sha256()
with open(target / "model.safetensors", "rb") as fh:
    for block in iter(lambda: fh.read(1 << 20), b""):
        digest.update(block)
if digest.hexdigest() != nano.WEIGHTS_SHA256:
    (target / "model.safetensors").unlink()
    sys.exit(f"✗ بصمة الأوزان لا تطابق المثبّتة: {digest.hexdigest()}")

(target / "REVISION").write_text(nano.REVISION + "\n")
print(f"✔ voyage-4-nano @ {nano.REVISION[:12]} في {target}")
