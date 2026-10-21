"""معايرة عتبة البوابة على الفهرس الحالي.

التشغيل:  python scripts/calibrate.py [ملف_الأسئلة.json]

يحسب ثقة كل سؤال من أسئلة المعايرة دون استدعاء النموذج، ثم يقترح عتبة.
شغّله بعد كل فهرسة بنموذج متجهات جديد، واضبط العتبة من صفحة الإعدادات.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import embed, retrieve, store  # noqa: E402

path = Path(sys.argv[1]) if len(sys.argv) > 1 else (
    Path(__file__).resolve().parent / "calibration_questions.json"
)
qs = json.loads(path.read_text(encoding="utf-8"))

store.init()
retrieve.warm()
mode = "متجهات ونص" if retrieve.status()["vectors"] else "نص فقط"
print(f"الفهرس: {store.chunk_count()} مقطع | البحث: {mode}")
if not embed.enabled():
    print("⚠ VOYAGE_API_KEY غير مضبوط: هذه معايرة للبحث النصي وحده.")
elif not retrieve.status()["vectors"]:
    print(f"⚠ {retrieve.status()['vector_note']}")


def score(q: str) -> float:
    return retrieve.search(q)["confidence"]


inside = sorted(((score(q), q) for q in qs["in_scope"]), reverse=True)
outside = sorted(((score(q), q) for q in qs["out_of_scope"]), reverse=True)

print("\n── داخل النطاق (يجب أن يُجاب) ──")
for s, q in inside:
    print(f"  {s:.3f}  {q}")
print("\n── خارج النطاق (يجب أن يُرفض) ──")
for s, q in outside:
    print(f"  {s:.3f}  {q}")

low_in = min(s for s, _ in inside)
high_out = max(s for s, _ in outside)
print()
if low_in > high_out:
    t = round((low_in + high_out) / 2, 2)
    print(f"✔ المقياسان منفصلان: أدنى سؤال مشروع {low_in:.3f}، "
          f"وأعلى سؤال خارجي {high_out:.3f}.")
    print(f"العتبة المقترحة: {t:.2f}")
else:
    print(f"⚠ المقياسان متداخلان: أدنى سؤال مشروع {low_in:.3f}، "
          f"وأعلى سؤال خارجي {high_out:.3f}.")
    print("الرفض الخاطئ يخسر سائلاً، والقبول الخاطئ تلتقطه الطبقتان ٢ و٣ "
          "بكلفة استدعاء، فالأولوية لتقليل الرفض الخاطئ:")
    print("  العتبة | يُرفض خطأً | يمرّ خطأً")
    best = None
    for i in range(5, 91):
        t = i / 100
        fr = sum(1 for s, _ in inside if s < t)
        fp = sum(1 for s, _ in outside if s >= t)
        if i % 5 == 0:
            print(f"  {t:.2f}   | {fr:>9} | {fp:>8}")
        key = (fr * 2 + fp, fr)
        if best is None or key < best[0]:
            best = (key, t)
    print(f"العتبة المقترحة: {best[1]:.2f}")
