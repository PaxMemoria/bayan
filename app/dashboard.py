"""لوحة تحكم بيان — بالعربية والإنجليزية، بلا JavaScript، خلف كلمة مرور.

تعرض حالة الفهرس والمتجهات، وأسئلة الجمهور ونتيجة كل منها مع تقييم
إجابتها، والتصحيحات المعتمدة التي يكتبها الفريق، وتجربة بيان دون قناة،
والعتبة والحدّ اليومي وزر الإيقاف، والمحظورين. اللغة تُختار برابط في
الشريط (?lang=en أو ?lang=ar) وتُحفظ في كوكي.

الخصوصية: معرّف واتساب هو رقم الهاتف، فلا تعرض اللوحة أي معرّف. كل
مستخدم يظهر ببصمة مشتقّة بـ SESSION_SECRET لا تُعكس إلى رقمه، والحظر
يُنفَّذ برقم الرسالة لا بالمعرّف.

Bayan's dashboard, in Arabic and English, with no JavaScript, behind a
password.

It shows the state of the index and the vectors, the public's questions
with the outcome of each and the rating of its answer, the approved
corrections the team writes, a way to try Bayan without a channel, the
threshold, the daily limit and the pause button, and the blocked users.
The language is chosen with a link in the bar (?lang=en or ?lang=ar) and
kept in a cookie.

Privacy: a WhatsApp ID is the phone number, so the dashboard shows no
IDs. Each user appears as a fingerprint derived with SESSION_SECRET that
cannot be reversed to their number, and blocking is done by message
number, not by ID.
"""
import asyncio
import datetime
import hashlib
import hmac
import html
import time
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from . import brain, config, embed, ingest, opportunities, retrieve, store

router = APIRouter()

COOKIE = "bayan_admin"
LANG_COOKIE = "bayan_lang"
SESSION_HOURS = 12
MAX_FORM_BYTES = 16_384

e = html.escape

# الإعداد الذي عويِرت عليه MIN_RELEVANCE الافتراضية (scripts/calibrate.py)
# The setting the default MIN_RELEVANCE was calibrated for (scripts/calibrate.py)
CALIBRATED_FOR = "voyage-4-nano@1024"
# سبب الحظر يُخزَّن رمزاً ويُعرض بلغة اللوحة. القيمة العربية القديمة مقبولة.
# The block reason is stored as a code and shown in the dashboard's
# language. The old Arabic value is still accepted.
BLOCK_REASON = "dashboard"

OUTCOMES = {
    "answered": "ok", "tool_list": "ok", "refused_gate": "warn",
    "refused_model": "muted", "error": "bad",
}
CHANNELS = ("telegram", "whatsapp", "messenger")

