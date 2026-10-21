"""Client Reports: one monthly page per client, assembled from fresh checks of their site and the
work recorded against it, ready to print or save as PDF."""

from __future__ import annotations

import datetime
import json
from urllib.parse import urlsplit

from ..db import now
from ..netguard import FetchFailed, FetchRefused
from . import ai_visibility, local_seo, search_perf, site_audit
from .common import (
    FAIL,
    PASS,
    Context,
    InputProblem,
    bullets,
    facts,
    headline,
    table,
    view,
)
from .site_audit import SPEED_CAVEAT

MONTH = 30 * 86400

# What each kind of run is called in a client's report. The run summaries are ours ("33 questions
# for dentist", "Imported amherstdental.com: 20 queries, 11 pages") and read as jargon there.
WORK = {
    ("site-audit", "page"): "Website health check",
    ("site-audit", "crawl"): "Full-site crawl for broken pages and duplicates",
    ("site-audit", "local"): "Local search and maps check",
    ("ai-visibility", "readiness"): "AI assistant readiness check",
    ("ai-visibility", "questions"): "Researched the questions customers ask AI assistants",
    ("ai-visibility", "answers"): "Checked how AI assistants answer about the business",
    ("search-performance", "import"): "Imported Google Search Console data",
    ("search-performance", "opportunities"): "Found search opportunities close to page one",
    ("search-performance", "changes"): "Compared search traffic between periods",
    ("content-studio", "keywords"): "Keyword research",
    ("content-studio", "brief"): "Content brief",
    ("content-studio", "draft"): "Content draft",
    ("content-studio", "grade"): "Graded page content against its keyword",
}
TOPIC_FIELDS = ("seed", "topic", "keyword", "niche")


def work_log(runs: list[dict]) -> list[str]:
    """One line per kind of work and topic, newest first, with how many times it was done."""
    seen: dict[str, list] = {}
    for r in runs:  # newest first
        label = WORK.get((r["tool"], r["subtool"]))
        if not label:
            continue
        inp = r["input"]
        topic = next((str(inp[k]).strip() for k in TOPIC_FIELDS if str(inp.get(k, "")).strip()), "")
        address = str(inp.get("url") or inp.get("site") or "").strip()
        if address:
            parts = urlsplit(address if "://" in address else "https://" + address)
            address = parts.netloc.lower().removeprefix("www.") + parts.path.rstrip("/")
        line = label + (f" of {address}" if address else "") + (f": “{topic}”" if topic else "")
        if line in seen:
            seen[line][0] += 1
        else:
            seen[line] = [1, r["created_at"]]
    out = []
    for line, (n, at) in seen.items():
        day = datetime.date.fromtimestamp(at).strftime("%d %b").lstrip("0")
        out.append(f"{line} ({day}" + (f", {n} times)" if n > 1 else ")"))
    return out


def _host(url: str) -> str:
    if not url:
        return ""
    return urlsplit(url if "://" in url else "https://" + url).netloc.lower().removeprefix("www.")


def previous_scores(db, user_id: int, host: str, subtool: str) -> int | None:
    for r in db.all(
        "SELECT input_json, score FROM runs WHERE user_id = ? AND subtool = ? AND "
        "score IS NOT NULL AND status = 'ok' AND created_at < ? ORDER BY id DESC "
        "LIMIT 50",
        user_id,
        subtool,
        now() - 3600,
    ):
        if _host(json.loads(r["input_json"]).get("url", "")) == host:
            return r["score"]
    return None


def build(client: dict, ctx: Context) -> dict:
    site = client["website"]
    if not site:
        raise InputProblem("Add the client's website first (Clients).")
    host = _host(site)
    sections: dict = {"client": client, "host": host, "generated_at": now()}
    try:
        sections["audit"] = site_audit.audit(site, fetch=ctx.fetch)
    except (FetchFailed, FetchRefused) as exc:
        sections["audit_error"] = str(exc)
    # A bot check is not the client's site: nothing from it goes in the report.
    if (sections.get("audit") or {}).get("blocked"):
        sections["audit_error"] = (
            f"The website check could not read the real page: {sections.pop('audit')['blocked']}."
        )
    else:
        try:
            # The client's market decides the local checks (WhatsApp advice only where it fits).
            sections["local"] = local_seo.audit(
                site, client.get("city", ""), ctx.fetch, country=client.get("country") or ""
            )
        except (FetchFailed, FetchRefused):
            pass
        try:
            sections["ai"] = ai_visibility.readiness(site, ctx.fetch)
        except (FetchFailed, FetchRefused):
            pass
    for key, sub in (("audit", "page"), ("local", "local"), ("ai", "readiness")):
        if key in sections:
            sections[f"{key}_before"] = previous_scores(ctx.db, ctx.user_id, host, sub)
    gsc_id = client.get("gsc_dataset")
    if gsc_id:
        try:
            data = search_perf.load_dataset(ctx, gsc_id)
            rows, source = search_perf.site_rows(data)
            sections["gsc"] = {
                "label": data["label"],
                "period": search_perf.period_text(data),
                "source": source,
                "labels": data.get("labels") or [],
                "now": search_perf.totals(rows),
                "before": search_perf.totals(rows, "prev_") if data.get("compare") else None,
                "top": sorted(data["queries"], key=lambda r: -r["clicks"])[:8],
            }
        except InputProblem:
            pass
    runs = []
    for r in ctx.db.all(
        "SELECT tool, subtool, summary, created_at, input_json FROM runs WHERE "
        "user_id = ? AND status = 'ok' AND created_at > ? ORDER BY id DESC",
        ctx.user_id,
        now() - MONTH,
    ):
        inp = json.loads(r["input_json"])
        if any(_host(str(v)) == host for k, v in inp.items() if k in ("url", "site")) or (
            client["name"].lower() in json.dumps(inp).lower()
        ):
            if r["tool"] != "client-reports":
                runs.append({**dict(r), "input": inp})
    # The agency's own account of the month comes first; the run log only backs it up.
    notes = [ln.strip(" -•\t") for ln in (client.get("work_notes") or "").splitlines()]
    sections["work"] = [ln for ln in notes if ln] + work_log(runs)[:25]
    return sections


