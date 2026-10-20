"""Drive the real app in headless Chrome, end to end, and save the screenshots in docs/.

    uv run python scripts/ui_check.py

The server runs in this process on a free port with a throwaway data folder. Websites are fixture
pages, and autocomplete and OpenStreetMap answers are recordings of real replies, so the walk is
the same on every machine. It registers; runs every sub-tool that can run without an AI engine;
uses Lead List and Clients; imports a Search Console export through the real file input; prints
a monthly report; checks the two AI sub-tools say what they need; turns on 2-step verification
with a code the page computes; signs out and back in; and repeats the core pages at phone width.
"""

from __future__ import annotations

import base64
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_engines import LOCAL  # noqa: E402
from test_site_audit import BAD, GOOD  # noqa: E402

from rankloom import server, sources  # noqa: E402
from rankloom.netguard import Response  # noqa: E402

WORDS = "Rooftop solar panels inverters net metering battery backup installation. " * 40
SOLAR_PAGES = {
    "/": GOOD.replace(
        "</body>",
        "<a href=/prices>Prices</a><a href=/about>About</a>"
        "<a href=/contact>Contact</a><a href=/old-offer>Offer</a></body>",
    ),
    "/prices": f"<html lang=en><head><title>Solar prices in Lahore</title></head><body>"
    f"<h1>Prices</h1><p>{WORDS}</p></body></html>",
    "/about": "<html lang=en><head><title>Solar prices in Lahore</title></head><body>"
    "<h1>About</h1><p>We install panels.</p></body></html>",
    "/contact": "<html lang=en><head><title>Contact</title></head><body><p>Call us</p></body></html>",
    "/robots.txt": "User-agent: *\nAllow: /\n\nUser-agent: GPTBot\nDisallow: /\n\n"
    "Sitemap: https://solar.example/sitemap.xml\n",
    "/sitemap.xml": "<urlset><url><loc>https://solar.example/</loc></url>"
    "<url><loc>https://solar.example/prices</loc></url></urlset>",
}
SITES = {"solar.example": SOLAR_PAGES, "bad.example": {"/": BAD}, "smile.example": {"/": LOCAL}}


def fixture_fetch(url: str) -> Response:
    parts = urlsplit(url)
    pages = SITES.get(parts.netloc.removeprefix("www."), {})
    path = parts.path or "/"
    if path not in pages:
        return Response(
            url=url,
            status=404,
            headers={"content-type": "text/html"},
            body=b"<h1>Not found</h1>",
            elapsed_ms=90,
        )
    ctype = "text/plain" if path.endswith(".txt") else "text/html; charset=utf-8"
    return Response(
        url=f"https://{parts.netloc}{path}",
        status=200,
        headers={"content-type": ctype, "content-encoding": "gzip"},
        body=pages[path].encode(),
        elapsed_ms=140,
    )


# Recorded from real autocomplete replies on 2026-10-20 (google, "solar lahore" and neighbours).
RECORDED = [
    "solar lahore",
    "solar panel price in lahore",
    "lahore solar market",
    "solar installation lahore",
    "how much does solar cost in lahore",
    "best solar company in lahore",
    "solar panel lahore price list",
    "solar lahore near me",
    "what is net metering lahore",
    "solar inverter price in pakistan",
    "is solar worth it in pakistan",
    "solar vs wapda bill",
    "dentist lahore",
    "best dentist in lahore",
    "dentist near me lahore",
    "how much is root canal in lahore",
]


def recorded_suggest(query: str, country: str = "pk", language: str = "en"):
    words = set(query.lower().split())
    hits = [p for p in RECORDED if words & set(p.split())]
    return "google", hits[:10]


def recorded_places(trade: str, city: str, limit: int = 50, country: str = ""):
    return [
        {
            "name": "Sunrise Dental",
            "category": "dentist",
            "website": "",
            "phone": "+92 42 3577 1234",
            "email": "",
            "address": "Main Boulevard, Gulberg",
            "city": city,
            "source": "OpenStreetMap",
        },
        {
            "name": "Old Town Dental",
            "category": "dentist",
            "website": "bad.example",
            "phone": "0300 1111111",
            "email": "",
            "address": "Mall Road",
            "city": city,
            "source": "OpenStreetMap",
        },
        {
            "name": "Smile Care",
            "category": "dentist",
            "website": "smile.example",
            "phone": "0300 1234567",
            "email": "",
            "address": "12 Main Boulevard",
            "city": city,
            "source": "OpenStreetMap",
        },
    ]


