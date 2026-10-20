"""Lead Finder: businesses of a trade in a city, each website quickly audited and ranked by how
much our help would change for them, and first messages that quote what was found.

Business Search reads OpenStreetMap (free, no key). Its coverage varies by country - in
Pakistan most listings carry a phone but no website - so the result always says how many
businesses had a website, and a business without one is itself a lead.
"""

from __future__ import annotations

import json
import re
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
# Speed is not here on purpose: it is measured from this server, and a slow connection here
# would have us tell a stranger their site is slow when it is not. Only facts read from the
# page itself are quoted to a business.
QUICK = (
    "https",
    "status",
    "viewport",
    "title",
    "description",
    "indexable",
    "robots",
    "h1",
    "schema",
)


HTTPS_NO_REDIRECT = (
    "visitors who type the plain address are not sent to the secure (padlock) version of the site"
)
# A site that did not answer *this* server may be up for everyone else (a timeout here is often
# the connection, not the site). It is shown to you as a thing to check, never quoted to them.
UNREACHABLE = "the website did not answer our check - open it in a browser before mentioning it"
# A bot check answered instead of the site: what it shows says nothing about their website.
BLOCKED = "the website showed our check a bot-protection page - open it in a browser instead"


def quick_audit(url: str, fetch) -> dict:
    try:
        r = audit(url, fetch=fetch)
    except (FetchFailed, FetchRefused) as exc:
        return {
            "reachable": False,
            "error": str(exc),
            "problems": [UNREACHABLE],
            "score": 0,
        }
    if r.get("blocked"):
        return {
            "reachable": False,
            "blocked": True,
            "error": r["blocked"],
            "problems": [BLOCKED],
            "score": 0,
        }
    bad = [c for c in r["checks"] if c["status"] != PASS and c["id"] in QUICK]
    bad.sort(key=lambda c: (c["status"] != FAIL, -c["weight"]))
    # The listed http:// address not redirecting does not mean there is no padlock: Brooklyn
    # Court's https:// site worked. Ask once before saying the site is not secure.
    secure_works = False
    if any(c["id"] == "https" and c["status"] == FAIL for c in bad):
        host = urlsplit(r.get("final_url") or url).netloc
        try:
            secure = audit(f"https://{host}/", fetch=fetch)
            secure_works = not secure.get("blocked") and urlsplit(
                secure.get("final_url", "")).scheme == "https"
        except (FetchFailed, FetchRefused):
            secure_works = False
    problems = []
    for c in bad:
        # A warning is a milder fact than a failure; quoting the failure's sentence for it would
        # tell an owner something untrue (a missing robots.txt does not block search engines).
        said = PLAIN.get(c["id"]) if c["status"] == FAIL else WARN_PLAIN.get(c["id"])
        if c["id"] == "https" and secure_works:
            said = HTTPS_NO_REDIRECT
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
    if lead.get("chain_site"):
        return 15  # a branch of a chain whose website we found: the brand runs its site
    if not lead.get("website"):
        return 50
    qa = lead.get("audit") or {}
    if not qa.get("reachable", True):
        return 45  # unknown until someone opens it in a browser
    return max(5, min(80, 100 - int(qa.get("score", 50))))


