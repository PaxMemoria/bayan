"""مصادر الفريق: الجزء الخامس من معرفة بيان، يضيفه الفريق من اللوحة.

ثلاثة أنواع: ملاحظة تُكتب في اللوحة، ورابط صفحة تُجلب ويُستخرج نصها
وتُزامَن يومياً، وملف يُرفع (PDF أو Word أو Markdown أو نص أو HTML) ويُحفظ
نصه لا الملف. يُقطَّع النص إلى مقاطع من نوع team وتُضاف إلى الفهرس القائم
فوراً بمتجهاتها، دون إعادة فهرسة كل شيء؛ وفي الفهرسة الكاملة تُعاد من
الجدول. كل مقطع يحمل عنوان مستنده ونوعه ومصدره وتاريخه.

الرابط يُفحص قبل الجلب: http أو https فقط، ولا عناوين محلية أو خاصة، مع
فحص كل تحويلة (حماية من SSRF)، وحدّ للحجم.

Team sources: the fifth part of Bayan's knowledge, added by the team from
the dashboard.

Three kinds: a note written in the dashboard, a page link that is fetched,
its text extracted and synced daily, and an uploaded file (PDF, Word,
Markdown, text or HTML) whose text is kept, not the file. The text is split
into chunks of type team and added to the existing index at once with
their vectors, without reindexing everything; a full reindex rebuilds them
from the table. Every chunk carries its document's title, kind, origin and
date.

A link is checked before fetching: http or https only, no local or private
addresses, every redirect checked (SSRF protection), and a size limit.
"""
import html
import io
import ipaddress
import re
import socket
import time
import zipfile
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import urlsplit

import httpx

from . import config, embed, safety, store
from .arabic import normalize_ar

KINDS = ("note", "url", "file")
KIND_AR = {"note": "ملاحظة", "url": "صفحة ويب", "file": "ملف"}
MAX_UPLOAD = 15 * 1024 * 1024
MAX_FETCH = 8 * 1024 * 1024
MAX_TEXT = 300_000
MIN_TEXT = 40
MAX_TITLE = 200
MAX_PDF_PAGES = 400
ALLOWED_EXT = {".pdf", ".txt", ".md", ".markdown", ".html", ".htm", ".docx"}
FETCH_TIMEOUT = 30
MAX_REDIRECTS = 5


# ───────────────────────────────── استخراج النص / Text extraction
class _HtmlText(HTMLParser):
    """نص صفحة HTML عامة ككتل: العناوين «## …» والفقرات وعناصر القوائم،
    من <main> أو <article> إن وُجدا وإلا من المتن كله، بلا تنقّل ولا سكربت.
    The text of a generic HTML page as blocks: «## …» headings, paragraphs
    and list items, from <main> or <article> when present, otherwise the
    whole body, without navigation or scripts."""
    SKIP = {"script", "style", "noscript", "nav", "header", "footer", "aside", "template",
            "svg", "iframe", "form", "button"}
    BLOCK = {"p", "li", "td", "th", "div", "blockquote", "pre", "section", "article", "main",
             "dd", "dt", "figcaption", "tr", "br"}
    HEAD = {"h1", "h2", "h3", "h4", "h5", "h6"}
    MAIN = {"main", "article"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.blocks: list[tuple[bool, str]] = []
        self._buf: list[str] = []
        self._kind = ""
        self._skip = 0
        self._main = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag in self.SKIP:
            self._skip += 1
            return
        if self._skip:
            return
        if tag in self.MAIN:
            self._main += 1
        if tag in self.HEAD:
            self._flush()
            self._kind = "h"
        elif tag in self.BLOCK:
            self._flush()

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in self.SKIP:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag in self.HEAD or tag in self.BLOCK:
            self._flush()
        if tag in self.MAIN:
            self._main = max(0, self._main - 1)

    def handle_data(self, data):
        if self._in_title:
            self.title = (self.title + data).strip()[:MAX_TITLE]
        elif not self._skip:
            self._buf.append(data)

    def _flush(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        self._buf = []
        kind, self._kind = self._kind, ""
        if text:
            self.blocks.append((self._main > 0, f"## {text}" if kind == "h" else text))

    def close(self):
        super().close()
        self._flush()


def html_to_text(page: str) -> tuple[str, str]:
    p = _HtmlText()
    p.feed(page)
    p.close()
    inside = [t for m, t in p.blocks if m]
    blocks = inside if inside else [t for _, t in p.blocks]
    return p.title, "\n\n".join(blocks)


def pdf_to_text(data: bytes) -> str:
    from pypdf import PdfReader  # استيراد محلي: المكتبة تُحمَّل عند الحاجة / loaded on demand
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as e:  # noqa: BLE001
            raise ValueError("ملف PDF مشفّر") from e
    parts = []
    for page in reader.pages[:MAX_PDF_PAGES]:
        text = (page.extract_text() or "").strip()
        if text:
            parts.append(re.sub(r"[ \t]+", " ", text))
    return "\n\n".join(parts)


def docx_to_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
    except (zipfile.BadZipFile, KeyError) as e:
        raise ValueError("ملف Word غير صالح") from e
    paras = []
    for para in re.split(r"</w:p>", xml):
        text = html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"<w:tab/>", " ", para))).strip()
        if text:
            style = re.search(r'<w:pStyle w:val="([^"]*)"', para)
            heading = style and style.group(1).lower().startswith(("heading", "title"))
            paras.append(f"## {text}" if heading else text)
    return "\n\n".join(paras)


