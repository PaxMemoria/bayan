"""صفحة سياسة الخصوصية لبيان (/privacy)، بالعربية ثم الإنجليزية.

الأرقام فيها (مدة الحفظ، الحدّ اليومي، ذاكرة المحادثة) تُقرأ من الإعدادات
نفسها، فلا تقول الصفحة غير ما يفعله الكود. أي تغيير فيما يُحفظ يستلزم تعديل
هذه الصفحة وتاريخها.

Bayan's privacy policy page (/privacy), in Arabic then English.

Its figures (retention period, daily limit, conversation memory) are read
from the settings themselves, so the page never says anything other than
what the code does. Any change to what is stored requires updating this
page and its date.
"""
import html

from fastapi.responses import HTMLResponse

from . import brain, config

UPDATED_AR = "23 تشرين الأول/أكتوبر 2026"
UPDATED_EN = "23 October 2026"
GENERAL_POLICY = "https://paxmemoria.org/privacy-policy"

CSS = """
:root{--bg:#f5f4f0;--ink:#1c1c1a;--muted:#696962;--line:#e2e0d9;--accent:#1d5c57}
@media (prefers-color-scheme:dark){:root{--bg:#10201E;--ink:#ecebe6;--muted:#a3a29b;
--line:#24403A;--accent:#EDA084}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);line-height:1.8;font-size:16px;
font-family:"SF Arabic","Noto Sans Arabic","Segoe UI","Geeza Pro",Tahoma,sans-serif}
main{max-width:760px;margin:auto;padding:28px 16px 64px}
section[lang=en]{font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
border-top:1px solid var(--line);margin-top:40px;padding-top:8px}
h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:28px 0 8px}
.muted{color:var(--muted);font-size:14px}a{color:var(--accent)}
ul{padding-inline-start:22px}li{margin:4px 0}
nav{font-size:14px;margin-bottom:18px}
"""

