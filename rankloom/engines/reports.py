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

MONTH = 30 * 86400


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
    try:
        sections["local"] = local_seo.audit(site, client.get("city", ""), ctx.fetch)
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
            sections["gsc"] = {
                "label": data["label"],
                "now": search_perf.totals(data["pages"] or data["queries"]),
                "before": search_perf.totals(data["pages"] or data["queries"], "prev_")
                if data.get("compare")
                else None,
                "top": sorted(data["queries"], key=lambda r: -r["clicks"])[:8],
            }
        except InputProblem:
            pass
    work = []
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
                work.append(r["summary"])
    sections["work"] = work[:25]
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
                fixes.append((c["status"], c["weight"], c["label"], c["fix"]))
    fixes.sort(key=lambda f: (f[0] != FAIL, -f[1]))
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
        gsc_block = table(
            "Google search results", ["", "This period", "Previous"], rows, gsc["label"]
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
    return f"Monthly report for {client['name']}", score, s