def gsc_zip_b64() -> str:
    head = (
        "Last 28 days Clicks,Previous 28 days Clicks,Last 28 days Impressions,"
        "Previous 28 days Impressions,Last 28 days CTR,Previous 28 days CTR,"
        "Last 28 days Position,Previous 28 days Position"
    )
    queries = [
        ("solar panel price in lahore", 120, 150, 5400, 5200, "2.2%", "2.9%", 4.2, 3.6),
        ("solar installation lahore", 64, 40, 2100, 1800, "3.05%", "2.2%", 6.1, 7.9),
        ("net metering lahore", 9, 12, 2600, 2300, "0.35%", "0.52%", 11.4, 10.8),
        ("solar inverter price", 3, 2, 1900, 1500, "0.16%", "0.13%", 14.2, 16.0),
        ("best solar company lahore", 31, 35, 900, 950, "3.4%", "3.7%", 3.1, 2.9),
        ("solar battery backup", 0, 4, 1300, 1100, "0%", "0.36%", 18.5, 15.2),
    ]
    pages = [
        ("https://solar.example/", 150, 170, 7000, 6800, "2.1%", "2.5%", 5.0, 4.6),
        ("https://solar.example/prices", 70, 55, 4100, 3600, "1.7%", "1.5%", 7.8, 9.0),
        ("https://solar.example/net-metering", 7, 20, 2400, 2200, "0.29%", "0.9%", 12.0, 9.5),
    ]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            "Queries.csv",
            "Top queries," + head + "\n" + "\n".join(",".join(map(str, q)) for q in queries),
        )
        z.writestr(
            "Pages.csv",
            "Top pages," + head + "\n" + "\n".join(",".join(map(str, p)) for p in pages),
        )
    return base64.b64encode(buf.getvalue()).decode()


CHROME = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
]
FORBID = ["undefined", "NaN", "[object Object]", "null"]

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


def fill_and_submit(
    values: dict, button="#main form button[type=submit]", after=1200
) -> list[dict]:
    steps = [{"fill": f"#main [name={k}]", "value": v} for k, v in values.items()]
    steps.append({"click": button, "after": after})
    return steps


def nav(path: str, after: int = 900) -> dict:
    return {"click": f".sidebar a[href='{path}']", "after": after}


def run_sub(
    path: str,
    values: dict,
    wait: str = ".result",
    shot: str | None = None,
    shots: Path | None = None,
) -> list[dict]:
    steps = [
        nav(path),
        {"waitFor": "#main form"},
        *fill_and_submit(values),
        {"waitFor": wait},
        {
            "label": f"no error notice after running {path}",
            "js": "return !document.querySelector('#panel .notice.bad:not([hidden])');",
        },
        {"audit": FORBID},
    ]
    if shot and shots:
        steps.append({"screenshot": str(shots / shot)})
    return steps


def auth_steps(name: str, email: str, pw: str) -> list[dict]:
    return [
        {"waitFor": "form"},
        {
            "label": "light theme for the screenshots",
            "js": "document.documentElement.dataset.theme='light'; return true;",
        },
        *[
            {"fill": f"input[name={k}]", "value": v}
            for k, v in {"name": name, "email": email, "password": pw, "confirm": pw}.items()
        ],
        {"click": "form button[type=submit]", "after": 900},
        {"waitFor": ".sidebar .nav"},
    ]


