"""Content Studio: real search phrasings for a topic, a brief built from them, a draft from the
configured AI engine with every checkable claim marked, and a grader for any page or text.

Keyword Ideas reads search-box autocomplete - what people actually type - not estimated search
volumes, which no free source provides. Each result says how many of its lookups were answered.
"""

from __future__ import annotations

import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from .. import ai, sources
from ..netguard import FetchFailed, FetchRefused
from .common import (
    FAIL,
    PASS,
    WARN,
    Context,
    InputProblem,
    bullets,
    check,
    checks,
    facts,
    headline,
    score_checks,
    sort_checks,
    table,
    text,
    view,
)
from .site_audit import normalise_url, parse_page

QUESTION = (
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
    "kya",
    "kaise",
    "kahan",
    "kyun",
)
COMMERCIAL = (
    "best",
    "top",
    "price",
    "prices",
    "cost",
    "cheap",
    "cheapest",
    "buy",
    "review",
    "reviews",
    "vs",
    "discount",
    "deal",
    "rate",
    "rates",
    "affordable",
    "quote",
)
LOCAL = ("near me", "nearby", " in ", "near")
STOP = set(
    "a an the of for to in on and or with by at is are be how what why which where when "
    "who can does do should my your near me best top vs from".split()
    # Filler and the sites people name in searches: true phrasings, but nothing to write about.
    + "much many number contact list online new today get one per after work full olx daraz "
    "amazon reddit youtube quora wikipedia facebook instagram tiktok".split()
)
MODIFIERS = [
    "best",
    "price",
    "cost",
    "near me",
    "vs",
    "for",
    "how to",
    "what is",
    "why",
    "which",
    "is",
    "can",
]
MODIFIERS_PK = ["price in pakistan", "in lahore", "in karachi", "kya hai", "kaise"]


def intent(phrase: str) -> str:
    p = f" {phrase.lower()} "
    first = phrase.lower().split(" ")[0] if phrase else ""
    if first in QUESTION or phrase.strip().endswith("?"):
        return "Questions"
    if any(f" {w} " in p for w in COMMERCIAL):
        return "Comparing and buying"
    if any(w in p for w in LOCAL):
        return "Local"
    return "Learning"


def expand(seed: str, country: str = "pk", deep: bool = False, budget_s: float = 45.0) -> dict:
    seed = " ".join(seed.split())
    if not seed:
        raise InputProblem("Enter a topic, e.g. rooftop solar.")
    lookups = [seed] + [
        f"{seed} {m}"
        for m in MODIFIERS
        if m not in ("how to", "what is", "why", "which", "is", "can")
    ]
    lookups += [f"{q} {seed}" for q in ("how to", "what is", "why", "which", "is", "can")]
    if country.lower() == "pk":
        lookups += [f"{seed} {m}" for m in MODIFIERS_PK]
    if deep:
        lookups += [f"{seed} {c}" for c in "abcdefghijklmnopqrstuvwxyz"]
    t0 = time.monotonic()

    def ask(q):
        if time.monotonic() - t0 > budget_s:
            return None
        try:
            return sources.suggest(q, country)
        except sources.SourceFailed:
            return None

    phrases: list[str] = []
    answered, providers = 0, Counter()
    with ThreadPoolExecutor(6) as pool:
        for res in pool.map(ask, lookups):
            if res:
                answered += 1
                providers[res[0]] += 1
                phrases.extend(res[1])
    seen, unique = set(), []
    head = seed.lower().split()[0]
    for p in phrases:
        k = " ".join(p.lower().split())
        if k not in seen and head in k:
            seen.add(k)
            unique.append(k)
    groups: dict[str, list[str]] = {}
    for p in unique:
        groups.setdefault(intent(p), []).append(p)
    # Words this tool added to the lookups ("kya", "lahore", "near me") are not words searchers
    # chose, so they must not come back as "related terms" a page is graded for missing.
    ours = {w for m in (*MODIFIERS, *MODIFIERS_PK, "how to", "what is") for w in m.split()}
    seed_words = set(seed.lower().split()) | ours
    terms = Counter(
        w
        for p in unique
        for w in re.findall(r"[a-z0-9']+", p)
        if w not in seed_words and w not in STOP and len(w) > 2
    )
    return {
        "seed": seed,
        "phrases": unique,
        "groups": groups,
        "terms": terms.most_common(25),
        "asked": len(lookups),
        "answered": answered,
        "provider": providers.most_common(1)[0][0] if providers else "",
    }


