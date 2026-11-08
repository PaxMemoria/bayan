"""السلامة الرقمية: الجزء الرابع من معرفة بيان، من مصدرين مفتوحي الرخصة.

- «عدّة الأمان» Security in a Box (فرونت لاين ديفندرز)، رخصة CC BY-SA 4.0:
  صفحاته العربية ليست في مستودعه (تُبنى من ملفات ترجمة خارجه)، فتُجلب
  صفحات /ar/ المذكورة في sitemap.xml وتُقرأ من HTML.
- «عدّة الإسعاف الأولي الرقمي» Digital First Aid Kit (RaReNet وCiviCERT)،
  رخصة CC BY 4.0: ملفات Markdown عربية في مستودعه على GitLab.

يُستدعى من دورة الفهرسة بعد قراءة ناتج الموقع. ما يُجلب يُحفظ في
DATA_DIR/safety.jsonl، فإن تعذّر الجلب في دورة لاحقة بقيت النسخة السابقة،
ولا تفشل الفهرسة كلها لأن موقعاً خارجياً تعطّل. كل مقطع يحمل في meta اسم
مصدره ورخصته ورابط صفحته وتاريخ مراجعتها، ليذكرها بيان في جوابه.

Digital safety: the fourth part of Bayan's knowledge, from two openly
licensed sources.

- Security in a Box (Front Line Defenders), CC BY-SA 4.0: its Arabic pages are
  not in its repository (they are built from translation files kept
  elsewhere), so the /ar/ pages listed in sitemap.xml are fetched and read
  from HTML.
- Digital First Aid Kit (RaReNet and CiviCERT), CC BY 4.0: Arabic Markdown
  files in its GitLab repository.

Called from the indexing cycle after the site's export is read. What is
fetched is kept in DATA_DIR/safety.jsonl, so if a later fetch fails the
previous copy stays, and the whole index does not fail because an external
site is down. Every chunk carries in meta its source's name, licence, page
link and review date, for Bayan to name in its answer.
"""
import html
import json
import logging
import re
from html.parser import HTMLParser
from pathlib import Path

import httpx

from . import config

logger = logging.getLogger("safety")

SOURCES = {
    "siab": {
        "name": "Security in a Box",
        "name_ar": "عدّة الأمان",
        "publisher": "Front Line Defenders",
        "licence": "CC BY-SA 4.0",
        "licence_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "home": "https://securityinabox.org/ar/",
    },
    "dfak": {
        "name": "Digital First Aid Kit",
        "name_ar": "عدّة الإسعاف الأولي الرقمي",
        "publisher": "RaReNet وCiviCERT",
        "licence": "CC BY 4.0",
        "licence_url": "https://creativecommons.org/licenses/by/4.0/",
        "home": "https://digitalfirstaid.org/ar/",
    },
}
USER_AGENT = "Bayan/1.0 (+https://bayan.paxmemoria.org)"
# أقصى طول للمقطع بالأحرف؛ الفقرات لا تُقطع من وسطها
# Maximum chunk length in characters; paragraphs are not cut in the middle
CHUNK_CHARS = 1100
# صفحة أقصر من هذا ليست محتوى (صفحات الأقسام في Security in a Box عنوان فقط)
# A page shorter than this is not content (section pages in Security in a Box
# are only a title)
MIN_PAGE_CHARS = 200


