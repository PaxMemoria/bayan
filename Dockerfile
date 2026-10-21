FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /srv

# git و node مطلوبان: بيان يسحب مستودع الموقع ويشغّل المُستخرِج بنفسه
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libxml2-dev libxslt1-dev git curl ca-certificates \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# torch للمعالج وحده: الإصدار الافتراضي على Linux يجرّ مكتبات CUDA بعدة GB
# لا يحتاجها خادم بلا بطاقة رسوميات.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu \
    torch==2.14.1 \
 && pip install --no-cache-dir -r requirements.txt

# النموذج المحلي voyage-4-nano (0.7 GB) يُنزَّل عند البناء بالمراجعة المثبّتة
# في app/nano، ويُتحقَّق من بصمة أوزانه. يُنسخ ما يحتاجه السكربت وحده،
# فتعديل بقية الكود لا يعيد تنزيل النموذج مع كل بناء.
ENV LOCAL_MODEL_DIR=/opt/models/voyage-4-nano
COPY app/__init__.py ./app/__init__.py
COPY app/nano ./app/nano
COPY scripts/fetch_model.py ./scripts/fetch_model.py
RUN python scripts/fetch_model.py
# بعد البناء لا يتصل الخادم بـ Hugging Face أبداً.
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1

COPY app ./app
COPY scripts ./scripts
COPY tests ./tests

ENV DATA_DIR=/srv/data
RUN mkdir -p /srv/data
VOLUME ["/srv/data"]

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
