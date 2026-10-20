"""Site Crawl: follow a site's own links (and its sitemap) and report what is wrong across pages -
broken pages, duplicate titles and descriptions, missing H1s, noindex, thin and slow pages.

Bounded in pages and in seconds, and the result says how many pages it found against how many it
read, so a crawl cut short by its budget never reads as a whole site.
"""

from __future__ import annotations

import re
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urldefrag, urljoin, urlsplit

from .. import robots
from ..netguard import FetchFailed, FetchRefused
from .common import (
    FAIL,
    PASS,
    WARN,
    Context,
    check,
    checks,
    headline,
    score_checks,
    sort_checks,
    table,
    view,
)
from .site_audit import normalise_url, parse_page

SKIP_EXT = re.compile(
    r"\.(pdf|jpe?g|png|gif|webp|svg|ico|zip|rar|gz|mp4|mp3|webm|avi|docx?|xlsx?|pptx?|css|js|xml|txt|json)$",
    re.I,
)
LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
WORKERS = 4


def _same_site(a: str, b: str) -> bool:
    strip = lambda h: h.lower().removeprefix("www.")  # noqa: E731
    return strip(urlsplit(a).netloc) == strip(urlsplit(b).netloc)


def _clean(base: str, href: str) -> str | None:
    href = href.strip()
    if not href or href.startswith(
        ("mailto:", "tel:", "javascript:", "#", "data:", "sms:", "whatsapp:")
    ):
        return None
    url = urldefrag(urljoin(base, href))[0]
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or SKIP_EXT.search(parts.path):
        return None
    return parts._replace(path=parts.path or "/").geturl()


def _sitemap_urls(fetch, origin: str, robots_text: str, limit: int = 200) -> list[str]:
    found: list[str] = []
    queue = robots.sitemaps(robots_text) or [origin + "/sitemap.xml"]
    seen = set()
    while queue and len(found) < limit and len(seen) < 6:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        try:
            r = fetch(sm)
        except (FetchFailed, FetchRefused):
            continue
        if r.status != 200:
            continue
        body = r.text()
        locs = LOC.findall(body)
        if "<sitemapindex" in body.lower():
            queue.extend(locs[:5])
        else:
            found.extend(locs)
    return found[:limit]


def crawl(start: str, fetch, max_pages: int = 25, budget_s: float = 75.0) -> dict:
    start = normalise_url(start)
    t0 = time.monotonic()
    first = fetch(start)
    home = first.url
    origin = f"{urlsplit(home).scheme}://{urlsplit(home).netloc}"
    try:
        rr = fetch(origin + "/robots.txt")
        robots_text = rr.text() if rr.status == 200 else ""
    except (FetchFailed, FetchRefused):
        robots_text = ""

    pages: dict[str, dict] = {}
    linked_from: dict[str, set[str]] = defaultdict(set)
    discovered: list[str] = [home]
    seen = {home}

    def record(url: str, resp) -> list[str]:
        info = {
            "url": url,
            "final": resp.url,
            "status": resp.status,
            "ms": resp.elapsed_ms,
            "hops": len(resp.chain),
            "title": "",
            "description": "",
            "h1": 0,
            "words": 0,
            "noindex": False,
            "html": "html" in resp.headers.get("content-type", ""),
        }
        out: list[str] = []
        if info["html"] and resp.status == 200:
            page = parse_page(resp.text())
            info.update(
                title=page.title or "",
                description=page.meta.get("description", ""),
                h1=sum(1 for lv, _ in page.headings if lv == 1),
                words=page.words,
                noindex="noindex"
                in (page.meta.get("robots", "") + resp.headers.get("x-robots-tag", "")).lower(),
            )
            for href in page.anchors:
                link = _clean(resp.url, href)
                if link and _same_site(link, home):
                    linked_from[link].add(url)
                    out.append(link)
        pages[url] = info
        return out

    def visit(url: str):
        try:
            return url, fetch(url), None
        except (FetchFailed, FetchRefused) as exc:
            return url, None, str(exc)

    frontier = record(home, first)
    for link in _sitemap_urls(fetch, origin, robots_text):
        if _same_site(link, home):
            frontier.append(_clean(home, link) or link)
    failed: dict[str, str] = {}
    out_of_time = False
    with ThreadPoolExecutor(WORKERS) as pool:
        while frontier and len(pages) < max_pages:
            batch = []
            for link in frontier:
                if link not in seen:
                    seen.add(link)
                    discovered.append(link)
                    if len(pages) + len(batch) < max_pages:
                        batch.append(link)
            frontier = []
            if not batch:
                break
            if time.monotonic() - t0 > budget_s:
                out_of_time = True
                break
            for url, resp, err in pool.map(visit, batch):
                if resp is None:
                    failed[url] = err or "failed"
                    pages[url] = {
                        "url": url,
                        "final": url,
                        "status": 0,
                        "ms": 0,
                        "hops": 0,
                        "title": "",
                        "description": "",
                        "h1": 0,
                        "words": 0,
                        "noindex": False,
                        "html": False,
                    }
                    continue
                frontier.extend(record(url, resp))
        for link in frontier:
            if link not in seen:
                seen.add(link)
                discovered.append(link)

    return {
        "start": start,
        "home": home,
        "pages": list(pages.values()),
        "failed": failed,
        "discovered": len(discovered),
        "max_pages": max_pages,
        "out_of_time": out_of_time,
        "linked_from": {k: sorted(v)[:3] for k, v in linked_from.items()},
        "seconds": round(time.monotonic() - t0, 1),
    }