# ───────────────────────────────────────────────────── النصوص / Strings
# كل نص في اللوحة: (العربية، الإنجليزية). المفاتيح ثابتة، فلا يُعرض في
# الصفحة نص يأتي من الرابط.
# Every dashboard string: (Arabic, English). The keys are fixed, so no text
# that comes from the URL is shown on the page.
TEXT: dict[str, tuple[str, str]] = {
    "dashboard": ("لوحة التحكم", "Dashboard"),
    "other_lang": ("English", "العربية"),
    "nav_home": ("نظرة عامة", "Overview"),
    "nav_messages": ("الأسئلة", "Questions"),
    "nav_try": ("جرّب بيان", "Try Bayan"),
    "nav_settings": ("الإعدادات", "Settings"),
    "nav_blocked": ("المحظورون", "Blocked"),
    "logout": ("خروج", "Log out"),
    "out_answered": ("أُجيب", "Answered"),
    "out_tool_list": ("قائمة أدوات", "Tool list"),
    "out_refused_gate": ("رفضته البوابة", "Refused by the gate"),
    "out_refused_model": ("رفضه النموذج", "Refused by the model"),
    "out_error": ("خطأ", "Error"),
    "ch_telegram": ("تيليغرام", "Telegram"),
    "ch_whatsapp": ("واتساب", "WhatsApp"),
    "ch_messenger": ("ماسنجر", "Messenger"),
    "type_tool": ("أداة", "Tool"),
    "type_tool_removed": ("أداة مُزالة", "Removed tool"),
    "type_investigation": ("تحقيق", "Investigation"),
    "type_about": ("من نحن", "About"),
    "flash_reindex": ("بدأت الفهرسة، وتستغرق دقائق. حدّث الصفحة بعدها لترى النتيجة.",
                      "Indexing has started and takes a few minutes. Refresh the page "
                      "afterwards to see the result."),
    "flash_busy": ("فهرسة جارية الآن، وستتبعها دورة أخرى تشمل آخر تعديل.",
                   "Indexing is already running. Another run will follow to include the "
                   "latest change."),
    "flash_saved": ("حُفظت الإعدادات.", "Settings saved."),
    "flash_blocked": ("حُظر المستخدم. لن يتلقى بعد الآن إلا رسالة الرفض.",
                      "User blocked. From now on they only get the refusal message."),
    "flash_unblocked": ("رُفع الحظر.", "Block removed."),
    "off_title": ("اللوحة غير مفعّلة", "Dashboard disabled"),
    "off_body": ("اللوحة معطّلة لأن ADMIN_PASSWORD أو SESSION_SECRET غير مضبوط في ملف "
                 "⁦.env⁩، أو أقصر من الحد الأدنى. كلمة المرور 12 حرفاً على "
                 "الأقل، والسرّ 32 حرفاً على الأقل.",
                 "The dashboard is off because ADMIN_PASSWORD or SESSION_SECRET is not "
                 "set in .env, or is too short. The password needs at least 12 "
                 "characters and the secret at least 32."),
    "off_gen": ("لتوليد سرّ:", "To generate a secret:"),
    "origin_denied": ("مصدر الطلب غير مسموح", "Request origin not allowed"),
    "too_large": ("الطلب أكبر من المسموح", "Request too large"),
    "login_title": ("الدخول إلى اللوحة", "Log in to the dashboard"),
    "login_bad": ("كلمة المرور غير صحيحة.", "Wrong password."),
    "login_slow": ("محاولات كثيرة. انتظر ربع ساعة ثم أعد المحاولة.",
                   "Too many attempts. Wait a quarter of an hour, then try again."),
    "password": ("كلمة المرور", "Password"),
    "login_btn": ("دخول", "Log in"),
    "a_paused": ("بيان متوقف الآن.", "Bayan is paused."),
    "a_paused_d": ("كل سؤال يُجاب برسالة الإيقاف. أعِد تشغيله من الإعدادات.",
                   "Every question gets the pause message. Turn it back on in Settings."),
    "a_empty": ("قاعدة المعرفة فارغة.", "The knowledge base is empty."),
    "a_empty_d": ("بيان يرفض كل سؤال. شغّل الفهرسة من أسفل هذه الصفحة.",
                  "Bayan refuses every question. Run indexing from the bottom of this page."),
    "a_novec": ("البحث الدلالي معطّل.", "Semantic search is off."),
    "a_novec_d": ("{note}. يرفض بيان الآن كل سؤال مصاغ بكلمات غير كلمات الموقع، "
                  "ومنها أسئلة مشروعة كثيرة.",
                  "{note}. Bayan now refuses any question worded differently from the "
                  "site, including many legitimate ones."),
    "a_thr": ("العتبة على قيمتها الابتدائية {v}.", "The threshold is at its initial value, {v}."),
    "a_thr_d": ("هذه القيمة معايَرة لـ {cal} لا لـ {cur}. شغّل scripts/calibrate.py "
                "واضبط العتبة من الإعدادات.",
                "This value was calibrated for {cal}, not {cur}. Run scripts/calibrate.py "
                "and set the threshold in Settings."),
    "a_failed": ("فشلت آخر فهرسة ({when}).", "The last indexing run failed ({when})."),
    "a_failed_d": ("الفهرس السابق ما زال يعمل. التفاصيل في أسفل الصفحة.",
                   "The previous index is still in use. Details at the bottom of the page."),
    "vec_on": ("تعمل", "On"),
    "vec_off": ("معطّلة", "Off"),
    "c_chunks": ("مقاطع قاعدة المعرفة", "Knowledge base passages"),
    "c_chunks_d": ("التحقيقات: {i}، الأدوات: {t}، الأدوات المُزالة: {r}.",
                   "Investigations: {i}, tools: {t}, removed tools: {r}."),
    "c_tools": ("أدوات الدليل", "Guide tools"),
    "c_tools_d": ("الحسّاسة: {s}، المُزالة: {r}.", "Sensitive: {s}, removed: {r}."),
    "c_vec": ("المتجهات ({p})", "Vectors ({p})"),
    "c_vec_d": ("مقاطع لها متجهات: {n} من {t}.", "Passages with vectors: {n} of {t}."),
    "c_thr": ("عتبة البوابة", "Gate threshold"),
    "thr_dash": ("مضبوطة من اللوحة.", "Set from the dashboard."),
    "thr_init": ("قيمة ابتدائية لم تُعدَّل من اللوحة.",
                 "Initial value, not changed from the dashboard."),
    "provider_local": ("على الخادم", "on the server"),
    "provider_voyage": ("عبر Voyage", "via Voyage"),
    "week": ("آخر 7 أيام", "Last 7 days"),
    "total_h": ("منذ البداية (أعداد فقط)", "Since the start (counts only)"),
    "total_help": ("تبقى هذه الأعداد بعد حذف الرسائل، ولا تحمل نصاً ولا معرّفات. المستخدمون هنا مجموع المستخدمين اليوميين، فمن سأل في يومين يُحسب مرتين.",
                   "These counts outlive the deleted messages and hold no text or identifiers. Users is the sum of daily users, so someone seen on two days counts twice."),
    "th_total": ("المجموع", "Total"),
    "th_first": ("أول يوم", "First day"),
    "week_n": ("عدد الأسئلة: {n}.", "Questions: {n}."),
    "th_outcome": ("النتيجة", "Outcome"),
    "th_count": ("العدد", "Count"),
    "th_share": ("النسبة", "Share"),
    "th_channel": ("القناة", "Channel"),
    "th_questions": ("الأسئلة", "Questions"),
    "th_users": ("المستخدمون", "Users"),
    "none_yet": ("لا أسئلة بعد.", "No questions yet."),
    "run_took": ("، والمدة بالثواني: {s}", ", taking {s} seconds"),
    "run_running": ("جارية الآن", "running now"),
    "run_ok": ("نجحت", "succeeded"),
    "run_failed": ("فشلت", "failed"),
    "run_line": ("بدأت {when}{took}. الحالة: {state}.", "Started {when}{took}. Status: {state}."),
    "run_none": ("لم تُشغَّل أي فهرسة بعد.", "No indexing has run yet."),
    "indexing": ("الفهرسة", "Indexing"),
    "reindex_btn": ("أعد الفهرسة الآن", "Reindex now"),
    "reindex_help": ("تسحب آخر نسخة من مستودع الموقع، وتشغّل المُستخرِج، وتولّد المتجهات، "
                     "وتستغرق بضع دقائق. الفهرس الحالي يبقى يعمل حتى تكتمل.",
                     "Pulls the latest site repository, runs the extractor and builds the "
                     "vectors, which takes a few minutes. The current index stays in use "
                     "until it finishes."),
    "help_refused_gate": ("أسئلة رفضتها البوابة قبل استدعاء النموذج. رتّبها حسب الثقة: إن "
                          "وجدت بين الأعلى ثقةً أسئلة مشروعة عن الأدوات أو التحقيقات، "
                          "فالعتبة أعلى مما ينبغي.",
                          "Questions the gate refused before calling the model. Sort them by "
                          "confidence: if the highest-scoring ones include legitimate "
                          "questions about tools or investigations, the threshold is too high."),
    "help_refused_model": ("أسئلة تجاوزت البوابة ثم رفضها النموذج. كثرتها تعني أن العتبة "
                           "أدنى مما ينبغي، وكل واحد منها استدعاء مدفوع للنموذج.",
                           "Questions that passed the gate and were then refused by the "
                           "model. Many of them mean the threshold is too low, and each one "
                           "is a paid model call."),
    "help_error": ("أسئلة فشل فيها استدعاء النموذج. راجع سجلّ الخادم.",
                   "Questions where the model call failed. Check the server log."),
    "q_title": ("أسئلة الجمهور", "Questions from the public"),
    "all": ("الكل", "All"),
    "all_channels": ("كل القنوات", "All channels"),
    "newest": ("الأحدث أولاً", "Newest first"),
    "highest": ("الأعلى ثقةً أولاً", "Highest confidence first"),
    "reply": ("ردّ بيان", "Bayan's reply"),
    "conf": ("الثقة {c}", "Confidence {c}"),
    "fp_title": ("بصمة المستخدم", "User fingerprint"),
    "user": ("المستخدم {fp}", "User {fp}"),
    "block_btn": ("احظر", "Block"),
    "none_here": ("لا أسئلة هنا.", "No questions here."),
    "older": ("أقدم", "Older"),
    "blocked_help": ("المحظور يتلقى رسالة الرفض على كل سؤال، ولا يُستدعى النموذج لأجله.",
                     "A blocked user gets the refusal message for every question, and the "
                     "model is never called for them."),
    "th_user": ("المستخدم", "User"),
    "th_reason": ("السبب", "Reason"),
    "th_since": ("منذ", "Since"),
    "unblock_btn": ("ارفع الحظر", "Unblock"),
    "nobody": ("لا أحد محظور.", "Nobody is blocked."),
    "reason_dashboard": ("حُظر من اللوحة", "Blocked from the dashboard"),
    "question": ("السؤال", "Question"),
    "ask_btn": ("اسأل بيان", "Ask Bayan"),
    "try_note": ("التجربة لا تُسجَّل في سجل الأسئلة. السؤال الذي يتجاوز البوابة يستدعي "
                 "النموذج فعلاً.",
                 "Tries are not saved to the question log. A question that passes the "
                 "gate does call the model."),
    "nothing": ("لا شيء", "None"),
    "cat_shown": ("{c}، والأدوات المعروضة منه: {n}", "{c}, tools shown: {n}"),
    "mode_vec": ("متجهات ونص", "vectors and text"),
    "mode_text": ("نص فقط", "text only"),
    "thr_v": ("العتبة {t}", "Threshold {t}"),
    "search_mode": ("البحث: {m}", "Search: {m}"),
    "answer_lang": ("لغة الإجابة: {l}", "Answer language: {l}"),
    "lang_ar": ("العربية", "Arabic"),
    "lang_en": ("الإنجليزية", "English"),
    "th_name_match": ("أدوات مطابقة بالاسم", "Tools matched by name"),
    "th_cat_match": ("تصنيف مطابق", "Matched category"),
    "passages": ("المقاطع المسترجعة", "Retrieved passages"),
    "th_type": ("النوع", "Type"),
    "th_title": ("العنوان", "Title"),
    "th_link": ("الرابط", "Link"),
    "no_passages": ("لا مقاطع.", "No passages."),
    "st_ok": ("مضبوطة.", "Configured."),
    "st_missing": ("ينقصها {need}.", "Missing {need}."),
    "need_tg": ("TELEGRAM_BOT_TOKEN و TELEGRAM_WEBHOOK_SECRET",
                "TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET"),
    "need_wa": ("مفاتيح Meta وواتساب", "the Meta and WhatsApp keys"),
    "need_ms": ("مفاتيح Meta و MESSENGER_PAGE_TOKEN", "the Meta keys and MESSENGER_PAGE_TOKEN"),
    "err_threshold": ("العتبة رقم بين 0.05 و 0.90.",
                      "The threshold is a number between 0.05 and 0.90."),
    "err_limit": ("الحدّ اليومي عدد صحيح بين 0 و 1000.",
                  "The daily limit is a whole number between 0 and 1000."),
    "f_answer_model": ("نموذج الإجابة", "Answer model"),
    "f_embed_model": ("نموذج المتجهات", "Embedding model"),
    "f_dim": ("أبعاد المتجه", "Vector dimensions"),
    "f_top_k": ("المقاطع لكل سؤال", "Passages per question"),
    "f_max_tools": ("أقصى عدد أدوات في القائمة", "Most tools in one list"),
    "f_rate": ("أقصى رسائل المستخدم الواحد", "Most messages per user"),
    "f_window": ("خلال (ثانية)", "Within (seconds)"),
    "f_history": ("الأسئلة السابقة التي يتذكرها", "Previous questions remembered"),
    "f_sources": ("عرض المصادر", "Show sources"),
    "yes": ("نعم", "Yes"),
    "no": ("لا", "No"),
    "s_thr": ("عتبة البوابة", "Gate threshold"),
    "s_thr_help": ("السؤال الذي تقلّ ثقته عن العتبة يُرفض قبل استدعاء النموذج. رفعها يقلّل "
                   "الإجابات الخاطئة ويزيد رفض الأسئلة المشروعة، وخفضها يفعل العكس. القيمة "
                   "الابتدائية في ⁦.env⁩ هي {v}.",
                   "A question whose confidence is below the threshold is refused before the "
                   "model is called. Raising it means fewer wrong answers and more "
                   "legitimate questions refused; lowering it does the opposite. The "
                   "initial value in .env is {v}."),
    "s_limit": ("حدّ الأسئلة لكل مستخدم في 24 ساعة", "Questions per user in 24 hours"),
    "s_limit_help": ("يُحسب لكل مستخدم في كل قناة على آخر 24 ساعة. من يبلغه يتلقى رسالة "
                     "تخبره متى يسأل مجدداً، ولا يُستدعى النموذج. 0 يعني بلا حدّ. القيمة "
                     "الابتدائية في ⁦.env⁩ هي {v}.",
                     "Counted per user in each channel over the last 24 hours. Anyone who "
                     "reaches it gets a message saying when they can ask again, and the "
                     "model is not called. 0 means no limit. The initial value in .env "
                     "is {v}."),
    "s_pause": ("أوقف بيان مؤقتاً", "Pause Bayan"),
    "s_pause_help": ("حين يتوقف بيان يُجاب كل سؤال بهذه الرسالة: «{m}»",
                     "While Bayan is paused, every question gets this message: “{m}”"),
    "save": ("احفظ", "Save"),
    "reset_thr": ("أعِد العتبة إلى قيمة ⁦.env⁩", "Reset the threshold to the .env value"),
    "channels": ("القنوات", "Channels"),
    "env_settings": ("إعدادات من ⁦.env⁩", "Settings from .env"),
    "env_help": ("تتغيّر بتعديل ملف ⁦.env⁩ على الخادم ثم إعادة تشغيله.",
                 "Changed by editing .env on the server and restarting."),
    # التقييم / Ratings
    "rate_summary": ("قيّم الإجابة", "Rate the answer"),
    "rate_up": ("👍 جيدة", "👍 Good"),
    "rate_down": ("👎 تحتاج تصحيحاً", "👎 Needs fixing"),
    "rate_clear": ("امسح التقييم", "Clear rating"),
    "rate_reason": ("السبب", "Reason"),
    "rate_note": ("ملاحظة (اختيارية)", "Note (optional)"),
    "rated_up": ("التقييم: جيدة", "Rating: good"),
    "rated_down": ("التقييم: تحتاج تصحيحاً", "Rating: needs fixing"),
    "rr_none": ("بلا سبب", "No reason"),
    "rr_wrong": ("معلومة خاطئة", "Wrong information"),
    "rr_missing": ("معلومة ناقصة", "Missing information"),
    "rr_refused_wrongly": ("رفض سؤالاً مشروعاً", "Refused a legitimate question"),
    "rr_should_refuse": ("كان يجب أن يرفض", "Should have refused"),
    "rr_format": ("التنسيق أو اللغة", "Formatting or language"),
    "rr_other": ("سبب آخر", "Other"),
    "r_all": ("كل التقييمات", "All ratings"),
    "r_none": ("بلا تقييم", "Unrated"),
    "write_fix": ("اكتب تصحيحاً", "Write a correction"),
    "flash_rated": ("حُفظ التقييم.", "Rating saved."),
    "c_ratings": ("التقييمات، آخر 7 أيام", "Ratings, last 7 days"),
    "c_ratings_d": ("👍 {up}، 👎 {down}. التصحيحات المفعّلة: {fixes}.",
                    "👍 {up}, 👎 {down}. Active corrections: {fixes}."),
    # التصحيحات / Corrections
    "nav_corrections": ("التصحيحات", "Corrections"),
    "fix_title": ("التصحيحات المعتمدة", "Approved corrections"),
    "fix_help": ("إجابات يكتبها الفريق لأسئلة أخطأ فيها بيان أو قصّر. حين يشبه سؤالٌ جديد "
                 "سؤالَ تصحيحٍ بما يكفي، يُرسل التصحيح إلى النموذج قبل غيره من المصادر "
                 "ويُقدَّم عليها، من لحظة حفظه ودون إعادة فهرسة.",
                 "Answers the team writes for questions Bayan got wrong or answered "
                 "poorly. When a new question is close enough to a correction's question, "
                 "the correction is sent to the model ahead of the other sources and takes "
                 "precedence over them, from the moment it is saved and without reindexing."),
    "fix_new": ("تصحيح جديد", "New correction"),
    "fix_edit": ("عدّل التصحيح", "Edit the correction"),
    "fix_q": ("السؤال", "Question"),
    "fix_q_help": ("اكتبه بكلماتك كما قد يسأله الناس، دون أي اسم أو رقم أو تفصيل شخصي من "
                   "الرسالة الأصلية، فالتصحيح يبقى بعد حذف الرسائل.",
                   "Write it in your own words, as people might ask it, without any name, "
                   "number or personal detail from the original message: the correction "
                   "stays after the messages are deleted."),
    "fix_a": ("الإجابة المعتمدة", "Approved answer"),
    "fix_a_help": ("ما يجب أن يقوله بيان. يعيد صياغتها بلغة السائل، وتبقى قواعد الروابط "
                   "سارية عليها.",
                   "What Bayan should say. It rewords it in the asker's language, and the "
                   "link rules still apply to it."),
    "fix_url": ("رابط المصدر (اختياري)", "Source link (optional)"),
    "fix_url_help": ("صفحة من {site} تُعرض مصدراً حين يستعمل بيان هذا التصحيح. إن تُرك "
                     "فارغاً تُعرض صفحة الدليل.",
                     "A page on {site}, shown as the source when Bayan uses this "
                     "correction. Left empty, the guide page is shown."),
    "fix_active": ("مفعّل: يستعمله بيان", "Active: Bayan uses it"),
    "fix_orig": ("السؤال الأصلي وردّ بيان عليه، للرجوع إليهما فقط",
                 "The original question and Bayan's reply, for reference only"),
    "fix_none": ("لا تصحيحات بعد. ابدأ من صفحة الأسئلة: «اكتب تصحيحاً» تحت أي إجابة.",
                 "No corrections yet. Start from the Questions page: “Write a correction” "
                 "under any answer."),
    "fix_try": ("جرّبه", "Try it"),
    "fix_delete": ("احذف", "Delete"),
    "fix_on": ("مفعّل", "Active"),
    "fix_off": ("معطّل", "Inactive"),
    "fix_novec": ("بلا متجه: يطابق السؤال نفسه وحده", "No vector: matches the same question only"),
    "fix_updated": ("آخر تعديل {when}", "Last edited {when}"),
    "fix_matched": ("تصحيحات مطابقة", "Matching corrections"),
    "fix_sim": ("الشبه {s}", "Similarity {s}"),
    "err_fix": ("السؤال والإجابة مطلوبان: السؤال حتى {q} حرف، والإجابة حتى {a} حرف.",
                "The question and the answer are required: up to {q} characters for the "
                "question and {a} for the answer."),
    "err_fix_url": ("رابط المصدر يجب أن يكون صفحة من {site}.",
                    "The source link must be a page on {site}."),
    "flash_fix_saved": ("حُفظ التصحيح، ويستعمله بيان من الآن.",
                        "Correction saved. Bayan uses it from now on."),
    "flash_fix_novec": ("حُفظ التصحيح، لكن تعذّر توليد متجه سؤاله، فلن يطابق الآن إلا السؤال "
                        "نفسه. يُعاد توليده عند إعادة تشغيل الخادم.",
                        "Correction saved, but its question's vector could not be produced, "
                        "so for now it only matches the same question. It is produced again "
                        "when the server restarts."),
    "flash_fix_deleted": ("حُذف التصحيح.", "Correction deleted."),
    "nav_opps": ("الفرص", "Opportunities"),
    "opp_title": ("الفرص الأسبوعية", "Weekly opportunities"),
    "opp_help": ("الصق قائمة الأسبوع (بنود مرقّمة، وتحت كل بند رابطه). تُقسَّم إلى فرصة لكل بند وتُحفظ برقم أسبوعها، ويبحث بيان فيها حين يُسأل عن زمالة أو منحة أو جائزة أو تدريب، في آخر {n} أسابيع فقط. ويُحفظ معها تصحيح «فرص الأسبوع N» ليبقى الجواب على «فرص» قائمة الأسبوع الأحدث. إعادة لصق أسبوع تستبدل قائمته.",
                 "Paste the week's list (numbered items, each with its link below). It is split into one opportunity per item and saved with its week number. Bayan searches them when asked for a fellowship, grant, award or training, in the last {n} weeks only. A «فرص الأسبوع N» correction is saved too, so «فرص» answers with the newest week's list. Pasting a week again replaces its list."),
    "opp_new": ("إضافة قائمة أسبوع", "Add a week's list"),
    "opp_week": ("رقم الأسبوع (ISO)", "Week number (ISO)"),
    "opp_year": ("السنة", "Year"),
    "opp_paste": ("القائمة", "The list"),
    "opp_save": ("احفظ القائمة", "Save the list"),
    "opp_none": ("لا قوائم بعد.", "No lists yet."),
    "opp_count": ("{n} فرص", "{n} opportunities"),
    "opp_delete": ("احذف الأسبوع", "Delete the week"),
    "err_opp": ("تأكد من رقم الأسبوع (1–53) والسنة، ومن أن القائمة فيها بند واحد على الأقل: سطر «1. العنوان» ورابطه.",
                "Check the week number (1–53) and the year, and that the list has at least one item: a «1. Title» line and its link."),
    "flash_opp_saved": ("حُفظت قائمة الأسبوع، ويبحث فيها بيان من الآن.",
                        "The week's list is saved. Bayan searches it from now on."),
    "flash_opp_deleted": ("حُذفت قائمة الأسبوع.", "The week's list was deleted."),
}
FLASH_KIND = {"reindex": "ok", "busy": "warn", "saved": "ok", "blocked": "ok",
              "unblocked": "ok", "rated": "ok", "fix_saved": "ok", "fix_novec": "warn",
              "fix_deleted": "ok", "opp_saved": "ok", "opp_deleted": "ok"}
