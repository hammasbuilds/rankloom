"""Each sub-tool engine against inputs whose right answer is known."""

import pytest
from test_site_audit import GOOD

from rankloom import ai, robots, sources
from rankloom.engines import ai_visibility, content, crawl, local_seo
from rankloom.engines.common import Context, InputProblem
from rankloom.netguard import Response


def site(pages: dict, ms: int = 100):
    """A fake website: path -> (status, html) or (status, html, headers)."""

    def fetch(url):
        from urllib.parse import urlsplit

        parts = urlsplit(url)
        key = parts.path or "/"
        if key not in pages:
            return Response(
                url=url,
                status=404,
                headers={"content-type": "text/html"},
                body=b"not found",
                elapsed_ms=ms,
            )
        status, html, *rest = pages[key]
        headers = {"content-type": "text/html", **(rest[0] if rest else {})}
        return Response(
            url=f"{parts.scheme}://{parts.netloc}{key}",
            status=status,
            headers=headers,
            body=html.encode(),
            elapsed_ms=ms,
        )

    return fetch


def html(title, body, extra_head=""):
    return (
        f"<html lang=en><head><title>{title}</title>"
        f'<meta name="description" content="{title} - a description long enough to pass the '
        f'length check comfortably here.">{extra_head}</head><body>{body}</body></html>'
    )


# --- robots ------------------------------------------------------------------------------------


ROBOTS = """
User-agent: *
Disallow: /private

User-agent: GPTBot
User-agent: CCBot
Disallow: /

User-agent: PerplexityBot
Disallow: /
Allow: /

Sitemap: https://x.example/sitemap.xml
"""


def test_robots_groups_and_the_most_specific_group_wins():
    assert robots.blocked(ROBOTS, "GPTBot")
    assert robots.blocked(ROBOTS, "CCBot")
    assert not robots.blocked(ROBOTS, "PerplexityBot")  # Allow: / overrides
    assert not robots.blocked(ROBOTS, "OAI-SearchBot")  # falls to *, which allows /
    assert robots.partial(ROBOTS, "OAI-SearchBot") == ["/private"]
    assert robots.sitemaps(ROBOTS) == ["https://x.example/sitemap.xml"]
    assert robots.rules_for("", "GPTBot") is None


# --- crawl -------------------------------------------------------------------------------------


def test_crawl_finds_broken_duplicate_and_thin_pages():
    words = "word " * 400
    pages = {
        "/": (
            200,
            html(
                "Home of Solar",
                f"<h1>Home</h1><a href=/a>a</a><a href=/b>b</a>"
                f"<a href=/missing>m</a><a href='https://other.example/'>x</a>"
                f"<a href=/file.pdf>pdf</a><a href='mailto:a@b'>mail</a><p>{words}</p>",
            ),
        ),
        "/a": (200, html("Same Title", f"<h1>A</h1><a href=/c>c</a><p>{words}</p>")),
        "/b": (200, html("Same Title", "<p>tiny</p>")),
        "/c": (200, html("Page C", f"<h1>C</h1><h1>again</h1><p>{words}</p>")),
    }
    r = crawl.crawl("https://solar.example/", site(pages), max_pages=10)
    read = {p["url"].rsplit("/", 1)[-1] or "/" for p in r["pages"]}
    assert read == {"/", "a", "b", "missing", "c"}  # never the PDF, mailto or other site
    checks = {c["id"]: c for c in crawl.analyse(r)}
    assert checks["broken"]["status"] == "fail" and "1 of 5" in checks["broken"]["detail"]
    assert checks["dup-title"]["status"] == "warn"
    assert checks["thin"]["status"] != "pass"
    assert "/" in r["linked_from"]["https://solar.example/missing"][0]


def test_crawl_respects_the_page_limit_and_says_so():
    links = "".join(f"<a href=/p{i}>p</a>" for i in range(30))
    pages = {"/": (200, html("Home", links))}
    for i in range(30):
        pages[f"/p{i}"] = (200, html(f"P{i}", "<h1>x</h1>"))
    summary, score, out = crawl.run(
        {"url": "solar.example", "pages": "10"}, Context(1, None, site(pages))
    )
    assert len(out["pages"]) == 10
    assert out["discovered"] == 31
    assert "Read 10 of 31" in out["view"]["headline"]["subtitle"]
    assert "page limit" in out["view"]["headline"]["subtitle"]


