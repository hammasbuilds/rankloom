"""Lead Finder: businesses of a trade in a city, each website quickly audited and ranked by how
much our help would change for them, and first messages that quote what was found.

Business Search reads OpenStreetMap (free, no key). Its coverage varies by country - in
Pakistan most listings carry a phone but no website - so the result always says how many
businesses had a website, and a business without one is itself a lead.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from .. import sources
from ..db import now
from ..netguard import FetchFailed, FetchRefused
from .common import (
    FAIL,
    PASS,
    WARN,
    Context,
    InputProblem,
    drafts,
    facts,
    headline,
    table,
    view,
)
from .site_audit import audit, normalise_url

# What each failed check costs the business, in words an owner understands.
PLAIN = {
    "https": "the site is not secure (no padlock), and browsers warn visitors away",
    "status": "the website does not load properly",
    "viewport": "the site is not set up for phones, where most of your customers are",
    "title": "the home page has no title, so Google has nothing to show for it",
    "description": "there is no search description, so Google writes its own",
    "speed": "the site is slow to load, and slow sites lose visitors before they see anything",
    "indexable": "the site tells Google not to list it",
    "robots": "the site blocks search engines completely",
    "h1": "the home page has no clear main heading",
    "schema": "Google and AI assistants are not told what the business is or where it is",
    "alt": "images have no descriptions, which costs image-search traffic",
    "social": "shared links show no preview card",
    "content": "the home page has very little text for Google to rank",
}
# The same checks when they only warn. A check missing here is not worth a stranger's time.
WARN_PLAIN = {
    "description": "the search description is too short or too long, so Google may rewrite it",
    "speed": "the site takes a few seconds to load, which loses some visitors",
    "h1": "the home page has more than one main heading, which blurs what it is about",
    "schema": "Google and AI assistants are not told what the business is or where it is",
    "content": "the home page has very little text for Google to rank",
}
QUICK = (
    "https",
    "status",
    "viewport",
    "title",
    "description",
    "speed",
    "indexable",
    "robots",
    "h1",
    "schema",
)


def quick_audit(url: str, fetch) -> dict:
    try:
        r = audit(url, fetch=fetch)
    except (FetchFailed, FetchRefused) as exc:
        return {
            "reachable": False,
            "error": str(exc),
            "problems": ["the website does not load"],
            "score": 0,
        }
    bad = [c for c in r["checks"] if c["status"] != PASS and c["id"] in QUICK]
    bad.sort(key=lambda c: (c["status"] != FAIL, -c["weight"]))
    problems = []
    for c in bad:
        # A warning is a milder fact than a failure; quoting the failure's sentence for it would
        # tell an owner something untrue (a missing robots.txt does not block search engines).
        said = PLAIN.get(c["id"]) if c["status"] == FAIL else WARN_PLAIN.get(c["id"])
        if said:
            problems.append(said)
    return {
        "reachable": True,
        "score": r["score"],
        "final_url": r["final_url"],
        "problems": problems,
        "failed_ids": [c["id"] for c in bad],
    }


def opportunity(lead: dict) -> int:
    """0-100: how much a business stands to gain from what we found.

    A business the directory lists without a website is not proven to lack one - chains often
    just have no website tag - so it ranks as a lead to check, below a website we checked and
    found weak."""
    if not lead.get("website"):
        return 50
    qa = lead.get("audit") or {}
    if not qa.get("reachable", True):
        return 85
    return max(5, min(80, 100 - int(qa.get("score", 50))))


def save_lead(db, user_id: int, lead: dict) -> int:
    t = now()
    db.run(
        "INSERT INTO leads (user_id, name, category, website, phone, email, address, city, "
        "source, score, problems, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(user_id, name, website) DO UPDATE SET score = excluded.score, "
        "problems = excluded.problems, phone = CASE WHEN excluded.phone != '' THEN excluded.phone "
        "ELSE leads.phone END, updated_at = excluded.updated_at",
        user_id,
        lead["name"][:200],
        lead.get("category", "")[:80],
        lead.get("website", "")[:300],
        lead.get("phone", "")[:60],
        lead.get("email", "")[:200],
        lead.get("address", "")[:300],
        lead.get("city", "")[:100],
        lead.get("source", "")[:120],
        lead.get("opportunity"),
        json.dumps(lead.get("problems", [])),
        t,
        t,
    )
    row = db.one(
        "SELECT id FROM leads WHERE user_id = ? AND name = ? AND website = ?",
        user_id,
        lead["name"][:200],
        lead.get("website", "")[:300],
    )
    return row["id"]


def search(
    trade: str,
    city: str,
    ctx: Context,
    find=None,
    budget_s: float = 70.0,
    audit_limit: int = 25,
    country: str = "",
) -> dict:
    if not trade or not city:
        raise InputProblem("Enter both a trade (e.g. dentist) and a city.")
    t0 = time.monotonic()
    try:
        found = (find or sources.places)(trade, city, country=country)
    except sources.SourceFailed as exc:
        raise InputProblem(f"The business directory did not answer ({exc}). Try again.") from exc
    with_site = [b for b in found if b["website"]]
    to_audit = with_site[:audit_limit]

    def run_one(b):
        if time.monotonic() - t0 > budget_s:
            return b, None
        site = b["website"] if "://" in b["website"] else "https://" + b["website"]
        return b, quick_audit(site, ctx.fetch)

    audited = 0
    with ThreadPoolExecutor(4) as pool:
        for b, qa in pool.map(run_one, to_audit):
            if qa is not None:
                b["audit"] = qa
                audited += 1
    for b in found:
        if b.get("region"):
            b["address"] = ", ".join(x for x in (b.get("address", ""), b["region"]) if x)
        if not b["website"]:
            b["problems"] = ["website not listed in the directory (check before contacting)"]
        elif b.get("audit"):
            b["problems"] = b["audit"]["problems"]
        else:
            b["problems"] = ["not audited (time budget)"]
        b["opportunity"] = opportunity(b)
        if ctx.db is not None:
            b["id"] = save_lead(ctx.db, ctx.user_id, b)
    found.sort(key=lambda b: -b["opportunity"])
    return {
        "trade": trade,
        "city": city,
        "found": len(found),
        "with_site": len(with_site),
        "audited": audited,
        "leads": found,
        "seconds": round(time.monotonic() - t0, 1),
    }


def run_search(fields: dict, ctx: Context):
    r = search(
        str(fields.get("trade", "")).strip(),
        str(fields.get("city", "")).strip(),
        ctx,
        country=str(fields.get("country", "")).strip(),
    )
    rows = []
    for b in r["leads"]:
        site = b["website"]
        rows.append(
            [
                b["name"],
                {
                    "text": urlsplit(site if "://" in site else "https://" + site).netloc or site,
                    "href": site if "://" in site else "https://" + site,
                }
                if site
                else "none",
                b["phone"] or "-",
                {
                    "status": FAIL
                    if b["opportunity"] >= 70
                    else WARN
                    if b["opportunity"] >= 35
                    else PASS,
                    "text": str(b["opportunity"]),
                },
                "; ".join(b["problems"][:2]) or "-",
                {"text": "Draft message", "route": f"/t/lead-finder/outreach?lead={b['id']}"}
                if b.get("id")
                else "",
            ]
        )
    r["view"] = view(
        headline(
            f"{r['found']} {r['trade']} businesses in {r['city']}",
            f"{r['with_site']} have a website, {r['audited']} audited in {r['seconds']} s. "
            "All saved to Lead List.",
            None,
        ),
        table(
            "Leads, most to gain first",
            ["Business", "Website", "Phone", "Opportunity", "Found", ""],
            rows,
            "Opportunity: higher means more to gain. 50 = no website listed - confirm before "
            "contacting, since the directory often lacks one a business has.",
        ),
    )
    return (
        f"{r['found']} {r['trade']} leads in {r['city']} ({r['with_site']} with a website)",
        None,
        r,
    )


# --- outreach ----------------------------------------------------------------------------------


def write_drafts(
    business: str, website: str, problems: list[str], sender: str, offer: str
) -> list[dict]:
    sender = sender or "[your name]"
    offer = offer or "a free 15-minute walkthrough of the full audit"
    if not website:
        hook = (
            f"I looked for {business}'s website and could not find one - which means "
            "anyone searching for what you offer finds your competitors first."
        )
        found = ["no website", "nothing for Google or Maps to show"]
        subject = f"{business} - customers searching online cannot find you"
    else:
        top = problems[:3] or ["a few things that are costing you visitors"]
        hook = f"I ran a quick check on {website} and found that {top[0]}."
        found = top
        subject = f"{business} - {len(found)} things I noticed on your website"
    bullet_lines = "\n".join(f"- {p[0].upper() + p[1:]}" for p in found)
    email = (
        f"Subject: {subject}\n\n"
        f"Hi {business} team,\n\n{hook}\n\nWhat I found:\n{bullet_lines}\n\n"
        f"Each of these is fixable, usually within a week. I would be glad to offer {offer}, "
        f"with no obligation.\n\nWould a short call this week suit you?\n\n{sender}"
    )
    short = (
        f"Hi {business} - {hook} I put together the full list of fixes; happy to share it "
        f"free if useful. - {sender}"
    )
    whatsapp = (
        f"Assalam o Alaikum! {hook} I can send you the full report free of charge - "
        f"shall I share it here? - {sender}"
    )
    return [
        {"label": "Email", "text": email},
        {"label": "LinkedIn or Instagram message", "text": short},
        {"label": "WhatsApp", "text": whatsapp},
    ]


def run_outreach(fields: dict, ctx: Context):
    lead = None
    lead_id = str(fields.get("lead", "")).strip()
    if lead_id.isdigit() and ctx.db is not None:
        lead = ctx.db.one(
            "SELECT * FROM leads WHERE id = ? AND user_id = ?", int(lead_id), ctx.user_id
        )
        if lead is None:
            raise InputProblem("That lead is not in your list.")
    business = str(fields.get("business", "")).strip() or (lead["name"] if lead else "")
    website = str(fields.get("site", "")).strip() or (lead["website"] if lead else "")
    if not business:
        raise InputProblem("Enter the business name, or open this from a lead.")
    problems: list[str] = []
    checked = False
    if website:
        qa = quick_audit(
            normalise_url(website if "://" in website else "https://" + website), ctx.fetch
        )
        problems, checked = qa["problems"], True
    elif lead:
        problems = json.loads(lead["problems"])
    items = write_drafts(
        business,
        website,
        problems,
        str(fields.get("sender", "")).strip(),
        str(fields.get("offer", "")).strip(),
    )
    if lead is not None and ctx.db is not None:
        ctx.db.run(
            "UPDATE leads SET problems = ?, updated_at = ? WHERE id = ?",
            json.dumps(problems),
            now(),
            lead["id"],
        )
    r = {
        "business": business,
        "website": website,
        "problems": problems,
        "drafts": items,
        "lead": lead["id"] if lead else None,
    }
    r["view"] = view(
        headline(
            f"First message to {business}",
            ("Based on a fresh check of " + website)
            if checked
            else "No website found - the message offers one",
            None,
        ),
        facts(
            "What the message quotes",
            [(f"Point {i + 1}", p) for i, p in enumerate(problems[:3] or ["no website"])],
        ),
        drafts(
            "Drafts",
            items,
            "Edit before sending. Send them yourself, one at a time."
            + (
                ""
                if website
                else " Confirm they really have no website first - directories often miss one."
            ),
        ),
    )
    return f"Outreach drafts for {business}", None, r
