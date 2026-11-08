"""فهرسة بيان من ناتج مُستخرِج الموقع.

لا زحف على الويب: الموقع تطبيق React، ومحتواه منظّم في src/data.
هذا الخادم يسحب نسخة للقراءة فقط من مستودع الموقع، يشغّل المُستخرِج
الموجود هناك، ثم يفهرس ملفيه.

التشغيل اليدوي:  python -m app.ingest
التشغيل الآلي :  POST /admin/reindex بسرّ REINDEX_SECRET

Indexing Bayan from the output of the site's extractor.

No web crawling: the site is a React app, and its content is structured
in src/data. This server pulls a read-only copy of the site repository,
runs the extractor that lives there, then indexes its two files.

Manual run:     python -m app.ingest
Automatic run:  POST /admin/reindex with the REINDEX_SECRET secret
"""
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from . import config, embed, safety, store
from .arabic import normalize_ar


def sync_repo(log: list[str]) -> None:
    """سحب أو تحديث نسخة القراءة من مستودع الموقع.
    Clone or update the read-only copy of the site repository."""
    git_sync(config.SITE_REPO, config.SITE_REPO_URL, config.SITE_BRANCH, log)


def git_sync(repo: Path, url: str, branch: str, log: list[str],
             label: str = "المستودع") -> None:
    """سحب أو تحديث نسخة ضحلة للقراءة من مستودع git على فرع واحد.
    Clone or update a shallow read-only copy of a git repository on one branch."""
    if (repo / ".git").exists():
        cmds = [
            # المرجع صريح: نسخة --depth 1 --branch تتبع فرعها الأول وحده، فلا
            # يحدّث «fetch origin main» المرجع origin/main إن تغيّر SITE_BRANCH.
            # Explicit refspec: a --depth 1 --branch clone tracks only its first
            # branch, so «fetch origin main» would not update origin/main if
            # SITE_BRANCH changed.
            ["git", "-C", str(repo), "fetch", "--depth", "1", "origin",
             f"+refs/heads/{branch}:refs/remotes/origin/{branch}"],
            ["git", "-C", str(repo), "reset", "--hard", f"origin/{branch}"],
        ]
    else:
        repo.parent.mkdir(parents=True, exist_ok=True)
        cmds = [["git", "clone", "--depth", "1", "--branch", branch, url, str(repo)]]
    for cmd in cmds:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise RuntimeError(f"فشل {' '.join(cmd[:3])}: {r.stderr.strip()[:400]}")
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()
    log.append(f"{label} عند {head}")


def run_extractor(log: list[str]) -> None:
    """يشغّل مُستخرِج الموقع معزولاً.

    ملفات src/data وحدات JavaScript تُنفَّذ هنا، ومن يدفع إلى main الموقع
    يكتبها. بلا عزل يصير تعديل في الموقع كوداً يعمل على خادم بيان بمفاتيحه
    وبأرقام هواتف الجمهور، وهذا ما فُصل المستودعان لمنعه. لذلك يُشغَّل:
    بلا متغيرات بيئة (فيها مفاتيح بيان)، وبنموذج صلاحيات Node: قراءة داخل
    المستودع وحده، وكتابة في bayan-export وحده، وبلا عمليات فرعية.

    Run the site's extractor in isolation.

    The files in src/data are JavaScript modules that run here, and anyone
    who pushes to the site's main branch writes them. Without isolation, an
    edit to the site becomes code running on Bayan's server, with its keys
    and the public's phone numbers, which is what the two repositories were
    separated to prevent. So it runs with no environment variables (they
    hold Bayan's keys), and under the Node permission model: reads only
    inside the repository, writes only in bayan-export, and no child
    processes.
    """
    repo = config.SITE_REPO.resolve()
    out = config.EXPORT_DIR.resolve()
    script = repo / "scripts" / "export-bayan-knowledge.mjs"
    if not script.exists():
        raise RuntimeError(f"المُستخرِج غير موجود: {script}")
    # الصلاحية تُمنح لمسار موجود عند الإقلاع، فيُنشأ المجلد قبل التشغيل
    # Permission is granted to a path that exists at startup, so the folder is
    # created before the run
    out.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["node", "--permission", f"--allow-fs-read={repo}",
         f"--allow-fs-write={out}", str(script)],
        cwd=str(repo), capture_output=True, text=True, timeout=600,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": "/tmp",  # nosec B108
             "LANG": "C.UTF-8"},
    )
    if r.returncode != 0:
        raise RuntimeError(f"فشل المُستخرِج: {r.stderr.strip()[:800]}")
    log.append(r.stdout.strip())