# --- local SEO ---------------------------------------------------------------------------------

LOCAL = html(
    "Smile Care Dentist Lahore",
    "<h1>Dentist in Lahore</h1><p>Call 0300-1234567 or visit 12 Main Boulevard, Gulberg.</p>"
    '<a href="tel:+923001234567">Call</a><a href="https://wa.me/923001234567">WhatsApp</a>'
    '<a href="https://g.page/smilecare/review">Review us</a>'
    '<iframe src="https://www.google.com/maps/embed?pb=1"></iframe>',
    '<script type="application/ld+json">{"@type":"Dentist","name":"Smile Care",'
    '"telephone":"+92 300 1234567","address":{"@type":"PostalAddress",'
    '"streetAddress":"12 Main Boulevard","addressLocality":"Lahore"},'
    '"openingHours":"Mo-Sa 10:00-20:00","geo":{"latitude":31.5,"longitude":74.3},'
    '"aggregateRating":{"ratingValue":4.8,"reviewCount":120},'
    '"sameAs":["https://facebook.com/smilecare"]}</script>',
)


def test_a_complete_local_page_passes_and_matching_phones_are_recognised():
    r = local_seo.audit("smile.example", "Lahore", site({"/": (200, LOCAL)}))
    failing = [c["id"] for c in r["checks"] if c["status"] != "pass"]
    assert failing == []
    assert r["score"] == 100


def test_a_phone_in_the_data_that_is_not_on_the_page_is_a_failure():
    page = LOCAL.replace("0300-1234567", "0321-7654321").replace(
        "tel:+923001234567", "tel:+923217654321"
    )
    r = local_seo.audit("smile.example", "Lahore", site({"/": (200, page)}))
    checks = {c["id"]: c for c in r["checks"]}
    assert checks["nap-match"]["status"] == "fail"


def test_a_bare_page_fails_the_local_basics():
    r = local_seo.audit("x.example", "Karachi", site({"/": (200, html("Welcome", "<p>Hi</p>"))}))
    checks = {c["id"]: c for c in r["checks"]}
    for cid in ("schema", "phone"):
        assert checks[cid]["status"] == "fail", cid
    assert checks["city"]["status"] == "warn"


# --- AI readiness ------------------------------------------------------------------------------


def test_ai_readiness_flags_blocked_answer_bots_and_script_only_pages():
    blocking = "User-agent: OAI-SearchBot\nDisallow: /\n\nUser-agent: GPTBot\nDisallow: /\n"
    pages = {
        "/": (
            200,
            "<html><head><title>App</title></head><body><div id=root></div>"
            "<script src=app.js></script></body></html>",
        ),
        "/robots.txt": (200, blocking, {"content-type": "text/plain"}),
    }
    r = ai_visibility.readiness("app.example", site(pages))
    checks = {c["id"]: c for c in r["checks"]}
    assert checks["answer-bots"]["status"] == "fail"
    assert "OAI-SearchBot" in checks["answer-bots"]["detail"]
    assert checks["training-bots"]["status"] == "warn"
    assert checks["rendered"]["status"] == "fail"
    gpt = next(a for a in r["agents"] if a["agent"] == "GPTBot")
    assert gpt["blocked"] and not gpt["critical"]


def test_ai_readiness_passes_a_well_described_page():
    faq = "".join(f"<h2>How much does solar cost {i}?</h2><p>answer</p>" for i in range(3))
    pages = {
        "/": (
            200,
            GOOD.replace(
                "</body>", f"{faq}<a href=/about>About</a><a href=/contact>Contact</a></body>"
            ),
            {"last-modified": "Mon, 19 Oct 2026 10:00:00 GMT"},
        ),
        "/robots.txt": (200, "User-agent: *\nAllow: /\n", {"content-type": "text/plain"}),
        "/llms.txt": (200, "# Solar\n", {"content-type": "text/plain"}),
    }
    r = ai_visibility.readiness("solar.example", site(pages))
    bad = {c["id"]: c["status"] for c in r["checks"] if c["status"] != "pass"}
    assert bad == {"entity": "warn"}  # the fixture's Organization has no sameAs links


