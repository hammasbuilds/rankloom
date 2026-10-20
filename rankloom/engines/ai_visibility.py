"""AI Visibility: can AI answer engines read a site, which questions decide whether they name it,
and - with an AI engine configured - do they name it.

Readiness is checked from the site itself. Question Builder uses real search-box autocomplete.
Answer Check asks the configured AI engine and reads its answers; it measures that engine, and
the page says so, rather than claiming to measure every assistant.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from .. import ai, robots, sources
from ..netguard import FetchFailed, FetchRefused
from . import market
from .common import (
    FAIL,
    PASS,
    WARN,
    Context,
    InputProblem,
    bullets,
    check,
    checks,
    headline,
    score_checks,
    sort_checks,
    table,
    view,
)
from .local_seo import LOCAL_TYPES
from .site_audit import jsonld_objects, normalise_url, parse_page

# (user-agent token, who runs it, what it does, answer-critical)
AI_AGENTS = [
    ("OAI-SearchBot", "OpenAI", "ChatGPT search results", True),
    ("ChatGPT-User", "OpenAI", "pages ChatGPT opens for a user", True),
    ("PerplexityBot", "Perplexity", "Perplexity answers", True),
    ("Perplexity-User", "Perplexity", "pages Perplexity opens for a user", True),
    ("Claude-SearchBot", "Anthropic", "Claude search results", True),
    ("Claude-User", "Anthropic", "pages Claude opens for a user", True),
    ("Googlebot", "Google", "Google Search and AI Overviews", True),
    ("Bingbot", "Microsoft", "Bing and Copilot answers", True),
    ("GPTBot", "OpenAI", "model training", False),
    ("ClaudeBot", "Anthropic", "model training", False),
    ("Google-Extended", "Google", "Gemini training", False),
    ("Applebot-Extended", "Apple", "Apple AI training", False),
    ("CCBot", "Common Crawl", "open dataset many models train on", False),
]
QUESTION_WORDS = (
    "how",
    "what",
    "why",
    "which",
    "where",
    "when",
    "who",
    "can",
    "is",
    "are",
    "does",
    "do",
    "should",
)


# --- readiness ---------------------------------------------------------------------------------


def readiness(url: str, fetch) -> dict:
    url = normalise_url(url)
    resp = fetch(url)
    page = parse_page(resp.text())
    origin = f"{urlsplit(resp.url).scheme}://{urlsplit(resp.url).netloc}"
    robots_text = ""
    try:
        r = fetch(origin + "/robots.txt")
        robots_text = r.text() if r.status == 200 else ""
    except (FetchFailed, FetchRefused):
        pass
    try:
        lt = fetch(origin + "/llms.txt")
        llms = lt.status == 200 and "html" not in lt.headers.get("content-type", "")
    except (FetchFailed, FetchRefused):
        llms = False

    agents = []
    for token, owner, purpose, critical in AI_AGENTS:
        is_blocked = robots.blocked(robots_text, token)
        agents.append(
            {
                "agent": token,
                "owner": owner,
                "purpose": purpose,
                "critical": critical,
                "blocked": is_blocked,
                "partial": robots.partial(robots_text, token),
            }
        )
    blocked_critical = [a["agent"] for a in agents if a["critical"] and a["blocked"]]
    blocked_training = [a["agent"] for a in agents if not a["critical"] and a["blocked"]]
    items = [
        check(
            "answer-bots",
            "Answer engines may read the site",
            FAIL if blocked_critical else PASS,
            "Blocked: " + ", ".join(blocked_critical)
            if blocked_critical
            else "No answer or search crawler is blocked.",
            "Remove the robots.txt rules blocking these crawlers; a site they cannot read "
            "cannot be cited.",
            3,
        ),
        check(
            "training-bots",
            "Training crawlers",
            WARN if blocked_training else PASS,
            "Blocked: " + ", ".join(blocked_training) if blocked_training else "None blocked.",
            "Blocking training crawlers is a choice, but models that never saw the site know "
            "less about the business.",
        ),
    ]
    snippet = (page.meta.get("robots", "") + "," + resp.headers.get("x-robots-tag", "")).lower()
    no_snip = "nosnippet" in snippet or "max-snippet:0" in snippet.replace(" ", "")
    items.append(
        check(
            "snippets",
            "Page can be quoted",
            FAIL if no_snip else PASS,
            "A nosnippet rule stops answers quoting the page." if no_snip else "No snippet limits.",
            "Remove nosnippet / max-snippet:0 so answers can quote the page.",
            2,
        )
    )
    scripts_only = page.words < 60
    items.append(
        check(
            "rendered",
            "Text is in the HTML, not added by scripts",
            FAIL if page.words < 60 else WARN if page.words < 200 else PASS,
            f"About {page.words} words arrive in the HTML.",
            "Most AI crawlers do not run JavaScript: render the main text on the server.",
            3,
        )
    )
    objs = jsonld_objects(page.jsonld)
    entity_types = LOCAL_TYPES | {"organization", "corporation", "onlinebusiness"}
    entity = next(
        (
            o
            for o in objs
            if {
                str(t).lower()
                for t in (o.get("@type") if isinstance(o.get("@type"), list) else [o.get("@type")])
            }
            & entity_types
        ),
        None,
    )
    named = bool(entity and entity.get("name"))
    linked = bool(entity and entity.get("sameAs"))
    items.append(
        check(
            "entity",
            "Business described as an entity",
            PASS if named and linked else WARN if entity else FAIL,
            (
                "Organization data with a name and sameAs links."
                if named and linked
                else "Organization data has no name."
                if entity and not named
                else "Organization data without sameAs links."
                if entity
                else "No Organization data."
            ),
            "Add Organization (or LocalBusiness) JSON-LD with name, logo, url and sameAs links to "
            "your profiles, so answers can tell your business apart from others with similar "
            "names.",
            2,
        )
    )
    q_heads = [
        t
        for lv, t in page.headings
        if lv >= 2 and (t.strip().endswith("?") or t.lower().split(" ")[0] in QUESTION_WORDS)
    ]
    faq = any("faqpage" in str(o.get("@type", "")).lower() for o in objs)
    items.append(
        check(
            "questions",
            "Answers questions directly",
            PASS if faq or len(q_heads) >= 2 else WARN,
            f"{len(q_heads)} question heading(s)" + (", FAQPage data." if faq else "."),
            "Add a short FAQ: the questions customers ask, each answered in two or three "
            "sentences.",
            2,
        )
    )
    desc = page.meta.get("description", "")
    items.append(
        check(
            "summary",
            "One-line summary of the business",
            PASS if 70 <= len(desc) <= 200 else WARN,
            f'"{desc}"' if desc else "No meta description.",
            "Write a description that says what you do, for whom, and where.",
        )
    )
    anchors = " ".join(page.anchors).lower()
    about = "about" in anchors
    contact = "contact" in anchors
    items.append(
        check(
            "trust",
            "About and contact pages linked",
            PASS if about and contact else WARN,
            f"About: {'yes' if about else 'no'}, contact: {'yes' if contact else 'no'}.",
            "Link an About page (who runs the business) and a Contact page from every page.",
        )
    )
    fresh = resp.headers.get("last-modified") or any(o.get("dateModified") for o in objs)
    items.append(
        check(
            "fresh",
            "Shows when it was updated",
            PASS if fresh else WARN,
            "A last-modified date is available." if fresh else "No update date found.",
            "Show a 'last updated' date and set dateModified in the page data.",
        )
    )
    items.append(
        check(
            "llms-txt",
            "llms.txt guide for AI tools",
            PASS if llms else WARN,
            "/llms.txt found." if llms else "No /llms.txt.",
            "Optionally publish /llms.txt: a short plain-text map of your most important pages. "
            "It is a young convention; it helps some tools and costs little.",
        )
    )
    items = sort_checks(items)
    score, counts = score_checks(items)
    return {
        "url": url,
        "final_url": resp.url,
        "score": score,
        "counts": counts,
        "checks": items,
        "agents": agents,
        "words": page.words,
        "scripts_only": scripts_only,
    }


def run_readiness(fields: dict, ctx: Context):
    r = readiness(str(fields.get("url", "")), ctx.fetch)
    rows = [
        [
            a["agent"],
            a["owner"],
            a["purpose"],
            {
                "status": FAIL
                if a["blocked"] and a["critical"]
                else WARN
                if a["blocked"]
                else PASS,
                "text": "blocked"
                if a["blocked"]
                else ("allowed, except " + ", ".join(a["partial"][:3]))
                if a["partial"]
                else "allowed",
            },
        ]
        for a in r["agents"]
    ]
    r["view"] = view(
        headline(
            r["final_url"],
            "Can AI answer engines read and cite this site?",
            r["score"],
            r["counts"],
        ),
        checks("Checks", r["checks"]),
        table(
            "AI crawlers in robots.txt",
            ["Crawler", "Run by", "Used for", "Access"],
            rows,
            "Answer and search crawlers decide whether you can be cited; training crawlers "
            "decide what models learn.",
        ),
    )
    c = r["counts"]
    return (
        f"{r['final_url']} AI readiness {r['score']}/100 - {c['fail']} fail, {c['warn']} warn",
        r["score"],
        r,
    )


# --- questions ---------------------------------------------------------------------------------


def template_questions(niche: str, city: str, brand: str = "") -> list[str]:
    where = f" in {city}" if city else ""
    qs = [
        f"Who is the best {niche}{where}?",
        f"Can you recommend a good {niche}{where}?",
        f"What are the top rated {niche} options{where}?",
        f"How much does a {niche} cost{where}?",
        f"Which {niche}{where} has the best reviews?",
        f"Is there an affordable {niche}{where}?",
    ]
    if brand:
        qs += [f"Is {brand} a good {niche}?", f"What do people say about {brand}?"]
    return qs


# Searches about working in the trade, not buying from it: "how much dentist earn", "dentist jobs".
_NOT_A_CUSTOMER = re.compile(
    r"\b(?:salary|salaries|earn|earns|earning|earnings|jobs?|career|careers|vacanc(?:y|ies)|"
    r"hiring|courses?|degree|internships?)\b"
)


def build_questions(niche: str, city: str, brand: str, country: str = "pk") -> dict:
    if not niche:
        raise InputProblem("Enter the service or product, e.g. dentist.")
    country = market.code(country)
    seeds = [
        f"best {niche} in {city}" if city else f"best {niche}",
        f"{niche} {city}".strip(),
        f"how much {niche}",
        f"{niche} near me",
    ]
    answered, phrasings = 0, []
    provider = ""

    def ask(seed):
        try:
            return sources.suggest(seed, country)
        except sources.SourceFailed:
            return None

    with ThreadPoolExecutor(4) as pool:
        for res in pool.map(ask, seeds):
            if res:
                answered += 1
                provider = provider or res[0]
                phrasings.extend(res[1])
    seen, real, dropped = set(), [], 0
    for p in phrasings:
        key = p.lower().strip()
        if key in seen or niche.split()[0].lower() not in key:
            continue
        seen.add(key)
        # A customer in Williamsville is not asking about Lahore, or about a dentist's pay.
        if market.foreign(key, country, city) or (
            _NOT_A_CUSTOMER.search(key) and not _NOT_A_CUSTOMER.search(niche.lower())
        ):
            dropped += 1
            continue
        real.append(p)
    as_questions = []
    for p in real:
        q = p.strip()
        if not q.endswith("?"):
            first = q.split(" ")[0].lower()
            q = (
                (q[0].upper() + q[1:] + "?")
                if first in QUESTION_WORDS
                else f"What is the {q}?"
                if q.lower().startswith(("best", "top", "cheapest"))
                else f"Tell me about {q}."
            )
        as_questions.append(q)
    return {
        "niche": niche,
        "city": city,
        "brand": brand,
        "templates": template_questions(niche, city, brand),
        "searched": real,
        "from_search": as_questions[:20],
        "provider": provider,
        "answered": answered,
        "asked": len(seeds),
        "country": country,
        "dropped": dropped,
    }


def run_questions(fields: dict, ctx: Context):
    r = build_questions(
        str(fields.get("niche", "")).strip(),
        str(fields.get("city", "")).strip(),
        str(fields.get("brand", "")).strip(),
        market.code(str(fields.get("country", ""))),
    )
    r["view"] = view(
        headline(
            f"Questions for {r['niche']}" + (f" in {r['city']}" if r["city"] else ""),
            f"{len(r['templates'])} standard questions, {len(r['searched'])} real search "
            f"phrasings in {market.NAMES[r['country']]} ({r['answered']} of {r['asked']} "
            "searches answered"
            + (f", from {r['provider']}" if r["provider"] else "")
            + (
                f"; {r['dropped']} about other places or about working in the trade left out"
                if r["dropped"]
                else ""
            )
            + ")",
        ),
        bullets(
            "Ask these in Answer Check",
            r["templates"],
            "Paste them into Answer Check, or let it use them by default.",
        ),
        bullets(
            "What people type into search",
            r["searched"],
            "Real autocomplete phrasings - the wording customers actually use.",
        ),
    )
    return (f"{len(r['templates']) + len(r['searched'])} questions for {r['niche']}", None, r)


# --- answers -----------------------------------------------------------------------------------

SYSTEM = (
    "You are a helpful local assistant. When asked for businesses, recommend specific, real "
    "businesses by name and give their website when you know it. Be concise."
)
DOMAIN = re.compile(r"\b(?:https?://)?(?:www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,})\b", re.I)
BOLD = re.compile(r"\*\*([^*\n]{2,60})\*\*")
LISTED = re.compile(
    r"^\s*(?:\d+[.)]|[-*•])\s+(?:\*\*)?([A-Z][^:\n*]{2,60}?)(?:\*\*)?\s*(?:[:\-–—(]|$)", re.M
)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def read_answer(answer: str, brand: str, site: str) -> dict:
    domain = urlsplit(normalise_url(site)).netloc.lower().removeprefix("www.") if site else ""
    text_norm = _norm(answer)
    mentioned = bool(brand and _norm(brand) and _norm(brand) in text_norm) or bool(
        domain and domain in answer.lower()
    )
    brand_key = _norm(brand)
    names = []
    for m in LISTED.findall(answer) + BOLD.findall(answer):
        n = m.strip(" .")
        # "Shaukat Khanum Memorial Cancer Hospital" is the brand "Shaukat Khanum", not a rival.
        if len(n.split()) <= 7 and _norm(n) and brand_key not in _norm(n):
            names.append(n)
    # A website given in the same line as the brand is the answer's address for the brand,
    # not a competitor - and when it is not the real one, that is a finding of its own: the
    # assistant is sending customers to the wrong address (or one that does not exist).
    yours, wrong, domains = [], [], []
    # One list item is one unit: "1. Shaukat Khanum ...\n   - Website: skmemorial.org" gives the
    # brand's address on the line below its name, and line by line it read as a rival.
    items = re.split(r"\n(?=\s{0,3}(?:\d+[.)]|[-*•])\s+\S)(?!\s{2,})", answer) if answer else [""]
    for line in items:
        about_brand = bool(brand_key) and brand_key in _norm(line)
        for d in DOMAIN.findall(line):
            d = d.lower().removeprefix("www.")
            if d == domain:
                yours.append(d)
            elif about_brand:
                wrong.append(d)
            else:
                domains.append(d)
    seen, competitors = set(), []
    for n in names + domains:
        key = _norm(n)
        if key and key not in seen and key not in {_norm(w) for w in wrong}:
            seen.add(key)
            competitors.append(n)
    return {
        "mentioned": mentioned,
        "competitors": competitors[:8],
        "site_cited": bool(yours),
        "wrong_sites": sorted(set(wrong)),
    }


def answer_check(fields: dict, engine: ai.Engine) -> dict:
    brand = str(fields.get("brand", "")).strip()
    site = str(fields.get("site", "")).strip()
    niche = str(fields.get("niche", "")).strip()
    city = str(fields.get("city", "")).strip()
    if not brand:
        raise InputProblem("Enter the brand name to look for.")
    typed = [q.strip() for q in str(fields.get("questions", "")).splitlines() if q.strip()]
    if not typed and not niche:
        raise InputProblem("Enter the niche (e.g. dentist) or paste questions to ask.")
    questions = (typed or template_questions(niche, city))[:8]
    rows = []
    for q in questions:
        try:
            answer = engine.complete(q, SYSTEM, max_tokens=600)
            rows.append({"question": q, "answer": answer, **read_answer(answer, brand, site)})
        except ai.AIUnavailable as exc:
            rows.append(
                {
                    "question": q,
                    "answer": "",
                    "error": str(exc),
                    "mentioned": False,
                    "competitors": [],
                }
            )
    answered = [r for r in rows if not r.get("error")]
    hits = sum(1 for r in answered if r["mentioned"])
    tally: dict[str, int] = {}
    for r in answered:
        for c in r["competitors"]:
            tally[c] = tally.get(c, 0) + 1
    rivals = sorted(tally.items(), key=lambda x: (-x[1], x[0]))[:12]
    rate = round(100 * hits / len(answered)) if answered else 0
    return {
        "brand": brand,
        "site": site,
        "rows": rows,
        "asked": len(rows),
        "answered": len(answered),
        "mentioned": hits,
        "rate": rate,
        "rivals": rivals,
    }


def run_answers(fields: dict, ctx: Context):
    r = answer_check(fields, ai.require())
    if not r["answered"]:
        raise ai.AIUnavailable(r["rows"][0].get("error", "The AI engine did not answer."))
    rows = [
        [
            q["question"],
            {
                "status": PASS if q["mentioned"] else FAIL,
                "text": "named"
                if q["mentioned"]
                else ("no answer" if q.get("error") else "not named"),
            },
            {"status": PASS, "text": "yours"}
            if q.get("site_cited")
            else {"status": FAIL, "text": "wrong: " + ", ".join(q["wrong_sites"][:2])}
            if q.get("wrong_sites")
            else "-",
            ", ".join(q["competitors"][:4]) or "-",
            (q["answer"][:220] + ("…" if len(q["answer"]) > 220 else "")) or q.get("error", ""),
        ]
        for q in r["rows"]
    ]
    wrong = sorted({w for q in r["rows"] for w in q.get("wrong_sites", [])})
    r["wrong_sites"] = wrong
    r["view"] = view(
        headline(
            f"{r['brand']} named in {r['mentioned']} of {r['answered']} answers",
            f"Mention rate {r['rate']}% · answers from the AI engine configured on this server",
            r["rate"],
        ),
        bullets(
            "Websites the answers give for you that are not yours",
            [
                f"{w} - check whether it is yours; if not, customers asking an assistant are "
                "being sent to the wrong address"
                for w in wrong
            ],
            "Make your real address consistent in your site's data, Google Business Profile "
            "and directories, so assistants learn the right one.",
        )
        if wrong
        else None,
        table(
            "Answers", ["Question", r["brand"], "Website given", "Named instead", "Answer"], rows
        ),
        table(
            "Named most often instead",
            ["Business", "Answers naming it"],
            [[n, c] for n, c in r["rivals"]],
        )
        if r["rivals"]
        else None,
    )
    return (f"{r['brand']} named in {r['mentioned']} of {r['answered']} AI answers", r["rate"], r)