def save_lead(db, user_id: int, lead: dict) -> int:
    t = now()
    # Branches that share a website are one lead (one site to fix); without one, each address
    # is its own business.
    branch = "" if lead.get("website") else lead.get("address", "")[:300]
    db.run(
        "INSERT INTO leads (user_id, name, category, website, phone, email, address, city, "
        "source, score, problems, created_at, updated_at, branch) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(user_id, name, website, branch) DO UPDATE SET score = excluded.score, "
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
        branch,
    )
    row = db.one(
        "SELECT id FROM leads WHERE user_id = ? AND name = ? AND website = ? AND branch = ?",
        user_id,
        lead["name"][:200],
        lead.get("website", "")[:300],
        branch,
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
    # A branch with no website of its own is usually a chain whose site another branch lists,
    # or whose brand tag names it: telling Gourmet or mydentist "I could not find your website"
    # is false and burns the lead.
    sites_by_name: dict[str, str] = {}
    for b in with_site:
        for key in (b["name"], b.get("brand", "")):
            if key:
                sites_by_name.setdefault(key.strip().lower(), b["website"])
    for b in found:
        if not b["website"]:
            b["chain_site"] = (
                b.get("brand_website")
                or sites_by_name.get(b["name"].strip().lower())
                or sites_by_name.get((b.get("brand") or "").strip().lower())
                or ""
            )
    for b in found:
        if b.get("region"):
            b["address"] = ", ".join(x for x in (b.get("address", ""), b["region"]) if x)
        if b.get("chain_site"):
            b["problems"] = [
                f"a branch of a chain - its website is probably {b['chain_site']} (check first)"
            ]
        elif not b["website"]:
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
    if not r["found"]:
        r["view"] = view(
            headline(
                f"No businesses found for “{r['trade']}” in {r['city']}",
                "OpenStreetMap lists none under that word. Try the trade's other names "
                "(plumber, plumbing, plumbing services), a neighbourhood or nearby city, or the "
                "country left empty. Coverage is thin in some cities.",
                None,
            ),
        )
        return f"0 {r['trade']} leads in {r['city']}", None, r
    r["view"] = view(
        headline(
            f"{r['found']} businesses found for “{r['trade']}” in {r['city']}",
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


# Where "Assalam o Alaikum" is the ordinary greeting; elsewhere it reads as a stranger guessing.
SALAAM = re.compile(
    r"\b(?:pakistan|united arab emirates|uae|saudi arabia|qatar|kuwait|bahrain|oman|lahore|"
    r"karachi|islamabad|rawalpindi|faisalabad|peshawar|multan|dubai|abu dhabi|sharjah|riyadh|"
    r"jeddah|doha|muscat)\b", re.I)


def write_drafts(
    business: str, website: str, problems: list[str], sender: str, offer: str, where: str = ""
) -> list[dict]:
    sender = sender or "[your name]"
    offer = offer or "a free 15-minute walkthrough of the full audit"
    greeting = "Assalam o Alaikum!" if SALAAM.search(where or "") else f"Hi {business},"
    if not website:
        # "Not listed" is what we know; "you have no website" and "nothing on Maps" are not -
        # the lead itself came from a map, and chains keep one central site.
        hook = (
            f"I could not find a website listed for {business}, and people who search for what "
            "you offer may be finding your competitors first."
        )
        found = ["no website listed where customers look for you"]
        subject = f"{business} - is there a website customers can find?"
    else:
        # Only facts read from their page are quoted; "did not answer our check" is ours to
        # verify, not theirs to be told.
        found = [p for p in problems if p not in (UNREACHABLE, BLOCKED)][:3]
        if found:
            hook = f"I ran a quick check on {website} and found that {found[0]}."
            n = len(found)
            subject = f"{business} - {n} thing{'s' if n != 1 else ''} I noticed on your website"
        else:
            # Nothing was found, so nothing is claimed: no "quick wins", no "fixable".
            hook = (
                f"I came across {website}. I help local businesses get found on Google and in "
                "AI assistants."
            )
            subject = f"{business} - help getting found online"
    if found:
        body = (
            f"{hook}\n\nWhat I found:\n"
            + "\n".join(f"- {p[0].upper() + p[1:]}" for p in found)
            + "\n\nEach of these is fixable, usually within a week. "
            f"I would be glad to offer {offer}, with no obligation."
        )
        share = "I put together the full list of fixes; happy to share it free if useful."
    else:
        body = f"{hook} If it would help, I would be glad to offer {offer}, with no obligation."
        share = "Happy to share a short free review if useful."
    email = (
        f"Subject: {subject}\n\n"
        f"Hi {business} team,\n\n{body}\n\nWould a short call this week suit you?\n\n{sender}"
    )
    short = f"Hi {business} - {hook} {share} - {sender}"
    whatsapp = (
        f"{greeting} {hook} {share} Shall I send it here? - {sender}"
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
        if not qa["reachable"] and lead:
            # A check that could not read the site found nothing out; keep what the last good
            # check found rather than wiping it.
            problems = [p for p in json.loads(lead["problems"]) if p not in problems] + problems
    elif lead:
        problems = json.loads(lead["problems"])
    where = " ".join(
        str(x) for x in (fields.get("country", ""), lead["address"] if lead else "",
                         lead["city"] if lead else "") if x
    )
    items = write_drafts(
        business,
        website,
        problems,
        str(fields.get("sender", "")).strip(),
        str(fields.get("offer", "")).strip(),
        where,
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
