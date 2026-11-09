# Changelog / سجل الإصدارات

## 1.0.0 — 2026-11-09

First public release. أول إصدار عام.

**Knowledge / المعرفة**
- Five kinds of content, all under the organisation's control: an exported content repository (passages and structured entries with categories, warnings and verification fields), team sources added from the dashboard (notes, links and files), weekly lists, openly licensed external sources with per-answer attribution, and approved corrections.
- خمسة أنواع من المحتوى كلها تحت سيطرة المنظمة: مستودع محتوى مصدَّر (مقاطع وسجلات مهيكلة بتصنيفات وتحذيرات وحقول تحقق)، ومصادر فريق من اللوحة (ملاحظات وروابط وملفات)، وقوائم أسبوعية، ومصادر خارجية مفتوحة الرخصة مع نسبة كل جواب، وتصحيحات معتمدة.

**Channels / القنوات**
- Telegram, WhatsApp and Facebook Messenger, private replies to Facebook Page comments, and the weekly list broadcast to subscribers.
- تيليغرام وواتساب وفيسبوك ماسنجر، والردّ الخاص على تعليقات صفحة فيسبوك، وبثّ القائمة الأسبوعية للمشتركين.

**The brain / العقل**
- Two retrieval paths (structured and semantic) with a confidence gate before the model, editorial rules enforced in code (the link filter, a verification field passed on as evidence rather than a safety verdict, removed and sensitive entries), approved corrections that take precedence over the sources, and an optional local model for some channels.
- استرجاع بمسارين (بنيوي ودلالي) وبوابة ثقة قبل النموذج، وقواعد تحريرية مُنفَّذة بالكود (مرشّح الروابط، حقل التحقق كدرجة دليل لا حكم أمان، السجلات المُزالة والحسّاسة)، وتصحيحات معتمدة تتقدّم على المصادر، ونموذج محلي اختياري لبعض القنوات.

**The dashboard / اللوحة**
- Google sign-in for the organisation's domain with roles (admin, editor, viewer) and an action log; English by default with Arabic at a click; questions, ratings, corrections, weekly lists, data sources, the bot's role page (scope, rules, texts, name, style, scenario preview), API keys, and a multi-turn team chat.
- دخول بحساب Google لنطاق المنظمة مع أدوار (مدير، محرر، مشاهد) وسجلّ إجراءات؛ الإنجليزية افتراضياً مع العربية بزر؛ الأسئلة والتقييمات والتصحيحات والقوائم الأسبوعية ومصادر البيانات وصفحة دور البوت (النطاق، القواعد، النصوص، الاسم، الأسلوب، معاينة السيناريوهات) ومفاتيح API ومحادثة الفريق متعددة الأدوار.

**Privacy and security / الخصوصية والأمان**
- No audience identifiers in the dashboard, messages deleted after the retention period, a published privacy policy; Bandit, pip-audit and gitleaks in CI; no secrets in the access log.
- لا معرّفات للجمهور في اللوحة، وحذف الرسائل بعد مدة الحفظ، وسياسة خصوصية منشورة؛ فحوص Bandit وpip-audit وgitleaks في CI؛ لا أسرار في سجلّ الوصول.