def run_keywords(fields: dict, ctx: Context):
    r = expand(
        str(fields.get("seed", "")),
        str(fields.get("country", "pk") or "pk").strip(),
        str(fields.get("depth", "")).lower() in ("deep", "on", "true", "1"),
    )
    order = ["Questions", "Comparing and buying", "Local", "Learning"]
    if not r["answered"]:
        raise InputProblem(
            "No search provider answered. Check the internet connection and try again."
        )
    r["view"] = view(
        headline(
            f"{len(r['phrases'])} real searches around “{r['seed']}”",
            f"{r['answered']} of {r['asked']} lookups answered"
            + (f", from {r['provider']}" if r["provider"] else "")
            + ". Autocomplete shows what people type, not how often.",
        ),
        *[
            bullets(f"{g} ({len(r['groups'][g])})", r["groups"][g])
            for g in order
            if r["groups"].get(g)
        ],
        table(
            "Words that keep coming up",
            ["Word", "Searches containing it"],
            [[w, n] for w, n in r["terms"][:15]],
        ),
    )
    return f"{len(r['phrases'])} keyword ideas for {r['seed']}", None, r


def brief(topic: str, country: str = "pk", ideas: dict | None = None) -> dict:
    ideas = ideas or expand(topic, country, budget_s=30.0)
    groups = ideas["groups"]
    questions = [
        q if q.endswith("?") else q[0].upper() + q[1:] + "?" for q in groups.get("Questions", [])
    ][:10]
    commercial = groups.get("Comparing and buying", [])[:6]
    terms = [w for w, _ in ideas["terms"][:15]]
    title = topic[0].upper() + topic[1:]
    outline = [f"H1: {title}: what to know before you decide"]
    outline += [f"H2: {q}" for q in questions[:5]]
    if commercial:
        outline.append(f"H2: Comparing your options ({', '.join(commercial[:3])})")
    outline.append("H2: Frequently asked questions")
    words = 1200 + 100 * min(len(questions), 6)
    return {
        "topic": topic,
        "title": f"{title} - prices, options and how to choose",
        "description": f"Everything to know about {topic}: costs, how to choose, and answers "
        f"to the questions people ask most.",
        "outline": outline,
        "questions": questions,
        "terms": terms,
        "words": words,
        "ideas": ideas,
    }


def run_brief(fields: dict, ctx: Context):
    topic = " ".join(str(fields.get("topic", "")).split())
    if not topic:
        raise InputProblem("Enter the topic or main keyword.")
    b = brief(topic)
    b["view"] = view(
        headline(
            f"Brief: {topic}",
            f"From {len(b['ideas']['phrases'])} real searches · aim for about {b['words']:,} words",
        ),
        facts("Search snippet", [("Title", b["title"]), ("Description", b["description"])]),
        bullets("Outline", b["outline"]),
        bullets(
            "Questions the page must answer",
            b["questions"]
            or ["No question phrasings found; answer the basics: what, how much, how to choose."],
        ),
        bullets("Words to use naturally", b["terms"]),
        bullets(
            "Before publishing",
            [
                "Answer each question in the first two sentences under its heading.",
                "Add FAQPage structured data for the FAQ section.",
                "Link to this page from at least three related pages on the site.",
                "Check every number, price and date against a source.",
            ],
        ),
    )
    return f"Brief for {topic}", None, b


CLAIM = re.compile(
    r"[^.!?\n]*(?:\d|%|\bRs\.?|\bPKR\b|\$|£|€|\b(?:best|only|first|largest|biggest|cheapest|"
    r"guaranteed|always|never|proven|studies|research shows|according to)\b)[^.!?\n]*[.!?]?",
    re.I,
)


def mark_claims(draft: str) -> list[str]:
    claims = []
    for m in CLAIM.finditer(draft):
        s = m.group(0).strip(" -*#")
        if len(s) > 25 and not s.lower().startswith(("h1", "h2")):
            claims.append(s)
    return claims[:40]


def run_draft(fields: dict, ctx: Context):
    engine = ai.require()
    topic = " ".join(str(fields.get("topic", "")).split())
    if not topic:
        raise InputProblem("Enter the topic or main keyword.")
    b = brief(topic)
    business = str(fields.get("business", "")).strip()
    prompt = (
        f"Write a helpful web article in plain English about: {topic}.\n"
        f"Use this outline exactly, as Markdown headings:\n"
        + "\n".join(b["outline"])
        + "\n\nAnswer each question in the first two sentences under its heading. "
        f"Use these words where natural: {', '.join(b['terms'][:12])}. "
        f"Aim for about {b['words']} words. Do not invent statistics; where a number is needed "
        "write [number to check]."
        + (
            f" The article is published by {business}; mention it once, naturally, near the end."
            if business
            else ""
        )
    )
    draft = engine.complete(
        prompt, "You are a careful web writer.", max_tokens=2600, temperature=0.5
    )
    claims = mark_claims(draft)
    r = {
        "topic": topic,
        "draft": draft,
        "claims": claims,
        "words": len(draft.split()),
        "brief": {k: b[k] for k in ("title", "description", "outline")},
    }
    r["view"] = view(
        headline(
            f"Draft: {topic}",
            f"{r['words']:,} words · {len(claims)} claims to check · "
            "written by the AI engine configured on this server",
        ),
        bullets(
            "Check these before publishing",
            claims or ["No numbers or strong claims found."],
            "Every sentence with a number, price, date or superlative.",
        ),
        text("Draft", draft),
    )
    return f"Draft for {topic}: {r['words']} words, {len(claims)} claims to check", None, r


