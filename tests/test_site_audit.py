from rankloom.engines import site_audit
from rankloom.netguard import Response

GOOD = (
    """<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rooftop solar in Lahore - prices and installers</title>
<meta name="description" content="What rooftop solar costs in Lahore in 2026, how net metering works, and how to choose an installer you can trust.">
<link rel="canonical" href="/solar">
<meta property="og:title" content="Solar"><meta property="og:description" content="d">
<meta property="og:image" content="/i.png">
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"Organization"},{"@type":"Article"}]}</script>
<script>var ignored = "these words are not page text at all";</script>
</head><body><h1>Rooftop solar</h1><h2>Costs</h2><h3>Panels</h3><h2>Installers</h2>
<img src="a.png" alt="Panels on a roof"><img src="divider.png" alt>
<a href="/contact">Contact</a><a href="https://other.example/">Other</a>
<p>"""
    + "word " * 400
    + "</p></body></html>"
)

BAD = """<html><head><meta name="robots" content="noindex, nofollow"></head>
<body><h1>One</h1><h1>Two</h1><h4>Deep</h4><img src="a.png"><img src="b.png"><img src="c.png">
<script type="application/ld+json">{not json</script><p>tiny</p></body></html>"""


def fetcher(pages):
    def fetch(url):
        status, body, headers, final, chain = pages.get(url, (404, "", {}, url, []))
        return Response(
            url=final,
            status=status,
            headers={"content-type": "text/html", **headers},
            body=body.encode(),
            elapsed_ms=120,
            chain=chain,
        )

    return fetch


def by_id(result):
    return {c["id"]: c for c in result["checks"]}


def test_a_well_built_page_passes_every_check():
    pages = {
        "https://solar.example/": (
            200,
            GOOD,
            {"content-encoding": "gzip"},
            "https://solar.example/",
            [],
        ),
        "https://solar.example/robots.txt": (
            200,
            "User-agent: *\nDisallow: /admin\nSitemap: https://solar.example/sitemap.xml",
            {},
            "",
            [],
        ),
    }
    result = site_audit.audit("solar.example", fetch=fetcher(pages))
    checks = by_id(result)
    assert len(checks) == 21
    # The About panel quotes the count; keep the claim tied to the code.
    from rankloom.tools import BY_SLUG

    page_audit = BY_SLUG["site-audit"]["subtools"][0]
    assert f"Runs {len(checks)} " in " ".join(page_audit["does"])
    assert f"{len(checks)} checks" in page_audit["tagline"]
    failing = [c for c in checks.values() if c["status"] != "pass"]
    assert failing == []
    assert result["score"] == 100
    assert result["facts"]["schema_types"] == ["Article", "Organization"]
    assert result["facts"]["links_internal"] == 1 and result["facts"]["links_external"] == 1
    assert all(c["fix"] == "" for c in checks.values())


def test_script_text_is_not_counted_as_page_words():
    pages = {"https://solar.example/": (200, GOOD, {}, "https://solar.example/", [])}
    words = site_audit.audit("https://solar.example/", fetch=fetcher(pages))["facts"]["words"]
    assert 400 <= words < 420


def test_a_bare_alt_counts_as_decorative_not_missing():
    pages = {"https://solar.example/": (200, GOOD, {}, "https://solar.example/", [])}
    checks = by_id(site_audit.audit("https://solar.example/", fetch=fetcher(pages)))
    assert checks["alt"]["status"] == "pass"


def test_a_broken_page_names_each_problem_with_a_fix():
    pages = {
        "http://bad.example/": (
            200,
            BAD,
            {},
            "http://bad.example/",
            [(301, "http://bad.example"), (302, "http://www.bad.example/")],
        ),
        "http://bad.example/robots.txt": (200, "User-agent: *\nDisallow: /\n", {}, "", []),
    }
    result = site_audit.audit("http://bad.example/", fetch=fetcher(pages))
    checks = by_id(result)
    for cid in ("https", "title", "description", "indexable", "viewport", "alt", "robots"):
        assert checks[cid]["status"] == "fail", cid
        assert checks[cid]["fix"], cid
    for cid in (
        "redirects",
        "h1",
        "outline",
        "canonical",
        "lang",
        "schema",
        "social",
        "content",
        "compression",
        "sitemap",
    ):
        assert checks[cid]["status"] == "warn", cid
    assert "not valid JSON" in checks["schema"]["detail"]
    assert "H1 -> H4" in checks["outline"]["detail"]
    assert result["score"] < 40
    order = [c["status"] for c in result["checks"]]
    assert order == sorted(order, key=["fail", "warn", "pass"].index)


def test_robots_disallow_for_one_bot_does_not_block_everyone():
    text = "User-agent: BadBot\nDisallow: /\n\nUser-agent: *\nDisallow: /private\n"
    assert not site_audit._robots_blocks_all(text)
    assert site_audit._robots_blocks_all("User-agent: *\nDisallow: /")


def test_a_non_html_address_stops_after_the_transport_checks():
    def fetch(url):
        return Response(
            url=url,
            status=200,
            headers={"content-type": "application/pdf"},
            body=b"%PDF",
            elapsed_ms=50,
        )

    result = site_audit.audit("https://x.example/file.pdf", fetch=fetch)
    checks = by_id(result)
    assert checks["html"]["status"] == "fail"
    assert "title" not in checks
    assert result["facts"] is None


def test_noindex_in_the_header_is_caught_too():
    pages = {
        "https://solar.example/": (
            200,
            GOOD,
            {"x-robots-tag": "noindex"},
            "https://solar.example/",
            [],
        )
    }
    checks = by_id(site_audit.audit("https://solar.example/", fetch=fetcher(pages)))
    assert checks["indexable"]["status"] == "fail"


def test_addresses_are_normalised_to_a_root_path():
    assert site_audit.normalise_url("example.com") == "https://example.com/"
    assert site_audit.normalise_url(" http://x.example/a?b=1 ") == "http://x.example/a?b=1"


def test_run_returns_a_summary_and_score():
    pages = {"https://solar.example/": (200, GOOD, {}, "https://solar.example/", [])}
    original = site_audit.safe_fetch
    try:
        site_audit.audit.__defaults__ = (fetcher(pages), None)
        summary, score, out = site_audit.run({"url": "solar.example"})
    finally:
        site_audit.audit.__defaults__ = (original, None)
    assert summary.startswith("https://solar.example/ scored")
    assert score == out["score"]