RATINGS = ("up", "down", "none")
# نموذج التصحيح أكبر من غيره: الحرف العربي 6 بايتات بعد ترميز الرابط
# The correction form is larger than the others: an Arabic character takes
# 6 bytes once URL-encoded
FIX_FORM_BYTES = 65_536
FIX_ANSWER_CHARS = 3000


def tr(lang: str):
    """دالة ترجمة للغة الطلب: T("key", v=...).
    A translation function for the request's language: T("key", v=...)."""
    i = 1 if lang == "en" else 0

    def T(key: str, **kw) -> str:
        text = TEXT[key][i]
        return text.format(**kw) if kw else text

    return T


def req_lang(request: Request) -> str:
    """?lang= يتقدّم على الكوكي، والافتراضي العربية.
    ?lang= takes precedence over the cookie, and the default is Arabic."""
    q = request.query_params.get("lang")
    if q in ("ar", "en"):
        return q
    return "en" if request.cookies.get(LANG_COOKIE) == "en" else "ar"


# ─────────────────────────────────────────────────────── الدخول / Login
def configured() -> bool:
    return len(config.ADMIN_PASSWORD) >= 12 and len(config.SESSION_SECRET) >= 32


def _sign(value: str) -> str:
    # بصمة كلمة المرور داخل التوقيع: تغييرها يُخرج كل الجلسات القائمة.
    # The password's hash is part of the signature: changing the password logs
    # out every existing session.
    pw = hashlib.sha256(config.ADMIN_PASSWORD.encode()).hexdigest()
    return hmac.new(
        config.SESSION_SECRET.encode(), f"{value}:{pw}".encode(), hashlib.sha256
    ).hexdigest()