def read_exports() -> tuple[list[dict], list[dict]]:
    if not config.KNOWLEDGE_PATH.exists():
        raise RuntimeError(f"لم يُعثر على {config.KNOWLEDGE_PATH}")
    chunks = [
        json.loads(line)
        for line in config.KNOWLEDGE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    tools = json.loads(config.TOOLS_PATH.read_text(encoding="utf-8"))
    return chunks, tools


def index(chunks: list[dict], tools: list[dict], log: list[str]) -> None:
    # الأدوات كقاعدة بيانات — تُستعلَم بالتصنيف والاسم مباشرة
    # Tools as a database, queried directly by category and name
    tool_rows = [
        {
            "name": t["name"],
            "norm_name": normalize_ar(t["name"]),
            "category_ar": t.get("category_ar"),
            "category_en": t.get("category_en"),
            "norm_category": normalize_ar(t.get("category_ar") or ""),
            "summary_ar": t.get("summary_ar"),
            "summary_en": t.get("summary_en"),
            "link": t.get("link"),
            "domain": t.get("domain"),
            "verification": t.get("verification"),
            "sensitive": int(bool(t.get("sensitive"))),
            "caution": t.get("caution"),
            "removed": int(bool(t.get("removed"))),
            "removal_type_ar": t.get("removal_type_ar"),
            "removal_reason_ar": t.get("removal_reason_ar"),
            "removal_date": t.get("removal_date"),
            "replacement": t.get("replacement"),
            "url": t.get("url"),
        }
        for t in tools
    ]

    rows = [
        {
            "ext_id": c["id"],
            "type": c["type"],
            "title": c.get("title"),
            "url": c["url"],
            "text": c["text"],
            "norm_text": normalize_ar(c["text"]),
            # لغة المقطع في meta، ليختار الاسترجاع نسخة التحقيق بلغة السائل
            # The passage language goes in meta, so retrieval can pick the version of
            # an investigation in the asker's language
            "meta": {**c.get("meta", {}), "lang": c.get("lang", "ar")},
        }
        for c in chunks
    ]

    # المتجهات تُولَّد قبل لمس الفهرس: إن فشلت يبقى الفهرس السابق يعمل.
    # ومع وجود المفتاح لا نفهرس بلا متجهات بصمت — الفشل يُعلَن.
    # Vectors are generated before the index is touched: if that fails, the
    # previous index keeps working. And when the key is present we never
    # index without vectors silently; the failure is reported.
    if embed.enabled():
        log.append(f"جاري توليد المتجهات ({embed.model_id()})...")
        vectors = embed.embed([r["text"] for r in rows], input_type="document")
        if not vectors or len(vectors) != len(rows):
            raise RuntimeError("عدد المتجهات لا يطابق عدد المقاطع")
        for row, vec in zip(rows, vectors):
            row["embedding"] = vec
    else:
        log.append(f"⚠ {embed.unavailable_reason()}. البحث النصي وحده.")

    store.replace_index(tool_rows, rows, embed.model_id() if embed.enabled() else "")


_running = threading.Lock()


def running() -> bool:
    return _running.locked()


def run(pull: bool = True) -> tuple[bool, str]:
    """ينفّذ دورة فهرسة كاملة ويُرجع (نجح، التفاصيل).
    Run a full indexing cycle and return (succeeded, details)."""
    if not _running.acquire(blocking=False):
        return False, "فهرسة أخرى جارية الآن."
    try:
        return _run(pull)
    finally:
        _running.release()


_queue = threading.Lock()
_again = False


def start_background(pull: bool = True) -> str:
    """يبدأ فهرسة في الخلفية ويعود فوراً: "started" أو "queued".

    الفهرسة بالنموذج المحلي تستغرق دقائق على معالج خادم، وطلب ينتظرها
    يتجاوز مهلة workflow الموقع. وإشارة تصل أثناء فهرسة جارية تُحفظ
    لدورة واحدة بعدها، فتعديل دُمج أثناء الفهرسة لا يفوت بيان.

    Start indexing in the background and return at once: "started" or
    "queued".

    Indexing with the local model takes minutes on a server CPU, and a
    request that waited for it would go past the site workflow's timeout. A
    signal that arrives while indexing is running is kept for one more cycle
    after it, so a change merged during indexing is not missed by Bayan.
    """
    global _again
    with _queue:
        if not _running.acquire(blocking=False):
            _again = True
            return "queued"
    threading.Thread(target=_background, args=(pull,), daemon=True).start()
    return "started"


def _background(pull: bool) -> None:
    """يملك _running من لحظة start_background حتى آخر دورة.
    Holds _running from the moment of start_background until the last cycle."""
    global _again
    while True:
        try:
            _run(pull)
        except Exception:  # noqa: BLE001 — _run يسجّل فشله، وهذا احتياط للقفل
            # _run logs its own failure; this is a safeguard for the lock
            pass
        with _queue:
            # التحرير داخل _queue: إشارة تصل بين القرار والتحرير لا تضيع
            # Release inside _queue: a signal that arrives between the decision and
            # the release is not lost
            if not _again:
                _running.release()
                return
            _again = False


def _run(pull: bool) -> tuple[bool, str]:
    store.init()
    run_id = store.start_run()
    log: list[str] = []
    try:
        if pull:
            sync_repo(log)
            run_extractor(log)
        chunks, tools = read_exports()
        # السلامة الرقمية من مصدريها الخارجيين؛ تعذّرهما لا يُفشل الدورة
        # Digital safety from its two external sources; their failure does not
        # fail the cycle
        chunks += safety.collect(log, pull)
        index(chunks, tools, log)
        c = store.counts()
        log.append(
            f"مفهرس: {c['_chunks']} مقطع "
            f"({c.get('investigation', 0)} تحقيقات، {c.get('tool', 0)} أدوات، "
            f"{c.get('tool_removed', 0)} مُزالة، {c.get('safety', 0)} سلامة رقمية) | "
            f"{c['_tools']} سجل أداة"
        )
        detail = "\n".join(log)
        store.finish_run(run_id, True, c["_chunks"], c["_tools"], detail)
        return True, detail
    except Exception as e:  # noqa: BLE001
        log.append(f"✗ {e}")
        detail = "\n".join(log)
        store.finish_run(run_id, False, 0, 0, detail)
        return False, detail


if __name__ == "__main__":
    pull = "--no-pull" not in sys.argv
    ok, detail = run(pull=pull)
    print(detail)
    sys.exit(0 if ok else 1)
