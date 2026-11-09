[العربية](README.md)

# Bayan: the Pax Memoria assistant

[![Security scans](https://github.com/PaxMemoria/bayan/actions/workflows/security-sast.yml/badge.svg?branch=main)](https://github.com/PaxMemoria/bayan/actions/workflows/security-sast.yml) [![Offline tests](https://github.com/PaxMemoria/bayan/actions/workflows/python-app.yml/badge.svg?branch=main)](https://github.com/PaxMemoria/bayan/actions/workflows/python-app.yml)

A bot that answers the public's questions about Pax Memoria's **open-source
tools guide**, its **published investigations**, the **weekly opportunities**
and **digital safety** from two openly licensed sources, and goes no further
than those. It answers in the asker's language, Arabic or English, and runs on
Telegram, WhatsApp and Facebook Messenger with the same brain and the same
knowledge base.

---

## Why a repository separate from the site's

Bayan stores the public's questions and their IDs, and a WhatsApp ID **is the
phone number**. Your audience is people asking about investigations into
killings. This data must not come near the site repository or its CI logs.

In addition, more people push to the site repository, by the nature of the
work, and Bayan speaks for the organization on WhatsApp, Telegram and
Facebook: the separation means that changing what the bot says requires a
different permission from the one needed to edit an article.

**What stays in the site repository**: only `scripts/export-bayan-knowledge.mjs`,
because it reads the internal structure of `src/data`. Keeping it next to the
data means that whoever changes the data's shape sees the script they are
about to break.

---

## How Bayan is kept within the data

Four layers, each of which is enough on its own:

| # | Layer | Where | What it does |
|---|---|---|---|
| 1 | Retrieval gate | `retrieve.py` | Computes a confidence score; below the threshold ⇒ refusal **before** the model is called. An out-of-scope question costs zero calls. |
| 2 | Restricted model | `brain.py` | Receives only the retrieved passages, and is forbidden from using its general knowledge. |
| 3 | Output check | `brain.py` | A refusal marker or an empty answer ⇒ a standard message. |
| 4 | **Link filter** | `brain.py` | **Deterministically** neutralizes any link or domain of a sensitive or removed tool **anywhere in the guide**, whatever the model wrote: a domain is written with defanged dots, such as archive[.]is, so it stays readable without becoming a link, and for a tool hosted on a shared platform such as GitHub the guide page replaces its link. Editorial rules are not left to a model's obedience. |

The filter covers the whole guide, not only the retrieved tools, because 71
of the knowledge passages themselves carry the link of a sensitive tool or
the domain of a removed tool ("its former domain (not to be opened):
github.com/…" («نطاقها السابق (لا يُفتح): github.com/…»)), and they reach the
model through the semantic path. Telegram and WhatsApp also turn a bare domain
into a clickable link. A link to an ordinary tool that shares a prefix with a
banned link (such as Google custom search engines) is exempted by exact match.

---

## Digital safety: the fourth part

The first three parts of the knowledge come from Pax Memoria itself: the
tools and the investigations from the site repository, the opportunities
from the dashboard. The fourth part comes from two external, openly licensed
sources that `app/safety.py` fetches on every reindex:

| Source | Licence | How it is fetched |
|---|---|---|
| [Security in a Box](https://securityinabox.org/ar/) (Front Line Defenders) | CC BY-SA 4.0 | Its Arabic pages are not in its repository, so the `/ar/` pages in `sitemap.xml` are fetched and read from HTML (without the blog, the "about" pages and the policies). |
| [Digital First Aid Kit](https://digitalfirstaid.org/ar/) (RaReNet and CiviCERT) | CC BY 4.0 | A shallow clone of its GitLab repository; the `content/ar` files are read (topics, pages and support organisations). |

Every chunk carries its source, licence, page link and review date, and the
system instructions require Bayan to name them in the answer, to stay general
guidance rather than a judgement on the asker's situation, and to refer anyone
describing an ongoing danger to the support organisations. What is fetched is
kept in `DATA_DIR/safety.jsonl`; if a source is down on a later cycle, its
previous copy stays and the reindex does not fail. `SAFETY_SOURCES` (default
`siab,dfak`) limits the sources, and an empty value disables the part.

---

## Two retrieval paths

Tools are a **database**, not text, so they have two paths:

- **Structured**: "What translation tools are there?" («ما أدوات الترجمة؟»)
  ⇒ a filter on the category field that returns the full list, in order. A
  list is only shown when the question looks like a request for a list, so
  that someone asking about a single tool is not flooded.
- **Semantic**: "How do I verify the date of a photo?" («كيف أتحقق من تاريخ
  صورة؟») is a question of meaning, so it goes to hybrid search.

Investigations are text, so they go to the semantic path only.

---

## ⚠ Why vectors are necessary, not optional

Without vectors, only lexical search runs, and it measures matching words,
not meaning. `scripts/calibrate.py` measures the difference on 20 legitimate
questions and 16 out-of-scope questions (`scripts/calibration_questions.json`):

| At threshold 0.30 | Lexical search alone | `voyage-4-nano` at 1024 dimensions |
|---|---|---|
| Legitimate questions wrongly refused | 13 of 20 | 0 of 20 |
| Out-of-scope questions that reach the model | 0 of 16 | 6 of 16 |

"How do I verify a photo's geographic location?" («كيف أتحقق من موقع صورة
جغرافياً؟») scores lower with lexical search than "What is the capital of
France?" («ما هي عاصمة فرنسا؟»), because the question uses words other than
the words in the content, and that is exactly what the public's questions look
like.

Separation with vectors is not complete. The out-of-scope questions with the
highest confidence are deliberately close to the guide's topics, such as "How
do I hack into someone else's Facebook account?" («كيف أخترق حساب فيسبوك لشخص
آخر؟», 0.46), and the guide does contain Facebook tools. No threshold separates
them without refusing legitimate questions, so the model refuses them in
layers 2 and 3, and each of those is a paid call. The 0.30 threshold prefers
not to refuse a legitimate asker, and can be raised from the dashboard if
Refused by the model («رفضه النموذج») becomes frequent in the question log.

### The local model `voyage-4-nano` (default)

It runs on Bayan's own server, so no question from the public leaves the
server, and no key or account is needed. The model has open weights
(Apache 2.0), comes from Voyage AI, and shares one vector space with the rest
of the voyage-4 family.

- **No code from the network**: the model code is copied into
  `app/nano/modeling.py` from a pinned revision, with its license and its
  copyright notice, instead of using `trust_remote_code`.
- **Pinned weights**: `scripts/fetch_model.py` downloads the weights (0.7 GB)
  at the same revision when the Docker image is built, and checks their
  SHA-256 hash. After the build, the server runs without a connection to
  Hugging Face (`HF_HUB_OFFLINE=1`).
- **CPU-only `torch`**, so no CUDA libraries are installed.

What we measured in a Linux Docker container on 10 cores, with a 4 GB memory
limit and no network. torch is slower on Linux than on macOS, so these figures
are closer to what a server can expect:

| | |
|---|---|
| Loading the model at startup | 4 seconds, in the background |
| Indexing 1,039 passages | 453 seconds |
| Time per question (vector and retrieval) | about 600 ms |
| Server memory while running | 1.8 GB |
| Peak memory during indexing | under 3 GB (it completed within the 4 GB limit) |
| Image size | 3.7 GB, of which the model is 0.7 GB and torch 0.65 GB |

**The server needs at least 4 GB of memory available to Bayan.**
`EMBED_THREADS` sets the number of cores if Bayan shares the server with other
software.

### The Voyage service (optional)

`EMBED_PROVIDER=voyage` with `VOYAGE_API_KEY`. The key is created in MongoDB
Atlas from the "AI Model APIs" menu, and works with
`https://ai.mongodb.com/v1/embeddings` (`VOYAGE_ENDPOINT`). An account without
a payment method was limited to three requests and 10 thousand tokens per
minute, which is less than a single batch of Bayan's passages, so check the
limits in Atlas before indexing. With this option the text of every question
is sent to the service, including out-of-scope questions that never reach the
answer model.

### What protects the index

Indexing generates the vectors **before** touching the index, so if it fails
the previous index keeps working and the failure shows in the dashboard. The
server picks up the new index by itself, without a restart. If the vectors
fail during a live question, the question is answered with lexical search
instead of Bayan going silent. Changing the provider, `EMBED_MODEL` or
`EMBED_DIM` disables semantic search until the index is rebuilt, because
vectors from two different settings cannot be compared.

---

## Editorial rules

Drawn from the fields of your own data, and enforced in code, not only in the
prompt:

- **`Verification` is a grade of evidence from the OTVS audit, not a safety
  verdict.** Bayan is forbidden from saying "verified" («موثّقة»), "safe"
  («آمنة») or "approved" («معتمدة»). `trained` is passed on as "not reviewed
  live in the latest audit" («لم تُراجَع حيّاً في آخر تدقيق»).
- **Sensitive tools, or tools with a `Caution`**: the warning must be passed
  on, and the direct link is forbidden. The asker is referred to
  `/osint-tools` so that the warning is seen in context, exactly as your site
  does.
- **Removed tools (69)**: Bayan says that they were removed, when and why,
  with no link and no domain that can be opened, and gives the replacement if
  there is one.
- **Investigations**: no attribution of responsibility or intent except in the
  investigation's own wording, no estimating of numbers, and no generalizing
  from one incident to a pattern.
- **Replacements**: a tool is called a replacement for a removed tool only if
  it is in the removed tool's Replacement field. Other tools in the same
  category are described as other tools, not replacements.
- **Sources**: every source the model receives is numbered, and the model ends
  its answer with a hidden line naming the numbers it relied on, so the asker
  sees only those links. Without this, an answer about tracking flights cited
  two unrelated investigations.
- **The same rules in English**: "verified", "safe", "approved" and "trusted"
  are as forbidden as their Arabic counterparts.

---

## The two languages and the answer model

- **Language detection** (`app/i18n.py`): two or more Arabic letters make a
  question Arabic; otherwise Latin letters make it English, and any other
  language is answered in Arabic. Tool names are mostly in Latin letters, so
  «ما هي أداة Google Earth Pro؟» stays Arabic.
- **Investigations in both languages**: the extractor exports 20 Arabic and
  13 English investigations. An investigation that has a version in the
  asker's language is not also retrieved in the other language, so one story
  does not take two of the six passage slots.
- **Fixed messages** (refusal, daily limit, pause, error) exist in both
  languages; the welcome and `/help` carry both at once, since a command has
  no language.
- **The answer model**: `ANSWER_MODEL`, with thinking depth `ANSWER_EFFORT`
  (default `medium`, because the editorial rules are strict). No
  `temperature`: the API removed it on 21 October 2026, and thinking tokens
  count against `MAX_OUTPUT_TOKENS` (4000). A safety-classifier decline is
  treated as a model refusal, and `ANSWER_FALLBACK=default` reruns cyber and
  frontier_llm declines on a fallback model so a legitimate question about a
  security tool is not refused by mistake. The SDK version is pinned in
  `requirements.txt`: an unpinned update is what broke every answer in the
  first deployment.

---

## Running

```bash
cp .env.example .env     # set ANTHROPIC_API_KEY and the dashboard and channel keys
docker compose up -d --build   # the first build downloads the local model (0.7 GB)
docker compose exec bayan python -m app.ingest
```

After the first indexing, and after any change of embedding model, calibrate
the threshold: `docker compose exec bayan python scripts/calibrate.py`.

`python -m app.ingest` pulls the site repository, runs the extractor, and
indexes. Add `--no-pull` to index from existing files without pulling.

### Trying it before connecting any channel

From a browser: the Try Bayan («جرّب بيان») page in the dashboard. From the
command line, only from inside the server:

```bash
docker compose exec bayan curl -s localhost:8000/debug/ask \
  -H 'content-type: application/json' \
  -d '{"question":"ما هي أدوات الترجمة؟"}'
```

It returns the answer, the confidence score, the matched tools, the category
and the passages. `/debug/ask` only answers from inside the server; left open,
it would let anyone call the model with no rate limit. Then:

```bash
docker compose exec bayan python tests/test_bayan.py    # on the real index
docker compose exec bayan python tests/test_offline.py  # with no keys and no network
```

---

## Dashboard

At `PUBLIC_URL/admin`, in English by default and in Arabic with a button in the
sidebar (the choice is kept in a cookie), without JavaScript. It is enabled when
`.env` sets `ADMIN_PASSWORD` (at least 12 characters) and `SESSION_SECRET` (at
least 32 characters, `python -c "import secrets;print(secrets.token_urlsafe(48))"`).

- **Overview** («نظرة عامة»): the state of the index and the vectors, a red
  alert with its reason for as long as semantic search is off, the outcomes of
  questions in the last 7 days, and the last indexing run with a button to run
  it again.
- **Questions** («الأسئلة»): every question with Bayan's reply and its
  confidence score, filterable by outcome, channel and rating. The questions
  the gate refused, sorted by confidence, are the tool for tuning the
  threshold. Under each answer: a 👍 or 👎 rating with a reason and a note, and
  a "Write a correction" link.
- **Corrections** («التصحيحات»): approved answers the team writes in its own
  words. Every new question is compared with their questions, and one that
  reaches `CORRECTION_MIN_SIMILARITY` (0.75) is sent to the model ahead of the
  other sources and takes precedence over them, from the moment it is saved and
  without reindexing. They are also a test set that grows over time:
  `scripts/check_corrections.py` asks their questions again after any change.
- **Try Bayan** («جرّب بيان»): a question without a channel, with the
  retrieved passages and the matching corrections.
- **Data sources** («مصادر البيانات», editors and above): the fifth part of
  the knowledge, added by the team from the dashboard: a note, a page link
  whose text is fetched and synced daily, or a file (PDF, Word, Markdown, text
  or HTML) whose text is kept, not the file. It enters the index at once with
  its vectors, without a full reindex (`app/sources.py`), and Bayan treats it
  as a source within its scope and names the document. Links are checked
  before fetching (http/https only, no local or private addresses, every
  redirect checked, 8 MB cap) and files up to 15 MB.
- **Bayan's role** («دور بيان», admin only): Bayan's scope, extra team rules
  appended to the system instructions, and the refusal, welcome and paused
  texts in both languages, edited from the dashboard, applied at once and
  taking precedence over `.env`; an empty field restores the default, and the
  fixed rules (no general knowledge, the link and investigation rules) cannot
  be changed there.
- **Settings** («الإعدادات», admin only): the threshold, the daily question
  limit and the pause button, applied without a restart, the connection status
  of each channel, and **API keys**: the Claude, Gemini, Voyage and local-model
  keys and the Facebook page and WhatsApp tokens can be saved from the
  dashboard into Bayan's database; they take precedence over `.env` and work at
  once, only their last four characters are shown after saving, and every save
  or clear goes to the action log. The Telegram token and the Meta app secret
  stay in `.env`, since changing them needs a restart.
- **Blocked** («المحظورون»): blocking from the question log, and lifting a
  block.

**Privacy**: a WhatsApp ID is the phone number, so the dashboard shows no IDs.
Each user appears as an eight-character fingerprint derived with
`SESSION_SECRET`, so it cannot be reversed to the number by trying every
number, and blocking is done by message number. The session is a signed
`HttpOnly`, `SameSite=Strict` cookie that lasts 12 hours, changing the
password logs out every session, and login attempts are limited to five every
quarter of an hour.

---

## Automatic updates

1. On Bayan's server: `bash scripts/setup_deploy_key.sh`, then add the public
   key to the site repository as a **read-only Deploy key**.
2. Copy `site-workflow/bayan-reindex.yml` into the site repository under
   `.github/workflows/`.
3. Add to the site repository's secrets: `BAYAN_REINDEX_URL` and
   `BAYAN_REINDEX_SECRET`.

On every merge that touches the tools or the investigations, the workflow
runs the extractor **as a check first** (so if a change to the data structure
breaks it, the workflow fails at once, instead of Bayan silently failing to
learn about the latest investigation), then sends a single signal to the
server. The server replies at once with 202 and indexes in the background,
because indexing with the local model takes minutes (453 seconds in a
container on 10 cores); the result is shown in the dashboard. If a signal
arrives while indexing is running, one more cycle follows that includes the
latest change.

**None of Bayan's keys pass through the site's CI.**

---

## Connecting the channels

**Telegram** (the fastest, no approvals): `@BotFather` → `/newbot` → put the
token and `TELEGRAM_WEBHOOK_SECRET` in `.env` →
`python scripts/set_telegram_webhook.py`. The secret is required: without it
the server refuses every update, because anyone who knew the URL could send
fake updates.

**WhatsApp**: a Business app on developers.facebook.com → the WhatsApp product
→ a webhook at `…/webhooks/meta` with `META_VERIFY_TOKEN` → subscribe to
`messages`. Use a System User Token in production (the temporary token is
valid for 24 hours).

**Messenger**: the same app → the Messenger product → the same webhook URL →
subscribe to `messages` and `messaging_postbacks` → App Review for
`pages_messaging`.

---

## Structure

```
app/
  config.py     settings from .env
  arabic.py     Arabic normalization + overlap weighted by rarity
  store.py      SQLite: chunks + tools + messages + settings
  ingest.py     pull the repository, run the extractor, index
  embed.py      vectors: the local model or the Voyage service
  nano/         voyage-4-nano: the copied code, its license and the pinned revision
  retrieve.py   the two paths: structured + semantic
  brain.py      ★ the four layers and the editorial rules
  dashboard.py  the dashboard, ratings and approved corrections
  overview.py   the overview of the guide and investigations, for general questions
  main.py       webhooks + /admin/reindex + /debug/ask
  channels/     Telegram, WhatsApp, Messenger
scripts/        Telegram webhook, deploy key, model download, threshold calibration, correction checks
site-workflow/  copied into the site repository
tests/          test_bayan on the real index, test_offline with no keys
```

## Privacy and data deletion

- **The privacy policy** is at `PUBLIC_URL/privacy`, in Arabic and English
  (`app/privacy.py`). Askers reach it with `/privacy` or «الخصوصية», and the
  welcome links to it. Its figures (retention period, daily limit,
  conversation memory) are read from the settings themselves.
- **Automatic deletion**: questions and answers are deleted after
  `MESSAGE_RETENTION_DAYS` (30 days), at startup and then every 6 hours. The
  database runs with `secure_delete`, so deleted text does not linger in the
  file.
- **Deleting a conversation**: `/reset` or «مسح» deletes the asker's
  conversation immediately. The daily limit counts from a separate record
  (identifier and time, 24 hours), so deleting the conversation does not
  reset it.
- **Ratings and corrections**: an answer's rating is deleted with its message.
  An approved correction is written by the team in its own words, without any
  personal detail from the message, so it stays after the messages are deleted.
- **Logs**: Bayan writes no question text to the server log, and the Docker
  log is capped at 3 files of 10 MB.

## Security notes

- The `X-Hub-Signature-256` signature is verified on every request from Meta.
- Telegram is protected by a `secret_token` in the header, and it is required.
- `/debug/ask` works only from inside the server, and `/admin/status` is
  behind the dashboard login.
- The site extractor runs in isolation, because the `src/data` files are
  JavaScript modules written by everyone who pushes to the site's `main`. It
  runs with no environment variables, so it cannot see Bayan's keys, and the
  Node permission model limits its reads to the site repository and its writes
  to `bayan-export`, and stops it from running commands. So a malicious change
  there cannot reach Bayan's keys or the question database. Node 22 does not
  restrict the network in this model, but nothing secret is available for the
  extractor to send.
- The dashboard blocks all scripts with a CSP header, escapes all text from
  the public, and rejects requests from another origin.
- `seen_events` prevents a duplicate reply when a webhook is sent again.
- A rate limit per user + a block table.
- A daily limit: 10 questions per user in any 24 hours, per channel
  (`DAILY_LIMIT`, adjustable from the dashboard). Anyone who reaches it gets a
  message telling them when they can ask again, and the model is not called.
  Commands such as `/start` are not counted.
- `.env` and `data/` are excluded in `.gitignore`. Keep the repository
  **private**.