def _new_session() -> str:
    exp = str(int(time.time()) + SESSION_HOURS * 3600)
    return f"{exp}.{_sign('session:' + exp)}"


def is_admin(request: Request) -> bool:
    if not configured():
        return False
    exp, _, sig = (request.cookies.get(COOKIE) or "").partition(".")
    if not exp.isdigit() or int(exp) < time.time():
        return False
    return hmac.compare_digest(sig, _sign("session:" + exp))


def _gate(request: Request) -> Response | None:
    """None إن كان الطلب من مسؤول، وإلا الرد المناسب.
    None if the request comes from an admin, otherwise the appropriate response."""
    if not configured():
        T = tr(req_lang(request))
        return page(
            request, T("off_title"),
            f'<div class="card"><p>{T("off_body")}</p><p>{T("off_gen")} '
            "<code>python -c \"import secrets;print(secrets.token_urlsafe(48))\"</code>"
            "</p></div>",
            nav=False, status=503,
        )
    if not is_admin(request):
        return RedirectResponse("/admin/login", status_code=303)
    return None


def _same_origin(request: Request) -> bool:
    origin = request.headers.get("origin") or request.headers.get("referer")
    if not origin or origin == "null":
        # The SameSite=Strict cookie is enough here
        return True  # الكوكي SameSite=Strict يكفي هنا
    return urlsplit(origin).netloc == request.headers.get("host", "")


def _plain(key: str, status: int) -> Response:
    """رد نصي قصير باللغتين، لطلبات لا صفحة لها.
    A short plain-text response in both languages, for requests with no page."""
    ar, en = TEXT[key]
    return Response(f"{ar} / {en}", status_code=status)


async def _form(request: Request, limit: int = MAX_FORM_BYTES) -> dict[str, str] | None:
    if int(request.headers.get("content-length") or 0) > limit:
        return None
    body = (await request.body())[:limit].decode("utf-8", "replace")
    return {k: v[0] for k, v in parse_qs(body, keep_blank_values=True).items()}


async def _post_gate(request: Request,
                     limit: int = MAX_FORM_BYTES) -> tuple[Response | None, dict]:
    denied = _gate(request)
    if denied:
        return denied, {}
    if not _same_origin(request):
        return _plain("origin_denied", 403), {}
    form = await _form(request, limit)
    if form is None:
        return _plain("too_large", 413), {}
    return None, form


def _back(path: str, **params) -> RedirectResponse:
    query = urlencode({k: v for k, v in params.items() if v})
    return RedirectResponse(path + (f"?{query}" if query else ""), status_code=303)


def _safe_next(value: str) -> str:
    if value.startswith("/admin") and "//" not in value and "\n" not in value:
        return value
    return "/admin"


def fingerprint(channel: str, user_id: str) -> str:
    """بصمة ثابتة للمستخدم لا تكشف رقمه. مفتاحها سرّ الخادم، فلا تُعكس
    بتجربة كل أرقام الهواتف كما يُعكس تجزيء غير مفتاحي.

    A stable fingerprint for the user that does not reveal their number. It
    is keyed with the server secret, so it cannot be reversed by trying
    every phone number, as an unkeyed hash can.
    """
    digest = hmac.new(
        config.SESSION_SECRET.encode(), f"uid:{channel}:{user_id}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return digest[:8]


# ─────────────────────────────────────────────────────── القالب / Template
CSS = """
:root{--bg:#f5f4f0;--panel:#fff;--ink:#1c1c1a;--muted:#696962;--line:#e2e0d9;
--accent:#1d5c57;--accent-ink:#fff;--ok:#2b7149;--ok-bg:#e6f2ea;--warn:#8f5200;
--warn-bg:#fdf1dc;--bad:#a8241c;--bad-bg:#fbe7e5;--code:#efede7}
@media (prefers-color-scheme:dark){:root{--bg:#151614;--panel:#1e201d;--ink:#ecebe6;
--muted:#a3a29b;--line:#34362f;--accent:#7cc4bc;--accent-ink:#0f1a19;--ok:#8fd1a6;
--ok-bg:#1d3226;--warn:#f1bf72;--warn-bg:#3a2d16;--bad:#f39c94;--bad-bg:#3d1f1c;
--code:#2a2c27}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);line-height:1.7;
font-family:"SF Arabic","Noto Sans Arabic","Segoe UI","Geeza Pro",Tahoma,sans-serif;
font-size:15px}
html[lang=en] body{font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--accent)}
header{background:var(--panel);border-bottom:1px solid var(--line)}
.bar{max-width:1100px;margin:auto;padding:10px 16px;display:flex;flex-wrap:wrap;
align-items:center;gap:6px 18px}
.brand{font-weight:700;font-size:17px;margin-inline-end:auto}
.brand small{color:var(--muted);font-weight:400}
nav{display:flex;flex-wrap:wrap;gap:4px;align-items:center}
nav a{padding:4px 10px;border-radius:6px;text-decoration:none;color:var(--ink)}
nav a.on{background:var(--accent);color:var(--accent-ink)}
nav a.lang{border:1px solid var(--line)}
nav form{display:inline}
main{max-width:1100px;margin:auto;padding:20px 16px 60px}
h1{font-size:22px;margin:0 0 14px}
h2{font-size:17px;margin:26px 0 10px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;
padding:14px 16px;margin-bottom:12px}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
.stat b{display:block;font-size:26px;line-height:1.3}
.stat span{color:var(--muted);font-size:13px}
.alert{border-radius:10px;padding:12px 16px;margin-bottom:12px;border:1px solid}
.alert.bad{background:var(--bad-bg);border-color:var(--bad);color:var(--ink)}
.alert.warn{background:var(--warn-bg);border-color:var(--warn)}
.alert.ok{background:var(--ok-bg);border-color:var(--ok)}
.alert strong{display:block}
.badge{display:inline-block;font-size:12px;padding:1px 8px;border-radius:99px;
border:1px solid currentColor;white-space:nowrap}
.badge.ok{color:var(--ok)}.badge.warn{color:var(--warn)}.badge.bad{color:var(--bad)}
.badge.muted{color:var(--muted)}
.muted{color:var(--muted)}
.meta{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:13px;color:var(--muted);
align-items:center}
.q{font-size:16px;margin:6px 0;white-space:pre-wrap;overflow-wrap:anywhere}
pre,.reply{white-space:pre-wrap;overflow-wrap:anywhere;background:var(--code);
border-radius:8px;padding:10px 12px;margin:8px 0;font-family:inherit;font-size:14px}
pre.log{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;direction:ltr;
text-align:left}
code{background:var(--code);padding:1px 5px;border-radius:4px;direction:ltr;
unicode-bidi:embed;font-size:13px}
details summary{cursor:pointer;color:var(--accent);font-size:14px}
.tabs{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px}
.tabs a{padding:3px 12px;border:1px solid var(--line);border-radius:99px;
text-decoration:none;color:var(--ink);background:var(--panel);font-size:14px}
.tabs a.on{border-color:var(--accent);color:var(--accent);font-weight:700}
button,.btn{font:inherit;background:var(--accent);color:var(--accent-ink);border:0;
border-radius:7px;padding:6px 14px;cursor:pointer;text-decoration:none}
button.ghost{background:transparent;color:var(--ink);border:1px solid var(--line)}
button.danger{background:transparent;color:var(--bad);border:1px solid var(--bad)}
button.small{font-size:13px;padding:1px 10px}
.meta form{margin-inline-start:auto}
button:disabled{opacity:.5;cursor:default}
input,textarea,select{font:inherit;color:var(--ink);background:var(--bg);
border:1px solid var(--line);border-radius:7px;padding:7px 10px;width:100%}
.rate{margin-top:8px}.rate form{max-width:560px}
.rated{margin-top:6px}
input[type=checkbox]{width:auto}
label{display:block;margin:10px 0 4px;font-weight:600}
.row{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.row form{margin:0}
table{width:100%;border-collapse:collapse;font-size:14px}
td,th{padding:6px 8px;border-bottom:1px solid var(--line);text-align:start;
vertical-align:top}
td.wrap{overflow-wrap:anywhere}
.state.ok{color:var(--ok);font-weight:600}.state.muted{color:var(--muted)}
th{color:var(--muted);font-weight:600}
.bar-chart{height:8px;border-radius:4px;background:var(--line);overflow:hidden}
.bar-chart i{display:block;height:100%;background:var(--accent)}
.help{color:var(--muted);font-size:14px;margin:-6px 0 14px}
"""

NAV = [
    ("/admin", "nav_home", "home"),
    ("/admin/messages", "nav_messages", "messages"),
    ("/admin/try", "nav_try", "try"),
    ("/admin/corrections", "nav_corrections", "corrections"),
    ("/admin/opportunities", "nav_opps", "opportunities"),
    ("/admin/settings", "nav_settings", "settings"),
    ("/admin/blocked", "nav_blocked", "blocked"),
]

HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; img-src data:; "
        "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    ),
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


def _lang_link(request: Request, other: str) -> str:
    """رابط الصفحة نفسها باللغة الأخرى، مع بقية معاملاتها.
    A link to the same page in the other language, keeping its other parameters."""
    params = {k: v for k, v in request.query_params.items() if k not in ("lang", "msg")}
    params["lang"] = other
    return f"{request.url.path}?{urlencode(params)}"


def page(request: Request, title: str, body: str, active: str = "", nav: bool = True,
         status: int = 200, flash: str = "") -> HTMLResponse:
    lang = req_lang(request)
    T = tr(lang)
    other = "ar" if lang == "en" else "en"
    links = ""
    if nav:
        links = "".join(
            f'<a href="{href}" class="{"on" if key == active else ""}">{T(label)}</a>'
            for href, label, key in NAV
        )
    links += (f'<a class="lang" href="{e(_lang_link(request, other))}" '
              f'lang="{other}">{T("other_lang")}</a>')
    if nav:
        links += ('<form method="post" action="/admin/logout">'
                  f'<button class="ghost" type="submit">{T("logout")}</button></form>')
    note = ""
    if flash in FLASH_KIND:
        note = f'<div class="alert {FLASH_KIND[flash]}">{e(T("flash_" + flash))}</div>'
    name = config.BOT_NAME_EN if lang == "en" else config.BOT_NAME
    doc = f"""<!doctype html>
<html lang="{lang}" dir="{'ltr' if lang == 'en' else 'rtl'}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{e(title)} · {e(name)}</title><style>{CSS}</style></head>
<body><header><div class="bar"><div class="brand">{e(name)}
<small>{T("dashboard")}</small></div><nav>{links}</nav></div></header>
<main><h1>{e(title)}</h1>{note}{body}</main></body></html>"""
    resp = HTMLResponse(doc, status_code=status, headers=HEADERS)
    if request.query_params.get("lang") in ("ar", "en"):
        resp.set_cookie(LANG_COOKIE, lang, max_age=365 * 86400, httponly=True,
                        samesite="strict", path="/admin",
                        secure=config.PUBLIC_URL.startswith("https://"))
    return resp


def when(ts: float | None) -> str:
    if not ts:
        return "—"
    # عزل اتجاهي: بدونه يقلب السطر العربي ترتيب التاريخ والساعة
    # Directional isolation: without it, an Arabic line reverses the order of
    # the date and the time
    return "⁦" + time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts)) + " UTC⁩"


