/*
 * Bayan website chat widget. Served by Bayan at /widget.js; a site embeds it
 * with one script tag pointing at that address (defer).
 * No dependencies, no cookies: a random conversation ID lives in the
 * browser's localStorage, and the thread of the current tab in sessionStorage.
 * Everything renders inside a shadow root so the site's styles do not leak in.
 *
 * ودجت الدردشة على الموقع. يقدّمه بيان على /widget.js، ويضمّنه الموقع بسطر
 * واحد. بلا مكتبات ولا كوكي: معرّف عشوائي للمحادثة في localStorage، ومحادثة
 * التبويب الحالي في sessionStorage، وكل شيء داخل shadow root.
 */
(function () {
  "use strict";
  if (window.__bayanChat) return;
  window.__bayanChat = true;

  var C = __BAYAN_CONFIG__;
  var ID_KEY = "bayan-chat-id";
  var LOG_KEY = "bayan-chat-log";
  var MAX_LOG = 40;

  // ── Storage, guarded: private windows and blocked storage must not break the chat
  function load(store, key) {
    try { return window[store].getItem(key); } catch (e) { return null; }
  }
  function save(store, key, value) {
    try { window[store].setItem(key, value); } catch (e) { /* ignore */ }
  }
  function drop(store, key) {
    try { window[store].removeItem(key); } catch (e) { /* ignore */ }
  }

  function newId() {
    var bytes = new Uint8Array(18);
    (window.crypto || window.msCrypto).getRandomValues(bytes);
    var out = "";
    for (var i = 0; i < bytes.length; i++) out += ("0" + bytes[i].toString(16)).slice(-2);
    return out;
  }
  function sessionId() {
    var id = load("localStorage", ID_KEY);
    if (!id || !/^[A-Za-z0-9_-]{16,64}$/.test(id)) {
      id = newId();
      save("localStorage", ID_KEY, id);
    }
    return id;
  }

  // ── Language: the page's language, matched to a supported code
  function pickLang(raw) {
    var l = String(raw || "en").toLowerCase();
    var i;
    for (i = 0; i < C.languages.length; i++) if (C.languages[i].toLowerCase() === l) return C.languages[i];
    var primary = l.split(/[-_]/)[0];
    for (i = 0; i < C.languages.length; i++) if (C.languages[i].toLowerCase().split("-")[0] === primary) return C.languages[i];
    return "en";
  }
  // لغة بلد الزائر (من الخادم) أولاً، ولغة الصفحة إن لم يكن للبلد لغة أو غيّر
  // الزائر لغة الصفحة / The visitor's country language (from the server) first,
  // and the page's language when the country has none or the visitor switches
  // the page's language
  var geoLang = null, pageTouched = false;
  function lang() {
    if (geoLang && !pageTouched) return geoLang;
    return pickLang(document.documentElement.lang || navigator.language);
  }
  function S(key) {
    var s = C.strings[lang()] || C.strings.en;
    return s[key] || C.strings.en[key] || "";
  }
  function isRtl() { return C.rtl.indexOf(lang()) !== -1; }

  // ── Rendering: text nodes only; links and **bold** built with DOM calls
  var TOKEN = /(https?:\/\/[^\s<>"'()\[\]]+)|\*\*([^*\n]+)\*\*/g;
  function renderText(el, text) {
    var lines = String(text).split("\n");
    for (var n = 0; n < lines.length; n++) {
      if (n) el.appendChild(document.createElement("br"));
      var line = lines[n], last = 0, m;
      TOKEN.lastIndex = 0;
      while ((m = TOKEN.exec(line))) {
        if (m.index > last) el.appendChild(document.createTextNode(line.slice(last, m.index)));
        if (m[1]) {
          var url = m[1].replace(/[.,;:!?،؛]+$/, "");
          var a = document.createElement("a");
          a.href = url;
          a.target = "_blank";
          a.rel = "noopener noreferrer nofollow";
          a.textContent = url;
          el.appendChild(a);
          if (url.length < m[1].length) el.appendChild(document.createTextNode(m[1].slice(url.length)));
        } else {
          var b = document.createElement("strong");
          b.textContent = m[2];
          el.appendChild(b);
        }
        last = m.index + m[0].length;
      }
      if (last < line.length) el.appendChild(document.createTextNode(line.slice(last)));
    }
  }

  var CSS = [
    ":host{all:initial;font-family:inherit}",
    "*{box-sizing:border-box;font-family:inherit}",
    ".wrap{--bg:#fcfaf5;--paper:#f3efe6;--ink:#1b1f1c;--muted:#6b6f68;--line:#e3dbcb;--accent:#3b7350;--accent-ink:#fff;--me:#e4efe6;",
    "position:fixed;bottom:calc(20px + var(--lift,0px));inset-inline-end:20px;z-index:2147483000;transition:bottom .2s;font-size:15px;line-height:1.55;color:var(--ink)}",
    "@media (prefers-color-scheme:dark){.wrap{--bg:#172926;--paper:#0f1715;--ink:#ecebe6;--muted:#9faea4;--line:#24403a;--accent:#8fd1a6;--accent-ink:#0f1a19;--me:#1d3226}}",
    ".bubble{width:56px;height:56px;border-radius:50%;border:0;background:var(--accent);color:var(--accent-ink);cursor:pointer;display:grid;place-items:center;box-shadow:0 6px 20px rgba(0,0,0,.22)}",
    ".bubble svg{width:26px;height:26px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}",
    ".bubble:focus-visible,button:focus-visible,textarea:focus-visible{outline:2px solid var(--accent);outline-offset:2px}",
    ".panel{position:absolute;bottom:72px;inset-inline-end:0;width:min(380px,calc(100vw - 24px));height:min(560px,calc(100vh - 110px - var(--lift,0px)));background:var(--bg);",
    "border:1px solid var(--line);border-radius:16px;box-shadow:0 18px 50px rgba(0,0,0,.25);display:flex;flex-direction:column;overflow:hidden}",
    ".panel[hidden]{display:none}",
    ".head{display:flex;align-items:center;gap:8px;padding:12px 14px;background:var(--accent);color:var(--accent-ink)}",
    ".head b{flex:1;font-size:15px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
    ".head button{background:transparent;border:1px solid rgba(255,255,255,.45);color:inherit;border-radius:8px;padding:3px 8px;font-size:12.5px;cursor:pointer}",
    ".log{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px;background:var(--paper)}",
    ".msg{max-width:88%;padding:9px 12px;border-radius:12px;white-space:normal;overflow-wrap:anywhere;font-size:14.5px}",
    ".bot{align-self:flex-start;background:var(--bg);border:1px solid var(--line)}",
    ".me{align-self:flex-end;background:var(--me)}",
    ".msg a{color:var(--accent);text-decoration:underline}",
    ".wait{align-self:flex-start;color:var(--muted);font-size:13px;font-style:italic}",
    ".form{display:flex;gap:8px;padding:10px;border-top:1px solid var(--line);background:var(--bg)}",
    "textarea{flex:1;resize:none;min-height:42px;max-height:120px;border:1px solid var(--line);border-radius:10px;padding:9px 10px;font-size:14.5px;background:var(--paper);color:var(--ink)}",
    ".send{border:0;border-radius:10px;padding:0 14px;background:var(--accent);color:var(--accent-ink);font-weight:600;cursor:pointer}",
    ".send:disabled{opacity:.55;cursor:default}",
    ".foot{padding:6px 12px 9px;font-size:11.5px;color:var(--muted);background:var(--bg);display:flex;gap:6px;flex-wrap:wrap}",
    ".foot a{color:var(--muted)}",
    "@media (max-width:480px){.wrap{bottom:calc(12px + var(--lift,0px));inset-inline-end:12px}.panel{bottom:66px}}",
    "@media print{.wrap{display:none}}"
  ].join("");

  var ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16v11H9l-5 4z"/><path d="M8 9.5h8M8 12.5h5"/></svg>';

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function mount() {
    var host = document.createElement("div");
    host.id = "bayan-chat";
    document.body.appendChild(host);
    var root = host.attachShadow ? host.attachShadow({ mode: "open" }) : host;
    var style = el("style");
    style.textContent = CSS;
    root.appendChild(style);

    var wrap = el("div", "wrap");
    var bubble = el("button", "bubble");
    bubble.type = "button";
    bubble.innerHTML = ICON;
    var panel = el("div", "panel");
    panel.hidden = true;
    panel.setAttribute("role", "dialog");

    var head = el("div", "head");
    var title = el("b");
    var fresh = el("button");
    fresh.type = "button";
    var close = el("button");
    close.type = "button";
    head.appendChild(title);
    head.appendChild(fresh);
    head.appendChild(close);

    var log = el("div", "log");
    log.setAttribute("aria-live", "polite");
    var form = el("form", "form");
    var input = el("textarea");
    input.rows = 1;
    input.maxLength = 600;
    var send = el("button", "send");
    send.type = "submit";
    form.appendChild(input);
    form.appendChild(send);
    var foot = el("div", "foot");
    var note = el("span");
    var privacy = el("a");
    privacy.href = C.privacy;
    privacy.target = "_blank";
    privacy.rel = "noopener noreferrer";
    foot.appendChild(note);
    foot.appendChild(privacy);

    panel.appendChild(head);
    panel.appendChild(log);
    panel.appendChild(form);
    panel.appendChild(foot);
    wrap.appendChild(panel);
    wrap.appendChild(bubble);
    root.appendChild(wrap);

    var thread = [];
    try { thread = JSON.parse(load("sessionStorage", LOG_KEY) || "[]") || []; } catch (e) { thread = []; }
    var busy = false;

    function texts() {
      wrap.dir = isRtl() ? "rtl" : "ltr";
      wrap.lang = lang();
      bubble.setAttribute("aria-label", S("open"));
      bubble.title = S("open");
      panel.setAttribute("aria-label", S("title"));
      title.textContent = S("title");
      fresh.textContent = S("new");
      close.textContent = S("close");
      close.setAttribute("aria-label", S("close"));
      input.placeholder = S("placeholder");
      input.setAttribute("aria-label", S("placeholder"));
      send.textContent = S("send");
      note.textContent = S("disclaimer");
      privacy.textContent = S("privacy");
    }

    function add(role, text, keep) {
      var m = el("div", "msg " + (role === "me" ? "me" : "bot"));
      m.dir = "auto";
      renderText(m, text);
      log.appendChild(m);
      log.scrollTop = log.scrollHeight;
      if (keep) {
        thread.push([role, text]);
        if (thread.length > MAX_LOG) thread = thread.slice(-MAX_LOG);
        save("sessionStorage", LOG_KEY, JSON.stringify(thread));
      }
    }

    function draw() {
      log.textContent = "";
      add("bot", S("intro"), false);
      for (var i = 0; i < thread.length; i++) add(thread[i][0], thread[i][1], false);
    }

    function open() {
      texts();
      draw();
      panel.hidden = false;
      bubble.setAttribute("aria-expanded", "true");
      setTimeout(function () { input.focus(); }, 30);
    }
    function hide() {
      panel.hidden = true;
      bubble.setAttribute("aria-expanded", "false");
      bubble.focus();
    }

    function post(message) {
      var ctl = window.AbortController ? new AbortController() : null;
      var timer = ctl ? setTimeout(function () { ctl.abort(); }, 120000) : null;
      return fetch(C.endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session: sessionId(), message: message, lang: lang() }),
        credentials: "omit",
        signal: ctl ? ctl.signal : undefined
      }).then(function (r) {
        if (timer) clearTimeout(timer);
        return r.json().catch(function () { return {}; }).then(function (data) {
          if (data && data.messages && data.messages.length) return data.messages;
          if (r.status === 503) return [S("unavailable")];
          if (!r.ok) return [S("error")];
          return [];
        });
      }, function () {
        if (timer) clearTimeout(timer);
        return [S("error")];
      });
    }

    function ask(text) {
      if (busy || !text) return;
      busy = true;
      send.disabled = true;
      add("me", text, true);
      var wait = el("div", "wait", S("thinking"));
      log.appendChild(wait);
      log.scrollTop = log.scrollHeight;
      post(text).then(function (messages) {
        wait.remove();
        for (var i = 0; i < messages.length; i++) add("bot", messages[i], true);
        busy = false;
        send.disabled = false;
        input.focus();
      });
    }

    bubble.addEventListener("click", function () { if (panel.hidden) open(); else hide(); });
    close.addEventListener("click", hide);
    fresh.addEventListener("click", function () {
      // يحذف المحادثة على الخادم ثم يبدأ معرّفاً جديداً / Deletes the conversation
      // on the server, then starts a new ID
      if (thread.length) post("/reset");
      drop("localStorage", ID_KEY);
      drop("sessionStorage", LOG_KEY);
      thread = [];
      draw();
      input.focus();
    });
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var text = input.value.trim();
      input.value = "";
      ask(text);
    });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event("submit", { cancelable: true }));
      }
    });
    wrap.addEventListener("keydown", function (e) { if (e.key === "Escape" && !panel.hidden) hide(); });

    texts();
    // لغة الصفحة قد تتغيّر دون إعادة تحميل (تطبيق صفحة واحدة) / The page language
    // may change without a reload (a single-page app)
    if (window.MutationObserver) {
      new MutationObserver(function () { pageTouched = true; texts(); if (!panel.hidden) draw(); })
        .observe(document.documentElement, { attributes: true, attributeFilter: ["lang"] });
    }

    if (C.geo && window.fetch) {
      fetch(C.geo, { credentials: "omit" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (!d || !d.lang || pageTouched || C.languages.indexOf(d.lang) < 0) return;
          var before = lang();
          geoLang = d.lang;
          if (lang() !== before) { texts(); if (!panel.hidden) draw(); }
        })
        .catch(function () {});
    }

    // لا تغطّي الفقاعة شريطاً ثابتاً أسفل الصفحة، مثل شريط الموافقة على الكوكيز:
    // ترتفع فوقه ما دام ظاهراً وتعود حين يختفي.
    // The bubble does not cover a bar fixed to the bottom of the page, such as a
    // cookie consent banner: it rises above it while it shows and drops back when
    // it goes.
    var lifted = 0, queued = false;
    function lift() {
      queued = false;
      if (!document.elementsFromPoint) return;
      var vh = window.innerHeight, r = bubble.getBoundingClientRect(), need = 0;
      var hits = document.elementsFromPoint(r.left + r.width / 2, Math.min(r.bottom + lifted - 4, vh - 1));
      for (var i = 0; i < hits.length; i++) {
        for (var n = hits[i]; n && n !== document.body && n !== document.documentElement; n = n.parentElement) {
          if (n === host) break;
          var st = getComputedStyle(n);
          if (st.position !== "fixed" && st.position !== "sticky") continue;
          var b = n.getBoundingClientRect();
          if (b.bottom >= vh - 2 && b.height < vh * 0.6 && st.visibility !== "hidden" &&
              st.pointerEvents !== "none" && parseFloat(st.opacity) > 0) {
            need = Math.max(need, Math.ceil(vh - b.top + 8));
          }
          break;
        }
      }
      if (need !== lifted) {
        lifted = need;
        wrap.style.setProperty("--lift", need + "px");
      }
    }
    function queue() {
      if (queued) return;
      queued = true;
      (window.requestAnimationFrame || setTimeout)(lift);
    }
    window.addEventListener("resize", queue);
    window.addEventListener("scroll", queue, { passive: true });
    document.addEventListener("transitionend", queue, true);
    document.addEventListener("animationend", queue, true);
    if (window.MutationObserver) {
      new MutationObserver(queue).observe(document.body, {
        childList: true, subtree: true, attributes: true, attributeFilter: ["class", "style", "hidden"]
      });
    }
    setInterval(queue, 2000);
    queue();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mount);
  else mount();
})();
