"""مقارنة إجابات موديلات الجواب على أسئلة حقيقية، جنباً إلى جنب.

التشغيل على الخادم، داخل الحاوية:
    python scripts/compare_models.py [عدد_الأسئلة] > /srv/data/compare.md

لا يغيّر الإنتاج ولا يسجّل في سجل الأسئلة: يستدعي brain.answer مباشرة بقيم
ANSWER_MODEL و ANSWER_EFFORT مؤقتة. يستهلك رصيد API بعدد الأسئلة × عدد الصيغ.

Compare the answer models on real questions, side by side.

Run on the server, inside the container:
    python scripts/compare_models.py [number_of_questions] > /srv/data/compare.md

It changes nothing in production and writes nothing to the question log: it
calls brain.answer directly with temporary ANSWER_MODEL and ANSWER_EFFORT
values. It spends API credit: questions x variants.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import brain, config, retrieve, store  # noqa: E402

# (الاسم، الموديل، عمق التفكير) / (label, model, effort)
VARIANTS = [
    ("الحالي: Sonnet medium", "claude-sonnet-5-5", "medium"),
    ("Sonnet low", "claude-sonnet-5-5", "low"),
    ("Haiku medium", "claude-haiku-5-5", "medium"),
]

n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
questions = json.loads(
    (Path(__file__).resolve().parent / "calibration_questions.json").read_text(encoding="utf-8")
)["in_scope"][:n]

store.init()
retrieve.warm()
original = (config.ANSWER_MODEL, config.ANSWER_EFFORT)
print(f"# مقارنة الموديلات ({len(questions)} سؤالاً)\n")
for q in questions:
    print(f"## {q}\n")
    for label, model, effort in VARIANTS:
        config.ANSWER_MODEL, config.ANSWER_EFFORT = model, effort
        start = time.time()
        try:
            res = brain.answer(q, "console", "compare")
            text, outcome = res["text"], res["outcome"]
        except Exception as exc:  # noqa: BLE001
            text, outcome = f"خطأ: {type(exc).__name__}: {str(exc)[:200]}", "error"
        took = time.time() - start
        print(f"### {label} — {outcome} — {took:.1f} ث — {len(text)} حرفاً\n")
        print(text.strip() + "\n")
config.ANSWER_MODEL, config.ANSWER_EFFORT = original
