"""Site Audit: twenty-one on-page and technical checks on one page, each with its fix.

`audit()` takes the fetcher as a parameter, so tests run every check against fixture pages with
no network, and the live tool runs the same code through `netguard.safe_fetch`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .. import robots
from ..netguard import FetchFailed, FetchRefused, Response, offered_encoding, safe_fetch
from .common import (
    FAIL,
    PASS,
    WARN,
    Context,
    check,
    headline,
    score_checks,
    sort_checks,
    view,
)
from .common import checks as checks_block
from .common import facts as facts_block
from .common import text as text_block

Fetch = Callable[[str], Response]
MAX_TEXT = 200_000

# One speed rule for every tool that times a page, and one caveat with it: the time is measured
# from this server, so it is a reason to run a speed test, not a number to quote.
SPEED_GOOD_MS = 800
SPEED_SLOW_MS = 2500
SPEED_CAVEAT = (
    "measured from this server - a slow connection here slows it too, so confirm with a speed "
    "test before quoting it"
)


def speed_status(ms: int) -> str:
    return PASS if ms < SPEED_GOOD_MS else WARN if ms < SPEED_SLOW_MS else FAIL


# A bot check stands in front of the page: Cloudflare's "Just a moment...", a "Human
# Verification" form, a captcha. Auditing it scored katzsdelicatessen.com 70/100 and advised
# writing a description for a page no visitor ever sees.
_CHALLENGE_TITLE = re.compile(
    r"just a moment|attention required|human verification|verify(?:ing)? (?:that )?you are "
    r"(?:a )?human|are you a (?:human|robot)|checking your browser|security check|access denied|"
    r"pardon our interruption|ddos-guard|bot verification|captcha|one more step",
    re.I,
)
_CHALLENGE_BODY = re.compile(
    r"enable javascript and cookies to continue|javascript is disabled|checking if the site "
    r"connection is secure|verify you are human|press (?:&|and) hold|incapsula|px-captcha|"
    r"perimeterx|datadome|sucuri website firewall|captcha",
    re.I,
)


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self.meta: dict[str, str] = {}
        self.links: list[dict[str, str]] = []
        self.lang = ""
        self.headings: list[tuple[int, str]] = []
        self.images: list[dict[str, str | None]] = []
        self.anchors: list[str] = []
        self.jsonld: list[str] = []
        self.iframes: list[str] = []
        self.text_parts: list[str] = []
        self._text_len = 0
        self.words = 0
        self._stack: list[str] = []
        self._buf: list[str] = []
        self._in: str | None = None

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "html":
            self.lang = a.get("lang", "").strip()
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or a.get("http-equiv") or "").lower()
            if key:
                self.meta.setdefault(key, a.get("content", "").strip())
        elif tag == "link":
            self.links.append(a)
        elif tag == "img":
            # A bare `alt` is an empty alt (decorative image), not a missing one. An image inside
            # <noscript>, or one a pixel across, is a tracking pixel, not content.
            tiny = a.get("width", "").strip() in ("0", "1") or a.get("height", "").strip() in (
                "0",
                "1",
            )
            self.images.append(
                {
                    "src": a.get("src") or a.get("data-src"),
                    "alt": a["alt"] if "alt" in a else None,
                    "pixel": tiny or "noscript" in self._stack,
                }
            )
        elif tag == "a" and a.get("href"):
            self.anchors.append(a["href"])
        elif tag == "iframe" and a.get("src"):
            self.iframes.append(a["src"])
        if tag in ("p", "br", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section"):
            self.text_parts.append("\n")
        if tag in ("title", "h1", "h2", "h3", "h4", "h5", "h6") or (
            tag == "script" and a.get("type", "").lower() == "application/ld+json"
        ):
            self._in = "jsonld" if tag == "script" else tag
            self._buf = []
        if tag in ("script", "style", "noscript", "template"):
            self._stack.append(tag)

    def handle_endtag(self, tag):
        if self._in and (tag == self._in or (self._in == "jsonld" and tag == "script")):
            text = " ".join("".join(self._buf).split())
            if self._in == "title":
                if self.title is None:
                    self.title = text
            elif self._in == "jsonld":
                self.jsonld.append("".join(self._buf))
            else:
                self.headings.append((int(self._in[1]), text))
            self._in = None
        if self._stack and self._stack[-1] == tag:
            self._stack.pop()

    def handle_data(self, data):
        if self._in:
            self._buf.append(data)
        if not self._stack:
            self.words += len(data.split())
            if self._text_len < MAX_TEXT:
                self.text_parts.append(data)
                self._text_len += len(data)

    @property
    def text(self) -> str:
        """Visible text, with block boundaries kept as line breaks."""
        lines = (" ".join(line.split()) for line in "".join(self.text_parts).splitlines())
        return "\n".join(line for line in lines if line)


def normalise_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        raise FetchRefused("Enter a page address.")
    if "://" not in raw:
        raw = "https://" + raw
    parts = urlsplit(raw)
    if not parts.path:
        raw = parts._replace(path="/").geturl()
    return raw


_check = check


def parse_page(html: str) -> _Page:
    page = _Page()
    page.feed(html)
    page.close()
    return page


def jsonld_objects(blocks: list[str]) -> list[dict]:
    """Every JSON-LD object on the page, @graph members included, as flat dicts."""
    out: list[dict] = []
    for block in blocks:
        try:
            data = json.loads(block)
        except ValueError:
            continue
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                out.append(item)
                if isinstance(item.get("@graph"), list):
                    stack.extend(item["@graph"])
    return out


def _jsonld_types(blocks: list[str]) -> tuple[list[str], int]:
    types: list[str] = []
    broken = 0
    for block in blocks:
        try:
            data = json.loads(block)
        except ValueError:
            broken += 1
            continue
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                t = item.get("@type")
                if isinstance(t, str):
                    types.append(t)
                elif isinstance(t, list):
                    types.extend(str(x) for x in t)
                stack.extend(item.get("@graph", []) if isinstance(item.get("@graph"), list) else [])
    return sorted(set(types)), broken


def challenge(resp: Response, page: _Page | None) -> str:
    """Why this response is a bot check and not the page, or "" when it is the page."""
    if resp.headers.get("cf-mitigated", "").lower() == "challenge":
        return "Cloudflare answered with a challenge"
    title = (page.title if page else "") or ""
    if title and _CHALLENGE_TITLE.search(title) and (page is None or page.words < 400):
        return f'the page is a bot check titled "{title}"'
    # Body words alone also appear on real pages ("protected by reCAPTCHA"), so they count only
    # on an error answer or a page with almost no text.
    small = page is None or page.words < 150
    if (resp.status in (401, 403, 405, 429, 503) or small) and _CHALLENGE_BODY.search(
        resp.text()[:200_000]
    ):
        return f"the server answered {resp.status} with a bot check"
    return ""


def _robots_blocks_all(text: str) -> bool:
    return robots.blocked(text, "*")


def audit(url: str, fetch: Fetch = safe_fetch, probe: Callable[[str], str] | None = None) -> dict:
    url = normalise_url(url)
    resp = fetch(url)
    if probe is None and fetch is safe_fetch:
        probe = offered_encoding
    checks: list[dict] = []
    final = resp.url
    scheme = urlsplit(final).scheme
    is_html = "html" in resp.headers.get("content-type", "").lower()
    page = parse_page(resp.text()) if is_html else None
    blocked = challenge(resp, page)
    if blocked:
        return blocked_result(url, resp, blocked)

    checks.append(
        _check(
            "https",
            "Served over HTTPS",
            PASS if scheme == "https" else FAIL,
            f"Final address uses {scheme}.",
            "Install a TLS certificate and redirect every http:// address to https://.",
            3,
        )
    )
    checks.append(
        _check(
            "status",
            "Page answers 200 OK",
            PASS if resp.status == 200 else FAIL,
            f"The server answered {resp.status}.",
            "Make the page return 200; search engines drop pages that answer with an error.",
            3,
        )
    )
    hops = len(resp.chain)
    checks.append(
        _check(
            "redirects",
            "Short redirect chain",
            PASS if hops <= 1 else WARN,
            f"{hops} redirect(s) before the page."
            + (" " + " -> ".join(u for _, u in resp.chain) if hops else ""),
            "Link straight to the final address so crawlers and visitors skip the hops.",
        )
    )
    ms = resp.elapsed_ms
    checks.append(
        _check(
            "speed",
            "Fast server response",
            speed_status(ms),
            f"Took {ms} ms, {SPEED_CAVEAT}.",
            "Confirm the time with a speed test first; if it holds, cache the page, use a CDN, "
            f"or move to faster hosting - aim for under {SPEED_GOOD_MS} ms.",
            2,
        )
    )
    size_kb = len(resp.body) / 1024
    checks.append(
        _check(
            "weight",
            "Reasonable HTML size",
            PASS if size_kb < 300 else WARN if size_kb < 1000 else FAIL,
            f"The HTML is {size_kb:,.0f} KB"
            + (" (cut off at the size limit)." if resp.truncated else "."),
            "Move inline scripts, styles and data out of the HTML document.",
        )
    )
    enc = resp.headers.get("content-encoding", "").lower()
    how = f"Content-Encoding: {enc}." if enc else ""
    if not enc and probe is not None:
        try:
            offered = probe(final)
        except (FetchFailed, FetchRefused):
            offered = ""
        if offered:
            enc = offered
            how = f"Content-Encoding: {offered} (served when a browser accepts it)."
    checks.append(
        _check(
            "compression",
            "Compressed transfer",
            PASS if enc in ("gzip", "br", "deflate", "zstd") else WARN,
            how
            or (
                "No compression for gzip or deflate"
                + ("; Brotli was asked for too." if probe is not None else " (Brotli not checked).")
            ),
            "Turn on gzip or Brotli compression on the web server.",
        )
    )

    ctype = resp.headers.get("content-type", "")
    if page is None:
        checks.append(
            _check(
                "html",
                "The address is an HTML page",
                FAIL,
                f"Content-Type is {ctype or 'missing'}, so there is no page to check.",
                "Audit the address of an HTML page.",
                3,
            )
        )
        return _finish(url, resp, checks, None)

    title = page.title or ""
    checks.append(
        _check(
            "title",
            "Page has a title",
            PASS if title else FAIL,
            f'"{title}"' if title else "No <title> element.",
            "Add a <title> that names the page's topic and your brand.",
            3,
        )
    )
    tl = len(title)
    checks.append(
        _check(
            "title-length",
            "Title is 15-60 characters",
            PASS if 15 <= tl <= 60 else WARN,
            f"{tl} characters.",
            "Search results cut titles at about 60 characters; keep the key words first.",
        )
    )
    desc = page.meta.get("description", "")
    dl = len(desc)
    checks.append(
        _check(
            "description",
            "Meta description of 70-160 characters",
            PASS if 70 <= dl <= 160 else WARN if desc else FAIL,
            f"{dl} characters." if desc else "No meta description.",
            "Write a 70-160 character summary that would make a searcher click.",
            2,
        )
    )
    h1s = [t for level, t in page.headings if level == 1]
    checks.append(
        _check(
            "h1",
            "Exactly one H1 heading",
            PASS if len(h1s) == 1 else WARN if h1s else FAIL,
            f"{len(h1s)} H1 heading(s)"
            + (": " + ", ".join(f'"{t}"' for t in h1s[:3]) if h1s else "."),
            "Give the page one H1 that states what it is about.",
            2,
        )
    )
    skips = [
        (a, b)
        for (a, _), (b, _) in zip(page.headings, page.headings[1:], strict=False)
        if b > a + 1
    ]
    checks.append(
        _check(
            "outline",
            "Headings do not skip levels",
            PASS if not skips else WARN,
            "Heading levels go down one at a time."
            if not skips
            else "Skipped: " + ", ".join(f"H{a} -> H{b}" for a, b in skips[:5]),
            "Nest headings in order (H2 under H1, H3 under H2) so the outline reads as a contents.",
        )
    )
    canon = next(
        (
            ln.get("href", "")
            for ln in page.links
            if "canonical" in ln.get("rel", "").lower().split()
        ),
        "",
    )
    canon_abs = urljoin(final, canon) if canon else ""
    checks.append(
        _check(
            "canonical",
            "Canonical address declared",
            PASS if canon else WARN,
            canon_abs or "No <link rel=canonical>.",
            'Add <link rel="canonical" href="..."> pointing at the page\'s preferred address.',
        )
    )
    robots_meta = (
        page.meta.get("robots", "").lower() + "," + resp.headers.get("x-robots-tag", "").lower()
    )
    noindex = "noindex" in robots_meta
    checks.append(
        _check(
            "indexable",
            "Page allows indexing",
            FAIL if noindex else PASS,
            "A robots rule says noindex." if noindex else "No noindex rule found.",
            "Remove the noindex rule from the robots meta tag or X-Robots-Tag header.",
            3,
        )
    )
    checks.append(
        _check(
            "viewport",
            "Mobile viewport set",
            PASS
            if "width=device-width" in page.meta.get("viewport", "").replace(" ", "")
            else FAIL,
            page.meta.get("viewport") or "No viewport meta tag.",
            'Add <meta name="viewport" content="width=device-width, initial-scale=1">.',
            2,
        )
    )
    checks.append(
        _check(
            "lang",
            "Language declared",
            PASS if page.lang else WARN,
            f'lang="{page.lang}"' if page.lang else "The <html> element has no lang attribute.",
            'Add lang="en" (or ur, ar ...) to the <html> element.',
        )
    )
    images = [i for i in page.images if not i["pixel"]]
    missing_alt = [i for i in images if i["alt"] is None]
    named = ", ".join(
        str(i["src"] or "(no src)").split("?")[0].rsplit("/", 1)[-1][:60] for i in missing_alt[:5]
    )
    checks.append(
        _check(
            "alt",
            "Images have alt text",
            PASS if not missing_alt else WARN if len(missing_alt) <= 2 else FAIL,
            f"{len(missing_alt)} of {len(images)} images have no alt attribute"
            + ((": " + named + (" ..." if len(missing_alt) > 5 else "")) if missing_alt else "")
            + ".",
            'Describe each image in an alt attribute; use alt="" for purely decorative ones.',
        )
    )
    types, broken = _jsonld_types(page.jsonld)
    checks.append(
        _check(
            "schema",
            "Structured data present",
            PASS if types and not broken else WARN,
            ("Types: " + ", ".join(types) if types else "No JSON-LD structured data.")
            + (f" {broken} block(s) are not valid JSON." if broken else ""),
            "Add JSON-LD (Organization, LocalBusiness, Product or Article) so search and AI "
            "answers can read who you are.",
            2,
        )
    )
    og = [k for k in ("og:title", "og:description", "og:image") if page.meta.get(k)]
    checks.append(
        _check(
            "social",
            "Social preview tags",
            PASS if len(og) == 3 else WARN,
            f"{len(og)} of 3 Open Graph tags present ({', '.join(og) or 'none'}).",
            "Add og:title, og:description and og:image so shared links show a preview card.",
        )
    )
    checks.append(
        _check(
            "content",
            "Enough text to rank",
            PASS if page.words >= 300 else WARN,
            f"About {page.words:,} words of visible text.",
            "Pages with very little text rarely rank; answer the visitor's question in full.",
        )
    )

    origin = f"{scheme}://{urlsplit(final).netloc}"
    robots_text = ""
    try:
        r = fetch(origin + "/robots.txt")
        if r.status == 200:
            robots_text = r.text()
        robots_status = r.status
    except (FetchFailed, FetchRefused):
        robots_status = 0
    blocked = _robots_blocks_all(robots_text)
    checks.append(
        _check(
            "robots",
            "robots.txt lets crawlers in",
            FAIL if blocked else PASS if robots_status == 200 else WARN,
            "robots.txt blocks every crawler with Disallow: /."
            if blocked
            else "robots.txt found and does not block the site."
            if robots_status == 200
            else f"No robots.txt (answered {robots_status or 'nothing'}).",
            "Serve a robots.txt that allows crawling and names your sitemap.",
            2,
        )
    )
    sitemap = bool(robots.sitemaps(robots_text))
    if not sitemap:
        try:
            sitemap = fetch(origin + "/sitemap.xml").status == 200
        except (FetchFailed, FetchRefused):
            sitemap = False
    checks.append(
        _check(
            "sitemap",
            "Sitemap available",
            PASS if sitemap else WARN,
            "A sitemap is listed or answers at /sitemap.xml." if sitemap else "No sitemap found.",
            "Publish /sitemap.xml and list it in robots.txt.",
        )
    )

    internal = sum(
        1 for h in page.anchors if urlsplit(urljoin(final, h)).netloc == urlsplit(final).netloc
    )
    facts = {
        "title": title,
        "description": desc,
        "h1": h1s[:3],
        "words": page.words,
        "images": len(images),
        "links_internal": internal,
        "links_external": len(page.anchors) - internal,
        "schema_types": types,
    }
    return _finish(url, resp, checks, facts)


def _finish(url: str, resp: Response, checks: list[dict], facts: dict | None) -> dict:
    score, counts = score_checks(checks)
    return {
        "url": url,
        "final_url": resp.url,
        "status": resp.status,
        "elapsed_ms": resp.elapsed_ms,
        "score": score,
        "counts": counts,
        "checks": sort_checks(checks),
        "facts": facts,
    }


def blocked_result(url: str, resp: Response, reason: str) -> dict:
    """No score: nothing read from a bot check is true of the page visitors see."""
    return {
        "url": url,
        "final_url": resp.url,
        "status": resp.status,
        "elapsed_ms": resp.elapsed_ms,
        "blocked": reason,
        "score": None,
        "counts": {PASS: 0, WARN: 0, FAIL: 0},
        "checks": [],
        "facts": None,
    }


BLOCKED_ADVICE = (
    "Nothing here describes the real page, so there is no score and no advice. Open the site in a "
    "browser to check it by hand, or ask the owner to let RankloomBot through their bot "
    "protection, and run the check again."
)


def blocked_view(result: dict, what: str = "page") -> dict:
    return view(
        headline(result["final_url"], f"Could not read the real {what}: {result['blocked']}"),
        text_block("Bot protection stopped the check", BLOCKED_ADVICE),
    )


def audit_view(result: dict) -> dict:
    if result.get("blocked"):
        return blocked_view(result)
    f = result["facts"]
    fact_block = (
        facts_block(
            "What the page says about itself",
            [
                ("Title", f["title"] or "-"),
                ("Description", f["description"] or "-"),
                ("H1", " | ".join(f["h1"]) or "-"),
                ("Words", f"{f['words']:,}"),
                ("Links in / out", f"{f['links_internal']} / {f['links_external']}"),
                ("Structured data", ", ".join(f["schema_types"]) or "none"),
            ],
        )
        if f
        else None
    )
    return view(
        headline(
            result["final_url"],
            f"Answered {result['status']} in {result['elapsed_ms']} ms",
            result["score"],
            result["counts"],
        ),
        fact_block,
        checks_block("Checks", result["checks"], "Failures first, then warnings, heaviest first"),
    )


def run(fields: dict, ctx: Context | None = None) -> tuple[str, int | None, dict]:
    fetch = ctx.fetch if ctx else None
    result = audit(str(fields.get("url", "")), **({"fetch": fetch} if fetch else {}))
    if result.get("blocked"):
        return (
            f"{result['final_url']}: could not read the real page ({result['blocked']})",
            None,
            {**result, "view": audit_view(result)},
        )
    c = result["counts"]
    summary = (
        f"{result['final_url']} scored {result['score']}/100 - {c['fail']} fail, {c['warn']} warn"
    )
    return summary, result["score"], {**result, "view": audit_view(result)}