def badge(outcome: str | None, T) -> str:
    kind = OUTCOMES.get(outcome or "", "muted")
    label = T(f"out_{outcome}") if outcome in OUTCOMES else (outcome or "?")
    return f'<span class="badge {kind}">{e(label)}</span>'


def channel_name(channel: str, T) -> str:
    return T(f"ch_{channel}") if channel in CHANNELS else channel


def pct(n: int, total: int) -> str:
    return f"{round(100 * n / total)}%" if total else "0%"


def _provider_label(T) -> str:
    where = T("provider_local") if config.EMBED_PROVIDER == "local" else T("provider_voyage")
    return f"{config.EMBED_MODEL} {where}"


# ─────────────────────────────────────────────────── الدخول والخروج / Login and logout
@router.get("/admin/login")
async def login_form(request: Request, error: str = ""):
    if not configured():
        return _gate(request)
    if is_admin(request):
        return RedirectResponse("/admin", status_code=303)
    T = tr(req_lang(request))
    msg = {"bad": T("login_bad"), "slow": T("login_slow")}.get(error, "")
    body = f"""<div class="card" style="max-width:420px">
{f'<div class="alert bad">{e(msg)}</div>' if msg else ''}
<form method="post" action="/admin/login">
<label for="pw">{T("password")}</label>
<input id="pw" name="password" type="password" autocomplete="current-password" required autofocus>
<p><button type="submit">{T("login_btn")}</button></p></form></div>"""
    return page(request, T("login_title"), body, nav=False)


@router.post("/admin/login")
async def login(request: Request):
    if not configured():
        return _gate(request)
    if not _same_origin(request):
        return _plain("origin_denied", 403)
    ip = request.client.host if request.client else "?"
    if not store.throttle("admin-login", ip, 5, 900):
        return _back("/admin/login", error="slow")
    form = await _form(request) or {}
    if not hmac.compare_digest(
        (form.get("password") or "").encode(), config.ADMIN_PASSWORD.encode()
    ):
        return _back("/admin/login", error="bad")
    resp = RedirectResponse("/admin", status_code=303)
    resp.set_cookie(
        COOKIE, _new_session(), max_age=SESSION_HOURS * 3600, httponly=True,
        samesite="strict", path="/admin",
        secure=config.PUBLIC_URL.startswith("https://"),
    )
    return resp


@router.post("/admin/logout")
async def logout():
    resp = RedirectResponse("/admin/login", status_code=303)
    resp.delete_cookie(COOKIE, path="/admin")
    return resp


# ─────────────────────────────────────────────────────── نظرة عامة / Overview
def _alerts(T, lang: str, counts: dict, emb: int, status: dict, last: dict | None) -> str:
    out = []
    if brain.paused():
        out.append(("bad", T("a_paused"), T("a_paused_d")))
    if counts["_chunks"] == 0:
        out.append(("bad", T("a_empty"), T("a_empty_d")))
    note = status["vector_note_en"] if lang == "en" else status["vector_note"]
    if note:
        out.append(("bad", T("a_novec"), T("a_novec_d", note=note)))
    elif (emb and store.setting("min_relevance", "") == ""
          and embed.model_id() != CALIBRATED_FOR):
        out.append(("warn", T("a_thr", v=f"{config.MIN_RELEVANCE:.2f}"),
                    T("a_thr_d", cal=CALIBRATED_FOR, cur=embed.model_id())))
    if last and last.get("finished") and not last.get("ok"):
        out.append(("warn", T("a_failed", when=when(last["started"])), T("a_failed_d")))
    return "".join(
        f'<div class="alert {k}"><strong>{e(t)}</strong>{e(d)}</div>'
        for k, t, d in out
    )


@router.get("/admin")
async def overview(request: Request, msg: str = ""):
    if denied := _gate(request):
        return denied
    lang = req_lang(request)
    T = tr(lang)
    retrieve.ensure_fresh()
    counts = store.counts()
    emb = store.embedded_count()
    status = retrieve.status()
    last = store.last_run()
    week = time.time() - 7 * 86400
    outcomes = store.outcome_stats(week)
    channels = store.channel_stats(week)
    total = sum(outcomes.values())
    thr = brain.threshold()
    rates = store.rating_stats(week)
    fixes = len(store.corrections(active_only=True))

    vec_ok = T("vec_on") if status["vectors"] else T("vec_off")
    thr_src = T("thr_dash") if store.setting("min_relevance", "") else T("thr_init")
    cards = f"""<div class="grid">
<div class="card stat"><span>{T("c_chunks")}</span><b>{counts['_chunks']}</b>
<span>{T("c_chunks_d", i=counts.get('investigation', 0), t=counts.get('tool', 0),
          r=counts.get('tool_removed', 0))}</span></div>
<div class="card stat"><span>{T("c_tools")}</span><b>{counts['_tools']}</b>
<span>{T("c_tools_d", s=counts['_tools_sensitive'], r=counts['_tools_removed'])}</span></div>
<div class="card stat"><span>{e(T("c_vec", p=_provider_label(T)))}</span><b>{vec_ok}</b>
<span>{T("c_vec_d", n=emb, t=counts['_chunks'])}</span></div>
<div class="card stat"><span>{T("c_thr")}</span><b>{thr:.2f}</b>
<span>{thr_src}</span></div>
<div class="card stat"><span>{T("c_ratings")}</span>
<b><a href="/admin/messages?rating=down">{rates.get('down', 0)}</a></b>
<span>{T("c_ratings_d", up=rates.get('up', 0), down=rates.get('down', 0), fixes=fixes)}</span></div>
</div>"""

    rows = ""
    for key in OUTCOMES:
        n = outcomes.get(key, 0)
        rows += (
            f'<tr><td><a href="/admin/messages?outcome={key}">{badge(key, T)}</a></td>'
            f"<td>{n}</td><td>{pct(n, total)}</td>"
            f'<td style="width:40%"><div class="bar-chart"><i style="width:{pct(n, total)}">'
            f"</i></div></td></tr>"
        )
    ch_rows = "".join(
        f"<tr><td>{e(channel_name(c, T))}</td><td>{v['questions']}</td>"
        f"<td>{v['users']}</td></tr>"
        for c, v in sorted(channels.items())
    ) or f'<tr><td colspan="3" class="muted">{T("none_yet")}</td></tr>'
    activity = f"""<h2>{T("week")}</h2><p class="help">{T("week_n", n=total)}</p>
<div class="grid"><div class="card"><table>
<tr><th>{T("th_outcome")}</th><th>{T("th_count")}</th><th>{T("th_share")}</th><th></th></tr>
{rows}</table></div>
<div class="card"><table><tr><th>{T("th_channel")}</th><th>{T("th_questions")}</th>
<th>{T("th_users")}</th></tr>{ch_rows}</table></div></div>"""

    totals = store.usage_totals()
    tt_rows = "".join(
        f"<tr><td>{e(channel_name(c, T))}</td><td>{v['questions']}</td>"
        f"<td>{v['users']}</td><td>{e(v['first'])}</td></tr>"
        for c, v in sorted(totals.items())
    ) or f'<tr><td colspan="4" class="muted">{T("none_yet")}</td></tr>'
    tt_all = (f'<tr><th>{T("th_total")}</th><th>{sum(v["questions"] for v in totals.values())}</th>'
              f'<th>{sum(v["users"] for v in totals.values())}</th><th></th></tr>') if totals else ""
    activity += f"""<h2>{T("total_h")}</h2><p class="help">{T("total_help")}</p>
<div class="card"><table><tr><th>{T("th_channel")}</th><th>{T("th_questions")}</th>
<th>{T("th_users")}</th><th>{T("th_first")}</th></tr>{tt_rows}{tt_all}</table></div>"""

    if last:
        took = (T("run_took", s=round(last["finished"] - last["started"]))
                if last.get("finished") else "")
        state = (T("run_running") if not last.get("finished")
                 else T("run_ok") if last.get("ok") else T("run_failed"))
        run_html = (f'<p>{T("run_line", when=when(last["started"]), took=took, state=f"<strong>{state}</strong>")}</p>'
                    f'<pre class="log">{e(last.get("detail") or "")}</pre>')
    else:
        run_html = f'<p class="muted">{T("run_none")}</p>'
    busy = ingest.running()
    reindex = f"""<h2>{T("indexing")}</h2><div class="card">{run_html}
<form method="post" action="/admin/reindex-now" class="row">
<button type="submit" {'disabled' if busy else ''}>{T("reindex_btn")}</button>
<span class="muted">{T("reindex_help")}</span></form></div>"""

    alerts = _alerts(T, lang, counts, emb, status, last)
    return page(request, T("nav_home"), alerts + cards + activity + reindex, "home",
                flash=msg)


