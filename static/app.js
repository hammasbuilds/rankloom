// Rankloom web app. No framework, no build step. Every piece of user data reaches the page
// through textContent, never innerHTML, so nothing a user or a fetched page types can run here.
(() => {
  "use strict";

  const root = document.getElementById("app");
  const state = { user: null, tools: [], bySlug: {}, shell: null };
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
    sun: "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10zM12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42",
    check: "M20 6L9 17l-5-5",
    alert: "M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4M12 17h.01",
    x: "M18 6L6 18M6 6l12 12",
    info: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 16v-4M12 8h.01",
    menu: "M3 12h18M3 6h18M3 18h18",
    git: "M6 3v12M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 9a9 9 0 0 1-9 9",
    shield: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
    play: "M5 3l14 9-14 9V3z",
    download: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3",
    "site-audit": "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.35-4.35",
    "ai-visibility": "M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z",
    "keyword-radar": "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 18a6 6 0 1 0 0-12 6 6 0 0 0 0 12zM12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
    "trend-watch": "M23 6l-9.5 9.5-5-5L1 18M17 6h6v6",
    "lead-finder": "M21 10c0 7-9 13-9 13S3 17 3 10a9 9 0 0 1 18 0zM12 13a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
    "outreach-writer": "M22 2L11 13M22 2l-7 20-4-9-9-4z",
    "content-studio": "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M16 13H8M16 17H8M10 9H8",
    "social-planner": "M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zM16 2v4M8 2v4M3 10h18",
    "launch-kit": "M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09zM12 15l-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2zM9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5",
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
    const d = new Date(iso + "T00:00:00");
    return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
  }
  function initials(name) {
    return (name || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");
  }
  function save(key, val) { try { localStorage.setItem(key, val); } catch (e) { /* ignore */ } }

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

  // A form wired to an endpoint: disables while sending, puts field errors under the field.
  function form({ fields, submit, onSubmit, extra, submitClass = "primary block" }) {
    const el = h("form", { novalidate: true });
    const errs = {};
    const inputs = {};
    for (const f of fields) {
      const id = `f-${f.name}-${Math.random().toString(36).slice(2, 7)}`;
      const input = h("input", { id, name: f.name, type: f.type || "text", placeholder: f.placeholder || "",
        autocomplete: f.autocomplete || "off", required: f.required, value: f.value, readonly: f.readonly,
        inputmode: f.inputmode, maxlength: f.maxlength, class: f.class, spellcheck: "false" });
      inputs[f.name] = input;
      errs[f.name] = h("div", { class: "err", hidden: true });
      el.append(h("div", { class: "field" },
        h("label", { for: id, text: f.label }), input, f.hint ? h("div", { class: "hint", text: f.hint }) : null,
        errs[f.name]));
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
      const values = Object.fromEntries(Object.entries(inputs).map(([k, i]) => [k, i.value]));
      btn.disabled = true;
      const label = btn.textContent;
      clear(btn).append(h("span", { class: "spinner" }), " Working…");
      try { await onSubmit(values, inputs); }
      catch (e) {
        const field = e.data && e.data.field;
        if (field && errs[field]) {
          errs[field].textContent = e.message; errs[field].hidden = false;
          inputs[field].setAttribute("aria-invalid", "true"); inputs[field].focus();
        } else {
          clear(general).append(icon("alert"), h("div", { text: e.message })); general.hidden = false;
        }
      } finally {
        btn.disabled = false; clear(btn).append(label);
      }
    });
    el.inputs = inputs;
    return el;
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
    if (win) win.opener = null; else window.open(path, "_blank");
  }

  if (channel) {
    channel.onmessage = (ev) => {
      if (ev.data === "signed-out") { state.user = null; go("/login", true); }
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
    if (!me.user) { go(`/login?next=${encodeURIComponent(path + location.hash)}`, true); return; }
    if (!state.tools.length) {
      const t = await api("GET", "/api/tools");
      state.tools = t.tools;
      state.bySlug = Object.fromEntries(t.tools.map((x) => [x.slug, x]));
    }
    const main = shell(path);
    const m = path.match(/^\/t\/([a-z0-9-]+)$/);
    if (path === "/app") return overview(main);
    if (path === "/settings") return settings(main);
    if (m && state.bySlug[m[1]]) return toolPage(main, state.bySlug[m[1]]);
    notFound(main);
  }

  // ---------------------------------------------------------------- shell
  function shell(path) {
    if (!state.shell) {
      const nav = h("ul", { class: "nav", "aria-label": "Tools" });
      for (const t of state.tools) {
        const href = `/t/${t.slug}`;
        nav.append(h("li", null,
          h("a", { class: "item", href, "data-link": true, "data-path": href, title: t.tagline },
            icon(t.slug), h("span", { text: t.name })),
          h("button", { class: "pop", type: "button", title: `Open ${t.name} in a new window`,
            "aria-label": `Open ${t.name} in a new window`, onclick: () => popOut(href) }, icon("external"))));
      }
      const top = h("ul", { class: "nav" },
        h("li", null, h("a", { class: "item", href: "/app", "data-link": true, "data-path": "/app" },
          icon("overview"), h("span", { text: "Overview" }))));
      const themeBtn = h("button", { class: "btn ghost small", type: "button", onclick: toggleTheme },
        icon("moon"), h("span", { text: "Theme" }));
      const foot = h("div", { class: "sidebar-foot" },
        h("ul", { class: "nav" }, h("li", null, h("a", { class: "item", href: "/settings", "data-link": true,
          "data-path": "/settings" }, icon("settings"), h("span", { text: "Settings" })))),
        h("div", { class: "who" }, h("div", { class: "avatar", text: initials(state.user.name) }),
          h("div", { class: "meta" }, h("div", { text: state.user.name }),
            h("div", { class: "email", text: state.user.email }))),
        h("div", { class: "foot-actions" }, themeBtn,
          h("button", { class: "btn ghost small", type: "button", onclick: signOut }, icon("logout"),
            h("span", { text: "Sign out" }))));
      const sidebar = h("aside", { class: "sidebar", "aria-label": "Main" },
        h("a", { class: "brand", href: "/app", "data-link": true }, logo(), "Rankloom"),
        top, h("div", { class: "nav-label", text: "Tools" }), nav, foot);
      const main = h("main", { class: "main", id: "main" });
      const wrap = h("div", { class: "shell" });
      const topbar = h("div", { class: "topbar" },
        h("button", { class: "btn ghost icon-btn", type: "button", "aria-label": "Open menu",
          onclick: () => wrap.classList.add("nav-open") }, icon("menu")),
        h("a", { class: "brand", href: "/app", "data-link": true }, logo(), "Rankloom"));
      const scrim = h("div", { class: "scrim", hidden: true });
      wrap.addEventListener("click", (ev) => {
        if (ev.target.closest(".sidebar a[data-link]") || ev.target === scrim) wrap.classList.remove("nav-open");
      });
      new MutationObserver(() => { scrim.hidden = !wrap.classList.contains("nav-open"); })
        .observe(wrap, { attributes: true, attributeFilter: ["class"] });
      wrap.append(sidebar, scrim, h("div", null, topbar, main));
      clear(root).append(wrap);
      state.shell = { wrap, main };
    }
    for (const a of state.shell.wrap.querySelectorAll("a[data-path]")) {
      if (a.dataset.path === path) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    }
    window.scrollTo(0, 0);
    return clear(state.shell.main);
  }

  function toggleTheme() {
    const rootEl = document.documentElement;
    const dark = rootEl.dataset.theme ? rootEl.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    rootEl.dataset.theme = dark ? "light" : "dark";
    save("rl-theme", rootEl.dataset.theme);
  }

  async function signOut() {
    try { await api("POST", "/api/auth/logout"); } catch (e) { /* signed out either way */ }
    state.user = null; state.shell = null;
    if (channel) channel.postMessage("signed-out");
    go("/login", true);
  }

  function page(main, title, lede, actions) {
    document.title = `${title} · Rankloom`;
    const head = h("div", { class: "page-head" },
      h("div", null, h("h1", { text: title }), lede ? h("p", { class: "lede", text: lede }) : null),
      actions ? h("div", { class: "head-actions" }, actions) : null);
    const body = h("div", { class: "page" }, head);
    main.append(body);
    return body;
  }

  function notFound(main) {
    const p = page(main, "Page not found", "That address does not match a page in Rankloom.");
    p.append(h("a", { class: "btn", href: "/app", "data-link": true, text: "Back to overview" }));
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

  // One series of bars over days. `unit` names the value in the tooltip.
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

  // Scores out of 100 across runs, oldest first.
  function lineChart(points, { label }) {
    const box = h("div", { class: "chart-box" });
    const svg = s("svg", { class: "chart", role: "img", "aria-label": label });
    box.append(svg, dataTable(points.map((p) => [new Date(p.created_at * 1000).toLocaleString(), p.score]), ["Run", "Score"]));
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
      if (points.length > 1) {
        svg.append(s("polyline", { class: "line", points: points.map((p, i) => `${xs(i)},${ys(p.score)}`).join(" ") }));
      }
      points.forEach((p, i) => {
        const dot = s("circle", { class: "dot", cx: xs(i), cy: ys(p.score), r: 4.5 });
        const hit = s("circle", { class: "hit", cx: xs(i), cy: ys(p.score), r: 14 });
        hit.addEventListener("mousemove", (ev) => showTip(ev, [`${p.score} / 100`, new Date(p.created_at * 1000).toLocaleString(), p.summary]));
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
        h("thead", null, h("tr", null, head.map((c, i) => h("th", { class: i ? "num" : null, text: c })))),
        h("tbody", null, rows.map((r) => h("tr", null, r.map((c, i) => h("td", { class: i ? "num" : null, text: String(c) })))))));
  }

  function tile(k, v, sub) {
    return h("div", { class: "tile" }, h("div", { class: "k", text: k }), h("div", { class: "v", text: v }),
      sub ? h("div", { class: "s", text: sub }) : null);
  }
  function statusPill(status) {
    return status === "live"
      ? h("span", { class: "pill live" }, icon("check"), "Live")
      : h("span", { class: "pill building" }, icon("settings"), "Being built");
  }

  // ---------------------------------------------------------------- overview
  async function overview(main) {
    const first = (state.user.name || "").split(" ")[0];
    const p = page(main, `Welcome back, ${first}`, "Every tool in one place. Open any of them here, or in a window of its own to use several side by side.");
    const body = h("div", { class: "loading", text: "Loading your workspace…" });
    p.append(body);
    let d;
    try { d = await api("GET", "/api/dashboard"); }
    catch (e) { clear(body).append(e.message); return; }
    const live = d.tools.filter((t) => t.status === "live").length;
    const runs = d.tools.reduce((a, t) => a + t.runs, 0);
    const opens = d.tools.reduce((a, t) => a + t.opens, 0);
    swap(body,
      h("div", { class: "grid tiles" },
        tile("Tools", `${live} of ${d.tools.length}`, "running now"),
        tile("Runs", String(runs), "all time"),
        tile("Tool visits", String(opens), "all time"),
        tile("Imported repos", String(d.imports), "from GitHub")),
      h("div", { class: "grid two" },
        h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "Runs per day" }), h("p", { text: "Last 14 days, all tools" })),
          barChart(d.daily.map((x) => ({ day: x.day, value: x.runs })), { unit: "runs", label: "Runs per day over the last 14 days" })),
        h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "Tool visits per day" }), h("p", { text: "Last 14 days, all tools" })),
          barChart(d.daily.map((x) => ({ day: x.day, value: x.opens })), { unit: "visits", alt: true, label: "Tool visits per day over the last 14 days" }))),
      h("div", { class: "card" },
        h("div", { class: "card-head" }, h("h2", { text: "Your tools" }), h("p", { text: "Click a name to open it here; the arrow opens a new window" })),
        h("div", { class: "table-wrap" }, h("table", { class: "table" },
          h("thead", null, h("tr", null, h("th", { text: "Tool" }), h("th", { text: "Status" }), h("th", { class: "num", text: "Visits" }),
            h("th", { class: "num", text: "Runs" }), h("th", { text: "Last used" }), h("th", null, h("span", { class: "sr-only", text: "Open" })))),
          h("tbody", null, d.tools.map((t) => {
            const meta = state.bySlug[t.slug];
            return h("tr", null,
              h("td", null, h("a", { href: `/t/${t.slug}`, "data-link": true, text: t.name }),
                h("div", { class: "muted", text: meta.tagline })),
              h("td", null, statusPill(t.status)),
              h("td", { class: "num", text: String(t.opens) }),
              h("td", { class: "num", text: String(t.runs) }),
              h("td", { class: "muted", text: ago(t.last) }),
              h("td", { class: "num" }, h("button", { class: "btn small ghost", type: "button", title: `Open ${t.name} in a new window`,
                onclick: () => popOut(`/t/${t.slug}`) }, icon("external"), "New window")));
          }))))),
      h("div", { class: "card" },
        h("div", { class: "card-head" }, h("h2", { text: "Recent runs" })),
        d.recent.length ? h("div", { class: "table-wrap" }, h("table", { class: "table" },
          h("tbody", null, d.recent.map((r) => h("tr", { class: "click", onclick: () => go(`/t/${r.tool}?run=${r.id}#run`) },
            h("td", { text: state.bySlug[r.tool] ? state.bySlug[r.tool].name : r.tool }),
            h("td", { text: r.summary }),
            h("td", { class: "num", text: r.score === null ? "" : `${r.score}/100` }),
            h("td", { class: "muted", text: ago(r.created_at) })))))) :
          h("p", { class: "muted" }, "No runs yet. Start with ",
            h("a", { href: "/t/site-audit", "data-link": true, text: "Site Audit" }), " - it is live now.")));
  }

  // ---------------------------------------------------------------- tool page
  function toolPage(main, tool) {
    api("POST", "/api/events", { tool: tool.slug, kind: "open" }).catch(() => {});
    const p = page(main, tool.name, tool.tagline, [
      statusPill(tool.status),
      h("button", { class: "btn small", type: "button", onclick: () => popOut(location.pathname + location.search + location.hash) },
        icon("external"), "Open in new window"),
    ]);
    const tabs = [["run", "Run"], ["dashboard", "Dashboard"], ["about", "About"]];
    const bar = h("div", { class: "tabs", role: "tablist" });
    const panel = h("div", { role: "tabpanel" });
    p.append(bar, panel);
    const select = (key, push = true) => {
      for (const b of bar.children) b.setAttribute("aria-selected", String(b.dataset.key === key));
      if (push) history.replaceState({}, "", `${location.pathname}${location.search}#${key}`);
      clear(panel);
      if (key === "run") runPanel(panel, tool);
      else if (key === "dashboard") dashboardPanel(panel, tool);
      else aboutPanel(panel, tool);
    };
    for (const [key, label] of tabs) {
      bar.append(h("button", { role: "tab", type: "button", "data-key": key, text: label, onclick: () => select(key) }));
    }
    const fromHash = location.hash.slice(1);
    select(tabs.some(([k]) => k === fromHash) ? fromHash : tool.status === "live" ? "run" : "about", false);
  }

  function aboutPanel(panel, tool) {
    panel.append(h("div", { class: "card about" },
      h("h2", { text: `What ${tool.name} does` }),
      h("p", { text: tool.about, class: "mt" }),
      h("ul", { class: "checklist" }, tool.does.map((d) => h("li", null, icon("check"), h("span", { text: d })))),
      h("div", { class: "io" },
        h("div", null, h("div", { class: "k", text: "You give it" }), h("div", { text: tool.input })),
        h("div", null, h("div", { class: "k", text: "You get back" }), h("div", { text: tool.output })))));
  }

  async function runPanel(panel, tool) {
    if (tool.status !== "live") {
      panel.append(h("div", { class: "notice warn" }, icon("alert"),
        h("div", null, h("strong", { text: `${tool.name} is being built. ` }),
          "The form below shows what it will take. Its dashboard is already recording your visits, and the About tab says what it will do.")));
    }
    const card = h("div", { class: "card" });
    panel.append(card);
    const result = h("div");
    panel.append(result);
    let repoOptions = null;
    if (tool.fields.some((f) => f.type === "repo")) {
      try { repoOptions = (await api("GET", "/api/imports")).imports; } catch (e) { repoOptions = []; }
    }
    const fields = tool.fields.map((f) => ({ ...f, type: f.type === "url" ? "text" : f.type === "repo" ? "text" : f.type,
      inputmode: f.type === "url" ? "url" : null, required: !!f.required,
      hint: f.type === "repo" ? (repoOptions && repoOptions.length ? `Imported: ${repoOptions.map((r) => r.repo).join(", ")}`
        : "Import a repository first under Settings → GitHub.") : null }));
    const f = form({
      fields, submit: tool.status === "live" ? h("span", null, "Run ", tool.name) : "Not running yet",
      submitClass: "primary",
      onSubmit: async (values) => {
        if (tool.status !== "live") throw new Error(`${tool.name} is not running yet - its engine is being built.`);
        clear(result).append(h("div", { class: "card loading" }, h("span", { class: "spinner" }), " Running…"));
        try {
          const r = await api("POST", `/api/tools/${tool.slug}/run`, { fields: values });
          showResult(result, tool, r);
        } catch (e) {
          clear(result);
          throw e;
        }
      },
    });
    if (tool.status !== "live") f.querySelector("button[type=submit]").disabled = true;
    card.append(h("div", { class: "card-head" }, h("h2", { text: "Run" }), h("p", { text: tool.input })), f);
    const want = new URLSearchParams(location.search).get("run");
    if (want) {
      try {
        const r = await api("GET", `/api/runs/${encodeURIComponent(want)}`);
        if (r.tool === tool.slug) {
          for (const [k, v] of Object.entries(r.input)) if (f.inputs[k]) f.inputs[k].value = v;
          showResult(result, tool, r);
        }
      } catch (e) { /* stale link: just show the form */ }
    }
  }

  function showResult(result, tool, r) {
    clear(result);
    if (r.status === "error") {
      result.append(h("div", { class: "notice bad" }, icon("alert"), h("div", { text: r.summary })));
      return;
    }
    if (tool.slug === "site-audit") result.append(auditView(r.output, r));
    else result.append(h("pre", { class: "card mono", text: JSON.stringify(r.output, null, 2) }));
  }

  function auditView(o, r) {
    const C = 2 * Math.PI * 34;
    const ring = s("svg", { class: "ring", viewBox: "0 0 84 84", role: "img", "aria-label": `Score ${o.score} out of 100` },
      s("circle", { class: "track", cx: 42, cy: 42, r: 34, fill: "none", "stroke-width": 8 }),
      s("circle", { class: "bar", cx: 42, cy: 42, r: 34, fill: "none", "stroke-width": 8,
        "stroke-dasharray": C, "stroke-dashoffset": C * (1 - o.score / 100), transform: "rotate(-90 42 42)" }),
      s("text", { x: 42, y: 50, "text-anchor": "middle" }, String(o.score)));
    const st = { pass: ["check", "Pass"], warn: ["alert", "Warning"], fail: ["x", "Fail"] };
    const badge = (k) => h("span", { class: `status ${k}` }, icon(st[k][0]), st[k][1]);
    const wrap = h("div");
    wrap.append(h("div", { class: "card" },
      h("div", { class: "score" }, ring,
        h("div", { class: "grow" },
          h("h2", { text: o.final_url }),
          h("p", { class: "muted", text: `Answered ${o.status} in ${o.elapsed_ms} ms · run ${ago(r.created_at || Date.now() / 1000)}` }),
          h("div", { class: "counts" },
            h("span", { class: "status fail" }, icon("x"), `${o.counts.fail} fail`),
            h("span", { class: "status warn" }, icon("alert"), `${o.counts.warn} warning`),
            h("span", { class: "status pass" }, icon("check"), `${o.counts.pass} pass`))))));
    if (o.facts) {
      const fx = o.facts;
      wrap.append(h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "What the page says about itself" })),
        h("div", { class: "facts" },
          [["Title", fx.title || "—"], ["Description", fx.description || "—"], ["H1", fx.h1.join(" · ") || "—"],
            ["Words", fx.words.toLocaleString()], ["Links in / out", `${fx.links_internal} / ${fx.links_external}`],
            ["Structured data", fx.schema_types.join(", ") || "none"]]
            .map(([k, v]) => h("div", { title: v }, h("div", { class: "k", text: k }), h("div", { class: "v", text: v }))))));
    }
    wrap.append(h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "Checks" }),
      h("p", { text: "Failures first, then warnings, heaviest first" })),
      h("ul", { class: "checks" }, o.checks.map((c) => h("li", null, badge(c.status),
        h("div", null, h("div", { class: "label", text: c.label }), h("div", { class: "detail", text: c.detail }),
          c.fix ? h("div", { class: "fix" }, h("b", { text: "Fix: " }), c.fix) : null))))));
    return wrap;
  }

  async function dashboardPanel(panel, tool) {
    const body = h("div", { class: "loading", text: "Loading…" });
    panel.append(body);
    let st, runs;
    try {
      [st, runs] = await Promise.all([api("GET", `/api/tools/${tool.slug}/stats`), api("GET", `/api/tools/${tool.slug}/runs`)]);
    } catch (e) { clear(body).append(e.message); return; }
    const rate = st.runs ? `${Math.round((100 * st.ok) / st.runs)}%` : "—";
    const scoring = tool.slug === "site-audit";
    swap(body,
      h("div", { class: "grid tiles" },
        tile("Visits", String(st.opens), "times you opened it"),
        tile("Runs", String(st.runs), st.last_run ? `last ${ago(st.last_run)}` : "none yet"),
        tile("Succeeded", rate, st.errors ? `${st.errors} failed` : "no failures"),
        scoring ? tile("Average score", st.avg_score === null ? "—" : `${st.avg_score}`, st.best_score === null ? "" : `best ${st.best_score}`)
          : tile("Average time", st.avg_ms === null ? "—" : `${(st.avg_ms / 1000).toFixed(1)} s`, "per run")),
      h("div", { class: "grid two" },
        h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "Runs per day" }), h("p", { text: "Last 14 days" })),
          barChart(st.daily.map((x) => ({ day: x.day, value: x.runs })), { unit: "runs", label: `${tool.name} runs per day` })),
        h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "Visits per day" }), h("p", { text: "Last 14 days" })),
          barChart(st.daily.map((x) => ({ day: x.day, value: x.opens })), { unit: "visits", alt: true, label: `${tool.name} visits per day` }))),
      scoring && st.scores.length ? h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "Score over your last runs" }),
        h("p", { text: "Out of 100, oldest on the left" })), lineChart(st.scores, { label: "Audit score over recent runs" })) : null,
      h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "Run history" }), h("p", { text: "Click a run to open its result" })),
        runs.runs.length ? h("div", { class: "table-wrap" }, h("table", { class: "table" },
          h("thead", null, h("tr", null, h("th", { text: "When" }), h("th", { text: "Result" }), h("th", { class: "num", text: "Score" }), h("th", { class: "num", text: "Time" }))),
          h("tbody", null, runs.runs.map((r) => h("tr", { class: "click", onclick: () => go(`/t/${tool.slug}?run=${r.id}#run`) },
            h("td", { class: "muted", text: ago(r.created_at) }),
            h("td", null, r.status === "error" ? h("span", { class: "status fail" }, icon("x"), "Failed") : null, " ", r.summary),
            h("td", { class: "num", text: r.score === null ? "" : String(r.score) }),
            h("td", { class: "num", text: `${(r.duration_ms / 1000).toFixed(1)} s` })))))) :
          h("p", { class: "muted", text: tool.status === "live" ? "No runs yet - use the Run tab." : "Runs will appear here once the engine is live." })));
  }

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

    // Profile
    sec("profile", "Profile").append(form({
      fields: [{ name: "name", label: "Name", value: state.user.name, autocomplete: "name" },
        { name: "email", label: "Email", value: state.user.email, readonly: true }],
      submit: "Save", submitClass: "primary",
      onSubmit: async (v) => {
        await api("POST", "/api/account/profile", { name: v.name });
        state.user.name = v.name.trim(); state.shell = null; toast("Profile saved"); render();
      },
    }));

    // Password
    const pw = sec("password", "Change password", "Changing it signs you out everywhere else.");
    const pwForm = form({
      fields: [{ name: "current", label: "Current password", type: "password", autocomplete: "current-password" },
        { name: "new", label: "New password", type: "password", autocomplete: "new-password", hint: "At least 10 characters." },
        { name: "confirm", label: "Repeat new password", type: "password", autocomplete: "new-password" }],
      submit: "Change password", submitClass: "primary",
      onSubmit: async (v, inputs) => {
        if (v.new !== v.confirm) { const e = new Error("The two new passwords are different."); e.data = { field: "confirm" }; throw e; }
        const r = await api("POST", "/api/account/password", { current: v.current, new: v.new });
        Object.values(inputs).forEach((i) => { i.value = ""; });
        toast(r.other_sessions_ended ? `Password changed. ${r.other_sessions_ended} other device(s) signed out.` : "Password changed.");
      },
    });
    pw.append(pwForm);

    // 2-step
    const tfa = sec("two-step", "2-step verification", "Ask for a code from an authenticator app every time you sign in.");
    const tfaBody = h("div");
    tfa.append(tfaBody);
    await renderTwoStep(tfaBody);

    // Sessions
    const ss = sec("sessions", "Devices", "Everywhere your account is signed in.");
    const ssBody = h("div");
    ss.append(ssBody);
    renderSessions(ssBody);

    // GitHub
    const gh = sec("github", "GitHub", "Connect your account to import repositories into your tools.");
    const ghBody = h("div");
    gh.append(ghBody);
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
        h("button", { class: "btn", type: "button", onclick: () => {
          const a = h("a", { href: URL.createObjectURL(new Blob([text], { type: "text/plain" })), download: "rankloom-recovery-codes.txt" });
          document.body.append(a); a.click(); a.remove();
        } }, icon("download"), "Download"),
        h("button", { class: "btn", type: "button", onclick: () => navigator.clipboard.writeText(text).then(() => toast("Copied")) }, "Copy"),
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
    const filter = h("input", { type: "search", placeholder: "Filter repositories", "aria-label": "Filter repositories" });
    box.append(h("h3", { text: "Imported repositories" }), imported,
      h("h3", { text: "Import a repository", class: "mt" }), h("div", { class: "field" }, filter), list);
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
      const q = filter.value.toLowerCase();
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
    filter.addEventListener("input", drawRepos);
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

    "/register": () => authPage("Create your account", "One account for all nine tools.",
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
          fields: [{ name: "password", label: "New password", type: "password", autocomplete: "new-password", hint: "At least 10 characters." },
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