def _delta(now_score, before) -> str:
    if before is None:
        return f"{now_score}/100"
    return f"{now_score}/100 (was {before}, {now_score - before:+d})"


def run_report(fields: dict, ctx: Context):
    cid = str(fields.get("client", "")).strip()
    if not cid.isdigit():
        raise InputProblem("Choose a client.")
    row = ctx.db.one("SELECT * FROM clients WHERE id = ? AND user_id = ?", int(cid), ctx.user_id)
    if row is None:
        raise InputProblem("That client is not in your list.")
    client = dict(row)
    s = build(client, ctx)
    month = datetime.date.today().strftime("%B %Y")
    head_facts = [("Website", s["host"]), ("Prepared", month)]
    if "audit" in s:
        head_facts.append(("Website health", _delta(s["audit"]["score"], s.get("audit_before"))))
    if "local" in s:
        head_facts.append(("Local search", _delta(s["local"]["score"], s.get("local_before"))))
    if "ai" in s:
        head_facts.append(("AI readiness", _delta(s["ai"]["score"], s.get("ai_before"))))
    fixes = []
    for key in ("audit", "local", "ai"):
        for c in (s.get(key) or {}).get("checks", []):
            if c["status"] != PASS and c["fix"]:
                fix = c["fix"]
                if c["id"] in ("speed", "slow"):
                    # The time was taken from our server; the client must not read it as fact.
                    fix = f"Speed {SPEED_CAVEAT}. {fix}"
                fixes.append((c["status"], c["weight"], c["label"], fix))
    fixes.sort(key=lambda f: (f[0] != FAIL, -f[1]))
    # Fixes the agency chose to leave out (it knows the client: a fix already agreed, or one it
    # does not offer). Matched on the issue name as the report shows it.
    hidden = {ln.strip().lower() for ln in (client.get("hide_fixes") or "").splitlines() if ln.strip()}
    left_out = [f for f in fixes if f[2].lower() in hidden]
    fixes = [f for f in fixes if f[2].lower() not in hidden]
    gsc = s.get("gsc")
    gsc_block = None
    if gsc:
        n, b = gsc["now"], gsc["before"]
        rows = [
            ["Clicks", f"{n['clicks']:,}", f"{b['clicks']:,}" if b else "-"],
            ["Impressions", f"{n['impressions']:,}", f"{b['impressions']:,}" if b else "-"],
            [
                "Click-through rate",
                search_perf.pct(n["ctr"]),
                search_perf.pct(b["ctr"]) if b else "-",
            ],
            ["Average position", f"{n['position']:.1f}", f"{b['position']:.1f}" if b else "-"],
        ]
        when = gsc["labels"] or ["This period", "Previous"]
        gsc_block = table(
            "Google search results",
            ["", when[0], when[1] if len(when) > 1 else "Previous"],
            rows,
            (gsc["period"] or "Period not stated in the export")
            + f" · from Google Search Console ({gsc['source']}).",
        )
    score = s["audit"]["score"] if "audit" in s else None
    s["view"] = view(
        headline(
            f"{client['name']} - {month}",
            f"Monthly search report · {s['host']}"
            + (f" · prepared by {client['brand']}" if client.get("brand") else ""),
            score,
        ),
        facts("Summary", head_facts),
        gsc_block,
        table(
            "Top searches bringing visitors",
            ["Search", "Clicks", "Position"],
            [[q["key"], int(q["clicks"]), f"{q.get('position', 0):.1f}"] for q in gsc["top"]],
        )
        if gsc and gsc["top"]
        else None,
        table(
            "What to fix next",
            ["", "Issue", "Fix"],
            [
                [{"status": st, "text": "urgent" if st == FAIL else "next"}, label, fix]
                for st, _, label, fix in fixes[:8]
            ],
        )
        if fixes
        else None,
        bullets(
            "Work done this month",
            s["work"] or ["No recorded work for this site in the last 30 days."],
        ),
        bullets("Could not check", [s["audit_error"]]) if s.get("audit_error") else None,
    )
    s["left_out"] = [label for _, _, label, _ in left_out]
    note = f" ({len(left_out)} fix{'es' if len(left_out) != 1 else ''} left out by choice)" if left_out else ""
    return f"Monthly report for {client['name']}{note}", score, s