# --- questions and keywords (autocomplete patched) ---------------------------------------------


@pytest.fixture
def fake_suggest(monkeypatch):
    calls = []

    def suggest(q, country="pk", language="en"):
        calls.append(q)
        base = q.lower()
        return "google", [
            base,
            f"{base} price",
            f"how much is {base}",
            f"{base} near me",
            "unrelated thing",
        ]

    monkeypatch.setattr(sources, "suggest", suggest)
    return calls


def test_keyword_ideas_group_by_intent_and_count_lookups(fake_suggest):
    r = content.expand("rooftop solar", "pk")
    assert r["answered"] == r["asked"] == len(fake_suggest)
    assert "unrelated thing" not in r["phrases"]
    assert any(p.startswith("how much") for p in r["groups"]["Questions"])
    assert any("price" in p for p in r["groups"]["Comparing and buying"])
    assert any("near me" in p for p in r["groups"]["Local"])
    assert r["asked"] > 15  # modifiers, question prefixes and Pakistani phrasings


def test_keyword_ideas_report_when_no_provider_answers(monkeypatch):
    def down(*a, **k):
        raise sources.SourceFailed("down")

    monkeypatch.setattr(sources, "suggest", down)
    with pytest.raises(InputProblem):
        content.run_keywords({"seed": "solar"}, Context(1))


def test_question_builder_mixes_templates_and_real_phrasings(fake_suggest):
    r = ai_visibility.build_questions("dentist", "Lahore", "Smile Care")
    assert "Who is the best dentist in Lahore?" in r["templates"]
    assert "Is Smile Care a good dentist?" in r["templates"]
    assert r["answered"] == r["asked"] == 4
    assert all(q.endswith(("?", ".")) for q in r["from_search"])


def test_a_brief_turns_real_questions_into_headings(fake_suggest):
    b = content.brief("rooftop solar")
    assert any(h.startswith("H2: How much") for h in b["outline"])
    assert b["outline"][0].startswith("H1: Rooftop solar")
    assert "price" in b["terms"]


# --- answer check and drafts (AI engine faked) -------------------------------------------------


class FakeEngine:
    def __init__(self, answers):
        self.answers = answers
        self.prompts = []

    def complete(self, prompt, system="", max_tokens=900, temperature=0.3):
        self.prompts.append(prompt)
        return self.answers[(len(self.prompts) - 1) % len(self.answers)]


def test_answer_check_counts_mentions_and_names_competitors():
    engine = FakeEngine(
        [
            "Here are good options:\n1. **Smile Care Clinic** - smilecare.pk\n2. **Bright Teeth** "
            "- brightteeth.pk\n",
            "I recommend **Bright Teeth** (brightteeth.pk) and **Dental Hub**.",
        ]
    )
    r = ai_visibility.answer_check(
        {
            "brand": "Smile Care Clinic",
            "site": "smilecare.pk",
            "niche": "dentist",
            "city": "Lahore",
        },
        engine,
    )
    assert r["asked"] == 6 and r["answered"] == 6
    assert r["mentioned"] == 3 and r["rate"] == 50
    rivals = dict(r["rivals"])
    assert rivals["Bright Teeth"] == 6
    assert "Smile Care Clinic" not in rivals


def test_answer_check_finds_the_brand_by_its_domain_alone():
    seen = ai_visibility.read_answer(
        "Try the clinic at smilecare.pk for implants.", "Smile Care", "https://www.smilecare.pk/"
    )
    assert seen["mentioned"]


def test_answer_check_refuses_without_an_engine(monkeypatch):
    monkeypatch.delenv("RANKLOOM_AI", raising=False)
    with pytest.raises(ai.AIUnavailable):
        ai_visibility.run_answers({"brand": "x", "niche": "y"}, Context(1))