def plain_to_text(data: bytes) -> str:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("cp1256", "replace")
    text = text.replace("\r\n", "\n")
    # عناوين Markdown بأي مستوى تصير «## …» ليبدأ بها مقطع
    # Markdown headings of any level become «## …» so a chunk starts with them
    text = re.sub(r"^#{1,6}\s+", "## ", text, flags=re.M)
    return text


def extract(filename: str, data: bytes) -> tuple[str, str]:
    """(العنوان، النص) من ملف مرفوع. ValueError للنوع أو الحجم أو الملف التالف.
    (title, text) from an uploaded file. ValueError for the type, size or a
    broken file."""
    name = PurePosixPath(filename.replace("\\", "/")).name
    ext = PurePosixPath(name).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise ValueError("type")
    if len(data) > MAX_UPLOAD:
        raise ValueError("big")
    title = PurePosixPath(name).stem[:MAX_TITLE] or name
    if ext == ".pdf":
        text = pdf_to_text(data)
    elif ext == ".docx":
        text = docx_to_text(data)
    elif ext in (".html", ".htm"):
        page_title, text = html_to_text(data.decode("utf-8", "replace"))
        title = page_title or title
    else:
        text = plain_to_text(data)
    return title, text


# ───────────────────────────────────── جلب الروابط / Fetching links
_PRIVATE_HOSTS = {"localhost", "localhost.localdomain"}


def check_url(url: str) -> str:
    """يرفض ما ليس http(s) أو ما يشير إلى عنوان محلي أو خاص. يعيد الرابط.
    Rejects anything that is not http(s) or points to a local or private
    address. Returns the URL."""
    url = (url or "").strip()
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme not in ("http", "https") or not host or len(url) > 2000:
        raise ValueError("url")
    if host in _PRIVATE_HOSTS or host.endswith((".local", ".internal", ".localhost")):
        raise ValueError("url")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise ValueError("url") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise ValueError("url")
    return url


def fetch(url: str) -> tuple[str, str]:
    """(العنوان، النص) من صفحة على الويب، مع فحص كل تحويلة وحدّ للحجم.
    (title, text) from a web page, checking every redirect and capping the
    size."""
    url = check_url(url)
    with httpx.Client(timeout=FETCH_TIMEOUT, follow_redirects=False,
                      headers={"User-Agent": safety.USER_AGENT}) as client:
        for _ in range(MAX_REDIRECTS + 1):
            r = client.get(url)
            if r.is_redirect and r.headers.get("location"):
                url = check_url(str(r.next_request.url) if r.next_request else r.headers["location"])
                continue
            break
        else:
            raise ValueError("fetch")
        r.raise_for_status()
    if int(r.headers.get("content-length") or 0) > MAX_FETCH or len(r.content) > MAX_FETCH:
        raise ValueError("big")
    ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype == "application/pdf" or url.lower().endswith(".pdf"):
        title = PurePosixPath(urlsplit(url).path).stem or url
        return title[:MAX_TITLE], pdf_to_text(r.content)
    if ctype.startswith("text/html") or ctype in ("application/xhtml+xml", ""):
        title, text = html_to_text(r.text)
        return (title or url)[:MAX_TITLE], text
    if ctype.startswith("text/"):
        return url[:MAX_TITLE], plain_to_text(r.content)
    raise ValueError("type")


# ─────────────────────────────────────── المقاطع / Chunks
def _records(src: dict) -> list[dict]:
    blocks = [b for b in re.split(r"\n\s*\n", src["text"])]
    date = time.strftime("%Y-%m-%d", time.gmtime(src["synced"]))
    url = src["origin"] if src["kind"] == "url" else ""
    out = []
    for n, chunk in enumerate(safety.chunk_blocks(blocks)):
        out.append({
            "id": f"team:{src['id']}:{n}", "type": "team", "lang": safety._lang(chunk),
            "title": src["title"], "url": url, "text": f"{src['title']}\n{chunk}",
            "meta": {"source": src["title"], "kind": src["kind"], "origin": src["origin"],
                     "date": date, "by": src["added_by"], "source_id": src["id"]},
        })
    return out


def all_chunks() -> list[dict]:
    """مقاطع كل مصادر الفريق، للفهرسة الكاملة. All team sources' chunks, for a
    full reindex."""
    out: list[dict] = []
    for row in store.team_sources():
        src = store.team_source(row["id"])
        if src:
            out += _records(src)
    return out