def desktop_plan(base: str, shots: Path) -> dict:
    email, pw = "ayesha@example.com", "tall-orange-river-42"
    zip_b64 = gsc_zip_b64()
    steps = [
        *auth_steps("Ayesha Khan", email, pw),
        {
            "label": "seven tool names in the sidebar, no numbers",
            "js": "const n=[...document.querySelectorAll('.sidebar .nav.tools > li.tool > .row > a.item')].map(a=>a.textContent.trim());"
            "return [n, n.some(t=>/\\d/.test(t))];",
            "expect": [
                [
                    "Site Audit",
                    "AI Visibility",
                    "Lead Finder",
                    "Search Performance",
                    "Content Studio",
                    "Client Reports",
                    "Job Radar",
                ],
                False,
            ],
        },
        {
            "label": "every tool and sub-tool has a window button",
            "js": "return document.querySelectorAll('.sidebar .nav.tools .pop').length;",
            "expect": 7 + 25,
        },
        {
            "label": "the window button opens a popup window, not just a tab",
            "js": "let got=null; const o=window.open; window.open=(u,t,f)=>{got=got||[u,f];return {};};"
            "document.querySelector('.sidebar .nav.tools .pop').click(); window.open=o;"
            "return got && got[0]==='/t/site-audit' && /popup=yes/.test(got[1]);",
        },
        {"waitFor": ".tile"},
        {"screenshot": str(shots / "overview.png")},
        nav("/t/site-audit"),
        {"waitFor": ".subgrid"},
        {
            "label": "opening a tool expands its sub-tools in the sidebar",
            "js": "return [...document.querySelectorAll('li.tool.open .subnav a')].map(a=>a.textContent);",
            "expect": ["Page Audit", "Site Crawl", "Local SEO Check"],
        },
        {"screenshot": str(shots / "tool-home.png")},
        *run_sub("/t/site-audit/page", {"url": "bad.example"}, ".result .checks"),
        *run_sub(
            "/t/site-audit/page",
            {"url": "solar.example"},
            ".result .checks",
            "page-audit.png",
            shots,
        ),
        {"expectText": ".result .ring", "contains": "100"},
        nav("/t/site-audit/crawl"),
        {"waitFor": "#main form"},
        *fill_and_submit({"url": "solar.example"}),
        {"waitFor": ".result table"},
        {
            "label": "crawl read the linked pages and flagged the broken one",
            "js": "const t=document.querySelector('.result').innerText; return t.includes('/old-offer') && t.includes('Read 5 of');",
        },
        {"screenshot": str(shots / "site-crawl.png")},
        nav("/t/site-audit/local"),
        {"waitFor": "#main form"},
        *fill_and_submit({"url": "smile.example", "city": "Lahore"}),
        {"waitFor": ".result .checks"},
        {
            "label": "a complete local page scores 100",
            "js": "const r=document.querySelector('#panel .result'); return [r.querySelector('h2').textContent, r.querySelector('.ring text').textContent];",
            "expect": ["https://smile.example/", "100"],
        },
        nav("/t/ai-visibility/readiness"),
        {"waitFor": "#main form"},
        *fill_and_submit({"url": "solar.example"}),
        {"waitFor": ".result table"},
        {
            "label": "GPTBot shows as blocked",
            "js": "return [...document.querySelectorAll('.result tr')].some(r=>r.innerText.includes('GPTBot') && r.innerText.includes('blocked'));",
        },
        {"screenshot": str(shots / "ai-readiness.png")},
        *run_sub(
            "/t/ai-visibility/questions",
            {"niche": "dentist", "city": "Lahore", "brand": "Smile Care"},
            ".result ul.plain",
        ),
        nav("/t/ai-visibility/answers"),
        {"waitFor": ".notice.warn"},
        {
            "label": "Answer Check says it needs an AI engine and cannot be run",
            "js": "return document.querySelector('#main form button[type=submit]').disabled && document.querySelector('.notice.warn').innerText.includes('AI engine');",
        },
        nav("/t/lead-finder/search"),
        {"waitFor": "#main form"},
        *fill_and_submit({"trade": "dentists", "city": "Lahore"}),
        {"waitFor": ".result table"},
        {
            "label": "leads are ranked by opportunity, most to gain first",
            "js": "const v=[...document.querySelectorAll('.result tbody tr')].map(r=>+r.cells[3].innerText);"
            "return [v.length, v.every((x,i)=>!i||v[i-1]>=x)];",
            "expect": [3, True],
        },
        {"screenshot": str(shots / "lead-search.png")},
        nav("/t/lead-finder/list"),
        {"waitFor": "table.leads tbody tr"},
        {
            "label": "three saved leads",
            "js": "return document.querySelectorAll('table.leads tbody tr').length;",
            "expect": 3,
        },
        {"select": "table.leads tbody tr select", "value": "contacted"},
        {
            "label": "status saved",
            "js": "await new Promise(r=>setTimeout(r,600)); const d=await (await fetch('/api/leads')).json(); return d.leads.filter(l=>l.status==='contacted').length;",
            "expect": 1,
        },
        {"screenshot": str(shots / "lead-list.png")},
        {"click": "table.leads tbody tr:nth-child(2) a.btn", "after": 1200},
        {"expectText": "#main .notice", "contains": "Writing to lead"},
        {"click": "#main form button[type=submit]", "after": 1500},
        {"waitFor": ".result .drafts"},
        {
            "label": "three drafts",
            "js": "return document.querySelectorAll('.result .draft').length;",
            "expect": 3,
        },
        {"screenshot": str(shots / "outreach.png")},
        nav("/t/search-performance/import"),
        {"waitFor": "#main form"},
        {"fill": "#main [name=site]", "value": "solar.example"},
        {
            "label": "attach a Search Console export to the real file input",
            "js": f"const b=atob('{zip_b64}'); const u=new Uint8Array(b.length); for(let i=0;i<b.length;i++) u[i]=b.charCodeAt(i);"
            "const dt=new DataTransfer(); dt.items.add(new File([u],'solar.example-Performance.zip',{type:'application/zip'}));"
            "const i=document.querySelector('#main input[type=file]'); i.files=dt.files; return i.files.length;",
            "expect": 1,
        },
        {"click": "#main form button[type=submit]", "after": 1500},
        {"waitFor": ".result table"},
        {"expectText": ".result", "contains": "6 queries and 3 pages"},
        nav("/t/search-performance/opportunities"),
        {"waitFor": "#main select option[value]"},
        {"click": "#main form button[type=submit]", "after": 1500},
        {"waitFor": ".result table"},
        {
            "label": "net metering is a striking-distance query",
            "js": "return document.querySelector('.result').innerText.includes('net metering lahore');",
        },
        {"audit": FORBID},
        {"screenshot": str(shots / "opportunities.png")},
        nav("/t/search-performance/changes"),
        {"waitFor": "#main select option[value]"},
        {"click": "#main form button[type=submit]", "after": 1500},
        {"waitFor": ".result table"},
        {"expectText": ".result h2", "contains": "Clicks 245"},
        {"screenshot": str(shots / "changes.png")},
        *run_sub(
            "/t/content-studio/keywords",
            {"seed": "solar lahore"},
            ".result ul.plain",
            "keywords.png",
            shots,
        ),
        *run_sub("/t/content-studio/brief", {"topic": "solar lahore"}, ".result ul.plain"),
        *run_sub(
            "/t/content-studio/grade",
            {"keyword": "solar", "url": "solar.example/prices"},
            ".result .checks",
        ),
        nav("/t/content-studio/draft"),
        {"waitFor": ".notice.warn"},
        nav("/t/client-reports/clients"),
        {"waitFor": "#panel .card"},
        {"click": "#panel .card-head .btn.primary", "after": 600},
        {"fill": "#panel [name=name]", "value": "Sun Power Lahore"},
        {"fill": "#panel [name=website]", "value": "solar.example"},
        {"fill": "#panel [name=city]", "value": "Lahore"},
        {"fill": "#panel [name=brand]", "value": "Ayesha Digital"},
        {
            "label": "link the imported Search Console report",
            "js": "await new Promise(r=>setTimeout(r,500)); const s=document.querySelector('#panel select[name=gsc_dataset]'); s.value=s.options[0].value; return !!s.value;",
        },
        {"click": "#panel form button[type=submit]", "after": 1200},
        {"expectText": "#panel table", "contains": "Sun Power Lahore"},
        {"click": "#panel table a.btn.primary", "after": 1000},
        {"waitFor": "#main select option[value]"},
        {"click": "#main form button[type=submit]", "after": 2500},
        {"waitFor": ".result.report"},
        {
            "label": "the report has search numbers, fixes and the month's work",
            "js": "const t=document.querySelector('.result.report').innerText; return ['Google search results','What to fix next','Work done this month','Sun Power Lahore'].every(x=>t.includes(x));",
        },
        {"audit": FORBID},
        {"screenshot": str(shots / "client-report.png")},
        nav("/t/site-audit"),
        {"click": "button[data-key=dashboard]", "after": 1200},
        {"waitFor": ".chart-box svg"},
        {
            "label": "dashboard lists every sub-tool with its runs",
            "js": "return [...document.querySelectorAll('#panel table')[0].querySelectorAll('tbody tr')].map(r=>r.cells[0].innerText+':'+r.cells[1].innerText);",
            "expect": ["Page Audit:2", "Site Crawl:1", "Local SEO Check:1"],
        },
        {"audit": FORBID},
        {"screenshot": str(shots / "dashboard.png")},
        {"click": "button[data-key=about]", "after": 300},
        {"expectText": "#panel", "contains": "What Site Audit does"},
        # Job Radar, against a fixture job-radar folder
        nav("/t/job-radar"),
        {"waitFor": ".subgrid"},
        {
            "label": "Job Radar has its seven pages",
            "js": "return document.querySelectorAll('.subgrid .subcard').length;",
            "expect": 7,
        },
        nav("/t/job-radar/jobs"),
        {"waitFor": ".chips .chip"},
        {
            "label": "every country with a role is a chip",
            "js": "return [...document.querySelectorAll('.chips .chip')].map(c=>c.firstChild.textContent).sort();",
            "expect": ["Germany", "Not stated", "Pakistan", "Singapore", "United Kingdom"],
        },
        {"screenshot": str(shots / "job-radar-jobs.png")},
        {
            "js": "[...document.querySelectorAll('.chips .chip')].find(c=>c.firstChild.textContent==='Singapore').click(); return true;",
            "after": 900,
        },
        {"waitFor": "table.jobs tbody tr"},
        {
            "label": "a country chip filters to that country",
            "js": "return [...document.querySelectorAll('table.jobs tbody tr')].map(r=>r.cells[1].innerText);",
            "expect": ["Grab"],
        },
        {
            "label": "the filter is in the address, so a new window opens on it",
            "js": "return location.search.includes('country=Singapore');",
        },
        {"js": "document.querySelector('.toolbar .btn.ghost').click(); return true;", "after": 900},
        {"waitFor": "table.jobs tbody tr"},
        {"select": "#panel select[aria-label='Terms']", "value": "Small contract", "after": 900},
        {"js": "await new Promise(r=>setTimeout(r,900)); return true;"},
        {
            "label": "terms filter",
            "js": "return [...document.querySelectorAll('table.jobs tbody tr')].map(r=>r.cells[1].innerText);",
            "expect": ["Mercor"],
        },
        {"js": "document.querySelector('.toolbar .btn.ghost').click(); return true;", "after": 900},
        {
            "js": "document.querySelector('#jr-reach').click(); await new Promise(r=>setTimeout(r,900)); return true;"
        },
        {
            "label": "only reachable roles hides the one that refuses sponsorship",
            "js": "return [...document.querySelectorAll('table.jobs tbody tr')].map(r=>r.cells[1].innerText).includes('Zaizi');",
            "expect": False,
        },
        {"audit": FORBID},
        nav("/t/job-radar/fellowships"),
        {"waitFor": "#panel table"},
        {"expectText": "#panel", "contains": "Source: Greenhouse 2026-10-20"},
        nav("/t/job-radar/pakistan"),
        {"waitFor": "#panel table"},
        {"expectText": "#panel", "contains": "Assistant Director (IT)"},
        nav("/t/job-radar/yc"),
        {"waitFor": "#panel table"},
        {
            "label": "YC shows a real profile and a labelled search",
            "js": "return [...document.querySelectorAll('#panel tbody tr')].map(r=>r.cells[3].innerText);",
            "expect": ["Profile", "Search"],
        },
        {"select": "#panel select[aria-label='Hiring']", "value": "0", "after": 900},
        {
            "js": "await new Promise(r=>setTimeout(r,900)); return [...document.querySelectorAll('#panel tbody tr')].length;",
            "expect": 1,
            "label": "not-hiring filter",
        },
        {"screenshot": str(shots / "job-radar-yc.png")},
        nav("/t/job-radar/accelerators"),
        {"waitFor": "#panel .chip.on"},
        {
            "label": "the portfolio opens on the programme with the most AI roles",
            "js": "return document.querySelector('#panel .chip.on').firstChild.textContent;",
            "expect": "Techstars",
        },
        {
            "label": "AI roles only, and the portfolio keeps a company with no roles",
            "js": "const t=[...document.querySelectorAll('#panel table')];"
            " return [t[0].tBodies[0].rows.length, [...t[1].tBodies[0].rows].map(r=>r.cells[0].innerText)];",
            "expect": [2, ["Helgen", "Quiet Labs"]],
        },
        {"click": "#pf-junior", "after": 900},
        {
            "label": "no-senior filter leaves the computer vision role",
            "js": "await new Promise(r=>setTimeout(r,600)); return document.querySelector('#panel table tbody tr td').innerText;",
            "expect": "Computer Vision Engineer",
        },
        {"click": "#panel .chips .chip:not(.on)", "after": 900},
        {
            "label": "switching programme shows its own companies",
            "js": "await new Promise(r=>setTimeout(r,600)); return document.querySelector('#panel').innerText.includes('Antler portfolio companies');",
        },
        {"expectText": "#panel", "contains": "All accelerators and founder programmes"},
        {"audit": FORBID},
        nav("/t/job-radar/platforms"),
        {"waitFor": "#panel table"},
        {"expectText": "#panel", "contains": "AI training and evaluation roles open now"},
        nav("/t/job-radar/crawl"),
        {"waitFor": "#panel .head-actions .btn.primary"},
        {"click": "#panel .head-actions .btn.primary", "after": 4500},
        {
            "label": "a crawl started from the page runs and its log appears",
            "js": "return document.querySelector('pre.log').textContent.includes('crawl fixture done');",
        },
        {"audit": FORBID},
        nav("/settings"),
        {"waitFor": "#two-step .btn.primary"},
        {"click": "#two-step .btn.primary", "after": 700},
        {"waitFor": ".qr svg"},
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
        {"audit": FORBID},
        {
            "label": "dark theme",
            "js": "document.documentElement.dataset.theme='dark'; return true;",
        },
        nav("/app"),
        {"waitFor": ".tile"},
        {"screenshot": str(shots / "overview-dark.png")},
        {
            "label": "sign out",
            "js": "[...document.querySelectorAll('.sidebar button')].find(b=>b.textContent.includes('Sign out')).click(); return true;",
            "after": 900,
        },
        {"expectText": "h1", "contains": "Sign in"},
        {"fill": "input[name=email]", "value": email},
        {"fill": "input[name=password]", "value": pw},
        {"click": "form button[type=submit]", "after": 900},
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
    no_sideways = {
        "label": "no sideways scroll at phone width",
        "js": "return document.documentElement.scrollWidth <= window.innerWidth;",
    }
    steps = [
        *auth_steps("Bilal", "bilal@example.com", "tall-orange-river-42"),
        no_sideways,
        {"click": ".topbar button", "after": 400},
        {
            "label": "menu opens the tool list",
            "js": "return document.querySelector('.shell').classList.contains('nav-open');",
        },
        {"click": ".sidebar a[href='/t/site-audit']", "after": 700},
        {"click": ".topbar button", "after": 400},
        {"screenshot": str(shots / "mobile-menu.png")},
        {"click": ".sidebar a[href='/t/site-audit/page']", "after": 700},
        {
            "label": "choosing a sub-tool closes the menu",
            "js": "return !document.querySelector('.shell').classList.contains('nav-open');",
        },
        *fill_and_submit({"url": "bad.example"}),
        {"waitFor": ".result .checks"},
        no_sideways,
        {"screenshot": str(shots / "mobile-audit.png")},
        {
            "js": "history.pushState({}, '', '/t/lead-finder/search'); dispatchEvent(new PopStateEvent('popstate')); return true;",
            "after": 900,
        },
        *fill_and_submit({"trade": "dentists", "city": "Lahore"}),
        {"waitFor": ".result table"},
        no_sideways,
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
    os.environ.pop("RANKLOOM_AI", None)
    sources.suggest = recorded_suggest
    sources.places = recorded_places
    failed = 0
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as data:
        from test_jobradar_link import build

        radar = build(Path(data) / "job-radar")
        (radar / "scripts" / "fetch.py").write_text(
            "print('crawl fixture done')\n", encoding="utf-8"
        )
        os.environ["RANKLOOM_JOBRADAR_DIR"] = str(radar)
        os.environ.pop("JOBRADAR_DB", None)
        app = server.App(data, "http://127.0.0.1")
        app.fetch = fixture_fetch
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
                    timeout=600,
                )
                out = proc.stdout.strip()
                report = json.loads(out) if out.startswith("{") else {}
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