HEADERS = {
    "Content-Security-Policy": ("default-src 'none'; style-src 'unsafe-inline'; "
                                "frame-ancestors 'none'; base-uri 'none'"),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def _arabic(days: int, limit: int, turns: int, contact: str) -> str:
    limit_line = (f"<li>لتطبيق حدّ الأسئلة ({limit} في كل 24 ساعة) ومنع إساءة الاستعمال.</li>"
                  if limit > 0 else "<li>لمنع إساءة الاستعمال.</li>")
    return f"""
<h1>سياسة الخصوصية لبيان</h1>
<p class="muted">آخر تحديث: {UPDATED_AR}</p>
<p>بيان مساعد آلي تديره باكس ميموريا، يجيب عن دليل أدوات المصادر المفتوحة
والتحقيقات المنشورة عبر تطبيقات المراسلة (تيليغرام حالياً). تشرح هذه الصفحة ما
يحفظه بيان من بياناتك وما يفعله بها، وتكمّل
<a href="{GENERAL_POLICY}">سياسة الخصوصية العامة لباكس ميموريا</a>.</p>

<h2>ما نحفظه</h2>
<ul>
<li>نص أسئلتك وإجابات بيان عليها.</li>
<li>معرّفك في القناة التي تراسلنا منها: رقم المحادثة في تيليغرام، أو رقم هاتفك
في واتساب، أو المعرّف الذي تمنحه فيسبوك لمحادثتك مع صفحتنا في ماسنجر.</li>
<li>وقت كل رسالة، وهل أُجيبت أم رُفضت.</li>
</ul>
<p>لا نطلب اسمك ولا نحفظه، ولا نحفظ الصور أو الملفات أو الرسائل الصوتية، فبيان لا
يقرؤها أصلاً. نستعمل لغة واجهة تيليغرام لاختيار لغة الترحيب، ولا نحفظها.</p>

<h2>لماذا نحفظه</h2>
<ul>
<li>للإجابة عن سؤالك.</li>
<li>لتذكّر آخر {turns} أسئلة في محادثتك، كي يفهم بيان السؤال الذي يتبع سؤالاً سابقاً.</li>
{limit_line}
<li>لمراجعة جودة الإجابات وتحسينها. يرى فريقنا في لوحة التحكم الأسئلة والإجابات
دون أي معرّف، فكل مستخدم يظهر ببصمة لا تُعكس إلى رقمه.</li>
</ul>

<h2>من يتلقى بياناتك</h2>
<ul>
<li>منصة المراسلة التي تستعملها (تيليغرام أو ميتا)، وفق سياستها الخاصة.</li>
<li>مزوّد نموذج لغوي يكتب الإجابة. يتلقى نص سؤالك، وآخر أسئلتك وإجاباتها في
المحادثة، ومقاطع من موقعنا، ولا يتلقى معرّفك.</li>
<li>البحث في محتوى موقعنا يجري على خادمنا، فلا يُرسل سؤالك إلى أي خدمة بحث خارجية.</li>
</ul>
<p>لا نبيع بياناتك، ولا نستعملها للإعلان، ولا نشاركها مع أي جهة غير ما سبق.</p>

<h2>مدة الحفظ</h2>
<ul>
<li>الأسئلة والإجابات: {days} يوماً، ثم تُحذف تلقائياً.</li>
<li>أوقات أسئلتك لتطبيق الحدّ اليومي: 24 ساعة.</li>
<li>سجلّ منع الرسائل المكررة: 24 ساعة، وسجلّ منع الإرسال السريع: ساعة واحدة.</li>
<li>إن حُظر مستخدم لإساءة الاستعمال، يبقى معرّفه في قائمة الحظر ما دام الحظر قائماً.</li>
<li>سجلّات الخادم التقنية لا تحوي نص أسئلتك.</li>
</ul>

<h2>حقوقك</h2>
<ul>
<li>اكتب /reset أو «مسح» لحذف محادثتك المحفوظة فوراً.</li>
<li>للاطلاع على بياناتك أو حذفها أو لأي طلب آخر، راسلنا على
<a href="mailto:{contact}">{contact}</a>.</li>
</ul>

<h2>الأمان</h2>
<p>الاتصال بخادمنا مشفّر، ولوحة التحكم محمية بكلمة مرور ولا تعرض أي معرّف.</p>

<h2>التعديلات</h2>
<p>ننشر أي تعديل على هذه الصفحة مع تاريخه.</p>
"""


def _english(days: int, limit: int, turns: int, contact: str) -> str:
    limit_line = (f"<li>To apply the question limit ({limit} every 24 hours) and prevent "
                  "misuse.</li>" if limit > 0 else "<li>To prevent misuse.</li>")
    return f"""
<h1>Bayan privacy policy</h1>
<p class="muted">Last updated: {UPDATED_EN}</p>
<p>Bayan is an automated assistant run by Pax Memoria. It answers questions
about our open-source tools guide and our published investigations through
messaging apps (Telegram for now). This page explains what Bayan stores about
you and what it does with it, and supplements
<a href="{GENERAL_POLICY}">Pax Memoria's general privacy policy</a>.</p>

<h2>What we store</h2>
<ul>
<li>The text of your questions and Bayan's answers.</li>
<li>Your identifier on the channel you write from: the chat ID on Telegram,
your phone number on WhatsApp, or the ID Facebook assigns to your conversation
with our page on Messenger.</li>
<li>The time of each message, and whether it was answered or refused.</li>
</ul>
<p>We do not ask for or store your name, and we do not store photos, files or
voice messages: Bayan does not read them at all. We use your Telegram
interface language to choose the language of the welcome, and do not store it.</p>

<h2>Why we store it</h2>
<ul>
<li>To answer your question.</li>
<li>To remember the last {turns} questions in your conversation, so Bayan
understands a question that follows an earlier one.</li>
{limit_line}
<li>To review and improve the quality of answers. In the dashboard our team
sees questions and answers without any identifier: each user appears as a
fingerprint that cannot be traced back to their number.</li>
</ul>

<h2>Who receives your data</h2>
<ul>
<li>The messaging platform you use (Telegram or Meta), under its own policy.</li>
<li>A language-model provider that writes the answer. It receives the text of
your question, your recent questions and answers in the conversation, and
passages from our site, but not your identifier.</li>
<li>Searching our site's content happens on our own server, so your question
is not sent to any outside search service.</li>
</ul>
<p>We do not sell your data, use it for advertising, or share it with anyone
other than the above.</p>

<h2>How long we keep it</h2>
<ul>
<li>Questions and answers: {days} days, then deleted automatically.</li>
<li>The times of your questions, for the daily limit: 24 hours.</li>
<li>The record that prevents duplicate messages: 24 hours; the record that
prevents rapid-fire sending: one hour.</li>
<li>If a user is blocked for misuse, their identifier stays on the block list
for as long as the block lasts.</li>
<li>The server's technical logs do not contain the text of your questions.</li>
</ul>

<h2>Your rights</h2>
<ul>
<li>Send /reset to delete your saved conversation immediately.</li>
<li>To see or delete your data, or for any other request, write to
<a href="mailto:{contact}">{contact}</a>.</li>
</ul>

<h2>Security</h2>
<p>Connections to our server are encrypted, and the dashboard is
password-protected and shows no identifiers.</p>

<h2>Changes</h2>
<p>We publish any change on this page with its date.</p>
"""


def page() -> HTMLResponse:
    days, limit = config.MESSAGE_RETENTION_DAYS, brain.daily_limit()
    turns, contact = config.HISTORY_TURNS, html.escape(config.PRIVACY_CONTACT)
    doc = f"""<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>سياسة الخصوصية لبيان · Bayan privacy policy</title>
<style>{CSS}</style></head><body><main>
<nav><a href="#en" lang="en">English below</a></nav>
<section lang="ar" dir="rtl">{_arabic(days, limit, turns, contact)}</section>
<section lang="en" dir="ltr" id="en">{_english(days, limit, turns, contact)}</section>
</main></body></html>"""
    return HTMLResponse(doc, headers=HEADERS)