# ──────────────────────────────── التقطيع المشترك / Shared chunking
def chunk_blocks(blocks: list[str], limit: int = CHUNK_CHARS) -> list[str]:
    """يجمع الكتل (فقرات وعناوين «## …») في مقاطع لا تتجاوز limit حرفاً.

    العنوان يبدأ مقطعاً جديداً إن كان المقطع الحالي ممتلئاً نصفه، ويبقى
    مع ما بعده لا مع ما قبله. فقرة أطول من الحدّ تبقى مقطعاً وحدها.

    Join the blocks (paragraphs and «## …» headings) into chunks of at most
    limit characters. A heading starts a new chunk when the current one is
    half full, and stays with what follows it, not with what precedes it. A
    paragraph longer than the limit stays a chunk on its own.
    """
    chunks: list[str] = []
    cur: list[str] = []
    size = 0
    for b in _split_long(blocks, limit):
        heading = b.startswith("## ")
        if cur and (size + len(b) + 1 > limit or (heading and size > limit // 2)):
            chunks.append("\n".join(cur))
            cur, size = [], 0
        cur.append(b)
        size += len(b) + 1
    if cur:
        chunks.append("\n".join(cur))
    # عنوان بقي وحده في آخر مقطع لا يفيد
    # A heading left alone in the last chunk is of no use
    if len(chunks) > 1 and chunks[-1].startswith("## ") and "\n" not in chunks[-1]:
        chunks.pop()
    return chunks


def _lang(text: str) -> str:
    """بعض صفحات /ar/ في Security in a Box لم تُترجم بعد وتُعرض بالإنجليزية،
    فلغة المقطع من حروفه لا من مساره.
    Some /ar/ pages in Security in a Box are not translated yet and show in
    English, so the chunk's language comes from its letters, not its path."""
    arabic = len(re.findall(r"[؀-ۿ]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    return "ar" if arabic >= latin // 4 else "en"


_SENTENCE_END = re.compile(r"(?<=[.!?؟।])\s+")


def _split_long(blocks: list[str], limit: int) -> list[str]:
    """فقرة أطول من الحدّ تُقسَم عند نهايات الجمل إلى قطع لا تتجاوزه.
    A paragraph longer than the limit is split at sentence ends into pieces
    within it."""
    out: list[str] = []
    for b in blocks:
        b = b.strip()
        if not b:
            continue
        if len(b) <= limit:
            out.append(b)
            continue
        piece = ""
        for sentence in _SENTENCE_END.split(b):
            if piece and len(piece) + len(sentence) + 1 > limit:
                out.append(piece)
                piece = ""
            piece = f"{piece} {sentence}".strip()
        if piece:
            out.append(piece)
    return out


def _records(source: str, slug: str, title: str, url: str, date: str,
             blocks: list[str]) -> list[dict]:
    src = SOURCES[source]
    out = []
    for n, text in enumerate(chunk_blocks(blocks)):
        out.append({
            "id": f"safety:{source}:{slug}:{n}",
            "type": "safety",
            "lang": _lang(text),
            "title": title,
            "url": url,
            "text": f"{title}\n{text}",
            "meta": {
                "source": src["name"], "source_ar": src["name_ar"],
                "publisher": src["publisher"], "licence": src["licence"],
                "licence_url": src["licence_url"], "date": date, "slug": slug,
            },
        })
    return out


# ───────────────────────── Security in a Box: من HTML / from HTML
class _SiabPage(HTMLParser):
    """يقرأ <main id="content"> من صفحة عربية: العنوان، تاريخ المراجعة، والكتل.

    يتجاهل مسار التنقّل والفهرس والصور. العناوين h2–h4 تصير «## …»، وعناصر
    القوائم «- …»، وroجِع في <p class="meta"> تاريخ المراجعة.

    Reads <main id="content"> of an Arabic page: the title, the review date and
    the blocks. Breadcrumbs, the table of contents and images are ignored.
    h2–h4 become «## …», list items «- …», and the «روجِع» line in
    <p class="meta"> is the review date.
    """
    SKIP = {("ul", "breadcrumbs"), ("div", "search-breadcrumbs"), ("div", "toc"),
            ("nav", ""), ("script", ""), ("style", ""), ("figure", "")}
    VOID = {"img", "br", "hr", "input", "meta", "link", "source"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.date = ""
        self.blocks: list[str] = []
        self._in_main = False
        self._stack: list[str] = []
        self._skip_at: int | None = None
        self._cur: list[str] | None = None
        self._kind = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "main" and a.get("id") == "content":
            self._in_main = True
            return
        if not self._in_main or tag in self.VOID:
            return
        self._stack.append(tag)
        if self._skip_at is not None:
            return
        key = (tag, a.get("id") or a.get("class") or "")
        if key in self.SKIP or (tag, "") in self.SKIP:
            self._skip_at = len(self._stack)
            return
        if tag == "h1":
            self._open("h1")
        elif tag in ("h2", "h3", "h4"):
            self._open("h")
        elif tag == "p":
            self._open("meta" if a.get("class") == "meta" else "p")
        elif tag in ("li", "summary"):
            self._open("li" if tag == "li" else "p")

    def handle_endtag(self, tag):
        if not self._in_main or tag in self.VOID:
            return
        if tag == "main":
            self._close()
            self._in_main = False
            return
        if tag in self._stack:
            while self._stack and self._stack.pop() != tag:
                pass
        if self._skip_at is not None and len(self._stack) < self._skip_at:
            self._skip_at = None
            return
        if tag in ("h1", "h2", "h3", "h4", "p", "li", "summary"):
            self._close()

    def handle_data(self, data):
        if self._in_main and self._skip_at is None and self._cur is not None:
            self._cur.append(data)

    def _open(self, kind: str) -> None:
        self._close()
        self._cur, self._kind = [], kind

    def _close(self) -> None:
        if self._cur is None:
            return
        text = re.sub(r"\s+", " ", "".join(self._cur)).strip()
        kind, self._cur = self._kind, None
        if not text:
            return
        if kind == "h1":
            self.title = self.title or text
        elif kind == "meta":
            m = re.search(r"روجِع\s+(.+)", text)
            self.date = m.group(1).strip() if m else text
        elif kind == "h":
            self.blocks.append(f"## {text}")
        elif kind == "li":
            self.blocks.append(f"- {text}")
        else:
            self.blocks.append(text)


def parse_siab(page: str, url: str) -> list[dict]:
    """مقاطع صفحة عربية واحدة من Security in a Box، أو [] إن لم تكن محتوى.
    The chunks of one Arabic Security in a Box page, or [] if it is not content."""
    p = _SiabPage()
    p.feed(page)
    p.close()
    body = "\n".join(p.blocks)
    if not p.title or len(body) < MIN_PAGE_CHARS:
        return []
    slug = url.split("/ar/", 1)[-1].strip("/") or "home"
    return _records("siab", slug, p.title, url, p.date, p.blocks)


# صفحات ليست إرشاداً: الرئيسية، عن الموقع، المدونة، السياسات، صفحة الخطأ
# Pages that are not guidance: home, about, blog, policies, the error page
_SIAB_SKIP = re.compile(r"/ar/(?:404|about|blog|disclaimer|data-use-policy|key)(?:/|$)")


def siab_urls(sitemap: str) -> list[str]:
    """الصفحات العربية الإرشادية من sitemap.xml، بترتيبها.
    The Arabic guidance pages from sitemap.xml, in order."""
    urls = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sitemap)
    out = []
    for u in urls:
        u = html.unescape(u)
        if "/ar/" in u and not _SIAB_SKIP.search(u) and not u.endswith("/ar/"):
            out.append(u)
    return out


def fetch_siab(log: list[str], client: httpx.Client) -> list[dict]:
    sitemap = client.get("https://securityinabox.org/sitemap.xml").raise_for_status().text
    urls = siab_urls(sitemap)
    if not urls:
        raise RuntimeError("sitemap.xml بلا صفحات عربية")
    chunks: list[dict] = []
    pages = failed = 0
    for u in urls:
        try:
            r = client.get(u)
            r.raise_for_status()
        except httpx.HTTPError as e:
            failed += 1
            log.append(f"⚠ Security in a Box: تعذّر {u}: {e}")
            continue
        recs = parse_siab(r.text, u)
        if recs:
            pages += 1
            chunks += recs
    # فشل واسع يعني الموقع متعطّل لا صفحة واحدة: تبقى النسخة السابقة
    # A wide failure means the site is down, not one page: the previous copy stays
    if failed > len(urls) // 5:
        raise RuntimeError(f"Security in a Box: فشل {failed} من {len(urls)} صفحة")
    log.append(f"Security in a Box: {pages} صفحة عربية، {len(chunks)} مقطع")
    return chunks


# ───────────────────────── Digital First Aid Kit: من Markdown / from Markdown
def front_matter(text: str) -> tuple[dict, str]:
    """(حقول الواجهة، المتن). قيمة على أسطر عدّة تُلحق بمفتاحها.
    (the front-matter fields, the body). A value spanning lines is appended
    to its key."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    fields: dict[str, str] = {}
    key = ""
    for line in text[3:end].splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if val in (">", "|", ">-", "|-"):
                val = ""
            fields[key] = val.strip("\"'")
        elif key and line.strip():
            fields[key] = (fields[key] + " " + line.strip()).strip()
    return fields, text[end + 4:]


# رابط Markdown، ونصّه قد يحوي قوسين معقوفين داخليين مثل [[1]](#note-1)
# A Markdown link, whose text may hold inner brackets such as [[1]](#note-1)
_MD_LINK = re.compile(r"!?\[((?:[^\[\]]|\[[^\]]*\])*)\]\([^)]*\)")
_LINK_TAIL = re.compile(r"\]\((?:https?://|#|/)[^)]*\)")
_HTML_TAG = re.compile(r"<[^>]+>")


def _plain(md: str) -> str:
    """نصّ بلا وسوم Markdown أو HTML. Text without Markdown or HTML markup."""
    s = html.unescape(_HTML_TAG.sub(" ", md))
    s = _MD_LINK.sub(r"\1", s)
    # ذيل رابط انقطع نصّه عن قوسه (نصّ على سطرين) / the tail of a link whose
    # text was cut from its bracket (text over two lines)
    s = _LINK_TAIL.sub("", s)
    s = re.sub(r"\*\*|__|`|[\[\]]", "", s)
    s = re.sub(r"[ \t ]+", " ", s)
    return s.strip()


def md_blocks(body: str) -> list[str]:
    """كتل المتن: عناوين «## …» وفقرات وعناصر قوائم.

    تُسقَط: العنوان الأول (هو عنوان الصفحة)، عناوين المراسي الإنجليزية
    التي تربط خطوات المسار (مثل «### account-disabled» و«## Workflow»)،
    وقوائم «Options» التي تحمل روابط «نعم/لا» إلى الخطوة التالية، فهي
    تنقّل لا معنى له خارج الصفحة.

    The body's blocks: «## …» headings, paragraphs and list items. Dropped:
    the first heading (it is the page title), the English anchor headings
    that link the workflow's steps («### account-disabled», «## Workflow»),
    and the «Options» lists whose «yes/no» links point to the next step,
    since that navigation means nothing outside the page.
    """
    blocks: list[str] = []
    para: list[str] = []
    in_options = False
    # تعليقات HTML في المتن قوالب للمحرّرين لا محتوى
    # HTML comments in the body are templates for editors, not content
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)

    def flush() -> None:
        if para:
            blocks.append(_plain(" ".join(para)))
            para.clear()

    for raw in body.splitlines():
        line = raw.strip()
        if line.startswith("> "):
            line = line[2:].strip()
        elif line == ">":
            line = ""
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            flush()
            text = _plain(m.group(2))
            in_options = text.lower() == "options"
            if in_options or m.group(1) == "#" or not re.search(r"[؀-ۿ]", text):
                continue
            blocks.append(f"## {text}")
            continue
        if in_options:
            continue
        if not line:
            flush()
            continue
        if re.match(r"^[-*]\s+", line) or re.match(r"^\d+[.)]\s+", line):
            flush()
            item = _plain(re.sub(r"^(?:[-*]|\d+[.)])\s+", "", line))
            if item:
                blocks.append(f"- {item}")
            continue
        # سطر مُزاح بعد عنصر قائمة تتمّةٌ له / an indented line after a list
        # item continues it
        if not para and blocks and blocks[-1].startswith("- ") and raw[:1] in (" ", "\t", ">"):
            blocks[-1] = _plain(f"{blocks[-1]} {line}")
            continue
        para.append(line)
    flush()
    return [b for b in blocks if b]


def parse_dfak(path: Path, base: str = "https://digitalfirstaid.org/ar/") -> list[dict]:
    """مقاطع ملف واحد من content/ar: موضوع أو صفحة أو منظمة دعم.
    The chunks of one file in content/ar: a topic, a page or a support organisation."""
    fields, body = front_matter(path.read_text(encoding="utf-8"))
    layout = fields.get("layout", "")
    date = fields.get("date", "")
    if layout == "organisation":
        name = fields.get("name") or path.stem
        head = [f"منظمة دعم: {name}"]
        for key, label in (("website", "الموقع"), ("languages", "اللغات"),
                           ("hours", "ساعات العمل"), ("response_time", "زمن الاستجابة"),
                           ("email", "البريد"), ("phone", "الهاتف")):
            if fields.get(key):
                head.append(f"{label}: {_plain(fields[key])}")
        blocks = ["\n".join(head)] + md_blocks(body)
        return _records("dfak", f"support/{path.stem}", name, f"{base}support/", date, blocks)
    if layout not in ("topic", "page"):
        return []
    permalink = fields.get("permalink", "").strip("/")
    title = fields.get("title", "")
    if not permalink or not title or permalink == "about":
        return []
    blocks = []
    if fields.get("summary"):
        blocks.append(_plain(fields["summary"]))
    blocks += md_blocks(body)
    return _records("dfak", permalink, title, f"{base}{permalink}/", date, blocks)


def read_dfak(repo: Path) -> list[dict]:
    root = repo / "content" / "ar"
    chunks: list[dict] = []
    for p in sorted(root.rglob("*.md")):
        if "contact-methods" in p.parts:
            continue
        chunks += parse_dfak(p)
    return chunks


def fetch_dfak(log: list[str]) -> list[dict]:
    # استيراد محلي: ingest يستورد هذه الوحدة / Local import: ingest imports this module
    from .ingest import git_sync
    repo = config.DFAK_REPO
    git_sync(repo, config.DFAK_REPO_URL, config.DFAK_BRANCH, log, label="DFAK")
    chunks = read_dfak(repo)
    if not chunks:
        raise RuntimeError("Digital First Aid Kit: لا ملفات عربية في content/ar")
    log.append(f"Digital First Aid Kit: {len(chunks)} مقطع")
    return chunks


# ────────────────────────────────────── الدورة / The cycle
def _cached() -> list[dict]:
    if not config.SAFETY_PATH.exists():
        return []
    return [json.loads(line)
            for line in config.SAFETY_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def collect(log: list[str], pull: bool = True) -> list[dict]:
    """مقاطع السلامة الرقمية لهذه الدورة.

    مع pull تُجلب المصادر المفعّلة في SAFETY_SOURCES وتُحفظ؛ وإن فشل مصدر
    بقيت مقاطعه من النسخة المحفوظة. بلا pull تُقرأ النسخة المحفوظة وحدها.

    The digital-safety chunks for this cycle. With pull, the sources enabled
    in SAFETY_SOURCES are fetched and saved; if one fails, its chunks come
    from the saved copy. Without pull, only the saved copy is read.
    """
    # بترتيب SOURCES الثابت لا ترتيب المجموعة / in SOURCES' fixed order, not the set's
    enabled = [s for s in SOURCES if s in config.SAFETY_SOURCES]
    if not enabled:
        return []
    cached = _cached()
    if not pull:
        return [c for c in cached if c["id"].split(":")[1] in enabled]
    out: list[dict] = []
    changed = False
    with httpx.Client(timeout=30, follow_redirects=True,
                      headers={"User-Agent": USER_AGENT}) as client:
        for source in enabled:
            try:
                fresh = fetch_siab(log, client) if source == "siab" else fetch_dfak(log)
                out += fresh
                changed = True
            except Exception as e:  # noqa: BLE001 — مصدر خارجي معطّل لا يُفشل الفهرسة
                # An external source that is down does not fail the index
                old = [c for c in cached if c["id"].split(":")[1] == source]
                log.append(f"⚠ {SOURCES[source]['name']}: {e} — "
                           + (f"أُبقي على {len(old)} مقطع من النسخة السابقة" if old
                              else "لا نسخة سابقة"))
                logger.warning("تعذّر جلب %s: %s", SOURCES[source]["name"], e)
                out += old
    if changed:
        config.SAFETY_PATH.parent.mkdir(parents=True, exist_ok=True)
        config.SAFETY_PATH.write_text(
            "\n".join(json.dumps(c, ensure_ascii=False) for c in out) + "\n",
            encoding="utf-8",
        )
    return out
