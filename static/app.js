// Rankloom web app. No framework, no build step. Every piece of user data reaches the page
// through textContent, never innerHTML, so nothing a user or a fetched page types can run here.
(() => {
  "use strict";

  const root = document.getElementById("app");
  const state = { user: null, tools: [], bySlug: {}, ai: false, shell: null };
  const channel = "BroadcastChannel" in window ? new BroadcastChannel("rankloom") : null;

  // ---------------------------------------------------------------- DOM helpers
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    setAttrs(el, attrs);
    append(el, kids);
    return el;
  }
  const SVGNS = "http://www.w3.org/2000/svg";
  function s(tag, attrs, ...kids) {
    const el = document.createElementNS(SVGNS, tag);
    setAttrs(el, attrs);
    append(el, kids);
    return el;
  }
  function setAttrs(el, attrs) {
    if (!attrs) return;
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
      else if (k === "class") el.setAttribute("class", v);
      else if (k === "text") el.textContent = v;
      else if (k === "value") el.value = v;
      else el.setAttribute(k, v === true ? "" : String(v));
    }
  }
  function append(el, kids) {
    for (const kid of kids.flat(Infinity)) {
      if (kid === null || kid === undefined || kid === false) continue;
      el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
  }
  // DOM append() writes null as the text "null"; conditional parts pass null when absent.
  function put(el, ...kids) { el.append(...kids.flat().filter((k) => k !== null && k !== undefined && k !== false)); return el; }
  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
  // Native append/replaceWith turn a null child into the text "null"; these skip it.
  function put(el, ...kids) { append(el, kids); return el; }
  function swap(el, ...kids) { el.replaceWith(...kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false)); }

  const ICONS = {
    overview: "M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z",
    settings: "M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6",
    external: "M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3",
    logout: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9",
    moon: "M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z",
    check: "M20 6L9 17l-5-5",
    alert: "M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4M12 17h.01",
    x: "M18 6L6 18M6 6l12 12",
    info: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 16v-4M12 8h.01",
    menu: "M3 12h18M3 6h18M3 18h18",
    git: "M6 3v12M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 9a9 9 0 0 1-9 9",
    shield: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
    download: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3",
    upload: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12",
    copy: "M20 9h-9a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2v-9a2 2 0 0 0-2-2zM5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1",
    print: "M6 9V2h12v7M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2M6 14h12v8H6z",
    chevron: "M9 18l6-6-6-6",
    trash: "M3 6h18M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2",
    "site-audit": "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.35-4.35",
    "ai-visibility": "M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z",
    "lead-finder": "M21 10c0 7-9 13-9 13S3 17 3 10a9 9 0 0 1 18 0zM12 13a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
    "search-performance": "M23 6l-9.5 9.5-5-5L1 18M17 6h6v6",
    "content-studio": "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M16 13H8M16 17H8M10 9H8",
    "client-reports": "M3 3v18h18M7 15l4-4 3 3 5-6",
    "job-radar": "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 18a6 6 0 1 0 0-12M12 12l7-7",
  };
  function icon(name) {
    return s("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": "2",
      "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" },
      s("path", { d: ICONS[name] || ICONS.info }));
  }
  function logo() {
    return s("svg", { viewBox: "0 0 32 32", "aria-hidden": "true" },
      s("rect", { width: 32, height: 32, rx: 8, fill: "#2a78d6" }),
      s("path", { d: "M8 22V10h7.5a4.5 4.5 0 0 1 0 9H12m3.5 0L22 24", fill: "none", stroke: "#fff",
        "stroke-width": "2.6", "stroke-linecap": "round", "stroke-linejoin": "round" }));
  }

  // ---------------------------------------------------------------- utilities
  let toastTimer = 0;
  function toast(msg) {
    const t = document.getElementById("toast");
    t.textContent = msg;
    t.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("show"), 3200);
  }
  function ago(ts) {
    if (!ts) return "never";
    const d = Math.max(0, Date.now() / 1000 - ts);
    if (d < 60) return "just now";
    if (d < 3600) return `${Math.floor(d / 60)} min ago`;
    if (d < 86400) return `${Math.floor(d / 3600)} h ago`;
    if (d < 86400 * 30) return `${Math.floor(d / 86400)} d ago`;
    return new Date(ts * 1000).toLocaleDateString();
  }
  function fmtDay(iso) {
    return new Date(iso + "T00:00:00").toLocaleDateString(undefined, { day: "numeric", month: "short" });
  }
  function initials(name) {
    return (name || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");
  }
  function save(key, val) { try { localStorage.setItem(key, val); } catch (e) { /* ignore */ } }
  function safeHref(u) { return /^https?:\/\//i.test(String(u || "")) ? String(u) : null; }
  function copyText(text) {
    if (navigator.clipboard) navigator.clipboard.writeText(text).then(() => toast("Copied"), () => toast("Could not copy"));
  }
  function download(name, text, type = "text/plain") {
    const a = h("a", { href: URL.createObjectURL(new Blob([text], { type })), download: name });
    document.body.append(a); a.click(); a.remove();
  }

  async function api(method, path, body) {
    const opts = { method, credentials: "same-origin", headers: { "X-Rankloom": "1" } };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    let res;
    try { res = await fetch(path, opts); }
    catch (e) { const err = new Error("The server could not be reached."); err.status = 0; throw err; }
    let data = {};
    try { data = await res.json(); } catch (e) { /* empty body */ }
    if (!res.ok) {
      const err = new Error(data.error || `Request failed (${res.status})`);
      err.status = res.status; err.data = data;
      throw err;
    }
    return data;
  }

  function readFile(file) {
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => resolve(String(r.result).split(",")[1] || "");
      r.onerror = () => reject(new Error(`Could not read ${file.name}`));
      r.readAsDataURL(file);
    });
  }

  // A form wired to an endpoint: disables while sending, puts field errors under the field.
  // Field types: text, url, email, password, textarea, select, hidden, file, dataset, client.
  function form({ fields, submit, onSubmit, extra, submitClass = "primary block", values = {} }) {
    const el = h("form", { novalidate: true });
    const errs = {};
    const inputs = {};
    for (const f of fields) {
      const id = `f-${f.name}-${Math.random().toString(36).slice(2, 7)}`;
      const preset = values[f.name] ?? f.value;
      let input;
      if (f.type === "hidden") {
        input = h("input", { type: "hidden", name: f.name, value: preset || "" });
        inputs[f.name] = input; el.append(input); continue;
      }
      if (f.type === "textarea") {
        input = h("textarea", { id, name: f.name, rows: 5, placeholder: f.placeholder || "", spellcheck: "false" });
        if (preset) input.value = preset;
      } else if (f.type === "select" || f.type === "dataset" || f.type === "client") {
        input = h("select", { id, name: f.name });
        for (const o of f.options || []) input.append(h("option", { value: o.value, text: o.label }));
        if (f.type !== "select") loadOptions(input, f.type, preset);
        else if (preset) input.value = preset;
      } else if (f.type === "file") {
        input = h("input", { id, name: f.name, type: "file", multiple: true, accept: f.accept || null });
      } else {
        input = h("input", { id, name: f.name, type: f.type === "url" ? "text" : (f.type || "text"),
          placeholder: f.placeholder || "", autocomplete: f.autocomplete || "off", value: preset,
          readonly: f.readonly, inputmode: f.type === "url" ? "url" : f.inputmode, maxlength: f.maxlength,
          class: f.class, spellcheck: "false" });
      }
      inputs[f.name] = input;
      errs[f.name] = h("div", { class: "err", hidden: true });
      el.append(h("div", { class: "field" },
        h("label", { for: id, text: f.label }), input,
        f.hint ? h("div", { class: "hint", text: f.hint }) : null, errs[f.name]));
    }
    const general = h("div", { class: "notice bad", hidden: true });
    const btn = h("button", { class: `btn ${submitClass}`, type: "submit" }, submit);
    if (extra) el.append(extra);
    el.append(general, btn);
    el.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      Object.values(errs).forEach((e) => { e.hidden = true; });
      Object.values(inputs).forEach((i) => i.removeAttribute("aria-invalid"));
      general.hidden = true;
      btn.disabled = true;
      const label = [...btn.childNodes];
      clear(btn).append(h("span", { class: "spinner" }), " Working…");
      try {
        const vals = {};
        for (const [k, i] of Object.entries(inputs)) {
          if (i.type === "file") vals[k] = await Promise.all([...i.files].map(async (f) => ({ name: f.name, data: await readFile(f) })));
          else vals[k] = i.value;
        }
        await onSubmit(vals, inputs);
      } catch (e) {
        const field = e.data && e.data.field;
        if (field && errs[field]) {
          errs[field].textContent = e.message; errs[field].hidden = false;
          inputs[field].setAttribute("aria-invalid", "true"); inputs[field].focus();
        } else {
          clear(general).append(icon("alert"), h("div", { text: e.message })); general.hidden = false;
        }
      } finally {
        btn.disabled = false; clear(btn).append(...label);
      }
    });
    el.inputs = inputs;
    el.general = general;
    return el;
  }

  async function loadOptions(select, kind, preset) {
    try {
      const d = await api("GET", `/api/options/${kind}`);
      clear(select);
      if (!d.options.length) {
        select.append(h("option", { value: "", text: kind === "dataset" ? "No reports imported yet" : "No clients yet" }));
        return;
      }
      for (const o of d.options) select.append(h("option", { value: o.value, text: o.label }));
      if (preset) select.value = preset;
    } catch (e) { select.append(h("option", { value: "", text: e.message })); }
  }

  // ---------------------------------------------------------------- routing
  const PUBLIC = new Set(["/login", "/register", "/forgot", "/reset", "/verify"]);

  function go(path, replace = false) {
    if (replace) history.replaceState({}, "", path); else history.pushState({}, "", path);
    render();
  }
  document.addEventListener("click", (ev) => {
    const a = ev.target.closest("a[data-link]");
    if (!a || ev.defaultPrevented || ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
    if (a.target === "_blank") return;
    ev.preventDefault();
    const url = new URL(a.href);
    if (url.pathname + url.search + url.hash === location.pathname + location.search + location.hash) return;
    go(url.pathname + url.search + url.hash);
  });
  window.addEventListener("popstate", render);

  // Open any tool in a window of its own, so several can sit side by side.
  function popOut(path) {
    const w = Math.min(1320, screen.availWidth - 40);
    const hgt = Math.min(900, screen.availHeight - 60);
    const win = window.open(path, "_blank", `popup=yes,width=${w},height=${hgt}`);
    if (win) win.opener = null;
    else toast("Your browser blocked the new window. Allow pop-ups for this site, or open the link with a middle click.");
  }
  function popBtn(path, label) {
    return h("button", { class: "pop", type: "button", title: `Open ${label} in a new window`,
      "aria-label": `Open ${label} in a new window`, onclick: (ev) => { ev.stopPropagation(); popOut(path); } }, icon("external"));
  }

  if (channel) {
    channel.onmessage = (ev) => {
      if (ev.data === "signed-out") { state.user = null; state.shell = null; go("/login", true); }
      if (ev.data === "signed-in" && !state.user) render();
    };
  }

  async function loadMe() {
    try {
      const me = await api("GET", "/api/me");
      state.user = me.user;
      return me;
    } catch (e) {
      state.user = null;
      return { user: null };
    }
  }

  function subOf(tool, slug) { return tool.subtools.find((x) => x.slug === slug); }

  async function render() {
    const path = location.pathname;
    if (path === "/" || path === "") { go(state.user ? "/app" : "/login", true); return; }
    if (PUBLIC.has(path)) {
      state.shell = null;
      if (path !== "/reset" && path !== "/verify") {
        const me = state.user ? { user: state.user } : await loadMe();
        if (me.user) { go("/app", true); return; }
      }
      return AUTH[path]();
    }
    const me = await loadMe();
    if (me.mfa_required) { go("/verify", true); return; }
    if (!me.user) { go(`/login?next=${encodeURIComponent(path + location.search + location.hash)}`, true); return; }
    if (!state.tools.length) {
      const t = await api("GET", "/api/tools");
      state.tools = t.tools; state.ai = t.ai;
      state.bySlug = Object.fromEntries(t.tools.map((x) => [x.slug, x]));
    }
    const m = path.match(/^\/t\/([a-z0-9-]+)(?:\/([a-z0-9-]+))?$/);
    const tool = m && state.bySlug[m[1]];
    const sub = tool && m[2] ? subOf(tool, m[2]) : null;
    const main = shell(path, tool);
    if (path === "/app") return overview(main);
    if (path === "/settings") return settings(main);
    if (tool && !m[2]) return toolHome(main, tool);
    if (tool && sub) return subPage(main, tool, sub);
    notFound(main);
  }

  // ---------------------------------------------------------------- shell
  function shell(path, activeTool) {
    if (!state.shell) {
      const nav = h("ul", { class: "nav tools", "aria-label": "Tools" });
      for (const t of state.tools) {
        const href = `/t/${t.slug}`;
        const subs = h("ul", { class: "subnav", "data-tool": t.slug, "aria-label": `${t.name} sub-tools` },
          t.subtools.map((x) => h("li", null, h("div", { class: "row" },
            h("a", { class: "item sub", href: `${href}/${x.slug}`, "data-link": true, "data-path": `${href}/${x.slug}`, title: x.tagline },
              h("span", { text: x.name })),
            popBtn(`${href}/${x.slug}`, x.name)))));
        nav.append(h("li", { class: "tool", "data-tool": t.slug },
          h("div", { class: "row" },
            h("a", { class: "item", href, "data-link": true, "data-path": href, title: t.tagline },
              icon(t.slug), h("span", { text: t.name })),
            popBtn(href, t.name)), subs));
      }
      const top = h("ul", { class: "nav" },
        h("li", null, h("a", { class: "item", href: "/app", "data-link": true, "data-path": "/app" },
          icon("overview"), h("span", { text: "Overview" }))));
      const foot = h("div", { class: "sidebar-foot" },
        h("ul", { class: "nav" }, h("li", null, h("a", { class: "item", href: "/settings", "data-link": true,
          "data-path": "/settings" }, icon("settings"), h("span", { text: "Settings" })))),
        h("div", { class: "who" }, h("div", { class: "avatar", text: initials(state.user.name) }),
          h("div", { class: "meta" }, h("div", { text: state.user.name }),
            h("div", { class: "email", text: state.user.email }))),
        h("div", { class: "foot-actions" },
          h("button", { class: "btn ghost small", type: "button", onclick: toggleTheme }, icon("moon"), h("span", { text: "Theme" })),
          h("button", { class: "btn ghost small", type: "button", onclick: signOut }, icon("logout"), h("span", { text: "Sign out" }))));
      const sidebar = h("aside", { class: "sidebar", id: "sidebar", "aria-label": "Main" },
        h("a", { class: "brand", href: "/app", "data-link": true }, logo(), "Rankloom"),
        top, h("div", { class: "nav-label", text: "Tools" }), nav, foot);
      const main = h("main", { class: "main", id: "main" });
      const wrap = h("div", { class: "shell" });
      const topbar = h("div", { class: "topbar" },
        h("button", { class: "btn ghost icon-btn menu-btn", type: "button", "aria-label": "Open menu",
          "aria-expanded": "false", "aria-controls": "sidebar",
          onclick: () => wrap.classList.add("nav-open") }, icon("menu")),
        h("a", { class: "brand", href: "/app", "data-link": true }, logo(), "Rankloom"));
      const scrim = h("div", { class: "scrim", hidden: true });
      wrap.addEventListener("click", (ev) => {
        if (ev.target.closest(".sidebar a[data-link]") || ev.target === scrim) wrap.classList.remove("nav-open");
      });
      new MutationObserver(() => {
        const open = wrap.classList.contains("nav-open");
        scrim.hidden = !open;
        topbar.querySelector(".menu-btn").setAttribute("aria-expanded", String(open));
      }).observe(wrap, { attributes: true, attributeFilter: ["class"] });
      document.addEventListener("keydown", (ev) => {
        if (ev.key === "Escape" && wrap.classList.contains("nav-open")) {
          wrap.classList.remove("nav-open");
          topbar.querySelector(".menu-btn").focus();
        }
      });
      wrap.append(sidebar, scrim, h("div", null, topbar, main));
      clear(root).append(wrap);
      state.shell = { wrap, main };
    }
    for (const a of state.shell.wrap.querySelectorAll("a[data-path]")) {
      if (a.dataset.path === path) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    }
    for (const li of state.shell.wrap.querySelectorAll("li.tool")) {
      li.classList.toggle("open", !!activeTool && li.dataset.tool === activeTool.slug);
    }
    window.scrollTo(0, 0);
    return clear(state.shell.main);
  }

  function toggleTheme() {
    const rootEl = document.documentElement;
    const dark = rootEl.dataset.theme ? rootEl.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    rootEl.dataset.theme = dark ? "light" : "dark";
    save("rl-theme", rootEl.dataset.theme);
  }

  async function signOut() {
    try { await api("POST", "/api/auth/logout"); } catch (e) { /* signed out either way */ }
    state.user = null; state.shell = null; state.tools = [];
    if (channel) channel.postMessage("signed-out");
    go("/login", true);
  }

  function page(main, title, lede, actions, crumb) {
    document.title = `${title} · Rankloom`;
    const head = h("div", { class: "page-head" },
      h("div", null, crumb || null, h("h1", { text: title }), lede ? h("p", { class: "lede", text: lede }) : null),
      actions ? h("div", { class: "head-actions" }, actions) : null);
    const body = h("div", { class: "page" }, head);
    main.append(body);
    return body;
  }

  function notFound(main) {
    const p = page(main, "Page not found", "That address does not match a page in Rankloom.");
    p.append(h("a", { class: "btn", href: "/app", "data-link": true, text: "Back to overview" }));
  }

  function tabs(p, list, initial, onSelect) {
    const bar = h("div", { class: "tabs", role: "tablist" });
    const panel = h("div", { role: "tabpanel", id: "panel" });
    p.append(bar, panel);
    const select = (key, push = true) => {
      for (const b of bar.children) b.setAttribute("aria-selected", String(b.dataset.key === key));
      if (push) history.replaceState({}, "", `${location.pathname}${location.search}#${key}`);
      clear(panel);
      onSelect(key, panel);
    };
    for (const [key, label] of list) {
      bar.append(h("button", { role: "tab", type: "button", "data-key": key, "aria-controls": "panel", text: label, onclick: () => select(key) }));
    }
    const fromHash = location.hash.slice(1);
    select(list.some(([k]) => k === fromHash) ? fromHash : initial, false);
  }

  // ---------------------------------------------------------------- charts
  const tip = document.getElementById("tip");
  function showTip(ev, lines) {
    clear(tip);
    lines.forEach((l, i) => tip.append(i ? h("div", { text: l }) : h("strong", { text: l })));
    tip.hidden = false;
    const r = tip.getBoundingClientRect();
    let x = ev.clientX + 12, y = ev.clientY - r.height - 10;
    if (x + r.width > innerWidth - 8) x = ev.clientX - r.width - 12;
    if (y < 8) y = ev.clientY + 16;
    tip.style.left = `${x}px`; tip.style.top = `${y}px`;
  }
  function hideTip() { tip.hidden = true; }

  function niceMax(v) {
    if (v <= 4) return 4;
    const p = 10 ** Math.floor(Math.log10(v));
    for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
    return 10 * p;
  }

  function barChart(points, { unit, alt = false, label }) {
    const box = h("div", { class: "chart-box" });
    const total = points.reduce((a, p) => a + p.value, 0);
    if (!total) {
      box.append(h("div", { class: "chart-empty", text: `No ${unit} in the last ${points.length} days yet.` }));
      return box;
    }
    const svg = s("svg", { class: "chart", role: "img", "aria-label": label });
    box.append(svg, dataTable(points.map((p) => [fmtDay(p.day), p.value]), ["Day", unit]));
    const draw = () => {
      const W = svg.clientWidth || 600, H = 180, L = 28, B = 22, T = 8;
      clear(svg); svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
      const max = niceMax(Math.max(...points.map((p) => p.value)));
      for (let i = 0; i <= 2; i++) {
        const y = T + (H - B - T) * (1 - i / 2);
        svg.append(s("line", { class: "gridline", x1: L, x2: W, y1: y, y2: y }),
          s("text", { class: "axis", x: L - 6, y: y + 4, "text-anchor": "end" }, String(Math.round(max * i / 2))));
      }
      const slot = (W - L) / points.length;
      const bw = Math.max(4, Math.min(28, slot - 6));
      points.forEach((p, i) => {
        const x = L + slot * i + (slot - bw) / 2;
        const base = H - B;
        const hh = (base - T) * (p.value / max);
        // Count back from today so the newest day is always labelled and labels never collide.
        if ((points.length - 1 - i) % Math.ceil(points.length / 7) === 0) {
          const last = i === points.length - 1;
          svg.append(s("text", { class: "axis", x: last ? Math.min(x + bw, W - 2) : x + bw / 2, y: H - 6,
            "text-anchor": last ? "end" : "middle" }, fmtDay(p.day)));
        }
        let bar = null;
        if (p.value > 0) {
          const r = Math.min(4, hh, bw / 2), y = base - hh;
          bar = s("path", { class: alt ? "bar alt" : "bar",
            d: `M${x},${base}V${y + r}Q${x},${y} ${x + r},${y}H${x + bw - r}Q${x + bw},${y} ${x + bw},${y + r}V${base}Z` });
        }
        const hit = s("rect", { class: "hit", x: L + slot * i, y: T, width: slot, height: base - T });
        hit.addEventListener("mousemove", (ev) => { showTip(ev, [fmtDay(p.day), `${p.value} ${unit}`]); if (bar) bar.classList.add("hover"); });
        hit.addEventListener("mouseleave", () => { hideTip(); if (bar) bar.classList.remove("hover"); });
        if (bar) svg.append(bar);
        svg.append(hit);
      });
    };
    requestAnimationFrame(draw);
    if ("ResizeObserver" in window) new ResizeObserver(() => draw()).observe(box);
    return box;
  }

  function lineChart(points, { label }) {
    const box = h("div", { class: "chart-box" });
    const svg = s("svg", { class: "chart", role: "img", "aria-label": label });
    box.append(svg, dataTable(points.map((p) => [new Date(p.created_at * 1000).toLocaleString(), p.name || "", p.score]), ["Run", "Sub-tool", "Score"]));
    const draw = () => {
      const W = svg.clientWidth || 600, H = 180, L = 28, R = 10, B = 14, T = 10;
      clear(svg); svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
      for (const v of [0, 50, 100]) {
        const y = T + (H - B - T) * (1 - v / 100);
        svg.append(s("line", { class: "gridline", x1: L, x2: W - R, y1: y, y2: y }),
          s("text", { class: "axis", x: L - 6, y: y + 4, "text-anchor": "end" }, String(v)));
      }
      const xs = (i) => points.length === 1 ? (L + W - R) / 2 : L + 8 + (W - R - L - 16) * (i / (points.length - 1));
      const ys = (v) => T + (H - B - T) * (1 - v / 100);
      if (points.length > 1) svg.append(s("polyline", { class: "line", points: points.map((p, i) => `${xs(i)},${ys(p.score)}`).join(" ") }));
      points.forEach((p, i) => {
        const dot = s("circle", { class: "dot", cx: xs(i), cy: ys(p.score), r: 4.5 });
        const hit = s("circle", { class: "hit", cx: xs(i), cy: ys(p.score), r: 14 });
        hit.addEventListener("mousemove", (ev) => showTip(ev, [`${p.score} / 100`, p.name || "", new Date(p.created_at * 1000).toLocaleString(), p.summary]));
        hit.addEventListener("mouseleave", hideTip);
        svg.append(dot, hit);
      });
    };
    requestAnimationFrame(draw);
    if ("ResizeObserver" in window) new ResizeObserver(() => draw()).observe(box);
    return box;
  }

  function dataTable(rows, head) {
    return h("details", { class: "as-table" }, h("summary", { text: "Show as a table" }),
      h("table", { class: "table" },
        h("thead", null, h("tr", null, head.map((c, i) => h("th", { class: i === head.length - 1 ? "num" : null, text: c })))),
        h("tbody", null, rows.map((r) => h("tr", null, r.map((c, i) => h("td", { class: i === r.length - 1 ? "num" : null, text: String(c) })))))));
  }

  function tile(k, v, sub) {
    return h("div", { class: "tile" }, h("div", { class: "k", text: k }), h("div", { class: "v", text: v }),
      sub ? h("div", { class: "s", text: sub }) : null);
  }
  function subStatus(sub) {
    if (sub.kind === "page") return h("span", { class: "pill", text: "Workspace" });
    return sub.status === "live"
      ? h("span", { class: "pill live" }, icon("check"), "Live")
      : h("span", { class: "pill building" }, icon("info"), "Needs AI engine");
  }
  const STATUS = { pass: ["check", "Pass"], warn: ["alert", "Warning"], fail: ["x", "Fail"] };
  function badge(k, text) { return h("span", { class: `status ${k}` }, icon(STATUS[k][0]), text || STATUS[k][1]); }

  // ---------------------------------------------------------------- result view
  function scoreRing(score) {
    const C = 2 * Math.PI * 34;
    return s("svg", { class: "ring", viewBox: "0 0 84 84", role: "img", "aria-label": `Score ${score} out of 100` },
      s("circle", { class: "track", cx: 42, cy: 42, r: 34, fill: "none", "stroke-width": 8 }),
      s("circle", { class: "bar", cx: 42, cy: 42, r: 34, fill: "none", "stroke-width": 8,
        "stroke-dasharray": C, "stroke-dashoffset": C * (1 - score / 100), transform: "rotate(-90 42 42)" }),
      s("text", { x: 42, y: 50, "text-anchor": "middle" }, String(score)));
  }

  function cell(c) {
    if (c === null || c === undefined) return "";
    if (typeof c !== "object") return String(c);
    if (c.status) return badge(c.status, c.text);
    if (c.route) return h("a", { href: c.route, "data-link": true, text: c.text });
    const href = safeHref(c.href);
    return href ? h("a", { href, target: "_blank", rel: "noopener noreferrer", text: c.text }) : String(c.text || "");
  }

  function block(b) {
    const head = h("div", { class: "card-head" }, h("h2", { text: b.title }), b.note ? h("p", { text: b.note }) : null);
    const card = h("div", { class: "card" }, head);
    if (b.type === "checks") {
      card.append(h("ul", { class: "checks" }, b.items.map((c) => h("li", null, badge(c.status),
        h("div", null, h("div", { class: "label", text: c.label }), h("div", { class: "detail", text: c.detail }),
          c.fix ? h("div", { class: "fix" }, h("b", { text: "Fix: " }), c.fix) : null)))));
    } else if (b.type === "facts") {
      card.append(h("div", { class: "facts" }, b.items.map(([k, v]) => h("div", { title: v },
        h("div", { class: "k", text: k }), h("div", { class: "v", text: v })))));
    } else if (b.type === "table") {
      if (!b.rows.length) card.append(h("p", { class: "muted", text: "Nothing here." }));
      else card.append(h("div", { class: "table-wrap" }, h("table", { class: "table" },
        h("thead", null, h("tr", null, b.columns.map((c) => h("th", { text: c })))),
        h("tbody", null, b.rows.map((r) => h("tr", null, r.map((c) => h("td", { class: typeof c === "number" ? "num" : null }, cell(c)))))))));
    } else if (b.type === "list") {
      card.append(h("ul", { class: "plain" }, b.items.map((x) => h("li", { text: x }))),
        h("div", { class: "head-actions mt" }, h("button", { class: "btn small", type: "button", onclick: () => copyText(b.items.join("\n")) }, icon("copy"), "Copy list")));
    } else if (b.type === "text") {
      card.append(h("div", { class: "prose" }, b.text.split(/\n{2,}/).map((para) => h("p", { text: para }))),
        h("div", { class: "head-actions mt" }, h("button", { class: "btn small", type: "button", onclick: () => copyText(b.text) }, icon("copy"), "Copy"),
          h("button", { class: "btn small", type: "button", onclick: () => download("draft.md", b.text, "text/markdown") }, icon("download"), "Download")));
    } else if (b.type === "drafts") {
      card.append(h("div", { class: "drafts" }, b.items.map((d) => h("div", { class: "draft" },
        h("div", { class: "row-between" }, h("h3", { text: d.label }),
          h("button", { class: "btn small", type: "button", onclick: () => copyText(d.text) }, icon("copy"), "Copy")),
        h("pre", { class: "draft-text", text: d.text })))));
    }
    return card;
  }

  function viewResult(output, run) {
    const v = output.view;
    const wrap = h("div", { class: "result" });
    if (!v) { wrap.append(h("pre", { class: "card mono", text: JSON.stringify(output, null, 2) })); return wrap; }
    const hd = v.headline;
    const c = hd.counts;
    wrap.append(h("div", { class: "card" }, h("div", { class: "score" },
      typeof hd.score === "number" ? scoreRing(hd.score) : null,
      h("div", { class: "grow" }, h("h2", { text: hd.title }),
        h("p", { class: "muted", text: [hd.subtitle, run && run.created_at ? `run ${ago(run.created_at)}` : ""].filter(Boolean).join(" · ") }),
        c ? h("div", { class: "counts" }, badge("fail", `${c.fail} fail`), badge("warn", `${c.warn} warning`), badge("pass", `${c.pass} pass`)) : null))));
    for (const b of v.blocks) wrap.append(block(b));
    return wrap;
  }

  // ---------------------------------------------------------------- overview
  async function overview(main) {
    const first = (state.user.name || "").split(" ")[0];
    const p = page(main, `Welcome, ${first}`, `${state.tools.length} tools, each with its own sub-tools. Open any of them here, or in a window of its own to use several side by side.`);
    const body = h("div", { class: "loading", text: "Loading your workspace…" });
    p.append(body);
    let d;
    try { d = await api("GET", "/api/dashboard"); } catch (e) { clear(body).append(e.message); return; }
    const runs = d.tools.reduce((a, t) => a + t.runs, 0);
    const subs = state.tools.reduce((a, t) => a + t.subtools.length, 0);
    swap(body,
      d.ai ? null : h("div", { class: "notice" }, icon("info"), h("div", null,
        h("strong", { text: "Answer Check and Draft Writer need an AI engine. " }),
        "Everything else runs now. Set one up on the server to switch those two on.")),
      h("div", { class: "grid tiles" },
        tile("Tools", `${state.tools.length}`, `${subs} sub-tools`),
        tile("Runs", String(runs), "all time"),
        tile("Leads", String(d.leads), "in Lead List"),
        tile("Clients", String(d.clients), "in Client Reports")),
      h("div", { class: "grid two" },
        h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "Runs per day" }), h("p", { text: "Last 14 days, all tools" })),
          barChart(d.daily.map((x) => ({ day: x.day, value: x.runs })), { unit: "runs", label: "Runs per day over the last 14 days" })),
        h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "Tool visits per day" }), h("p", { text: "Last 14 days, all tools" })),
          barChart(d.daily.map((x) => ({ day: x.day, value: x.opens })), { unit: "visits", alt: true, label: "Tool visits per day over the last 14 days" }))),
      h("div", { class: "card" },
        h("div", { class: "card-head" }, h("h2", { text: "Your tools" }), h("p", { text: "Click a name to open it here; the button opens a new window" })),
        h("div", { class: "table-wrap" }, h("table", { class: "table" },
          h("thead", null, h("tr", null, h("th", { text: "Tool" }), h("th", { text: "Sub-tools" }), h("th", { class: "num", text: "Visits" }),
            h("th", { class: "num", text: "Runs" }), h("th", { text: "Last used" }), h("th", null, h("span", { class: "sr-only", text: "Open" })))),
          h("tbody", null, d.tools.map((t) => {
            const meta = state.bySlug[t.slug];
            return h("tr", null,
              h("td", null, h("a", { href: `/t/${t.slug}`, "data-link": true, text: t.name }), h("div", { class: "muted", text: meta.tagline })),
              h("td", null, h("div", { class: "sub-links" }, meta.subtools.map((x) => h("a", { href: `/t/${t.slug}/${x.slug}`, "data-link": true, text: x.name })))),
              h("td", { class: "num", text: String(t.opens) }),
              h("td", { class: "num", text: String(t.runs) }),
              h("td", { class: "muted", text: ago(t.last) }),
              h("td", { class: "num" }, h("button", { class: "btn small ghost", type: "button", title: `Open ${t.name} in a new window`,
                onclick: () => popOut(`/t/${t.slug}`) }, icon("external"), "New window")));
          }))))),
      recentCard(d.recent));
  }

  function runLink(r) { return `/t/${r.tool}/${r.subtool}?run=${r.id}#run`; }
  function subName(tool, slug) { const t = state.bySlug[tool]; const x = t && subOf(t, slug); return x ? x.name : slug; }

  function recentCard(recent) {
    return h("div", { class: "card" },
      h("div", { class: "card-head" }, h("h2", { text: "Recent runs" })),
      recent.length ? h("div", { class: "table-wrap" }, h("table", { class: "table" },
        h("tbody", null, recent.map((r) => h("tr", { class: "click", onclick: () => go(runLink(r)) },
          h("td", { text: subName(r.tool, r.subtool) }),
          h("td", null, r.status === "error" ? badge("fail", "Failed") : null, " ", r.summary),
          h("td", { class: "num", text: r.score === null ? "" : `${r.score}/100` }),
          h("td", { class: "muted", text: ago(r.created_at) })))))) :
        h("p", { class: "muted" }, "No runs yet. Start with ", h("a", { href: "/t/site-audit/page", "data-link": true, text: "Page Audit" }), "."));
  }

  // ---------------------------------------------------------------- tool home
  function toolHome(main, tool) {
    api("POST", "/api/events", { tool: tool.slug, kind: "open" }).catch(() => {});
    const p = page(main, tool.name, tool.tagline, [
      h("button", { class: "btn small", type: "button", onclick: () => popOut(location.pathname + location.hash) }, icon("external"), "Open in new window")]);
    tabs(p, [["tools", "Sub-tools"], ["dashboard", "Dashboard"], ["about", "About"]], "tools", (key, panel) => {
      if (key === "tools") {
        put(panel, h("div", { class: "subgrid" }, tool.subtools.map((x) => h("div", { class: "card subcard" },
          h("div", { class: "row-between" }, h("h2", null, h("a", { href: `/t/${tool.slug}/${x.slug}`, "data-link": true, text: x.name })), subStatus(x)),
          h("p", { class: "muted", text: x.tagline }),
          h("div", { class: "head-actions mt" },
            h("a", { class: "btn small primary", href: `/t/${tool.slug}/${x.slug}`, "data-link": true, text: "Open" }),
            h("button", { class: "btn small", type: "button", onclick: () => popOut(`/t/${tool.slug}/${x.slug}`) }, icon("external"), "New window"))))));
      } else if (key === "dashboard") dashboardPanel(panel, tool);
      else aboutTool(panel, tool);
    });
  }

  function aboutTool(panel, tool) {
    put(panel, h("div", { class: "card about" }, h("h2", { text: `What ${tool.name} does` }), h("p", { class: "mt", text: tool.about })));
    for (const x of tool.subtools) put(panel, aboutCard(x));
  }
  function aboutCard(x) {
    return h("div", { class: "card about" },
      h("div", { class: "row-between" }, h("h2", { text: x.name }), subStatus(x)),
      h("p", { class: "mt", text: x.about }),
      h("ul", { class: "checklist" }, x.does.map((d) => h("li", null, icon("check"), h("span", { text: d })))),
      h("div", { class: "io" },
        h("div", null, h("div", { class: "k", text: "You give it" }), h("div", { text: x.input })),
        h("div", null, h("div", { class: "k", text: "You get back" }), h("div", { text: x.output }))));
  }

  async function dashboardPanel(panel, tool) {
    const body = h("div", { class: "loading", text: "Loading…" });
    put(panel, body);
    let st, runs;
    try { [st, runs] = await Promise.all([api("GET", `/api/tools/${tool.slug}/stats`), api("GET", `/api/tools/${tool.slug}/runs`)]); }
    catch (e) { clear(body).append(e.message); return; }
    const rate = st.runs ? `${Math.round((100 * st.ok) / st.runs)}%` : "—";
    const scores = st.scores.map((x) => ({ ...x, name: subName(tool.slug, x.subtool) }));
    swap(body,
      h("div", { class: "grid tiles" },
        tile("Visits", String(st.opens), "times opened"),
        tile("Runs", String(st.runs), st.last_run ? `last ${ago(st.last_run)}` : "none yet"),
        tile("Succeeded", rate, st.errors ? `${st.errors} failed` : "no failures"),
        tile("Average time", st.avg_ms === null ? "—" : `${(st.avg_ms / 1000).toFixed(1)} s`, "per run")),
      h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "By sub-tool" })),
        h("div", { class: "table-wrap" }, h("table", { class: "table" },
          h("thead", null, h("tr", null, h("th", { text: "Sub-tool" }), h("th", { class: "num", text: "Runs" }), h("th", { class: "num", text: "Succeeded" }),
            h("th", { class: "num", text: "Average score" }), h("th", { text: "Last run" }))),
          h("tbody", null, st.subtools.map((x) => h("tr", null,
            h("td", null, h("a", { href: `/t/${tool.slug}/${x.slug}`, "data-link": true, text: x.name })),
            h("td", { class: "num", text: String(x.runs) }), h("td", { class: "num", text: String(x.ok) }),
            h("td", { class: "num", text: x.avg_score === null ? "—" : String(x.avg_score) }),
            h("td", { class: "muted", text: ago(x.last) }))))))),
      h("div", { class: "grid two" },
        h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "Runs per day" }), h("p", { text: "Last 14 days" })),
          barChart(st.daily.map((x) => ({ day: x.day, value: x.runs })), { unit: "runs", label: `${tool.name} runs per day` })),
        h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "Visits per day" }), h("p", { text: "Last 14 days" })),
          barChart(st.daily.map((x) => ({ day: x.day, value: x.opens })), { unit: "visits", alt: true, label: `${tool.name} visits per day` }))),
      // One trend per sub-tool: a Page Audit score and a Local SEO score measure different
      // things, and joining them with one line drew a decline that never happened.
      [...new Set(scores.map((x) => x.subtool))].map((subtool) => {
        const own = scores.filter((x) => x.subtool === subtool);
        return h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: `${subName(tool.slug, subtool)}: score over your runs` }),
          h("p", { text: "Out of 100, oldest on the left" })), lineChart(own, { label: `${subName(tool.slug, subtool)} score over recent runs` }));
      }),
      historyCard(tool, runs.runs, true));
  }

  function historyCard(tool, runs, withSub) {
    return h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "Run history" }), h("p", { text: "Click a run to open its result" })),
      runs.length ? h("div", { class: "table-wrap" }, h("table", { class: "table" },
        h("thead", null, h("tr", null, h("th", { text: "When" }), withSub ? h("th", { text: "Sub-tool" }) : null, h("th", { text: "Result" }),
          h("th", { class: "num", text: "Score" }), h("th", { class: "num", text: "Time" }))),
        h("tbody", null, runs.map((r) => h("tr", { class: "click", onclick: () => go(runLink({ ...r, tool: tool.slug })) },
          h("td", { class: "muted", text: ago(r.created_at) }),
          withSub ? h("td", { text: subName(tool.slug, r.subtool) }) : null,
          h("td", null, r.status === "error" ? badge("fail", "Failed") : null, " ", r.summary),
          h("td", { class: "num", text: r.score === null ? "" : String(r.score) }),
          h("td", { class: "num nowrap", text: `${(r.duration_ms / 1000).toFixed(1)} s` })))))) :
        h("p", { class: "muted", text: "No runs yet." }));
  }

  // ---------------------------------------------------------------- sub-tool page
  function subPage(main, tool, sub) {
    api("POST", "/api/events", { tool: tool.slug, subtool: sub.slug, kind: "open" }).catch(() => {});
    const crumb = h("div", { class: "crumb" }, h("a", { href: `/t/${tool.slug}`, "data-link": true, text: tool.name }), icon("chevron"));
    const p = page(main, sub.name, sub.tagline, [subStatus(sub),
      h("button", { class: "btn small", type: "button", onclick: () => popOut(location.pathname + location.search + location.hash) }, icon("external"), "Open in new window")], crumb);
    const first = sub.kind === "page" ? "workspace" : "run";
    const list = sub.kind === "page" ? [["workspace", sub.name], ["about", "About"]] : [["run", "Run"], ["history", "History"], ["about", "About"]];
    tabs(p, list, first, (key, panel) => {
      if (key === "run") runPanel(panel, tool, sub);
      else if (key === "workspace") (PAGES[`${tool.slug}/${sub.slug}`] || notConnected)(panel);
      else if (key === "history") subHistory(panel, tool, sub);
      else put(panel, aboutCard(sub));
    });
  }

  async function subHistory(panel, tool, sub) {
    const body = h("div", { class: "loading", text: "Loading…" });
    put(panel, body);
    try {
      const d = await api("GET", `/api/tools/${tool.slug}/runs`);
      swap(body, historyCard(tool, d.runs.filter((r) => r.subtool === sub.slug), false));
    } catch (e) { clear(body).append(e.message); }
  }

  async function runPanel(panel, tool, sub) {
    if (sub.status === "needs-ai") {
      put(panel, h("div", { class: "notice warn" }, icon("alert"), h("div", null,
        h("strong", { text: `${sub.name} needs an AI engine. ` },),
        "Set one up on the server (see the README: RANKLOOM_AI). Until then this form shows what it will take.")));
    }
    const card = h("div", { class: "card" });
    const result = h("div");
    put(panel, card, result);
    const params = new URLSearchParams(location.search);
    const values = {};
    for (const f of sub.fields) if (params.get(f.name)) values[f.name] = params.get(f.name);
    if (values.lead) {
      try {
        const d = await api("GET", "/api/leads");
        const lead = d.leads.find((x) => String(x.id) === values.lead);
        if (lead) {
          values.business = values.business || lead.name;
          values.site = values.site || lead.website;
          card.append(h("div", { class: "notice" }, icon("info"), h("div", null, "Writing to lead ", h("strong", { text: lead.name }), lead.city ? ` in ${lead.city}` : "")));
        }
      } catch (e) { /* the form still works */ }
    }
    const f = form({
      fields: sub.fields, values, submitClass: "primary",
      submit: sub.status === "live" ? h("span", null, "Run ", sub.name) : "Needs an AI engine",
      onSubmit: async (vals) => {
        clear(result).append(h("div", { class: "card loading" }, h("span", { class: "spinner" }), ` Running ${sub.name}…`));
        try {
          const r = await api("POST", `/api/tools/${tool.slug}/${sub.slug}/run`, { fields: vals });
          showResult(result, r);
        } catch (e) {
          clear(result);
          if (e.data && e.data.output) { showResult(result, e.data); return; }
          throw e;
        }
      },
    });
    if (sub.status !== "live") f.querySelector("button[type=submit]").disabled = true;
    card.append(h("div", { class: "card-head" }, h("h2", { text: sub.name }), h("p", { text: sub.input })), f);
    const want = params.get("run");
    if (want) {
      try {
        const r = await api("GET", `/api/runs/${encodeURIComponent(want)}`);
        if (r.tool === tool.slug && r.subtool === sub.slug) {
          for (const [k, v] of Object.entries(r.input)) if (f.inputs[k] && f.inputs[k].type !== "file" && typeof v === "string") f.inputs[k].value = v;
          showResult(result, r);
        }
      } catch (e) { /* stale link: just show the form */ }
    }
  }

  function showResult(result, r) {
    clear(result);
    if (r.status === "error") {
      result.append(h("div", { class: "notice bad" }, icon("alert"), h("div", { text: r.summary })));
      return;
    }
    const isReport = r.tool === "client-reports";
    if (isReport) {
      result.append(h("div", { class: "head-actions report-actions" },
        h("button", { class: "btn primary", type: "button", onclick: () => window.print() }, icon("print"), "Print or save as PDF")));
    }
    const v = viewResult(r.output, r);
    if (isReport) v.classList.add("report");
    result.append(v);
  }

  // ---------------------------------------------------------------- Lead List
  async function leadList(panel) {
    const body = h("div", { class: "loading", text: "Loading leads…" });
    put(panel, body);
    let d;
    try { d = await api("GET", "/api/leads"); } catch (e) { clear(body).append(e.message); return; }
    const filter = h("select", { "aria-label": "Status" }, h("option", { value: "", text: "All statuses" }),
      d.statuses.map((x) => h("option", { value: x, text: x[0].toUpperCase() + x.slice(1) })));
    const search = h("input", { type: "search", placeholder: "Search name, city or website", "aria-label": "Search leads" });
    const fileInput = h("input", { type: "file", accept: ".csv", hidden: true });
    fileInput.addEventListener("change", async () => {
      const file = fileInput.files[0];
      if (!file) return;
      try {
        const text = await file.text();
        const r = await api("POST", "/api/leads/import", { csv: text });
        toast(`Imported ${r.added} lead(s)` + (r.skipped ? `, skipped ${r.skipped} without a name` : ""));
        clear(panel); leadList(panel);
      } catch (e) { toast(e.message); }
      fileInput.value = "";
    });
    const counts = Object.fromEntries(d.statuses.map((x) => [x, d.leads.filter((l) => l.status === x).length]));
    const tableBody = h("tbody");
    const draw = () => {
      clear(tableBody);
      const q = search.value.toLowerCase();
      const rows = d.leads.filter((l) => (!filter.value || l.status === filter.value) &&
        (!q || [l.name, l.city, l.website].join(" ").toLowerCase().includes(q)));
      if (!rows.length) { tableBody.append(h("tr", null, h("td", { colspan: 7, class: "muted", text: d.leads.length ? "No leads match." : "No leads yet. Run Business Search, or import a CSV." }))); return; }
      for (const l of rows.slice(0, 500)) {
        const status = h("select", { "aria-label": `Status of ${l.name}` }, d.statuses.map((x) => h("option", { value: x, text: x })));
        status.value = l.status;
        status.addEventListener("change", async () => {
          try { await api("POST", "/api/leads/update", { id: l.id, status: status.value }); l.status = status.value; toast(`${l.name}: ${status.value}`); }
          catch (e) { toast(e.message); status.value = l.status; }
        });
        const notes = h("input", { type: "text", value: l.notes, placeholder: "Notes", "aria-label": `Notes for ${l.name}` });
        notes.addEventListener("change", async () => {
          try { await api("POST", "/api/leads/update", { id: l.id, notes: notes.value }); l.notes = notes.value; toast("Notes saved"); }
          catch (e) { toast(e.message); }
        });
        const site = safeHref(l.website && !/^https?:/i.test(l.website) ? `https://${l.website}` : l.website);
        tableBody.append(h("tr", null,
          h("td", null, h("strong", { text: l.name }), h("div", { class: "muted", text: [l.category, l.city].filter(Boolean).join(" · ") })),
          h("td", null, site ? h("a", { href: site, target: "_blank", rel: "noopener noreferrer", text: l.website }) : h("span", { class: "muted", text: "no website" }),
            l.phone ? h("div", { class: "muted", text: l.phone }) : null),
          h("td", { class: "num", text: l.score === null ? "—" : String(l.score) }),
          h("td", { class: "muted small-text", text: (l.problems || []).slice(0, 2).join("; ") }),
          h("td", null, status), h("td", null, notes),
          h("td", { class: "num nowrap" },
            h("a", { class: "btn small", href: `/t/lead-finder/outreach?lead=${l.id}`, "data-link": true, text: "Draft" }),
            h("button", { class: "btn small ghost", type: "button", title: `Delete ${l.name}`, "aria-label": `Delete ${l.name}`, onclick: async () => {
              try { await api("POST", "/api/leads/delete", { id: l.id }); d.leads = d.leads.filter((x) => x.id !== l.id); draw(); } catch (e) { toast(e.message); }
            } }, icon("trash")))));
      }
    };
    filter.addEventListener("change", draw);
    search.addEventListener("input", draw);
    swap(body,
      h("div", { class: "grid tiles" }, d.statuses.slice(0, 4).map((x) => tile(x[0].toUpperCase() + x.slice(1), String(counts[x]), x === "new" ? "to contact" : ""))),
      h("div", { class: "card" },
        h("div", { class: "toolbar" }, search, filter,
          h("div", { class: "head-actions" },
            h("button", { class: "btn small", type: "button", onclick: () => fileInput.click() }, icon("upload"), "Import CSV"),
            h("a", { class: "btn small", href: "/api/leads/export", download: "rankloom-leads.csv" }, icon("download"), "Export CSV"),
            h("a", { class: "btn small primary", href: "/t/lead-finder/search", "data-link": true, text: "Find more" })), fileInput),
        h("p", { class: "muted small-text", text: "CSV import reads columns named name (or business), website, phone, email, address, city and category, in any order." }),
        h("div", { class: "table-wrap" }, h("table", { class: "table leads" },
          h("thead", null, h("tr", null, ["Business", "Website", "Opportunity", "Found", "Status", "Notes", ""].map((c) => h("th", { text: c })))),
          tableBody))));
    draw();
  }

  // ---------------------------------------------------------------- Clients
  async function clientsPage(panel) {
    const body = h("div", { class: "loading", text: "Loading clients…" });
    put(panel, body);
    let d;
    try { d = await api("GET", "/api/clients"); } catch (e) { clear(body).append(e.message); return; }
    const editor = h("div", { class: "card", hidden: true });
    const openEditor = (c) => {
      clear(editor).append(h("div", { class: "card-head" }, h("h2", { text: c ? `Edit ${c.name}` : "Add a client" })));
      const f = form({
        fields: [
          { name: "name", label: "Client name", required: true },
          { name: "website", label: "Website", type: "url", placeholder: "client.example" },
          { name: "city", label: "City", placeholder: "Lahore" },
          { name: "niche", label: "Business type", placeholder: "dentist" },
          { name: "contact", label: "Contact", placeholder: "name, email or phone" },
          { name: "brand", label: "Prepared by (shown on the report)", placeholder: "Your agency name" },
          { name: "gsc_dataset", label: "Search Console report", type: "dataset", hint: "Import one under Search Performance → Import Report." },
          { name: "notes", label: "Notes", type: "textarea" },
        ],
        values: c ? { ...c, gsc_dataset: c.gsc_dataset ? String(c.gsc_dataset) : "" } : {},
        submit: c ? "Save client" : "Add client", submitClass: "primary",
        onSubmit: async (v) => {
          await api("POST", "/api/clients/save", { ...v, id: c ? c.id : undefined, gsc_dataset: v.gsc_dataset || null });
          toast(c ? "Client saved" : "Client added"); clear(panel); clientsPage(panel);
        },
      });
      editor.append(f, h("button", { class: "btn ghost mt", type: "button", onclick: () => { editor.hidden = true; }, text: "Cancel" }));
      editor.hidden = false;
      editor.scrollIntoView({ behavior: "smooth", block: "start" });
    };
    swap(body,
      h("div", { class: "card" },
        h("div", { class: "card-head" }, h("h2", { text: `${d.clients.length} client(s)` }),
          h("button", { class: "btn small primary", type: "button", onclick: () => openEditor(null) }, "Add a client")),
        d.clients.length ? h("div", { class: "table-wrap" }, h("table", { class: "table" },
          h("thead", null, h("tr", null, ["Client", "Website", "Search Console", "Last report", ""].map((c) => h("th", { text: c })))),
          h("tbody", null, d.clients.map((c) => h("tr", null,
            h("td", null, h("strong", { text: c.name }), h("div", { class: "muted", text: [c.niche, c.city].filter(Boolean).join(" · ") })),
            h("td", { text: c.website || "—" }),
            h("td", { class: "muted", text: c.gsc_dataset ? "linked" : "—" }),
            h("td", null, c.last_report_id ? h("a", { href: `/t/client-reports/report?run=${c.last_report_id}#run`, "data-link": true, text: ago(c.last_report) }) : h("span", { class: "muted", text: "none" })),
            h("td", { class: "num nowrap" },
              h("a", { class: "btn small primary", href: `/t/client-reports/report?client=${c.id}`, "data-link": true, text: "Monthly report" }),
              h("button", { class: "btn small", type: "button", onclick: () => openEditor(c), text: "Edit" }),
              h("button", { class: "btn small ghost", type: "button", "aria-label": `Delete ${c.name}`, title: `Delete ${c.name}`, onclick: async () => {
                if (!window.confirm(`Delete ${c.name}? Their past reports stay in the history.`)) return;
                try { await api("POST", "/api/clients/delete", { id: c.id }); clear(panel); clientsPage(panel); } catch (e) { toast(e.message); }
              } }, icon("trash")))))))) :
          h("p", { class: "muted", text: "No clients yet. Add one to start sending monthly reports." })),
      editor);
  }

  // ---------------------------------------------------------------- Job Radar
  function notConnected(panel, message) {
    put(panel, h("div", { class: "notice warn" }, icon("alert"), h("div", null,
      h("strong", { text: "Job Radar is not connected. " }), message || "This page has nothing to show yet.",
      " ", h("a", { href: "/t/job-radar/crawl", "data-link": true, text: "Open Crawl" }))));
  }

  async function jrLoad(panel, path) {
    const body = h("div", { class: "loading", text: "Reading job-radar…" });
    put(panel, body);
    try { const d = await api("GET", path); body.remove(); return d; }
    catch (e) {
      body.remove();
      if (e.data && e.data.not_connected) notConnected(panel, e.message);
      else put(panel, h("div", { class: "notice bad" }, icon("alert"), h("div", { text: e.message })));
      return null;
    }
  }

  const JR_FILTERS = [
    ["country", "Country"], ["region", "Region"], ["family", "Title"], ["track", "Engineer or researcher"],
    ["workplace", "Workplace"], ["terms", "Terms"], ["years", "Experience"],
  ];
  const JR_FIXED = {
    region: [["europe", "Europe"], ["gulf", "Gulf"], ["pakistan", "Pakistan"], ["asia", "East & Southeast Asia"]],
    years: [["1", "Up to 1 year"], ["2", "Up to 2 years"], ["unstated", "Not stated"]],
  };

  async function jrJobs(panel) {
    const params = new URLSearchParams(location.search);
    const f = Object.fromEntries(JR_FILTERS.map(([k]) => [k, params.get(k) || ""]));
    f.q = params.get("q") || ""; f.reachable = params.get("reachable") || "";
    const qs = () => new URLSearchParams(Object.entries(f).filter(([, v]) => v)).toString();
    const d = await jrLoad(panel, `/api/jobradar/jobs?${qs()}`);
    if (!d) return;
    const rerun = () => {
      history.pushState({}, "", `${location.pathname}?${qs()}#workspace`);
      clear(panel); jrJobs(panel);
    };
    const selects = JR_FILTERS.map(([key, label]) => {
      const opts = JR_FIXED[key] || (d.facets[key === "country" ? "country" : key] || []).map(([v, n]) => [v, `${v} (${n})`]);
      if (f[key] && !opts.some(([v]) => v === f[key])) opts.unshift([f[key], `${f[key]} (0)`]);
      const sel = h("select", { "aria-label": label }, h("option", { value: "", text: `${label}: any` }),
        opts.map(([v, l]) => h("option", { value: v, text: l })));
      sel.value = f[key];
      sel.addEventListener("change", () => { f[key] = sel.value; rerun(); });
      return sel;
    });
    const search = h("input", { type: "search", placeholder: "Search title, company or city", value: f.q, "aria-label": "Search jobs" });
    search.addEventListener("change", () => { f.q = search.value; rerun(); });
    const reach = h("input", { type: "checkbox", id: "jr-reach" });
    reach.checked = f.reachable === "1";
    reach.addEventListener("change", () => { f.reachable = reach.checked ? "1" : ""; rerun(); });
    const chips = h("div", { class: "chips collapsible" }, d.facets.country.slice(0, 40).map(([c, n]) =>
      h("button", { type: "button", class: `chip${f.country === c ? " on" : ""}`, onclick: () => { f.country = f.country === c ? "" : c; rerun(); } },
        c, h("span", { text: String(n) }))));
    const moreChips = h("button", { class: "btn small ghost more-chips", type: "button",
      onclick: () => { chips.classList.toggle("expanded"); moreChips.textContent = chips.classList.contains("expanded") ? "Fewer countries" : "All countries"; } }, "All countries");
    // Green only for a stated way in; amber where the employer usually arranges the pass but
    // did not say, or the posting is silent; red where it refuses, locks or wants citizens.
    const route = (r) => {
      const parts = r.route.split(",");
      if (r.route_kind === "open") return badge("pass", parts.includes("sponsorship") ? "Sponsors visa" : parts.includes("remote") ? "Remote, open to you" : "In Pakistan");
      if (r.route_kind === "pass") return badge("warn", "Work pass usual, not stated");
      if (r.route_kind === "unclear") return badge("warn", r.route.replace(/^(onsite|hybrid|remote), /, ""));
      return badge("fail", r.route);
    };
    const labels = Object.fromEntries(JR_FILTERS);
    const active = Object.entries(f).filter(([k, v]) => v && k !== "reachable").map(([k, v]) =>
      h("button", { type: "button", class: "chip on removable", "aria-label": `Remove filter ${labels[k] || "Search"}: ${v}`,
        onclick: () => { f[k] = ""; rerun(); } }, `${labels[k] || "Search"}: ${(JR_FIXED[k] || []).find(([x]) => x === v)?.[1] || v}`));
    put(panel, 
      h("div", { class: "grid tiles" },
        tile("In the lens", String(d.total), "junior, target countries"),
        tile("Matching", String(d.matched), "with these filters"),
        tile("Countries", String(d.countries), "in these matches"),
        tile("With a way in", String(d.reachable), `of the ${d.matched} matching`)),
      h("div", { class: "card" },
        h("div", { class: "card-head" }, h("h2", { text: "Search by country" }), h("p", { text: "Click a country; click again to clear" })), chips, moreChips),
      h("div", { class: "card" },
        h("div", { class: "toolbar wrap" }, search, ...selects,
          h("label", { class: "check", for: "jr-reach" }, reach, " Only roles with a way in from Pakistan"),
          h("button", { class: "btn small ghost", type: "button", onclick: () => { for (const k of Object.keys(f)) f[k] = ""; rerun(); } }, "Clear filters")),
        active.length ? h("div", { class: "active-filters" }, h("span", { class: "muted small-text", text: "Filtering by:" }), active) : null,
        d.rows.length ? h("div", { class: "table-wrap" }, h("table", { class: "table jobs cards" },
          h("thead", null, h("tr", null, ["Role", "Company", "Country", "Title family", "Place", "Terms", "Experience", "Route", "Posted"].map((c) => h("th", { text: c })))),
          h("tbody", null, d.rows.map((r) => h("tr", null,
            h("td", null, safeHref(r.url) ? h("a", { href: r.url, target: "_blank", rel: "noopener noreferrer", text: r.title }) : r.title),
            h("td", { "data-label": "Company", text: r.company }),
            h("td", { "data-label": "Country", text: r.countries.join(", ") || "Not stated" }),
            h("td", { "data-label": "Title" }, h("span", { text: r.family }), h("span", { class: "muted small-text", text: ` · ${r.track}` })),
            h("td", { "data-label": "Place", text: r.workplace }), h("td", { "data-label": "Terms", text: r.terms }),
            h("td", { "data-label": "Experience", text: r.years === null ? "Not stated" : `${r.years} yr` }),
            h("td", { "data-label": "Route" }, route(r)),
            h("td", { class: "muted nowrap", "data-label": "Posted", text: r.posted ? r.posted.slice(0, 10) : "" }))))))
          : h("p", { class: "muted", text: "No roles match these filters." }),
        d.matched > d.rows.length ? h("p", { class: "muted small-text", text: `Showing the newest ${d.rows.length} of ${d.matched}. Narrow the filters to see the rest.` }) : null));
  }

  function directoryTable(entries) {
    return h("div", { class: "table-wrap" }, h("table", { class: "table" },
      h("thead", null, h("tr", null, ["Name", "What it is", "Pay", "Who can apply", "Open now", ""].map((c) => h("th", { text: c })))),
      h("tbody", null, entries.map((e) => h("tr", null,
        h("td", null, safeHref(e.url) ? h("a", { href: e.url, target: "_blank", rel: "noopener noreferrer", text: e.name }) : e.name,
          e.region && e.region !== "global" ? h("div", { class: "muted small-text", text: e.region }) : null),
        h("td", { text: e.what }),
        h("td", null, h("div", { text: e.pay }), e.pay_source ? h("div", { class: "muted small-text", text: `Source: ${e.pay_source}` }) : null),
        h("td", { class: "small-text", text: e.who || "" }),
        h("td", { class: "num", text: e.match ? String(e.live) : "—" }),
        h("td", null, safeHref(e.jobs_url) ? h("a", { class: "btn small", href: e.jobs_url, target: "_blank", rel: "noopener noreferrer", text: "Jobs" }) : null))))));
  }

  function postingsTable(rows, empty) {
    if (!rows.length) return h("p", { class: "muted", text: empty });
    return h("div", { class: "table-wrap" }, h("table", { class: "table" },
      h("thead", null, h("tr", null, ["Post", "Employer", "Where", "Experience", "Posted"].map((c) => h("th", { text: c })))),
      h("tbody", null, rows.map((r) => h("tr", null,
        h("td", null, safeHref(r.url) ? h("a", { href: r.url, target: "_blank", rel: "noopener noreferrer", text: r.title }) : r.title),
        h("td", { text: r.company }), h("td", { text: r.location || r.countries.join(", ") }),
        h("td", { text: r.years === null ? "Not stated" : `${r.years} yr` }),
        h("td", { class: "muted nowrap", text: r.posted ? r.posted.slice(0, 10) : "" }))))));
  }

  async function jrDirectory(panel, kind, title, note, withFamily) {
    const d = await jrLoad(panel, `/api/jobradar/directory?kind=${encodeURIComponent(kind)}${withFamily ? `&with=${withFamily}` : ""}`);
    if (!d) return;
    put(panel, h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: title }), h("p", { text: note })),
      d.entries.length ? directoryTable(d.entries) : h("p", { class: "muted", text: "Run a crawl to fill this list." })));
    return d;
  }

  async function jrFellowships(panel) {
    const d = await jrDirectory(panel, "Fellowship / paid programme", "Fellowships and paid programmes",
      "Pay is stated only where a live posting confirmed it; otherwise check the official page", "fellowship");
    if (d) put(panel, h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "Programme postings open now" }), h("p", { text: "Found by the crawl on company boards" })),
      postingsTable(d.postings, "No fellowship or residency postings in the last crawl.")));
  }

  async function jrPlatforms(panel) {
    const d = await jrDirectory(panel, "AI work platform", "AI work platforms",
      "Contract and small-contract work training and checking AI models", "platforms");
    if (d) put(panel, h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "AI training and evaluation roles open now" }),
      h("p", { text: "Model evaluator, AI data trainer, annotator and similar posts found by the crawl" })),
      postingsTable(d.postings, "No AI training or evaluation posts in the last crawl.")));
  }

  async function jrPakistan(panel) {
    const d = await jrLoad(panel, "/api/jobradar/directory?kind=x&with=pakistan");
    if (!d) return;
    put(panel, h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "Government and public-sector CS / IT / AI posts" }),
      h("p", { text: "National Job Portal and public employers in the crawl" })),
      postingsTable(d.postings, "No public-sector computing posts in the last crawl.")));
    await jrDirectory(panel, "Pakistan grant / funding", "Grants for junior scientists and researchers", "HEC, Ignite and other funders");
    await jrDirectory(panel, "Pakistan government jobs", "Where government computing jobs are advertised", "Commissions, boards and institutions");
  }

  async function jrYc(panel) {
    const params = new URLSearchParams(location.search);
    const f = { batch: params.get("batch") || "", hiring: params.get("hiring") || "", ai: params.get("ai") || "", q: params.get("q") || "" };
    const qs = () => new URLSearchParams(Object.entries(f).filter(([, v]) => v)).toString();
    const d = await jrLoad(panel, `/api/jobradar/yc?${qs()}`);
    if (!d) return;
    const rerun = () => { history.replaceState({}, "", `${location.pathname}?${qs()}#workspace`); clear(panel); jrYc(panel); };
    const batch = h("select", { "aria-label": "Batch" }, h("option", { value: "", text: "Batch: any" }),
      d.batches.map(([b, n]) => h("option", { value: b, text: `${b} (${n})` })));
    batch.value = f.batch; batch.addEventListener("change", () => { f.batch = batch.value; rerun(); });
    const hiring = h("select", { "aria-label": "Hiring" }, [["", "Hiring or not"], ["1", "Hiring now"], ["0", "Not hiring"]].map(([v, l]) => h("option", { value: v, text: l })));
    hiring.value = f.hiring; hiring.addEventListener("change", () => { f.hiring = hiring.value; rerun(); });
    const ai = h("input", { type: "checkbox", id: "yc-ai" }); ai.checked = f.ai === "1";
    ai.addEventListener("change", () => { f.ai = ai.checked ? "1" : ""; rerun(); });
    const search = h("input", { type: "search", placeholder: "Search name, product or city", value: f.q, "aria-label": "Search companies" });
    search.addEventListener("change", () => { f.q = search.value; rerun(); });
    const link = (href, text) => safeHref(href) ? h("a", { href, target: "_blank", rel: "noopener noreferrer", text }) : null;
    put(panel, 
      h("div", { class: "grid tiles" }, tile("Companies", String(d.total), "last three years of batches"),
        tile("Hiring now", String(d.hiring), "say so on YC"), tile("Matching", String(d.matched), "with these filters"),
        tile("LinkedIn read", String(d.linkedin_read), "from YC pages; the rest are searches")),
      h("div", { class: "card" }, h("div", { class: "toolbar wrap" }, search, batch, hiring,
        h("label", { class: "check", for: "yc-ai" }, ai, " AI companies only")),
        d.rows.length ? h("div", { class: "table-wrap" }, h("table", { class: "table" },
          h("thead", null, h("tr", null, ["Company", "Batch", "Status", "LinkedIn", "Website", "YC page", "Careers"].map((c) => h("th", { text: c })))),
          h("tbody", null, d.rows.map((r) => h("tr", null,
            h("td", null, h("strong", { text: r.name }), h("div", { class: "muted small-text", text: [r.one_liner, r.location].filter(Boolean).join(" · ") })),
            h("td", { class: "nowrap", text: r.batch }),
            h("td", null, r.status && r.status !== "Active" ? badge("fail", r.status)
              : r.hiring ? badge("pass", "Hiring") : h("span", { class: "pill", text: "Not hiring" })),
            h("td", null, link(r.linkedin, r.linkedin_source === "yc page" ? "Profile" : "Search")),
            h("td", null, link(r.website, "Website")),
            h("td", null, link(r.yc_url, "YC page")),
            h("td", null, link(r.jobs_url, r.hiring ? "Open roles" : "Jobs page"))))))) : h("p", { class: "muted", text: "No companies match." }),
        d.matched > d.rows.length ? h("p", { class: "muted small-text", text: `Showing ${d.rows.length} of ${d.matched}. Narrow by batch or search to see the rest.` }) : null));
  }

  async function jrAccelerators(panel) {
    const params = new URLSearchParams(location.search);
    const f = { programme: params.get("programme") || "", junior: params.get("junior") || "", family: params.get("family") || "", q: params.get("q") || "" };
    const qs = () => new URLSearchParams(Object.entries(f).filter(([, v]) => v)).toString();
    const d = await jrLoad(panel, `/api/jobradar/portfolio?${qs()}`);
    if (d) {
      const rerun = () => { history.replaceState({}, "", `${location.pathname}?${qs()}#workspace`); clear(panel); jrAccelerators(panel); };
      const link = (href, text) => safeHref(href) ? h("a", { href, target: "_blank", rel: "noopener noreferrer", text }) : text;
      const p = d.programmes.find((x) => x.name === d.programme);
      if (!p) {
        put(panel, h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "Portfolios" })),
          h("p", { class: "muted" }, "No portfolios read yet. ", h("a", { href: "/t/job-radar/crawl", "data-link": true, text: "Open Crawl" }), " and press Read portfolios.")));
      } else {
        const junior = h("input", { type: "checkbox", id: "pf-junior" }); junior.checked = f.junior === "1";
        junior.addEventListener("change", () => { f.junior = junior.checked ? "1" : ""; rerun(); });
        const search = h("input", { type: "search", placeholder: "Search company or role", value: f.q, "aria-label": "Search portfolio" });
        search.addEventListener("change", () => { f.q = search.value; rerun(); });
        const family = h("select", { "aria-label": "Title family" }, h("option", { value: "", text: "Title: any" }),
          d.families.map(([v, n]) => h("option", { value: v, text: `${v} (${n})` })));
        family.value = f.family; family.addEventListener("change", () => { f.family = family.value; rerun(); });
        put(panel, 
          h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "Portfolios" }), h("p", { text: "Companies each programme backs, read from its job board" })),
            h("div", { class: "chips" }, d.programmes.map((x) => h("button", { type: "button", class: `chip${x.name === d.programme ? " on" : ""}`, onclick: () => { f.programme = x.name; f.q = ""; f.family = ""; rerun(); } },
              x.name, h("span", { text: String(x.ai_roles) }))))),
          h("div", { class: "grid tiles" },
            tile("Companies", p.companies.toLocaleString(), `${p.name} ${p.kind === "accelerator" ? "has accelerated" : "has backed"}`),
            tile("Open postings", p.roles.toLocaleString(), "across those companies"),
            tile("AI postings", p.ai_roles.toLocaleString(), "AI titles, data work and fellowships"),
            tile("No senior title", p.junior_ai.toLocaleString(), "of the AI postings")),
          ...(p.failed ? [h("div", { class: "notice warn" }, icon("alert"), h("div", { text: `Part of this board could not be read last time: ${p.failed}` }))] : []),
          ...(!p.roles && p.companies ? [h("div", { class: "notice warn" }, icon("alert"), h("div", null,
            `${p.name}'s board lists its companies but not its job titles, so its roles cannot be counted or filtered here. `,
            link(p.board, "Open the board"), " to see them."))] : []),
          h("div", { class: "card" },
            h("div", { class: "card-head" }, h("h2", { text: `AI roles at ${p.name} companies` }), h("p", { text: "Titles are read from each job's address, which can drop a level word (Staff, Senior) and has no location. Open the role to confirm both." })),
            h("div", { class: "toolbar wrap" }, search, family, h("label", { class: "check", for: "pf-junior" }, junior, " No senior titles"),
              link(p.board, "Open the board")),
            d.roles.length ? h("div", { class: "table-wrap" }, h("table", { class: "table" },
              h("thead", null, h("tr", null, ["Role", "Company", "Title family", "Level"].map((c) => h("th", { text: c })))),
              h("tbody", null, d.roles.map((r) => h("tr", null,
                h("td", null, link(r.url, r.title), r.postings > 1 ? h("div", { class: "muted small-text", text: `${r.postings} postings with this title` }) : null),
                h("td", { text: r.company }),
                h("td", null, h("div", { text: r.family }), h("div", { class: "muted small-text", text: r.track })),
                h("td", null, r.junior ? badge("pass", r.level) : badge("warn", r.level)))))))
              : h("p", { class: "muted", text: "No AI roles match." }),
            ...(d.roles_matched > d.roles.length ? [h("p", { class: "muted small-text", text: `Showing ${d.roles.length} of ${d.roles_matched}. Search to narrow.` })] : [])),
          h("div", { class: "card" },
            h("div", { class: "card-head" }, h("h2", { text: `${p.name} portfolio companies` }), h("p", { text: "Most AI postings first; companies with nothing open are listed too" })),
            h("div", { class: "table-wrap" }, h("table", { class: "table" },
              h("thead", null, h("tr", null, ["Company", "Open postings", "AI postings", "No senior title", ""].map((c) => h("th", { text: c })))),
              h("tbody", null, d.companies.map((c) => h("tr", null,
                h("td", null, h("strong", { text: c.name })),
                h("td", { class: "num", text: String(c.roles) }), h("td", { class: "num", text: String(c.ai_roles) }),
                h("td", { class: "num", text: String(c.junior_ai) }),
                h("td", null, safeHref(c.url) ? h("a", { class: "btn small", href: c.url, target: "_blank", rel: "noopener noreferrer", text: "Company page" }) : null)))))),
            d.companies_matched > d.companies.length ? h("p", { class: "muted small-text", text: `Showing ${d.companies.length} of ${d.companies_matched.toLocaleString()}. Search to find the rest.` }) : null));
      }
    }
    await jrDirectory(panel, "Accelerator", "All accelerators and founder programmes", "Links to each programme's portfolio and job board; YC's recent batches are under YC Companies");
  }

  async function jrCrawl(panel) {
    const d = await jrLoad(panel, "/api/jobradar/status");
    if (!d) return;
    const c = d.counts || {};
    const logBox = h("pre", { class: "log", text: (d.crawl.log || []).join("\n") || "No crawl started from here yet." });
    const state = h("p", { class: "muted" });
    const showState = (cr) => { state.textContent = cr.running ? `Running: ${cr.label} (started ${ago(cr.started)})` : cr.what ? `Last: ${cr.label} - exit ${cr.exit}` : "Idle"; };
    showState(d.crawl);
    let timer = 0;
    const poll = async () => {
      try {
        const s = await api("GET", "/api/jobradar/status");
        logBox.textContent = s.crawl.log.join("\n"); showState(s.crawl);
        if (s.crawl.running && document.body.contains(logBox)) timer = setTimeout(poll, 3000);
      } catch (e) { /* the next click will say */ }
    };
    const start = (what) => async () => {
      try { const r = await api("POST", "/api/jobradar/crawl", { what }); showState(r.crawl); clearTimeout(timer); timer = setTimeout(poll, 1500); toast("Crawl started"); }
      catch (e) { toast(e.message); }
    };
    if (!d.connected) notConnected(panel, d.error);
    put(panel, 
      h("div", { class: "grid tiles" },
        tile("Last crawl", d.last_run ? ago(Date.parse(d.last_run) / 1000) : "never", d.last_run ? d.last_run.slice(0, 16).replace("T", " ") : ""),
        tile("Jobs in the lens", String(c.lens ?? 0), "junior, target countries"),
        tile("YC companies", String(c.yc_recent ?? 0), "last three years"),
        tile("Portfolio companies", String(c.portfolio_company ?? 0), "accelerators and investors"),
        tile("Company boards", String(c.discovered_boards ?? 0), "found by discovery")),
      h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "Run" }), h("p", { text: `job-radar at ${d.dir}` })),
        h("div", { class: "head-actions" },
          h("button", { class: "btn primary", type: "button", onclick: start("jobs") }, "Crawl job boards"),
          h("button", { class: "btn", type: "button", onclick: start("yc") }, "Refresh YC companies"),
          h("button", { class: "btn", type: "button", onclick: start("portfolios") }, "Read portfolios"),
          h("button", { class: "btn", type: "button", onclick: start("boards") }, "Discover more boards")),
        state, logBox),
      d.funnel.length ? h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "Last crawl's funnel" }), h("p", { text: "What each stage removed, and why" })),
        h("pre", { class: "log", text: d.funnel.join("\n") })) : null);
    if (d.crawl.running) timer = setTimeout(poll, 1500);
  }

  const PAGES = {
    "lead-finder/list": leadList,
    "client-reports/clients": clientsPage,
    "job-radar/jobs": jrJobs,
    "job-radar/platforms": jrPlatforms,
    "job-radar/fellowships": jrFellowships,
    "job-radar/pakistan": jrPakistan,
    "job-radar/yc": jrYc,
    "job-radar/accelerators": jrAccelerators,
    "job-radar/crawl": jrCrawl,
  };

  // ---------------------------------------------------------------- settings
  async function settings(main) {
    const p = page(main, "Settings", "Your profile, password, 2-step verification, signed-in devices and GitHub.");
    const sections = [["profile", "Profile"], ["password", "Password"], ["two-step", "2-step verification"], ["sessions", "Devices"], ["github", "GitHub"]];
    const content = h("div");
    p.append(h("div", { class: "settings" },
      h("nav", { "aria-label": "Settings sections" }, sections.map(([id, label]) => h("a", { href: `#${id}`, text: label }))),
      content));
    const sec = (id, title, sub) => {
      const c = h("section", { class: "card", id }, h("div", { class: "card-head" }, h("div", null, h("h2", { text: title }), sub ? h("p", { text: sub }) : null)));
      content.append(c);
      return c;
    };
    sec("profile", "Profile").append(form({
      fields: [{ name: "name", label: "Name", value: state.user.name, autocomplete: "name" },
        { name: "email", label: "Email", value: state.user.email, readonly: true }],
      submit: "Save", submitClass: "primary",
      onSubmit: async (v) => {
        await api("POST", "/api/account/profile", { name: v.name });
        state.user.name = v.name.trim(); state.shell = null; toast("Profile saved"); render();
      },
    }));
    sec("password", "Change password", "Changing it signs you out everywhere else.").append(form({
      fields: [{ name: "current", label: "Current password", type: "password", autocomplete: "current-password" },
        { name: "new", label: "New password", type: "password", autocomplete: "new-password", hint: "At least 10 characters, not built from your email." },
        { name: "confirm", label: "Repeat new password", type: "password", autocomplete: "new-password" }],
      submit: "Change password", submitClass: "primary",
      onSubmit: async (v, inputs) => {
        if (v.new !== v.confirm) { const e = new Error("The two new passwords are different."); e.data = { field: "confirm" }; throw e; }
        const r = await api("POST", "/api/account/password", { current: v.current, new: v.new });
        Object.values(inputs).forEach((i) => { i.value = ""; });
        toast(r.other_sessions_ended ? `Password changed. ${r.other_sessions_ended} other device(s) signed out.` : "Password changed.");
      },
    }));
    const tfaBody = h("div");
    sec("two-step", "2-step verification", "Ask for a code from an authenticator app every time you sign in.").append(tfaBody);
    await renderTwoStep(tfaBody);
    const ssBody = h("div");
    sec("sessions", "Devices", "Everywhere your account is signed in.").append(ssBody);
    renderSessions(ssBody);
    const ghBody = h("div");
    sec("github", "GitHub", "Connect your account to import repositories.").append(ghBody);
    renderGitHub(ghBody);
    const q = new URLSearchParams(location.search).get("github");
    if (q === "connected") toast("GitHub connected");
    else if (q === "failed") toast("GitHub sign-in failed. Try again.");
    else if (q === "state") toast("That GitHub sign-in expired. Try again.");
    if (location.hash) {
      const target = document.getElementById(location.hash.slice(1));
      if (target) requestAnimationFrame(() => target.scrollIntoView());
    }
  }

  async function renderTwoStep(box) {
    clear(box).append(h("div", { class: "loading", text: "Loading…" }));
    const st = await api("GET", "/api/2fa");
    clear(box);
    if (!st.enabled) {
      box.append(h("div", { class: "notice" }, icon("shield"), h("div", { text: "2-step verification is off. Anyone with your password can sign in." })),
        h("button", { class: "btn primary", type: "button", onclick: async (ev) => {
          ev.target.disabled = true;
          try { setupTwoStep(box, await api("POST", "/api/2fa/setup")); }
          catch (e) { toast(e.message); ev.target.disabled = false; }
        } }, "Turn on 2-step verification"));
      return;
    }
    box.append(h("div", { class: "notice good" }, icon("shield"),
      h("div", null, h("strong", { text: "2-step verification is on. " }), `${st.recovery_left} recovery code(s) left.`)));
    const confirmFields = [
      { name: "password", label: "Your password", type: "password", autocomplete: "current-password" },
      { name: "code", label: "Code from your app", inputmode: "numeric", maxlength: 6, autocomplete: "one-time-code" },
    ];
    const newCodes = h("div", { class: "card", hidden: true }, h("h3", { text: "New recovery codes" }),
      form({ fields: confirmFields, submit: "Make new codes", submitClass: "primary",
        onSubmit: async (v) => { const r = await api("POST", "/api/2fa/recovery", v); showCodes(box, r.recovery_codes); } }));
    const off = h("div", { class: "card", hidden: true }, h("h3", { text: "Turn off 2-step verification" }),
      form({ fields: confirmFields, submit: "Turn off", submitClass: "danger",
        onSubmit: async (v) => { await api("POST", "/api/2fa/disable", v); toast("2-step verification is off"); state.user.two_factor = false; renderTwoStep(box); } }));
    box.append(h("div", { class: "head-actions" },
      h("button", { class: "btn", type: "button", onclick: () => { newCodes.hidden = !newCodes.hidden; off.hidden = true; } }, "New recovery codes"),
      h("button", { class: "btn danger", type: "button", onclick: () => { off.hidden = !off.hidden; newCodes.hidden = true; } }, "Turn off")),
    newCodes, off);
  }

  function qrSvg(text) {
    const qr = window.qrcode(0, "M");
    qr.addData(text); qr.make();
    const n = qr.getModuleCount();
    let d = "";
    for (let r = 0; r < n; r++) for (let c = 0; c < n; c++) if (qr.isDark(r, c)) d += `M${c},${r}h1v1h-1z`;
    return s("svg", { viewBox: `-1 -1 ${n + 2} ${n + 2}`, role: "img", "aria-label": "QR code for your authenticator app", "shape-rendering": "crispEdges" },
      s("path", { d, fill: "#000" }));
  }

  function setupTwoStep(box, setup) {
    clear(box);
    const f = form({
      fields: [{ name: "code", label: "Enter the 6-digit code it shows", inputmode: "numeric", maxlength: 6, autocomplete: "one-time-code", class: "code" }],
      submit: "Turn on", submitClass: "primary",
      onSubmit: async (v) => {
        const r = await api("POST", "/api/2fa/enable", v);
        state.user.two_factor = true;
        showCodes(box, r.recovery_codes);
      },
    });
    let qr;
    try { qr = h("div", { class: "qr" }, qrSvg(setup.uri)); } catch (e) { qr = h("div", { class: "muted", text: "QR code unavailable - type the key instead." }); }
    box.append(h("div", { class: "setup" }, qr,
      h("div", null,
        h("p", { text: "1. Scan this with Google Authenticator, Microsoft Authenticator, 1Password or any authenticator app." }),
        h("p", { class: "muted", text: "Can't scan? Type this key into the app:" }),
        h("div", { class: "secret", text: setup.secret.replace(/(.{4})/g, "$1 ").trim() }),
        h("p", { text: "2. Enter the code the app shows to finish." }), f)));
  }

  function showCodes(box, codes) {
    clear(box);
    const text = `Rankloom recovery codes for ${state.user.email}\nEach code works once.\n\n${codes.join("\n")}\n`;
    box.append(h("div", { class: "notice good" }, icon("shield"),
      h("div", null, h("strong", { text: "Save these recovery codes now. " }), "Each one signs you in once if you lose your phone. They will not be shown again.")),
      h("div", { class: "codes" }, codes.map((c) => h("div", { text: c }))),
      h("div", { class: "head-actions" },
        h("button", { class: "btn", type: "button", onclick: () => download("rankloom-recovery-codes.txt", text) }, icon("download"), "Download"),
        h("button", { class: "btn", type: "button", onclick: () => copyText(text) }, icon("copy"), "Copy"),
        h("button", { class: "btn primary", type: "button", onclick: () => renderTwoStep(box) }, "I have saved them")));
  }

  async function renderSessions(box) {
    clear(box).append(h("div", { class: "loading", text: "Loading…" }));
    let d;
    try { d = await api("GET", "/api/account/sessions"); } catch (e) { clear(box).append(e.message); return; }
    const revoke = async (id) => {
      const r = await api("POST", "/api/account/sessions/revoke", { id });
      toast(r.ended ? `Signed out ${r.ended} device(s)` : "Nothing to sign out");
      renderSessions(box);
    };
    put(clear(box), h("div", { class: "table-wrap" }, h("table", { class: "table" },
      h("thead", null, h("tr", null, h("th", { text: "Device" }), h("th", { text: "Address" }), h("th", { text: "Last active" }), h("th", null))),
      h("tbody", null, d.sessions.map((x) => h("tr", null,
        h("td", null, h("div", { text: describeAgent(x.device) }), x.current ? h("span", { class: "pill live", text: "This device" }) : null),
        h("td", { class: "mono", text: x.ip }),
        h("td", { class: "muted", text: ago(x.last_seen) }),
        h("td", { class: "num" }, x.current ? null : h("button", { class: "btn small", type: "button", onclick: () => revoke(x.id) }, "Sign out"))))))),
    d.sessions.length > 1 ? h("button", { class: "btn danger", type: "button", onclick: () => revoke("others") }, "Sign out all other devices") : null);
  }

  function describeAgent(ua) {
    if (!ua) return "Unknown device";
    const browser = /Edg\//.test(ua) ? "Edge" : /Chrome\//.test(ua) ? "Chrome" : /Firefox\//.test(ua) ? "Firefox" : /Safari\//.test(ua) ? "Safari" : "Browser";
    const os = /Windows/.test(ua) ? "Windows" : /Android/.test(ua) ? "Android" : /iPhone|iPad/.test(ua) ? "iOS" : /Mac OS/.test(ua) ? "macOS" : /Linux/.test(ua) ? "Linux" : "";
    return os ? `${browser} on ${os}` : browser;
  }

  async function renderGitHub(box) {
    clear(box).append(h("div", { class: "loading", text: "Loading…" }));
    let st;
    try { st = await api("GET", "/api/github"); } catch (e) { clear(box).append(e.message); return; }
    clear(box);
    if (!st.connected) {
      if (st.oauth) {
        box.append(h("button", { class: "btn primary", type: "button", onclick: async () => {
          try { location.href = (await api("POST", "/api/github/start")).url; } catch (e) { toast(e.message); }
        } }, icon("git"), "Connect with GitHub"), h("p", { class: "muted", text: "Or use a personal access token:" }));
      } else {
        box.append(h("div", { class: "notice" }, icon("info"), h("div", null,
          "Connect with a personal access token. Create one at GitHub → Settings → Developer settings → Fine-grained tokens, with read access to ",
          h("strong", { text: "Contents" }), " and ", h("strong", { text: "Metadata" }), " for the repositories you want to import.")));
      }
      box.append(form({
        fields: [{ name: "token", label: "Personal access token", type: "password", placeholder: "github_pat_…", autocomplete: "off",
          hint: "Stored encrypted. Rankloom only reads; it never pushes to your repositories." }],
        submit: "Connect", submitClass: "primary",
        onSubmit: async (v) => { const r = await api("POST", "/api/github/token", v); toast(`Connected as ${r.login}`); renderGitHub(box); },
      }));
      return;
    }
    box.append(h("div", { class: "row-between" },
      h("div", { class: "notice good" }, icon("git"), h("div", null, "Connected as ", h("strong", { text: st.login }))),
      h("button", { class: "btn small danger", type: "button", onclick: async () => {
        await api("POST", "/api/github/disconnect"); toast("GitHub disconnected"); renderGitHub(box);
      } }, "Disconnect")));
    const imported = h("div");
    const list = h("div", { class: "repo-list" }, h("div", { class: "loading", text: "Loading your repositories…" }));
    const filterBox = h("input", { type: "search", placeholder: "Filter repositories", "aria-label": "Filter repositories" });
    box.append(h("h3", { text: "Imported repositories" }), imported,
      h("h3", { text: "Import a repository", class: "mt" }), h("div", { class: "field" }, filterBox), list);
    const refreshImports = async () => {
      const d = await api("GET", "/api/imports");
      clear(imported);
      if (!d.imports.length) { imported.append(h("p", { class: "muted", text: "Nothing imported yet." })); return; }
      imported.append(h("div", { class: "repo-list" }, d.imports.map((r) => h("div", { class: "r" },
        h("div", null, h("div", null, h("strong", { text: r.repo }), r.private ? h("span", { class: "pill", text: "private" }) : null),
          h("div", { class: "d", text: `${r.file_count} files · ${Object.keys(r.languages).slice(0, 4).join(", ") || "no languages detected"} · imported ${ago(r.imported_at)}` })),
        h("button", { class: "btn small", type: "button", onclick: async () => { await api("POST", "/api/imports/delete", { id: r.id }); refreshImports(); } }, "Remove")))));
    };
    refreshImports();
    let repos = [];
    const drawRepos = () => {
      const q = filterBox.value.toLowerCase();
      clear(list);
      const shown = repos.filter((r) => r.full_name.toLowerCase().includes(q));
      if (!shown.length) { list.append(h("div", { class: "loading", text: "No repositories match." })); return; }
      for (const r of shown) {
        const btn = h("button", { class: "btn small", type: "button" }, "Import");
        btn.addEventListener("click", async () => {
          btn.disabled = true; clear(btn).append(h("span", { class: "spinner" }));
          try { await api("POST", "/api/github/import", { repo: r.full_name }); toast(`Imported ${r.full_name}`); refreshImports(); }
          catch (e) { toast(e.message); }
          finally { btn.disabled = false; clear(btn).append("Import"); }
        });
        list.append(h("div", { class: "r" }, h("div", null,
          h("div", null, h("strong", { text: r.full_name }), r.private ? h("span", { class: "pill", text: "private" }) : null),
          h("div", { class: "d", text: [r.language, r.description].filter(Boolean).join(" · ") || "No description" })), btn));
      }
    };
    filterBox.addEventListener("input", drawRepos);
    try { repos = (await api("GET", "/api/github/repos")).repos; drawRepos(); }
    catch (e) { clear(list).append(h("div", { class: "loading", text: e.message })); }
  }

  // ---------------------------------------------------------------- auth pages
  function authPage(title, sub, ...content) {
    document.title = `${title} · Rankloom`;
    clear(root).append(h("div", { class: "auth" }, h("div", { class: "auth-card" },
      h("a", { class: "brand", href: "/login", "data-link": true }, logo(), "Rankloom"),
      h("div", { class: "card" }, h("h1", { text: title }), sub ? h("p", { class: "sub", text: sub }) : null, content))));
  }
  function nextPath() {
    const n = new URLSearchParams(location.search).get("next") || "/app";
    return n.startsWith("/") && !n.startsWith("//") ? n : "/app";
  }
  function signedIn() { if (channel) channel.postMessage("signed-in"); }

  const AUTH = {
    "/login": () => authPage("Sign in", "Welcome back. Sign in to your workspace.",
      form({
        fields: [{ name: "email", label: "Email", type: "email", autocomplete: "username" },
          { name: "password", label: "Password", type: "password", autocomplete: "current-password" }],
        extra: h("div", { class: "row-between field" }, h("span"), h("a", { href: "/forgot", "data-link": true, text: "Forgot password?" })),
        submit: "Sign in",
        onSubmit: async (v) => {
          const r = await api("POST", "/api/auth/login", v);
          if (r.mfa_required) { go(`/verify?next=${encodeURIComponent(nextPath())}`, true); return; }
          state.user = null; signedIn(); go(nextPath(), true);
        },
      }),
      h("p", { class: "auth-alt" }, "New here? ", h("a", { href: "/register", "data-link": true, text: "Create an account" }))),

    "/register": () => authPage("Create your account", "One account for every tool.",
      form({
        fields: [{ name: "name", label: "Name", autocomplete: "name" },
          { name: "email", label: "Email", type: "email", autocomplete: "email" },
          { name: "password", label: "Password", type: "password", autocomplete: "new-password", hint: "At least 10 characters, not built from your email." },
          { name: "confirm", label: "Repeat password", type: "password", autocomplete: "new-password" }],
        submit: "Create account",
        onSubmit: async (v) => {
          if (v.password !== v.confirm) { const e = new Error("The two passwords are different."); e.data = { field: "confirm" }; throw e; }
          await api("POST", "/api/auth/register", { name: v.name, email: v.email, password: v.password });
          signedIn(); go("/app", true);
        },
      }),
      h("p", { class: "auth-alt" }, "Already have an account? ", h("a", { href: "/login", "data-link": true, text: "Sign in" }))),

    "/forgot": () => {
      const done = h("div", { hidden: true });
      const f = form({
        fields: [{ name: "email", label: "Email", type: "email", autocomplete: "email" }],
        submit: "Send reset link",
        onSubmit: async (v) => {
          const r = await api("POST", "/api/auth/forgot", v);
          f.hidden = true;
          clear(done).append(h("div", { class: "notice good" }, icon("check"), h("div", null,
            "If an account exists for ", h("strong", { text: v.email }), ", a reset link is on its way. It works once, for one hour.",
            r.delivery === "outbox" ? h("p", { class: "muted", text: "Email is not set up on this server yet, so the link was written to the server console instead." }) : null)));
          done.hidden = false;
        },
      });
      authPage("Reset your password", "Enter your email and we will send you a link to set a new password.", f, done,
        h("p", { class: "auth-alt" }, h("a", { href: "/login", "data-link": true, text: "Back to sign in" })));
    },

    "/reset": () => {
      const token = new URLSearchParams(location.search).get("token") || "";
      authPage("Set a new password", "Choose a new password. This signs you out on every device.",
        form({
          fields: [{ name: "password", label: "New password", type: "password", autocomplete: "new-password", hint: "At least 10 characters, not built from your email." },
            { name: "confirm", label: "Repeat new password", type: "password", autocomplete: "new-password" }],
          submit: "Set password",
          onSubmit: async (v) => {
            if (v.password !== v.confirm) { const e = new Error("The two passwords are different."); e.data = { field: "confirm" }; throw e; }
            await api("POST", "/api/auth/reset", { token, password: v.password });
            toast("Password changed. Sign in with the new one.");
            go("/login", true);
          },
        }));
    },

    "/verify": () => {
      let recovery = false;
      const f = form({
        fields: [{ name: "code", label: "6-digit code", inputmode: "numeric", autocomplete: "one-time-code", maxlength: 11, class: "code" }],
        submit: "Verify",
        onSubmit: async (v) => {
          try { await api("POST", "/api/auth/2fa", v); }
          catch (e) { if (e.status === 401 && !e.message.includes("code")) { go("/login", true); return; } throw e; }
          state.user = null; signedIn(); go(nextPath(), true);
        },
      });
      const toggle = h("a", { href: "#", text: "Use a recovery code instead" });
      toggle.addEventListener("click", (ev) => {
        ev.preventDefault();
        recovery = !recovery;
        const input = f.inputs.code;
        input.value = "";
        input.closest(".field").querySelector("label").textContent = recovery ? "Recovery code" : "6-digit code";
        input.setAttribute("inputmode", recovery ? "text" : "numeric");
        input.classList.toggle("code", !recovery);
        toggle.textContent = recovery ? "Use a code from your app instead" : "Use a recovery code instead";
        input.focus();
      });
      authPage("2-step verification", "Open your authenticator app and enter the code it shows for Rankloom.", f,
        h("p", { class: "auth-alt" }, toggle), h("p", { class: "auth-alt" }, h("a", { href: "#", text: "Sign in as someone else",
          onclick: async (ev) => { ev.preventDefault(); await api("POST", "/api/auth/logout").catch(() => {}); go("/login", true); } })));
      f.inputs.code.focus();
    },
  };

  render();
})();
