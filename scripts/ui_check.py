"""Drive the real app in headless Chrome, end to end, and save the screenshots in docs/.

    uv run python scripts/ui_check.py

The server runs in this process on a free port with a throwaway data folder, and the Site Audit
engine reads two fixture pages instead of the internet, so the walk is the same on every machine.
The walk registers, runs two audits, reads the dashboard, turns on 2-step verification with a
code the page computes itself, signs out, signs back in through the 2-step screen, and then
repeats the core pages at phone width checking for sideways scrolling.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_site_audit import BAD, GOOD, fetcher  # noqa: E402

from rankloom import engines, server  # noqa: E402
from rankloom.engines import site_audit  # noqa: E402

PAGES = {
    "https://solar.example/": (
        200,
        GOOD,
        {"content-encoding": "gzip"},
        "https://solar.example/",
        [],
    ),
    "https://solar.example/robots.txt": (200, "User-agent: *\nSitemap: /sitemap.xml", {}, "", []),
    "https://bad.example/": (200, BAD, {}, "https://bad.example/", [(301, "http://bad.example/")]),
}

CHROME = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
]

FORBID = ["undefined", "NaN", "[object Object]", "null"]

# Computes the current TOTP code for the secret on screen with WebCrypto.
TOTP_JS = """
  const b32 = (s) => { const a = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'; let bits = '';
    for (const c of s.replace(/\\s/g, '')) bits += a.indexOf(c).toString(2).padStart(5, '0');
    const out = new Uint8Array(Math.floor(bits.length / 8));
    for (let i = 0; i < out.length; i++) out[i] = parseInt(bits.slice(i * 8, i * 8 + 8), 2);
    return out; };
  const totp = async (secret, offset = 0) => {
    const key = await crypto.subtle.importKey('raw', b32(secret), { name: 'HMAC', hash: 'SHA-1' }, false, ['sign']);
    const step = Math.floor(Date.now() / 30000) + offset; const msg = new Uint8Array(8);
    let x = step; for (let i = 7; i >= 0; i--) { msg[i] = x & 255; x = Math.floor(x / 256); }
    const mac = new Uint8Array(await crypto.subtle.sign('HMAC', key, msg)); const o = mac[19] & 15;
    const n = ((mac[o] & 127) << 24 | mac[o + 1] << 16 | mac[o + 2] << 8 | mac[o + 3]) % 1000000;
    return String(n).padStart(6, '0'); };
