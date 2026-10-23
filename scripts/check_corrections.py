"""يعيد طرح سؤال كل تصحيح مفعّل على بيان، ويعرض إجابته بجانب الإجابة المعتمدة.

التشغيل:  docker compose exec bayan python scripts/check_corrections.py

التصحيحات مجموعة اختبار تكبر مع الوقت: شغّله بعد كل تغيير في التعليمات أو
النموذج أو العتبة، وتأكّد أن كل سؤال ما زال يطابق تصحيحه وأن الإجابة تتفق
معه. كل سؤال يستدعي النموذج فعلاً، أي نحو سنت واحد لكل سؤال على Sonnet. لا
يُسجَّل شيء في سجل الأسئلة.

Ask Bayan the question of every active correction again, and show its
answer next to the approved answer.

Run:  docker compose exec bayan python scripts/check_corrections.py

The corrections are a test set that grows over time: run it after every
change to the instructions, the model or the threshold, and check that each
question still matches its correction and that the answer agrees with it.
Each question really calls the model, about one cent per question on
Sonnet. Nothing is saved to the question log.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import brain, retrieve, store  # noqa: E402

store.init()
retrieve.warm()
fixes = store.corrections(active_only=True)
if not fixes:
    sys.exit("لا تصحيحات مفعّلة / No active corrections")

missed = 0
for i, c in enumerate(fixes, 1):
    res = brain.answer(c["question"], "check", f"correction-{c['id']}")
    matched = any(f["id"] == c["id"] for f in (res["retrieval"] or {}).get("corrections", []))
    missed += not matched
    print(f"\n{'═' * 70}\n[{i}/{len(fixes)}] #{c['id']}  {c['question']}")
    print(f"طابق تصحيحه / matched its correction: {'نعم / yes' if matched else 'لا / NO'}"
          f"  |  {res['outcome']}")
    print(f"\n── المعتمدة / approved ──\n{c['answer']}")
    print(f"\n── بيان الآن / Bayan now ──\n{res['text']}")

print(f"\n{'═' * 70}\nالأسئلة: {len(fixes)} | لم تطابق تصحيحها: {missed}"
      f"\nQuestions: {len(fixes)} | did not match their correction: {missed}")
sys.exit(1 if missed else 0)