def test_draft_marks_every_checkable_claim(fake_suggest, monkeypatch):
    draft = (
        "# Rooftop solar\n\nSolar panels cost Rs 45,000 per kW in Lahore. They are the best "
        "investment you can make. Many homeowners find them useful for daytime loads.\n"
        "Net metering started in 2015 and pays back in 4 years."
    )
    monkeypatch.setattr(ai, "require", lambda: FakeEngine([draft]))
    summary, _, r = content.run_draft({"topic": "rooftop solar"}, Context(1))
    claims = " | ".join(r["claims"])
    assert "Rs 45,000" in claims and "best investment" in claims and "2015" in claims
    assert "daytime loads" not in claims


def test_ai_engine_strips_reasoning_blocks():
    assert ai.strip_thinking("<think>scratch</think>Answer") == "Answer"


def test_ai_engine_from_environment(monkeypatch):
    monkeypatch.setenv("RANKLOOM_AI", "openai")
    monkeypatch.setenv("RANKLOOM_AI_MODEL", "sonar")
    monkeypatch.setenv("RANKLOOM_AI_URL", "https://api.perplexity.ai")
    monkeypatch.setenv("RANKLOOM_AI_KEY", "k")
    e = ai.engine()
    sent = {}

    def post(url, body, headers):
        sent.update(url=url, body=body, headers=headers)
        return {"choices": [{"message": {"content": "hello"}}]}

    monkeypatch.setattr(ai, "post", post)
    assert e.complete("hi") == "hello"
    assert sent["url"] == "https://api.perplexity.ai/chat/completions"
    assert sent["headers"]["Authorization"] == "Bearer k"


# --- content grader ----------------------------------------------------------------------------


def test_grader_scores_a_strong_text_above_a_weak_one():
    strong = (
        "Rooftop solar in Lahore is cheaper than ever. " + "Panels, inverters and net "
        "metering explained simply. " * 120
    )
    weak = "Welcome to our website. We sell things."
    g1 = content.grade(
        "rooftop solar",
        strong,
        "Rooftop solar in Lahore",
        ["Rooftop solar"],
        4,
        ["panels", "inverters", "metering"],
    )
    g2 = content.grade("rooftop solar", weak, "Home", [], 0, ["panels", "inverters"])
    assert g1["score"] > 80 > g2["score"]
    assert {c["id"]: c["status"] for c in g2["checks"]}["kw-title"] == "fail"


# --- outreach wording --------------------------------------------------------------------------


def test_outreach_never_calls_a_missing_robots_txt_a_block():
    from rankloom.engines import leads

    plain_page = {"/": (200, html("Shop", "<h1>Shop</h1><p>" + "word " * 400 + "</p>"))}
    missing = leads.quick_audit("https://shop.example/", site(plain_page))
    assert not any("blocks search engines" in p for p in missing["problems"])
    blocked = {
        **plain_page,
        "/robots.txt": (200, "User-agent: *\nDisallow: /\n", {"content-type": "text/plain"}),
    }
    really = leads.quick_audit("https://shop.example/", site(blocked))
    assert any("blocks search engines" in p for p in really["problems"])


def test_a_no_website_draft_never_mentions_their_website():
    from rankloom.engines import leads

    email = leads.write_drafts("Sunrise Dental", "", [], "Ayesha", "")[0]["text"]
    assert "on your website" not in email and "cannot find you" in email


def test_opportunities_keep_a_small_sites_near_page_one_queries():
    from rankloom.engines import search_perf

    rows = [
        {"key": k, "clicks": c, "impressions": i, "ctr": c / i, "position": p}
        for k, c, i, p in [
            ("a", 120, 5400, 4.2),
            ("b", 64, 2100, 6.1),
            ("c", 9, 2600, 11.4),
            ("inverter", 3, 1900, 14.2),
            ("e", 31, 900, 3.1),
            ("battery", 0, 1300, 18.5),
        ]
    ]
    o = search_perf.opportunities({"queries": rows, "pages": []})
    assert "inverter" in [r["key"] for r in o["striking"]]
    assert "battery" in [r["key"] for r in o["zero"]]
    assert o["floor"] == 1300