def analyse(result: dict) -> list[dict]:
    pages = result["pages"]
    ok = [p for p in pages if p["status"] == 200 and p["html"]]
    broken = [p for p in pages if p["status"] >= 400 or p["status"] == 0]
    titles = Counter(p["title"] for p in ok if p["title"])
    descs = Counter(p["description"] for p in ok if p["description"])
    dup_t = [t for t, n in titles.items() if n > 1]
    dup_d = [d for d, n in descs.items() if n > 1]
    no_title = [p for p in ok if not p["title"]]
    no_desc = [p for p in ok if not p["description"]]
    bad_h1 = [p for p in ok if p["h1"] != 1]
    noindex = [p for p in ok if p["noindex"]]
    thin = [p for p in ok if p["words"] < 300]
    slow = [p for p in pages if p["ms"] > 2500]
    hops = [p for p in pages if p["hops"] > 1]
    n = max(len(ok), 1)

    def share(items):
        return f"{len(items)} of {len(ok)} pages"

    def status_for(items, warn_share=0.0, fail_share=0.3):
        if not items:
            return PASS
        return (
            FAIL if len(items) / n > fail_share else WARN if len(items) / n > warn_share else PASS
        )

    return [
        check(
            "broken",
            "No broken pages",
            FAIL if broken else PASS,
            f"{len(broken)} of {len(pages)} pages answered an error or did not answer.",
            "Fix or redirect each broken address, and update the links pointing at it.",
            3,
        ),
        check(
            "dup-title",
            "Unique titles",
            WARN if dup_t else PASS,
            f"{len(dup_t)} title(s) used on more than one page."
            if dup_t
            else "Every title is unique.",
            "Give each page its own title naming what is on that page.",
            2,
        ),
        check(
            "dup-desc",
            "Unique descriptions",
            WARN if dup_d else PASS,
            f"{len(dup_d)} description(s) repeated." if dup_d else "No repeated descriptions.",
            "Write a description for each page instead of one site-wide text.",
        ),
        check(
            "no-title",
            "Every page has a title",
            status_for(no_title, 0, 0.1),
            share(no_title) + " have no title.",
            "Add a <title> to each page.",
            3,
        ),
        check(
            "no-desc",
            "Every page has a description",
            status_for(no_desc, 0.2, 0.5),
            share(no_desc) + " have no meta description.",
            "Add a 70-160 character description to each page.",
            2,
        ),
        check(
            "h1",
            "One H1 per page",
            status_for(bad_h1, 0.2, 0.5),
            share(bad_h1) + " have no H1 or more than one.",
            "Give each page exactly one H1.",
        ),
        check(
            "noindex",
            "Pages are indexable",
            WARN if noindex else PASS,
            share(noindex) + " say noindex.",
            "Remove noindex from any page that should appear in search.",
            2,
        ),
        check(
            "thin",
            "Pages have enough text",
            status_for(thin, 0, 0.7),
            share(thin) + " have under 300 words.",
            "Expand thin pages or merge them into stronger ones.",
        ),
        check(
            "slow",
            "Pages respond quickly",
            status_for(slow, 0.1, 0.4),
            f"{len(slow)} of {len(pages)} pages took over 2.5 s.",
            "Cache pages and use faster hosting or a CDN.",
            2,
        ),
        check(
            "hops",
            "Internal links point at final addresses",
            WARN if hops else PASS,
            f"{len(hops)} page(s) were reached through more than one redirect.",
            "Update internal links to the final address.",
        ),
    ]


def run(fields: dict, ctx: Context) -> tuple[str, int, dict]:
    try:
        limit = max(5, min(50, int(fields.get("pages") or 25)))
    except ValueError:
        limit = 25
    result = crawl(str(fields.get("url", "")), ctx.fetch, max_pages=limit)
    items = sort_checks(analyse(result))
    score, counts = score_checks(items)
    read = len(result["pages"])
    cut = (
        " Stopped at the time budget."
        if result["out_of_time"]
        else " Stopped at the page limit."
        if result["discovered"] > read
        else ""
    )
    rows = []
    for p in sorted(result["pages"], key=lambda p: (p["status"] == 200, p["url"])):
        issues = []
        if p["status"] != 200:
            issues.append(f"answered {p['status'] or 'nothing'}")
        if p["status"] == 200 and p["html"]:
            if not p["title"]:
                issues.append("no title")
            if not p["description"]:
                issues.append("no description")
            if p["h1"] != 1:
                issues.append(f"{p['h1']} H1")
            if p["words"] < 300:
                issues.append("thin")
            if p["noindex"]:
                issues.append("noindex")
        if p["ms"] > 2500:
            issues.append("slow")
        st = PASS if not issues else FAIL if p["status"] != 200 else WARN
        rows.append(
            [
                {"text": urlsplit(p["url"]).path or "/", "href": p["url"]},
                {"status": st, "text": str(p["status"] or "-")},
                p["title"] or "-",
                p["words"],
                f"{p['ms']} ms",
                ", ".join(issues) or "ok",
            ]
        )
    broken_rows = [
        [
            {"text": p["url"], "href": p["url"]},
            p["status"] or "no answer",
            ", ".join(result["linked_from"].get(p["url"], [])) or "sitemap",
        ]
        for p in result["pages"]
        if p["status"] >= 400 or p["status"] == 0
    ]
    out = {**result, "checks": items, "score": score, "counts": counts}
    out["view"] = view(
        headline(
            result["home"],
            f"Read {read} of {result['discovered']} pages found in {result['seconds']} s.{cut}",
            score,
            counts,
        ),
        checks("Across the site", items),
        table("Broken pages", ["Address", "Answered", "Linked from"], broken_rows)
        if broken_rows
        else None,
        table("Every page read", ["Page", "Status", "Title", "Words", "Time", "Issues"], rows),
    )
    summary = (
        f"{result['home']}: {read} pages, scored {score}/100 - "
        f"{counts['fail']} fail, {counts['warn']} warn"
    )
    return summary, score, out