@router.post("/admin/reindex-now")
async def reindex_now(request: Request):
    denied, _ = await _post_gate(request)
    if denied:
        return denied
    state = ingest.start_background(pull=True)
    return _back("/admin", msg="reindex" if state == "started" else "busy")


# ─────────────────────────────────────────────────────── الأسئلة / Questions
@router.get("/admin/messages")
async def messages(request: Request, outcome: str = "", channel: str = "",
                   before: int = 0, sort: str = "", rating: str = "", msg: str = ""):
    if denied := _gate(request):
        return denied
    T = tr(req_lang(request))
    outcome = outcome if outcome in OUTCOMES else ""
    channel = channel if channel in CHANNELS else ""
    rating = rating if rating in RATINGS else ""
    by_conf = sort == "confidence"
    items = store.questions(outcome, channel, 0 if by_conf else before, by_conf,
                            limit=100 if by_conf else 50, rating=rating)

    def link(**kw) -> str:
        params = {"outcome": outcome, "channel": channel, "rating": rating,
                  "sort": sort if by_conf else ""}
        params.update(kw)
        query = urlencode({k: v for k, v in params.items() if v})
        return "/admin/messages" + (f"?{query}" if query else "")

    tabs = f'<a href="{link(outcome="")}" class="{"on" if not outcome else ""}">{T("all")}</a>'
    tabs += "".join(
        f'<a href="{link(outcome=k)}" class="{"on" if k == outcome else ""}">'
        f'{e(T("out_" + k))}</a>'
        for k in OUTCOMES
    )
    ch_tabs = (f'<a href="{link(channel="")}" class="{"on" if not channel else ""}">'
               f'{T("all_channels")}</a>')
    ch_tabs += "".join(
        f'<a href="{link(channel=k)}" class="{"on" if k == channel else ""}">'
        f'{e(channel_name(k, T))}</a>'
        for k in CHANNELS
    )
    sort_tab = (
        f'<a href="{link(sort="")}" class="{"" if by_conf else "on"}">{T("newest")}</a>'
        f'<a href="{link(sort="confidence")}" class="{"on" if by_conf else ""}">'
        f'{T("highest")}</a>'
    )
    r_tabs = (f'<a href="{link(rating="")}" class="{"on" if not rating else ""}">'
              f'{T("r_all")}</a>')
    r_tabs += "".join(
        f'<a href="{link(rating=k)}" class="{"on" if k == rating else ""}">'
        f'{T({"up": "rate_up", "down": "rate_down", "none": "r_none"}[k])}</a>'
        for k in RATINGS
    )
    head = (f'<div class="tabs">{tabs}</div><div class="tabs">{ch_tabs}</div>'
            f'<div class="tabs">{r_tabs}</div><div class="tabs">{sort_tab}</div>')
    if outcome in ("refused_gate", "refused_model", "error"):
        head += f'<p class="help">{e(T("help_" + outcome))}</p>'

    here = link(before=str(before) if before and not by_conf else "")
    cards = []
    for m in items:
        fp = fingerprint(m["channel"], m["user_id"])
        sources = "".join(
            f'<li><a href="{e(s)}" rel="noreferrer">{e(s)}</a></li>' for s in m["sources"]
        )
        reply = (f'<details><summary>{T("reply")}</summary>'
                 f'<div class="reply">{e(m["reply"])}</div>'
                 f'{f"<ul>{sources}</ul>" if sources else ""}</details>'
                 if m.get("reply") else "")
        conf = f"{m['confidence']:.2f}" if m["confidence"] is not None else "—"
        cards.append(f"""<div class="card" id="m{m['id']}">
<div class="meta">{badge(m['outcome'], T)}<span>{T("conf", c=conf)}</span>
<span>{e(channel_name(m['channel'], T))}</span>
<span title="{T("fp_title")}">{T("user", fp=fp)}</span><span>{when(m['ts'])}</span>
<form method="post" action="/admin/block">
<input type="hidden" name="msg_id" value="{m['id']}">
<input type="hidden" name="next" value="{e(here)}">
<button class="danger small" type="submit">{T("block_btn")}</button></form></div>
<div class="q">{e(m['content'])}</div>{reply}{_rating_html(m, here, T)}</div>""")
    body = head + ("".join(cards) or f'<div class="card muted">{T("none_here")}</div>')
    if items and not by_conf and len(items) == 50:
        body += (f'<p><a class="btn" href="{e(link(before=str(items[-1]["id"])))}">'
                 f'{T("older")}</a></p>')
    return page(request, T("q_title"), body, "messages", flash=msg)


def _rating_html(m: dict, here: str, T) -> str:
    """التقييم الحالي، ونموذج التقييم، ورابط كتابة تصحيح، تحت إجابة السؤال.
    The current rating, the rating form and the link to write a correction,
    under the question's answer."""
    mid = m["id"]
    shown = ""
    if m.get("rating"):
        up = m["rating"] > 0
        parts = [f'<span class="badge {"ok" if up else "bad"}">'
                 f'{T("rated_up") if up else T("rated_down")}</span>']
        if m.get("rating_reason") in store.RATING_REASONS:
            parts.append(f'<span>{T("rr_" + m["rating_reason"])}</span>')
        if m.get("rating_note"):
            parts.append(f'<span>{e(m["rating_note"])}</span>')
        shown = f'<div class="meta rated">{"".join(parts)}</div>'
    options = "".join(
        f'<option value="{r}" {"selected" if m.get("rating_reason") == r else ""}>'
        f'{T("rr_" + r)}</option>'
        for r in store.RATING_REASONS
    )
    clear = (f'<button class="ghost small" name="rating" value="clear" type="submit">'
             f'{T("rate_clear")}</button>' if m.get("rating") else "")
    return f"""{shown}<details class="rate"><summary>{T("rate_summary")}</summary>
<form method="post" action="/admin/rate">
<input type="hidden" name="msg_id" value="{mid}">
<input type="hidden" name="next" value="{e(here)}">
<label for="rr{mid}">{T("rate_reason")}</label>
<select id="rr{mid}" name="reason"><option value="">{T("rr_none")}</option>{options}</select>
<label for="rn{mid}">{T("rate_note")}</label>
<input id="rn{mid}" name="note" maxlength="300" value="{e(m.get('rating_note') or '')}">
<p class="row"><button name="rating" value="up" type="submit">{T("rate_up")}</button>
<button class="danger" name="rating" value="down" type="submit">{T("rate_down")}</button>
{clear}<a href="/admin/corrections/new?from={mid}">{T("write_fix")}</a></p>
</form></details>"""


@router.post("/admin/rate")
async def rate(request: Request):
    denied, form = await _post_gate(request)
    if denied:
        return denied
    nxt = _safe_next(form.get("next", ""))
    mid = form.get("msg_id") or ""
    if mid.isdigit():
        choice = form.get("rating")
        if choice == "clear":
            store.clear_rating(int(mid))
        elif choice in ("up", "down"):
            store.set_rating(int(mid), 1 if choice == "up" else -1,
                             form.get("reason", ""), (form.get("note") or "")[:300])
    sep = "&" if "?" in nxt else "?"
    return RedirectResponse(f"{nxt}{sep}msg=rated#m{mid if mid.isdigit() else ''}",
                            status_code=303)


@router.post("/admin/block")
async def block(request: Request):
    denied, form = await _post_gate(request)
    if denied:
        return denied
    nxt = _safe_next(form.get("next", ""))
    owner = store.message_owner(int(form.get("msg_id") or 0)) \
        if (form.get("msg_id") or "").isdigit() else None
    if owner:
        store.block(*owner, BLOCK_REASON)
    sep = "&" if "?" in nxt else "?"
    return RedirectResponse(f"{nxt}{sep}msg=blocked", status_code=303)


# ─────────────────────────────────────────────────────── المحظورون / Blocked
@router.get("/admin/blocked")
async def blocked(request: Request, msg: str = ""):
    if denied := _gate(request):
        return denied
    T = tr(req_lang(request))

    def reason(r: str | None) -> str:
        return T("reason_dashboard") if r in (BLOCK_REASON, "حُظر من اللوحة") else (r or "")

    rows = "".join(
        f"""<tr><td>{fingerprint(b['channel'], b['user_id'])}</td>
<td>{e(channel_name(b['channel'], T))}</td><td>{e(reason(b['reason']))}</td>
<td>{when(b['ts'])}</td><td><form method="post" action="/admin/unblock">
<input type="hidden" name="channel" value="{e(b['channel'])}">
<input type="hidden" name="fp" value="{fingerprint(b['channel'], b['user_id'])}">
<button class="ghost" type="submit">{T("unblock_btn")}</button></form></td></tr>"""
        for b in store.blocked_list()
    )
    body = f'<p class="help">{T("blocked_help")}</p>'
    body += (f'<div class="card"><table><tr><th>{T("th_user")}</th><th>{T("th_channel")}</th>'
             f'<th>{T("th_reason")}</th><th>{T("th_since")}</th><th></th></tr>{rows}</table></div>'
             if rows else f'<div class="card muted">{T("nobody")}</div>')
    return page(request, T("nav_blocked"), body, "blocked", flash=msg)