"""


def fill_and_submit(values: dict, button="form button[type=submit]") -> list[dict]:
    steps = [{"fill": f"input[name={k}]", "value": v} for k, v in values.items()]
    steps.append({"click": button, "after": 900})
    return steps


def desktop_plan(base: str, shots: Path) -> dict:
    email, pw = "ayesha@example.com", "tall-orange-river-42"
    steps = [
        {"waitFor": "form"},
        {
            "label": "light theme for the screenshots",
            "js": "document.documentElement.dataset.theme='light'; return true;",
        },
        *fill_and_submit({"name": "Ayesha Khan", "email": email, "password": pw, "confirm": pw}),
        {"waitFor": ".sidebar .nav"},
        {
            "label": "nine tool names in the sidebar, no numbers",
            "js": "const n=[...document.querySelectorAll('.sidebar .nav[aria-label=Tools] a.item')].map(a=>a.textContent.trim());"
            "return [n.length, n.every(t=>!/\\d/.test(t))];",
            "expect": [9, True],
        },
        {
            "label": "each tool name is a real link (so ctrl-click opens a tab)",
            "js": "return [...document.querySelectorAll('.sidebar .nav[aria-label=Tools] a.item')].every(a=>a.getAttribute('href').startsWith('/t/'));",
        },
        {
            "label": "the window button opens a popup window, not just a tab",
            "js": "let got=null; const o=window.open; window.open=(u,t,f)=>{got=got||[u,f];return {};};"
            "document.querySelector('.sidebar .pop').click(); window.open=o;"
            "return got && got[0].startsWith('/t/') && /popup=yes/.test(got[1]);",
        },
        {"waitFor": ".tile"},
        {"audit": FORBID},
        {"screenshot": str(shots / "overview.png")},
        {"click": "a.item[href='/t/site-audit']", "after": 600},
        {"waitFor": ".tabs"},
        {
            "label": "tabs",
            "js": "return [...document.querySelectorAll('.tabs button')].map(b=>b.textContent);",
            "expect": ["Run", "Dashboard", "About"],
        },
        *fill_and_submit({"url": "bad.example"}, "#main form button[type=submit]"),
        {"waitFor": ".checks"},
        *fill_and_submit({"url": "solar.example"}, "#main form button[type=submit]"),
        {"waitFor": ".checks"},
        {"expectText": ".ring", "contains": "100"},
        {"audit": FORBID},
        {"screenshot": str(shots / "site-audit.png")},
        {"click": "button[data-key=dashboard]", "after": 900},
        {"waitFor": ".chart-box svg"},
        {
            "label": "bars drawn",
            "js": "return document.querySelectorAll('.chart path.bar').length > 0;",
        },
        {
            "label": "dashboard counts both runs",
            "js": "return document.querySelectorAll('.tile .v')[1].textContent;",
            "expect": "2",
        },
        {
            "label": "score trend has a point per run",
            "js": "return document.querySelectorAll('.chart circle.dot').length;",
            "expect": 2,
        },
        {"audit": FORBID},
        {"screenshot": str(shots / "dashboard.png")},
        {"click": "button[data-key=about]", "after": 300},
        {"expectText": "[role=tabpanel]", "contains": "What Site Audit does"},
        {"click": "a.item[href='/t/lead-finder']", "after": 600},
        {
            "label": "a tool that is not live opens on About",
            "js": "return document.querySelector('.tabs [aria-selected=true]').textContent;",
            "expect": "About",
        },
        {"click": "button[data-key=run]", "after": 500},
        {"waitFor": ".notice.warn"},
        {
            "label": "a tool without an engine cannot be run",
            "js": "return document.querySelector('#main form button[type=submit]').disabled;",
        },
        {"click": "a.item[href='/settings']", "after": 900},
        {"waitFor": "#two-step .btn.primary"},
        {"click": "#two-step .btn.primary", "after": 700},
        {"waitFor": ".qr svg"},
        {
            "label": "QR code drew modules",
            "js": "return document.querySelector('.qr svg path').getAttribute('d').length > 500;",
        },
        {"screenshot": str(shots / "two-step-setup.png"), "of": "#two-step"},
        {
            "label": "enable 2-step with a code computed in the page",
            "js": TOTP_JS + "window.__secret = document.querySelector('.secret').textContent;"
            "const i=document.querySelector('#two-step input[name=code]'); i.value = await totp(window.__secret);"
            "document.querySelector('#two-step form button[type=submit]').click(); return true;",
            "after": 1200,
        },
        {"waitFor": ".codes"},
        {
            "label": "ten recovery codes shown once",
            "js": "return document.querySelectorAll('.codes div').length;",
            "expect": 10,
        },
        {"click": "#two-step .head-actions .btn.primary", "after": 700},
        {"expectText": "#two-step", "contains": "2-step verification is on"},
        {"expectNoEmpty": ["#sessions table"]},
        {"expectText": "#github", "contains": "personal access token"},
        {"audit": FORBID},
        {"screenshot": str(shots / "settings.png")},
        {
            "label": "dark theme",
            "js": "document.documentElement.dataset.theme='dark'; return true;",
        },
        {"click": "a.item[href='/app']", "after": 900},
        {"waitFor": ".tile"},
        {"screenshot": str(shots / "overview-dark.png")},
        {
            "label": "light theme again",
            "js": "document.documentElement.dataset.theme='light'; return true;",
        },
        {
            "label": "sign out",
            "js": "[...document.querySelectorAll('.sidebar button')].find(b=>b.textContent.includes('Sign out')).click(); return true;",
            "after": 900,
        },
        {"expectText": "h1", "contains": "Sign in"},
        {"screenshot": str(shots / "sign-in.png")},
        *fill_and_submit({"email": email, "password": pw}),
        {"expectText": "h1", "contains": "2-step verification"},
        {
            "label": "sign in through 2-step",
            "js": TOTP_JS
            + "const i=document.querySelector('input[name=code]'); i.value = await totp(window.__secret || '', 1);"
            "document.querySelector('form button[type=submit]').click(); return true;",
            "after": 1200,
        },
        {"waitFor": ".sidebar .nav"},
        {"expectText": ".who", "contains": "Ayesha Khan"},
    ]
    return {"url": f"{base}/register", "settle": 900, "steps": steps}


def mobile_plan(base: str, shots: Path) -> dict:
    pw = "tall-orange-river-42"
    no_sideways = {
        "label": "no sideways scroll at phone width",
        "js": "return document.documentElement.scrollWidth <= window.innerWidth;",
    }
    steps = [
        {"waitFor": "form"},
        no_sideways,
        *fill_and_submit(
            {"name": "Bilal", "email": "bilal@example.com", "password": pw, "confirm": pw}
        ),
        {"waitFor": ".topbar"},
        no_sideways,
        {"screenshot": str(shots / "mobile-overview.png")},
        {"click": ".topbar button", "after": 400},
        {
            "label": "menu opens the tool list",
            "js": "return document.querySelector('.shell').classList.contains('nav-open');",
        },
        {"screenshot": str(shots / "mobile-menu.png")},
        {"click": "a.item[href='/t/site-audit']", "after": 600},
        {
            "label": "choosing a tool closes the menu",
            "js": "return !document.querySelector('.shell').classList.contains('nav-open');",
        },
        *fill_and_submit({"url": "bad.example"}, "#main form button[type=submit]"),
        {"waitFor": ".checks"},
        no_sideways,
        {"screenshot": str(shots / "mobile-audit.png")},
    ]
    return {"url": f"{base}/register", "settle": 900, "steps": steps}


def main() -> int:
    chrome = next((c for c in CHROME if Path(c).exists()), shutil.which("chrome"))
    if not chrome:
        print("No Chrome found.")
        return 2
    shots = ROOT / "docs"
    shots.mkdir(exist_ok=True)
    os.environ["RANKLOOM_QUIET"] = "1"
    site_audit.audit.__defaults__ = (fetcher(PAGES),)
    engines.ENGINES["site-audit"] = site_audit.run
    failed = 0
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as data:
        app = server.App(data, "http://127.0.0.1")
        srv = server.make_server(app, "127.0.0.1", 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        try:
            for name, plan, width in (
                ("desktop", desktop_plan(base, shots), "1280"),
                ("phone", mobile_plan(base, shots), "390"),
            ):
                plan_path = Path(data) / f"{name}.json"
                plan_path.write_text(json.dumps(plan))
                proc = subprocess.run(
                    ["node", str(ROOT / "scripts" / "ui_smoke.mjs"), chrome, str(plan_path)],
                    capture_output=True,
                    text=True,
                    env={**os.environ, "UI_WIDTH": width},
                    timeout=300,
                )
                report = (
                    json.loads(proc.stdout or "{}") if proc.stdout.strip().startswith("{") else {}
                )
                ok = proc.returncode == 0
                failed += not ok
                print(
                    f"{name}: {'ok' if ok else 'FAILED'} - {len(report.get('log', []))} steps passed"
                )
                for line in report.get("failures", []) + report.get("problems", []):
                    print("   ", line)
                if not report:
                    print(proc.stdout[-2000:], proc.stderr[-2000:])
        finally:
            srv.shutdown()
            srv.server_close()
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
