[العربية](README.ar.md)

# Bayan: a grounded assistant for your organisation's content

[![Security scans](https://github.com/PaxMemoria/bayan/actions/workflows/security-sast.yml/badge.svg?branch=main)](https://github.com/PaxMemoria/bayan/actions/workflows/security-sast.yml) [![Offline tests](https://github.com/PaxMemoria/bayan/actions/workflows/python-app.yml/badge.svg?branch=main)](https://github.com/PaxMemoria/bayan/actions/workflows/python-app.yml)

Bayan answers the public's questions **only from the content you give it**:
your website or document repository, notes and files your team adds from a
dashboard, lists you publish every week, and openly licensed sources you
choose. It refuses everything else, answers in the asker's language (Arabic
and English today, more languages in progress), and runs on Telegram,
WhatsApp and Facebook Messenger with one brain and one knowledge base.

It was built by [Pax Memoria](https://paxmemoria.org), a non-profit, for its
own guide and publications, and is released under Apache 2.0 for any
organisation that needs the same: an assistant that cannot wander off its
sources, with the editorial rules enforced in code rather than left to a
model's obedience.

---

## How you feed it

Five kinds of content, all optional except the first:

| Part | Where it comes from | How it is kept fresh |
|---|---|---|
| **Your site or repository** | An extractor script of yours exports two files from your content: `knowledge.jsonl` (passages) and `tools.json` (structured entries with fields such as category, link, caution, verification). Bayan pulls the repository with a read-only deploy key and runs the script in isolation. | A workflow in your repository signals Bayan after every merge, and it reindexes in the background (`site-workflow/bayan-reindex.yml`). |
| **Team sources** | From the dashboard: a note, a page link, or an uploaded file (PDF, Word, Markdown, text, HTML). The extracted text is kept, not the file. | Added to the index at once with its vectors; links are re-fetched daily. |
| **Weekly lists** | Numbered lists the team pastes into the dashboard each week (for example opportunities, events, announcements), numbered by ISO week. | Published at once; broadcast to subscribers on the enabled channels. |
| **Openly licensed sources** | External sites or repositories under licences that allow reuse, fetched and attributed per answer (`app/safety.py`; the defaults are two digital-safety guides under CC BY-SA 4.0 and CC BY 4.0). | Re-fetched on every reindex; if a source is down, its previous copy stays. |
| **Approved corrections** | Answers the team writes in its own words for a question. | Take precedence over every other source from the moment they are saved. |

### The export contract

Your extractor produces, in a folder Bayan can read (`EXPORT_DIR`):

- `knowledge.jsonl`: one JSON object per line with `id`, `type` (for example
  `article`, `page`, `about`), `lang` (`ar` or `en`), `title`, `url`, `text`
  (the passage, roughly 500–1200 characters) and a free `meta` object
  (`slug`, `date`, `author`, `position`…). An article available in two
  languages uses the same slug with an `-en` suffix for the English version,
  so retrieval shows the asker one version, in their language.
- `tools.json`: a list of structured entries with `name`, `category_ar`,
  `category_en`, `summary_ar`, `summary_en`, `link`, `domain`, `verification`,
  `sensitive`, `caution`, `removed`, `removal_type_ar`, `removal_reason_ar`,
  `removal_date`, `replacement`, `url`. Any catalogue with categories fits:
  tools, services, organisations, datasets.

The reference extractor lives in the content repository, next to the data it
reads, so whoever changes the data's shape sees the script they are about to
break.

---

## Why a repository separate from your site's

Bayan stores the public's questions and channel identifiers, and a WhatsApp
identifier **is the phone number**. That data must not come near a content
repository or its CI logs. More people push to a content repository, by the
nature of the work, and the bot speaks for the organisation on public
channels: the separation means that changing what the bot says requires a
different permission from the one needed to edit a page.

---

## How Bayan is kept within the data

Four layers, each enough on its own:

| # | Layer | Where | What it does |
|---|---|---|---|
| 1 | Retrieval gate | `retrieve.py` | Computes a confidence score; below the threshold ⇒ refusal **before** the model is called. An out-of-scope question costs zero calls. |
| 2 | Restricted model | `brain.py` | Receives only the retrieved passages and is forbidden from using its general knowledge, even to explain a term. |
| 3 | Output check | `brain.py` | A refusal marker or an empty answer ⇒ a standard message. |
| 4 | **Link filter** | `brain.py` | **Deterministically** neutralises any link or domain of an entry marked sensitive or removed, **anywhere in the catalogue**, whatever the model wrote: the domain is written with defanged dots (`example[.]org`) so it stays readable without becoming a link, and an entry hosted on a shared platform is replaced by your catalogue page. |

The filter covers the whole catalogue, not only the retrieved entries,
because passages themselves can carry such links and reach the model through
the semantic path, and messaging apps turn a bare domain into a clickable
link.

---

## Two retrieval paths

Structured entries are a **database**, not text, so they have two paths:

- **Structured**: "What translation tools are there?" ⇒ a filter on the
  category field that returns the full list, in order. A list is only shown
  when the question looks like a request for a list.
- **Semantic**: "How do I verify the date of a photo?" is a question of
  meaning, so it goes to hybrid search (lexical + vectors, fused by rank).

Passages (articles, pages, team sources, external sources) go to the semantic
path only. An article that has a version in the asker's language is not also
retrieved in the other language.

---

## Why vectors are necessary, not optional

Without vectors only lexical search runs, and it measures matching words, not
meaning. `scripts/calibrate.py` measures the difference on a set of
legitimate and out-of-scope questions (`scripts/calibration_questions.json`,
add your own). In the reference deployment, lexical search alone wrongly
refused 13 of 20 legitimate questions at the default threshold; with vectors,
none. Separation is still not complete: out-of-scope questions deliberately
close to your topics can pass the gate and are refused by the model in layers
2 and 3, each a paid call. The threshold is tuned from the dashboard.

### The local embedding model (default)

`voyage-4-nano` runs on Bayan's own server, so no question leaves the server
and no key or account is needed. Open weights (Apache 2.0), one vector space
with the rest of the voyage-4 family.

- **No code from the network**: the model code is copied into
  `app/nano/modeling.py` from a pinned revision, with its licence, instead of
  `trust_remote_code`.
- **Pinned weights**: `scripts/fetch_model.py` downloads the weights (0.7 GB)
  at the same revision when the Docker image is built and checks their SHA-256.
  After the build the server runs offline from Hugging Face.
- **CPU-only `torch`**, no CUDA.

Measured in a Linux container on 10 cores with a 4 GB memory limit: loading
4 s at startup (in the background), indexing about 1,000 passages 453 s,
about 600 ms per question, 1.8 GB of memory while serving, under 3 GB at
peak. **The server needs at least 4 GB of memory available to Bayan**;
`EMBED_THREADS` sets the cores if the server is shared.

### The Voyage service (optional)

`EMBED_PROVIDER=voyage` with `VOYAGE_API_KEY`. With this option the text of
every question is sent to the service, including out-of-scope questions that
never reach the answer model.

### What protects the index

Indexing generates the vectors **before** touching the index: if it fails,
the previous index keeps working and the failure shows in the dashboard. The
server picks up a new index by itself, without a restart. If vectors fail
during a live question, the question is answered with lexical search instead
of the bot going silent. Changing the provider, `EMBED_MODEL` or `EMBED_DIM`
disables semantic search until the index is rebuilt.

---

## Editorial rules

Drawn from the fields of your data and enforced in code, not only in the
prompt:

- **A verification field is a grade of evidence, not a safety verdict**: the
  bot passes on the grade's wording and is forbidden from saying "verified",
  "safe", "approved" or "trusted" in either language.
- **Sensitive entries, or entries with a caution**: the warning must be passed
  on and the direct link is forbidden; the asker is referred to your catalogue
  page so the warning is seen in context.
- **Removed entries**: the bot says that they were removed, when and why, with
  no link and no domain that can be opened, and names the replacement only if
  the entry's own replacement field has one.
- **Published articles**: no attribution of responsibility or intent except in
  the article's own wording, no estimating of numbers, no generalising from
  one case to a pattern.
- **External sources**: the source is named once in the answer with the page's
  review date; the licence is added after the link in the source line.
- **Sources**: every source the model receives is numbered and the model ends
  its answer with a hidden line naming the numbers it relied on, so the asker
  sees only those links.
- **Team rules**: an admin can append rules of their own from the dashboard;
  they apply alongside the fixed ones and cannot override them.

---

## Languages and the answer model

- **Eleven languages from translation files**: Arabic and English (the
  originals), Brazilian Portuguese, Spanish, French, Swahili, Hindi, Urdu,
  Persian, Turkish and Indonesian. Each language is one JSON file in
  `app/locales/` (`ar.json`, `en.json`, `pt-BR.json`, ...) holding every text
  the public gets (greeting, welcome, refusal, daily limit, pause, error,
  subscription, privacy gist) and a `dashboard` section with the dashboard's
  strings. Whatever a file lacks falls back to English.
- **Adding a language**: copy `en.json` to `<code>.json` and translate its
  values, the `dashboard` section included, keeping the placeholders such as
  `{limit}` and `{bot_name}` and the command names such as `/subscribe`; add
  the code to `SUPPORTED_LANGUAGES` in `app/i18n.py`, and, for a Latin-script
  language, a set of its common words to `_MARKERS` there so it can be
  detected. Nothing else changes: the model answers in whatever language the
  prompt names.
- **Language detection** (`app/i18n.py`, no libraries): the script first
  (Arabic script is Arabic unless it carries Urdu-only or Persian letters;
  Devanagari is Hindi), then, for the Latin script, a small list of common
  words and distinctive characters per language; anything unknown is English.
  Names in Latin letters inside an Arabic sentence keep it Arabic, and a bare
  name on its own is English. Telegram's interface language sets the language
  of `/start` and of messages without text.
- **The sources stay in Arabic and English**: for a question in another
  language the sources are retrieved in English (Arabic for Urdu and Persian),
  and the system instructions tell the model to translate faithfully into the
  language named in the prompt, keeping names and links as they are and
  applying every rule in that language.
- **Fixed messages** come from the asker's language file. The refusal, welcome
  and paused texts edited on the dashboard's role page override the Arabic
  and English files only; the other languages keep their file's text.
- **The answer model**: `ANSWER_MODEL` (a Claude model by default, with a
  Gemini fallback if a key is set) and `ANSWER_EFFORT`. An optional local
  OpenAI-compatible model (`ANSWER_MODEL=local`, for example llama.cpp) can
  answer some channels, such as Facebook comments, at zero cost. A
  safety-classifier decline is treated as a model refusal, and
  `ANSWER_FALLBACK` reruns such declines on a fallback model so a legitimate
  question about a security topic is not refused by mistake.

---

## Running

```bash
cp .env.example .env     # set ANTHROPIC_API_KEY and the dashboard and channel keys
docker compose up -d --build   # the first build downloads the local model (0.7 GB)
docker compose exec bayan python -m app.ingest
```

`python -m app.ingest` pulls your content repository, runs the extractor and
indexes. Add `--no-pull` to index from existing files. After the first
indexing, and after any change of embedding model, calibrate the threshold:
`docker compose exec bayan python scripts/calibrate.py`.

Try it before connecting a channel: the "Try Bayan" page in the dashboard, or
from inside the server `curl -s localhost:8000/debug/ask -H 'content-type:
application/json' -d '{"question":"…"}'` (the route only answers from inside
the server). Tests: `tests/test_bayan.py` on the real index,
`tests/test_offline.py` with no keys and no network.

---

## Dashboard

At `PUBLIC_URL/admin`, without JavaScript, in English by default and in any
of the supported languages from the language list in the sidebar, each named
in its own language; the choice is kept in a cookie, and Arabic, Persian and
Urdu render right-to-left. The strings come from the `dashboard` section of
`app/locales/<code>.json`, with English for anything a language lacks; the
role page's editable texts stay Arabic and English. Enabled when `.env` sets `ADMIN_PASSWORD` and
`SESSION_SECRET`; the team signs in with Google accounts of your domain
(`GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`, `ALLOWED_EMAIL_DOMAIN`,
`ADMIN_EMAILS`) with roles admin, editor and viewer, and every action is in
an audit log.

- **Overview**: the state of the index and the vectors, the outcomes and
  topics of the last 7 days, unanswered questions, and the last indexing run.
- **Questions**: every question with the reply and its confidence score,
  filterable by outcome, channel and rating; a 👍/👎 rating with a reason, and
  a "Write a correction" link.
- **Corrections**: approved answers in the team's own words, matched to new
  questions by similarity and sent to the model ahead of the other sources.
  `scripts/check_corrections.py` re-asks them after any change.
- **Try Bayan**: each member's own multi-turn conversation with the bot, with
  the retrieved passages under each answer; outside the public counts.
- **Weekly lists** and **subscribers**: paste the week's list, see who
  subscribed, broadcast on the enabled channels.
- **Data sources**: notes, page links and files (see above).
- **Bayan's role**: the bot's name, scope, extra team rules, the refusal,
  welcome and paused texts, the response tone and length, and a scenario
  preview that shows how the bot replies with the current settings.
- **Settings**: the threshold, the daily limit, the pause switch, the channel
  status, and **API keys** saved from the dashboard (taking precedence over
  `.env`, applied at once, only the last four characters shown).
- **Team** and **Blocked**.

**Privacy**: the dashboard shows no audience identifiers; each user appears as
a keyed eight-character fingerprint. Sessions are signed `HttpOnly`,
`SameSite=Strict` cookies, and login attempts are rate-limited.

---

## Automatic updates

1. On Bayan's server: `bash scripts/setup_deploy_key.sh`, then add the public
   key to your content repository as a **read-only deploy key**.
2. Copy `site-workflow/bayan-reindex.yml` into that repository under
   `.github/workflows/` and adapt its paths to your content.
3. Add the repository secrets `BAYAN_REINDEX_URL` and `BAYAN_REINDEX_SECRET`.

On every merge that touches the content, the workflow runs the extractor as a
check first, then sends one signal to the server, which replies with 202 and
indexes in the background. **None of Bayan's keys pass through your CI.**

---

## Connecting the channels

**Telegram**: `@BotFather` → `/newbot` → put the token and
`TELEGRAM_WEBHOOK_SECRET` in `.env` → `python scripts/set_telegram_webhook.py`.

**WhatsApp**: a Business app on developers.facebook.com → the WhatsApp product
→ a webhook at `…/webhooks/meta` with `META_VERIFY_TOKEN` → subscribe to
`messages`. Use a System User token in production.

**Messenger and Page comments**: the same app → the Messenger product → the
same webhook → subscribe to `messages`; with a Page token the bot also polls
the Page's latest posts and sends a private reply to comments that match an
approved answer or mention the bot by name.

**Website**: add one line to your site's pages,
`<script src="https://<PUBLIC_URL>/widget.js" defer></script>`. It puts a chat
bubble in the corner of every page, in the page's language and direction, and
sends questions to `POST /chat`, which only accepts requests from the sites in
`WEB_CHAT_ORIGINS` (default: `SITE_URL` and its `www.` variant; `none`
disables it). No cookie and no sign-in: the browser keeps a random
conversation ID in its local storage, and the IP address is used in memory
only for the per-address limits (`WEB_IP_BURST`, `WEB_IP_DAILY`) on top of the
daily limit. The channel is switched off from Settings, and the bubble then
disappears from the site.

The chat window opens in the language of the visitor's country when Bayan has
one (Brazil in Portuguese, Kenya in Swahili, Syria in Arabic, and so on), and
in the page's language otherwise or when the visitor switches the page's
language. The country is looked up on the server in DB-IP's free "IP to
Country Lite" database ([IP Geolocation by DB-IP](https://db-ip.com), CC BY
4.0), which Bayan downloads and refreshes monthly into `data/geo/`; the
address is sent nowhere and neither it nor the country is stored. `GEO_LANG=0`
turns this off.

---

## Structure

```
app/
  config.py     settings from .env
  arabic.py     Arabic normalisation + overlap weighted by rarity
  store.py      SQLite: chunks, entries, messages, settings, team, audit
  ingest.py     pull the repository, run the extractor, index
  safety.py     openly licensed external sources
  sources.py    team sources from the dashboard
  opportunities.py  weekly lists;  broadcast.py  their broadcast
  embed.py      vectors: the local model or the Voyage service
  nano/         voyage-4-nano: the copied code, its licence and the pinned revision
  retrieve.py   the two paths: structured + semantic
  brain.py      ★ the four layers and the editorial rules
  role.py       the bot's role, texts and style, set from the dashboard
  keys.py       API keys set from the dashboard
  dashboard.py  the dashboard
  i18n.py       languages and fixed messages;  privacy.py  the privacy page
  main.py       webhooks, /admin/reindex, /debug/ask, background loops
  channels/     Telegram, WhatsApp, Messenger
scripts/        webhook setup, deploy key, model download, calibration, correction checks
site-workflow/  the workflow to copy into your content repository
tests/          test_bayan on the real index, test_offline with no keys
```

## Privacy and data deletion

- The privacy policy is served at `PUBLIC_URL/privacy` in both languages, and
  its figures (retention, daily limit, memory) are read from the settings.
- Questions and answers are deleted after `MESSAGE_RETENTION_DAYS` (30), with
  `secure_delete` so deleted text does not linger in the file; `/reset`
  deletes a conversation at once.
- The bot writes no question text to the server log; the OAuth code and
  webhook tokens are kept out of the access log.

## Security notes

- Meta's `X-Hub-Signature-256` is verified on every request; Telegram's
  `secret_token` is required.
- `/debug/ask` works only from inside the server.
- The extractor runs with no environment variables and under Node's permission
  model (reads only the content repository, writes only the export folder, no
  child processes), so a malicious change in the content repository cannot
  reach the bot's keys or its database.
- Links added as team sources are checked before fetching (http/https only, no
  local or private addresses, every redirect checked, size caps).
- CSP blocks all scripts in the dashboard; all public text is escaped;
  cross-origin requests are rejected.
- Per-user rate limit, a daily limit (`DAILY_LIMIT`, adjustable from the
  dashboard), a block table, and duplicate-event protection on webhooks.
- `.env` and `data/` are never committed; CI runs Bandit, pip-audit and
  gitleaks over the whole history.

---

## License

The code is under the [Apache License 2.0](LICENSE) (see `NOTICE`). The
names "Pax Memoria" and "Bayan / بيان" as the organisation uses them, and the
avatar in `assets/`, are not covered by the licence. Content fetched at run
time is not part of the repository and keeps its own licences. The current
version is in `app/__init__.py` and its history in `CHANGELOG.md`.