@router.post("/admin/unblock")
async def unblock(request: Request):
    denied, form = await _post_gate(request)
    if denied:
        return denied
    for b in store.blocked_list():
        if (b["channel"] == form.get("channel")
                and hmac.compare_digest(fingerprint(b["channel"], b["user_id"]),
                                        form.get("fp", ""))):
            store.unblock(b["channel"], b["user_id"])
    return _back("/admin/blocked", msg="unblocked")


# ─────────────────────────────────────────────────────── التجربة / Try Bayan
def _try_form(T, q: str = "") -> str:
    return f"""<div class="card"><form method="post" action="/admin/try">
<label for="q">{T("question")}</label>
<textarea id="q" name="q" rows="3" maxlength="{config.MAX_QUESTION_CHARS}" required>{e(q)}</textarea>
<p class="row"><button type="submit">{T("ask_btn")}</button>
<span class="muted">{T("try_note")}</span></p></form></div>"""


@router.get("/admin/try")
async def try_form(request: Request, q: str = ""):
    if denied := _gate(request):
        return denied
    T = tr(req_lang(request))
    # ?q= يملأ الخانة فقط (من رابط «جرّبه» في التصحيحات)، ولا يستدعي النموذج
    # ?q= only fills in the box (from the "Try it" link on a correction), and
    # does not call the model
    return page(request, T("nav_try"), _try_form(T, q[: config.MAX_QUESTION_CHARS]), "try")


@router.post("/admin/try")
async def try_ask(request: Request):
    denied, form = await _post_gate(request)
    if denied:
        return denied
    lang = req_lang(request)
    T = tr(lang)
    q = (form.get("q") or "").strip()[: config.MAX_QUESTION_CHARS]
    if not q:
        return page(request, T("nav_try"), _try_form(T), "try")
    res = await asyncio.to_thread(brain.answer, q, "admin", "console")
    r = res["retrieval"] or {"tools": [], "category": None, "category_tools": [],
                             "passages": [], "used_vectors": False}
    thr = brain.threshold()
    sep = ", " if lang == "en" else "، "
    tools = sep.join(e(t["name"]) for t in r["tools"]) or T("nothing")
    cat = r["category"]
    cat_name = (cat.get("category_en") if lang == "en" else None) or cat["category_ar"] \
        if cat else ""
    cat_html = (e(T("cat_shown", c=cat_name, n=len(r["category_tools"])))
                if cat else T("nothing"))
    passages = "".join(
        f'<tr><td>{e(T("type_" + p["type"]) if ("type_" + p["type"]) in TEXT else p["type"])}</td>'
        f'<td class="wrap">{e(p["title"] or "")}</td>'
        f'<td class="wrap"><a href="{e(p["url"])}" rel="noreferrer">{e(p["url"])}</a></td></tr>'
        for p in r["passages"]
    )
    fixes = sep.join(
        f'<a href="/admin/corrections/edit?id={c["id"]}">{e(c["question"])}</a> '
        f'<span class="muted">({T("fix_sim", s=round(c["similarity"], 2))})</span>'
        for c in r.get("corrections", [])
    ) or T("nothing")
    mode = T("mode_vec") if r.get("used_vectors") else T("mode_text")
    answer_lang = T("lang_en") if res.get("lang") == "en" else T("lang_ar")
    table = (f'<table><tr><th>{T("th_type")}</th><th>{T("th_title")}</th>'
             f'<th>{T("th_link")}</th></tr>{passages}</table>'
             if passages else f'<p class="muted">{T("no_passages")}</p>')
    body = _try_form(T, q) + f"""<div class="card">
<div class="meta">{badge(res['outcome'], T)}<span>{T("conf", c=f"{res['confidence']:.3f}")}</span>
<span>{T("thr_v", t=f"{thr:.2f}")}</span><span>{T("search_mode", m=mode)}</span>
<span>{T("answer_lang", l=answer_lang)}</span></div>
<div class="reply" dir="auto">{e(res['text'])}</div></div>
<div class="card"><table>
<tr><th>{T("fix_matched")}</th><td>{fixes}</td></tr>
<tr><th>{T("th_name_match")}</th><td>{tools}</td></tr>
<tr><th>{T("th_cat_match")}</th><td>{cat_html}</td></tr></table></div>
<h2>{T("passages")}</h2>
<div class="card">{table}</div>"""
    return page(request, T("nav_try"), body, "try")


# ─────────────────────────────────────────── التصحيحات المعتمدة / Approved corrections
@router.get("/admin/corrections")
async def corrections_list(request: Request, msg: str = ""):
    if denied := _gate(request):
        return denied
    T = tr(req_lang(request))
    model = embed.model_id()
    cards = []
    for c in store.corrections():
        state = (f'<span class="badge ok">{T("fix_on")}</span>' if c["active"]
                 else f'<span class="badge muted">{T("fix_off")}</span>')
        novec = ("" if c["vector"] is not None and c["embed_model"] == model
                 else f'<span class="badge warn">{T("fix_novec")}</span>')
        link = (f'<a href="{e(c["url"])}" rel="noreferrer">{e(c["url"])}</a>'
                if c["url"] else "")
        cards.append(f"""<div class="card">
<div class="meta">{state}{novec}<span>{T("fix_updated", when=when(c['updated']))}</span></div>
<div class="q">{e(c['question'])}</div>
<details><summary>{T("fix_a")}</summary><div class="reply">{e(c['answer'])}</div>{link}</details>
<p class="row"><a class="btn" href="/admin/corrections/edit?id={c['id']}">{T("fix_edit")}</a>
<a href="/admin/try?{urlencode({'q': c['question']})}">{T("fix_try")}</a>
<form method="post" action="/admin/corrections/delete">
<input type="hidden" name="id" value="{c['id']}">
<button class="danger small" type="submit">{T("fix_delete")}</button></form></p></div>""")
    body = (f'<p class="help">{T("fix_help")}</p>'
            f'<p><a class="btn" href="/admin/corrections/new">{T("fix_new")}</a></p>'
            + ("".join(cards) or f'<div class="card muted">{T("fix_none")}</div>'))
    return page(request, T("fix_title"), body, "corrections", flash=msg)


def _fix_form(T, c: dict, error: str = "", original: tuple[str, str | None] | None = None
              ) -> str:
    err = f'<div class="alert bad">{e(error)}</div>' if error else ""
    ref = ""
    if original:
        q, reply = original
        ref = (f'<details class="card"><summary>{T("fix_orig")}</summary>'
               f'<div class="q">{e(q)}</div>'
               f'{f"<div class=reply>{e(reply)}</div>" if reply else ""}</details>')
    return f"""{err}{ref}<div class="card"><form method="post" action="/admin/corrections/save">
<input type="hidden" name="id" value="{c.get('id') or ''}">
<label for="fq">{T("fix_q")}</label><p class="help">{T("fix_q_help")}</p>
<textarea id="fq" name="question" rows="2" maxlength="{config.MAX_QUESTION_CHARS}"
required>{e(c.get('question') or '')}</textarea>
<label for="fa">{T("fix_a")}</label><p class="help">{T("fix_a_help")}</p>
<textarea id="fa" name="answer" rows="8" maxlength="{FIX_ANSWER_CHARS}"
required>{e(c.get('answer') or '')}</textarea>
<label for="fu">{T("fix_url")}</label>
<p class="help">{e(T("fix_url_help", site=config.SITE_URL))}</p>
<input id="fu" name="url" type="url" dir="ltr" value="{e(c.get('url') or '')}">
<label><input type="checkbox" name="active" value="1"
{'checked' if c.get('active', 1) else ''}> {T("fix_active")}</label>
<p><button type="submit">{T("save")}</button></p></form></div>"""


@router.get("/admin/corrections/new")
async def correction_new(request: Request):
    if denied := _gate(request):
        return denied
    T = tr(req_lang(request))
    src = request.query_params.get("from", "")
    original = store.question_text(int(src)) if src.isdigit() else None
    # السؤال الأصلي يملأ الخانة ليُعاد صوغه، لا ليُحفظ كما هو
    # The original question fills the box to be reworded, not saved as it is
    c = {"question": original[0] if original else "", "active": 1}
    return page(request, T("fix_new"), _fix_form(T, c, original=original), "corrections")


@router.get("/admin/corrections/edit")
async def correction_edit(request: Request, id: int = 0):
    if denied := _gate(request):
        return denied
    T = tr(req_lang(request))
    c = store.correction(id)
    if not c:
        return _back("/admin/corrections")
    return page(request, T("fix_edit"), _fix_form(T, c), "corrections")


def _valid_fix_url(url: str) -> bool:
    site = urlsplit(config.SITE_URL)
    u = urlsplit(url)
    return u.scheme == "https" and u.netloc == site.netloc and "\n" not in url