def grade(
    keyword: str,
    body: str,
    title: str = "",
    h1: list[str] | None = None,
    h2: int | None = None,
    related: list[str] | None = None,
) -> dict:
    kw = " ".join(keyword.lower().split())
    if not kw:
        raise InputProblem("Enter the keyword the page should rank for.")
    words = re.findall(r"[A-Za-z0-9؀-ۿ']+", body)
    n = len(words)
    low = " ".join(w.lower() for w in words)
    first100 = " ".join(w.lower() for w in words[:100])
    count = low.count(kw)
    density = (count * len(kw.split()) / n) if n else 0
    sentences = [s for s in re.split(r"[.!?]+\s", body) if len(s.split()) > 2]
    avg = (sum(len(s.split()) for s in sentences) / len(sentences)) if sentences else 0
    items = []
    if title or h1 is not None:
        items.append(
            check(
                "kw-title",
                "Keyword in the title",
                PASS if kw in title.lower() else FAIL,
                f'"{title}"' if title else "No title.",
                "Put the keyword near the start of the title.",
                3,
            )
        )
        items.append(
            check(
                "kw-h1",
                "Keyword in the H1",
                PASS if any(kw in h.lower() for h in h1 or []) else WARN,
                " | ".join(h1 or []) or "No H1.",
                "Use the keyword in the main heading.",
                2,
            )
        )
    items.append(
        check(
            "kw-intro",
            "Keyword in the first 100 words",
            PASS if kw in first100 else WARN,
            "Found early." if kw in first100 else "Not in the opening.",
            "Say what the page is about in the first paragraph.",
            2,
        )
    )
    items.append(
        check(
            "density",
            "Keyword used naturally",
            PASS if 0.004 <= density <= 0.03 else WARN,
            f"Used {count} time(s), {100 * density:.1f}% of the words.",
            "Aim for roughly 0.5-3%: enough to be clear, not repeated for its own sake.",
        )
    )
    items.append(
        check(
            "length",
            "Long enough to answer fully",
            PASS if n >= 800 else WARN if n >= 300 else FAIL,
            f"{n:,} words.",
            "Most pages that rank for a topic answer it in 800+ words.",
            2,
        )
    )
    if h2 is not None:
        items.append(
            check(
                "sections",
                "Broken into sections",
                PASS if h2 >= 3 else WARN,
                f"{h2} H2 heading(s).",
                "Use an H2 for each question or step.",
                1,
            )
        )
    items.append(
        check(
            "readability",
            "Sentences easy to read",
            PASS if avg <= 22 else WARN,
            f"Average sentence is {avg:.0f} words.",
            "Keep most sentences under 20 words.",
        )
    )
    if related:
        hit = [t for t in related if t in low]
        share = len(hit) / len(related)
        items.append(
            check(
                "coverage",
                "Covers what searchers ask about",
                PASS if share >= 0.5 else WARN if share >= 0.25 else FAIL,
                f"Uses {len(hit)} of {len(related)} related words: "
                f"missing {', '.join(t for t in related if t not in hit)[:160]}.",
                "Work the missing words in where they are genuinely relevant.",
                2,
            )
        )
    items = sort_checks(items)
    score, counts = score_checks(items)
    return {"keyword": kw, "words": n, "score": score, "counts": counts, "checks": items}


def run_grade(fields: dict, ctx: Context):
    keyword = str(fields.get("keyword", ""))
    url = str(fields.get("url", "")).strip()
    body = str(fields.get("text", ""))
    title, h1, h2, source = "", None, None, "pasted text"
    if url:
        try:
            resp = ctx.fetch(normalise_url(url))
        except (FetchFailed, FetchRefused) as exc:
            raise InputProblem(str(exc)) from exc
        page = parse_page(resp.text())
        body = page.text
        title = page.title or ""
        h1 = [t for lv, t in page.headings if lv == 1]
        h2 = sum(1 for lv, _ in page.headings if lv == 2)
        source = resp.url
    elif not body.strip():
        raise InputProblem("Enter a page address or paste the text to grade.")
    related: list[str] = []
    try:
        related = [w for w, _ in expand(keyword, budget_s=15.0)["terms"][:12]]
    except InputProblem:
        related = []
    g = grade(keyword, body, title, h1, h2, related)
    g["view"] = view(
        headline(
            f"“{g['keyword']}” on {source}", f"{g['words']:,} words graded", g["score"], g["counts"]
        ),
        checks("Checks", g["checks"]),
    )
    return f"Content grade {g['score']}/100 for {g['keyword']}", g["score"], g
