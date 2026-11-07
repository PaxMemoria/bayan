FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv

# git و node مطلوبان: بيان يسحب مستودع الموقع ويشغّل المُستخرِج بنفسه
# git and node are required: Bayan pulls the site repository and runs the
# extractor itself
# openssh-client لسحب مستودع الموقع الخاص بمفتاح النشر: git يُثبَّت هنا بلا
# حزمه الموصى بها، فلا يأتي بعميل SSH.
# openssh-client is for pulling the private site repository with the deploy
# key: git is installed here without its recommended packages, so it does
# not bring an SSH client.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libxml2-dev libxslt1-dev git openssh-client curl ca-certificates \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/*

# مفاتيح GitHub الرسمية (من api.github.com/meta، بصمة ed25519
# SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU). تثبيتها يمنع أن يقبل
# الخادم مضيفاً ينتحل GitHub عند أول سحب.
# GitHub's official host keys (from api.github.com/meta, ed25519 fingerprint
# SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU). Pinning them stops the
# server from accepting a host that impersonates GitHub on the first pull.
RUN printf '%s\n' \
  'github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl' \
  'github.com ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBEmKSENjQEezOmxkZMy7opKgwFB9nkt5YRrYMjNuG5N87uRgg6CLrbo5wAdT/y6v0mKV0U2w0WZ2YB/++Tpockg=' \
  > /etc/ssh/ssh_known_hosts

COPY requirements.txt .
# torch للمعالج وحده: الإصدار الافتراضي على Linux يجرّ مكتبات CUDA بعدة GB
# لا يحتاجها خادم بلا بطاقة رسوميات.
# CPU-only torch: the default build on Linux pulls in several GB of CUDA
# libraries that a server without a graphics card does not need.
RUN pip install --no-cache-dir --upgrade pip setuptools \
 && pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu \
    torch==2.14.1 \
 && pip install --no-cache-dir -r requirements.txt

# النموذج المحلي voyage-4-nano (0.7 GB) يُنزَّل عند البناء بالمراجعة المثبّتة
# في app/nano، ويُتحقَّق من بصمة أوزانه. يُنسخ ما يحتاجه السكربت وحده،
# فتعديل بقية الكود لا يعيد تنزيل النموذج مع كل بناء.
# The local model voyage-4-nano (0.7 GB) is downloaded at build time at the
# revision pinned in app/nano, and the hash of its weights is checked. Only
# what the script needs is copied, so changes to the rest of the code do
# not download the model again on every build.
ENV LOCAL_MODEL_DIR=/opt/models/voyage-4-nano
COPY app/__init__.py ./app/__init__.py
COPY app/nano ./app/nano
COPY scripts/fetch_model.py ./scripts/fetch_model.py
RUN python scripts/fetch_model.py
# بعد البناء لا يتصل الخادم بـ Hugging Face أبداً.
# After the build, the server never connects to Hugging Face.
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1

COPY app ./app
COPY scripts ./scripts
COPY tests ./tests

ENV DATA_DIR=/srv/data
RUN mkdir -p /srv/data
VOLUME ["/srv/data"]

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
