"""فهرسة بيان من ناتج مُستخرِج الموقع.

لا زحف على الويب: الموقع تطبيق React، ومحتواه منظّم في src/data.
هذا الخادم يسحب نسخة للقراءة فقط من مستودع الموقع، يشغّل المُستخرِج
الموجود هناك، ثم يفهرس ملفيه.

التشغيل اليدوي:  python -m app.ingest
التشغيل الآلي :  POST /admin/reindex بسرّ REINDEX_SECRET
"""
import json
import subprocess
import sys
import threading

from . import config, embed, store
from .arabic import normalize_ar


def sync_repo(log: list[str]) -> None:
    """سحب أو تحديث نسخة القراءة من مستودع الموقع."""
    repo = config.SITE_REPO
    if (repo / ".git").exists():
        cmds = [
            ["git", "-C", str(repo), "fetch", "--depth", "1", "origin", config.SITE_BRANCH],
            ["git", "-C", str(repo), "reset", "--hard", f"origin/{config.SITE_BRANCH}"],
        ]
    else:
        repo.parent.mkdir(parents=True, exist_ok=True)
        cmds = [[
            "git", "clone", "--depth", "1", "--branch", config.SITE_BRANCH,
            config.SITE_REPO_URL, str(repo),
        ]]
    for cmd in cmds:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise RuntimeError(f"فشل {' '.join(cmd[:3])}: {r.stderr.strip()[:400]}")
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()
    log.append(f"المستودع عند {head}")


def run_extractor(log: list[str]) -> None:
    script = config.SITE_REPO / "scripts" / "export-bayan-knowledge.mjs"
    if not script.exists():
        raise RuntimeError(f"المُستخرِج غير موجود: {script}")
    r = subprocess.run(
        ["node", str(script)],
        cwd=str(config.SITE_REPO), capture_output=True, text=True, timeout=600,
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
            "meta": c.get("meta", {}),
        }
        for c in chunks
    ]

    # المتجهات تُولَّد قبل لمس الفهرس: إن فشلت يبقى الفهرس السابق يعمل.
    # ومع وجود المفتاح لا نفهرس بلا متجهات بصمت — الفشل يُعلَن.
    if embed.enabled():
        log.append(f"جاري توليد المتجهات ({config.EMBED_MODEL})...")
        vectors = embed.embed([r["text"] for r in rows], input_type="document")
        if not vectors or len(vectors) != len(rows):
            raise RuntimeError("عدد المتجهات لا يطابق عدد المقاطع")
        for row, vec in zip(rows, vectors):
            row["embedding"] = vec
    else:
        log.append("⚠ لا يوجد VOYAGE_API_KEY — البحث النصي وحده.")

    store.replace_index(tool_rows, rows,
                        config.EMBED_MODEL if embed.enabled() else "")


_running = threading.Lock()


def running() -> bool:
    return _running.locked()


def run(pull: bool = True) -> tuple[bool, str]:
    """ينفّذ دورة فهرسة كاملة ويُرجع (نجح، التفاصيل)."""
    if not _running.acquire(blocking=False):
        return False, "فهرسة أخرى جارية الآن."
    try:
        return _run(pull)
    finally:
        _running.release()


def _run(pull: bool) -> tuple[bool, str]:
    store.init()
    run_id = store.start_run()
    log: list[str] = []
    try:
        if pull:
            sync_repo(log)
            run_extractor(log)
        chunks, tools = read_exports()
        index(chunks, tools, log)
        c = store.counts()
        log.append(
            f"مفهرس: {c['_chunks']} مقطع "
            f"({c.get('investigation', 0)} تحقيقات، {c.get('tool', 0)} أدوات، "
            f"{c.get('tool_removed', 0)} مُزالة) | {c['_tools']} سجل أداة"
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