def _rows(records: list[dict]) -> list[dict]:
    return [{"ext_id": r["id"], "type": r["type"], "title": r["title"], "url": r["url"],
             "text": r["text"], "norm_text": normalize_ar(r["text"]),
             "meta": {**r["meta"], "lang": r["lang"]}} for r in records]


def index_source(source_id: int) -> tuple[int, bool]:
    """يستبدل مقاطع المصدر في الفهرس القائم: (عدد المقاطع، هل لها متجهات).
    Replaces the source's chunks in the existing index: (chunk count, whether
    they have vectors)."""
    src = store.team_source(source_id)
    if not src:
        return 0, False
    rows = _rows(_records(src))
    vectors = False
    if rows and embed.enabled():
        vecs = embed.embed([r["text"] for r in rows], input_type="document")
        if vecs and len(vecs) == len(rows):
            for row, vec in zip(rows, vecs):
                row["embedding"] = vec
            vectors = True
    store.delete_chunks(f"team:{source_id}:")
    store.add_chunks(rows)
    return len(rows), vectors


def _check_text(title: str, text: str) -> tuple[str, str]:
    title = re.sub(r"\s+", " ", title or "").strip()[:MAX_TITLE]
    text = (text or "").replace("\r\n", "\n").strip()
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT]
    if not title or len(text) < MIN_TEXT:
        raise ValueError("text")
    return title, text


def add_note(title: str, text: str, by: str) -> tuple[int, bool]:
    title, text = _check_text(title, text)
    source_id = store.add_team_source("note", title, "", text, by)
    _, vectors = index_source(source_id)
    store.audit(by, "source_add", f"note:{source_id}")
    return source_id, vectors


def add_url(url: str, by: str) -> tuple[int, bool]:
    url = check_url(url)
    title, text = fetch(url)
    title, text = _check_text(title or url, text)
    source_id = store.add_team_source("url", title, url, text, by)
    _, vectors = index_source(source_id)
    store.audit(by, "source_add", f"url:{source_id}")
    return source_id, vectors


def add_file(filename: str, data: bytes, by: str) -> tuple[int, bool]:
    title, text = extract(filename, data)
    title, text = _check_text(title, text)
    source_id = store.add_team_source("file", title, PurePosixPath(filename).name[:MAX_TITLE],
                                      text, by)
    _, vectors = index_source(source_id)
    store.audit(by, "source_add", f"file:{source_id}")
    return source_id, vectors


def remove(source_id: int, by: str) -> bool:
    if not store.team_source(source_id):
        return False
    store.delete_chunks(f"team:{source_id}:")
    store.delete_team_source(source_id)
    store.audit(by, "source_delete", str(source_id))
    return True


def sync_url(source_id: int) -> bool:
    """يعيد جلب رابط: True إن تغيّر نصه وأُعيدت فهرسته. تعذّر الجلب يُسجَّل
    في حال المصدر وتبقى مقاطعه.
    Refetches a link: True if its text changed and it was reindexed. A failed
    fetch is recorded in the source's state and its chunks stay."""
    src = store.team_source(source_id)
    if not src or src["kind"] != "url":
        return False
    try:
        title, text = fetch(src["origin"])
        _, text = _check_text(title or src["title"], text)
    except Exception as e:  # noqa: BLE001 — الحال تُعرض في اللوحة / the state shows in the dashboard
        store.update_team_source(source_id, None, "error", str(e) or e.__class__.__name__)
        return False
    changed = text != src["text"]
    store.update_team_source(source_id, text if changed else None, "ok", "",
                             title=title if title and title != src["title"] else None)
    if changed:
        index_source(source_id)
    return changed


def sync_all() -> dict:
    """مزامنة كل الروابط: {"changed": n, "failed": m}. Sync every link."""
    out = {"changed": 0, "failed": 0, "total": 0}
    for row in store.team_sources():
        if row["kind"] != "url":
            continue
        out["total"] += 1
        if sync_url(row["id"]):
            out["changed"] += 1
        elif (store.team_source(row["id"]) or {}).get("status") == "error":
            out["failed"] += 1
    return out


def chunk_counts() -> dict[int, int]:
    """عدد المقاطع لكل مصدر، للوحة. Chunk count per source, for the dashboard."""
    with store.db() as conn:
        rows = conn.execute(
            "SELECT meta FROM chunks WHERE type='team'"
        ).fetchall()
    out: dict[int, int] = {}
    for r in rows:
        try:
            sid = int(__import__("json").loads(r["meta"]).get("source_id", 0))
        except (ValueError, TypeError):
            continue
        out[sid] = out.get(sid, 0) + 1
    return out


def site_url_for(src: dict) -> str:
    return src["origin"] if src["kind"] == "url" else ""


def kind_label(kind: str, lang: str) -> str:
    if lang == "en":
        return {"note": "Note", "url": "Web page", "file": "File"}.get(kind, kind)
    return KIND_AR.get(kind, kind)


def unused() -> None:  # pragma: no cover
    _ = config