@router.post("/admin/corrections/save")
async def correction_save(request: Request):
    denied, form = await _post_gate(request, FIX_FORM_BYTES)
    if denied:
        return denied
    T = tr(req_lang(request))
    cid = int(form["id"]) if (form.get("id") or "").isdigit() else 0
    c = {"id": cid, "question": (form.get("question") or "").strip(),
         "answer": (form.get("answer") or "").strip(),
         "url": (form.get("url") or "").strip(), "active": bool(form.get("active"))}
    title = T("fix_edit") if cid else T("fix_new")
    if (not c["question"] or not c["answer"]
            or len(c["question"]) > config.MAX_QUESTION_CHARS
            or len(c["answer"]) > FIX_ANSWER_CHARS):
        error = T("err_fix", q=config.MAX_QUESTION_CHARS, a=FIX_ANSWER_CHARS)
        return page(request, title, _fix_form(T, c, error), "corrections", status=400)
    if c["url"] and not _valid_fix_url(c["url"]):
        error = T("err_fix_url", site=config.SITE_URL)
        return page(request, title, _fix_form(T, c, error), "corrections", status=400)
    if cid and not store.correction(cid):
        return _back("/admin/corrections")
    vector, model = await asyncio.to_thread(retrieve.embed_correction, c["question"])
    store.save_correction(c["question"], c["answer"], c["url"], c["active"],
                          vector, model, cid)
    return _back("/admin/corrections", msg="fix_saved" if vector is not None else "fix_novec")


@router.post("/admin/corrections/delete")
async def correction_delete(request: Request):
    denied, form = await _post_gate(request)
    if denied:
        return denied
    if (form.get("id") or "").isdigit():
        store.delete_correction(int(form["id"]))
    return _back("/admin/corrections", msg="fix_deleted")


# ─────────────────────────────────────────────────────── الفرص / Opportunities
def _opp_form(T, c: dict, error: str = "") -> str:
    err = f'<div class="alert bad">{e(error)}</div>' if error else ""
    return f"""{err}<div class="card"><form method="post" action="/admin/opportunities/save">
<label for="ow">{T("opp_week")}</label>
<input id="ow" name="week" type="number" min="1" max="53" required value="{e(str(c['week']))}">
<label for="oy">{T("opp_year")}</label>
<input id="oy" name="year" type="number" min="2000" max="2100" required value="{e(str(c['year']))}">
<label for="ot">{T("opp_paste")}</label>
<textarea id="ot" name="text" rows="14" dir="auto" required>{e(c.get('text') or '')}</textarea>
<p><button type="submit">{T("opp_save")}</button></p></form></div>"""


@router.get("/admin/opportunities")
async def opportunities_list(request: Request, msg: str = ""):
    if denied := _gate(request):
        return denied
    T = tr(req_lang(request))
    iso = datetime.date.today().isocalendar()
    cards = []
    for w in store.opportunity_weeks():
        items = "".join(
            f'<li>{e(i["title"])} <a href="{e(i["url"])}" rel="noreferrer" dir="ltr">{e(i["url"][:60])}</a></li>'
            for i in store.opportunity_week_items(w["year"], w["week"]))
        cards.append(f"""<div class="card"><div class="meta"><span>{w['year']} · {T("opp_week")} {w['week']}</span>
<span>{T("opp_count", n=w['n'])}</span></div><details><summary>{T("opp_paste")}</summary><ol>{items}</ol></details>
<form method="post" action="/admin/opportunities/delete">
<input type="hidden" name="year" value="{w['year']}"><input type="hidden" name="week" value="{w['week']}">
<button class="danger small" type="submit">{T("opp_delete")}</button></form></div>""")
    body = (f'<p class="help">{T("opp_help", n=config.OPPORTUNITY_WEEKS)}</p>'
            + _opp_form(T, {"week": iso[1], "year": iso[0]})
            + ("".join(cards) or f'<div class="card muted">{T("opp_none")}</div>'))
    return page(request, T("opp_title"), body, "opportunities", flash=msg)


@router.post("/admin/opportunities/save")
async def opportunities_save(request: Request):
    denied, form = await _post_gate(request, FIX_FORM_BYTES)
    if denied:
        return denied
    T = tr(req_lang(request))
    text = (form.get("text") or "").strip()
    try:
        week, year = int(form.get("week") or ""), int(form.get("year") or "")
    except ValueError:
        week = year = 0
    items = opportunities.parse_list(text) if text else []
    if not (1 <= week <= 53 and 2000 <= year <= 2100) or not items or len(text) > FIX_ANSWER_CHARS:
        c = {"week": form.get("week") or "", "year": form.get("year") or "", "text": text}
        return page(request, T("opp_title"), _opp_form(T, c, T("err_opp")),
                    "opportunities", status=400)
    store.save_opportunity_week(year, week, items)
    # تصحيح «فرص الأسبوع N» ليجيب «فرص» بالقائمة كاملة، ويُحدَّث إن وُجد
    # The «فرص الأسبوع N» correction, so «فرص» answers with the whole list; updated if it exists
    question = f"فرص الأسبوع {week}"
    existing = next((c for c in store.corrections() if c["question"] == question), None)
    vector, model = await asyncio.to_thread(retrieve.embed_correction, question)
    store.save_correction(question, text, "", True, vector, model,
                          existing["id"] if existing else 0)
    return _back("/admin/opportunities", msg="opp_saved")


@router.post("/admin/opportunities/delete")
async def opportunities_delete(request: Request):
    denied, form = await _post_gate(request)
    if denied:
        return denied
    if (form.get("year") or "").isdigit() and (form.get("week") or "").isdigit():
        store.delete_opportunity_week(int(form["year"]), int(form["week"]))
    return _back("/admin/opportunities", msg="opp_deleted")


# ─────────────────────────────────────────────────────── الإعدادات / Settings
def _channel_state(T) -> str:
    def row(name: str, ok: bool, need: str) -> str:
        state = (f'<span class="state ok">{T("st_ok")}</span>' if ok
                 else f'<span class="state muted">{e(T("st_missing", need=need))}</span>')
        return f'<tr><td>{e(name)}</td><td class="wrap">{state}</td></tr>'

    meta = bool(config.META_APP_SECRET and config.META_VERIFY_TOKEN)
    return (
        row(T("ch_telegram"),
            bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_WEBHOOK_SECRET), T("need_tg"))
        + row(T("ch_whatsapp"),
              meta and bool(config.WHATSAPP_TOKEN and config.WHATSAPP_PHONE_NUMBER_ID),
              T("need_wa"))
        + row(T("ch_messenger"), meta and bool(config.MESSENGER_PAGE_TOKEN), T("need_ms"))
    )


@router.get("/admin/settings")
async def settings(request: Request, msg: str = "", error: str = ""):
    if denied := _gate(request):
        return denied
    lang = req_lang(request)
    T = tr(lang)
    thr = brain.threshold()
    paused = brain.paused()
    err = {"threshold": "err_threshold", "limit": "err_limit"}.get(error)
    err_html = f'<div class="alert bad">{T(err)}</div>' if err else ""
    fixed = [
        (T("f_answer_model"), config.ANSWER_MODEL),
        (T("f_embed_model"), _provider_label(T)),
        (T("f_dim"), config.EMBED_DIM),
        (T("f_top_k"), config.TOP_K),
        (T("f_max_tools"), config.MAX_TOOLS_LISTED),
        (T("f_rate"), config.RATE_LIMIT_MESSAGES),
        (T("f_window"), config.RATE_LIMIT_WINDOW),
        (T("f_history"), config.HISTORY_TURNS),
        (T("f_sources"), T("yes") if config.SHOW_SOURCES else T("no")),
    ]
    fixed_rows = "".join(f"<tr><th>{e(k)}</th><td>{e(str(v))}</td></tr>" for k, v in fixed)
    paused_msg = config.PAUSED_MESSAGE_EN if lang == "en" else config.PAUSED_MESSAGE
    body = f"""{err_html}<div class="card"><form method="post" action="/admin/settings">
<label for="t">{T("s_thr")}</label>
<p class="help">{T("s_thr_help", v=f"{config.MIN_RELEVANCE:.2f}")}</p>
<input id="t" name="threshold" type="number" step="0.01" min="0.05" max="0.9"
value="{thr:.2f}" style="max-width:140px">
<label for="dl">{T("s_limit")}</label>
<p class="help">{T("s_limit_help", v=config.DAILY_LIMIT)}</p>
<input id="dl" name="daily_limit" type="number" step="1" min="0" max="1000"
value="{brain.daily_limit()}" style="max-width:140px">
<label><input type="checkbox" name="paused" value="1" {'checked' if paused else ''}>
{T("s_pause")}</label>
<p class="help">{e(T("s_pause_help", m=paused_msg))}</p>
<p class="row"><button type="submit">{T("save")}</button>
<button class="ghost" type="submit" name="reset" value="1">{T("reset_thr")}</button></p>
</form></div>
<h2>{T("channels")}</h2><div class="card"><table>{_channel_state(T)}</table></div>
<h2>{T("env_settings")}</h2>
<p class="help">{T("env_help")}</p>
<div class="card"><table>{fixed_rows}</table></div>"""
    return page(request, T("nav_settings"), body, "settings", flash=msg)


@router.post("/admin/settings")
async def save_settings(request: Request):
    denied, form = await _post_gate(request)
    if denied:
        return denied
    limit = (form.get("daily_limit") or "").strip()
    if limit:
        if not limit.isdigit() or int(limit) > 1000:
            return _back("/admin/settings", error="limit")
        store.set_setting("daily_limit", str(int(limit)))
    if form.get("reset"):
        store.clear_setting("min_relevance")
    else:
        try:
            thr = float(form.get("threshold", ""))
        except ValueError:
            thr = -1
        if not 0.05 <= thr <= 0.9:
            return _back("/admin/settings", error="threshold")
        store.set_setting("min_relevance", f"{thr:.2f}")
    store.set_setting("paused", "1" if form.get("paused") else "0")
    return _back("/admin/settings", msg="saved")
