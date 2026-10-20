"""Each sub-tool engine against inputs whose right answer is known."""

import pytest
from test_site_audit import GOOD

from rankloom import ai, robots, sources
from rankloom.engines import (
    ai_visibility,
    content,
    crawl,
    leads,
    local_seo,
    reports,
    search_perf,
    site_audit,
)
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
    assert b["outline"][0].startswith("H1: Rooftop Solar")
    assert "price" not in b["terms"]  # added by the lookups, not chosen by searchers


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
    assert "on your website" not in email and "could not find a website listed" in email
    # The lead came from a map, so "nothing on Maps" would be false.
    assert "Maps" not in email


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


def test_a_site_that_did_not_answer_is_never_quoted_to_the_business():
    from rankloom.engines import leads
    from rankloom.netguard import FetchFailed

    def down(url):
        raise FetchFailed("timed out")

    qa = leads.quick_audit("https://slow.example/", down)
    assert qa["problems"] == [leads.UNREACHABLE]
    email = leads.write_drafts("Pro Hygenist", "https://slow.example/", qa["problems"], "", "")[0]
    text = email["text"]
    assert "does not load" not in text and "did not answer" not in text
    # Nothing was found, so nothing is promised.
    assert "quick wins" not in text and "fixable" not in text and "What I found" not in text
    one = leads.write_drafts("A", "https://a.example/", ["the home page has no title"], "", "")
    assert "1 thing I noticed" in one[0]["text"]


def test_no_localbusiness_block_is_not_reported_as_a_missing_name():
    page = html(
        "Hospital",
        "<p>Call 042 3590 5000</p>",
        '<script type="application/ld+json">{"@type":"Organization","name":"SKM"}</script>',
    )
    r = local_seo.audit("skm.example", "Lahore", site({"/": (200, page)}))
    nap = next(c for c in r["checks"] if c["id"] == "nap-data")
    assert "Missing" not in nap["detail"] and "names SKM" in nap["detail"]


def test_words_the_tool_added_to_lookups_are_not_related_terms(fake_suggest):
    r = content.expand("rooftop solar", "pk")
    words = {w for w, _ in r["terms"]}
    assert not words & {"kya", "kaise", "lahore", "karachi", "pakistan", "much", "number"}


def test_a_website_given_beside_the_brand_is_not_a_rival_and_a_wrong_one_is_flagged():
    answer = (
        "1. Shaukat Khanum Memorial Cancer Hospital\n   - Website: www.skmemorial.org\n"
        "2. Agha Khan University Hospital\n   - Website: www.aku.edu\n"
    )
    seen = ai_visibility.read_answer(answer, "Shaukat Khanum", "shaukatkhanum.org.pk")
    assert seen["mentioned"]
    assert "Shaukat Khanum Memorial Cancer Hospital" not in seen["competitors"]
    assert "aku.edu" in seen["competitors"]
    # The website line sits under the brand's line; it is the brand's address in the answer.
    one = ai_visibility.read_answer(
        "Shaukat Khanum is best - visit www.skmch.org.", "Shaukat Khanum", "shaukatkhanum.org.pk"
    )
    assert one["wrong_sites"] == ["skmch.org"] and "skmch.org" not in one["competitors"]
    right = ai_visibility.read_answer(
        "Shaukat Khanum (shaukatkhanum.org.pk).", "Shaukat Khanum", "shaukatkhanum.org.pk"
    )
    assert right["site_cited"] and not right["wrong_sites"]


def test_two_words_that_travel_together_stay_one_term(monkeypatch):
    def suggest(q, country="pk", language="en"):
        return "google", [
            "solar panel price hall road",
            "solar panel hall road lahore",
            "hall road solar market",
            "solar panel inverter",
        ]

    monkeypatch.setattr(sources, "suggest", suggest)
    terms = dict(content.expand("solar panel", "pk")["terms"])
    assert "hall road" in terms and "hall" not in terms and "road" not in terms


def test_claims_skip_questions_and_plain_advice():
    claims = content.mark_claims(
        "How do I find the best installer in Lahore? Find the best solution for your budget. "
        "Sun Power is the best installer in Lahore. Panels last 25 years."
    )
    assert claims == ["Sun Power is the best installer in Lahore.", "Panels last 25 years."]


def test_a_website_on_the_line_under_the_brand_belongs_to_the_brand():
    answer = (
        "For cancer treatment in Lahore, consider:\n\n"
        "1. Shaukat Khanum Memorial Cancer Hospital\n   - Website: www.skmemorial.org\n\n"
        "2. Agha Khan University Hospital\n   - Website: www.aku.edu\n"
    )
    seen = ai_visibility.read_answer(answer, "Shaukat Khanum", "shaukatkhanum.org.pk")
    assert seen["wrong_sites"] == ["skmemorial.org"]
    assert "skmemorial.org" not in seen["competitors"] and "aku.edu" in seen["competitors"]


def test_comparison_heading_drops_phrases_that_restate_the_topic(monkeypatch):
    def suggest(q, country="pk", language="en"):
        return "google", [
            "solar panel prices in lahore hall road",
            "best solar panel brand",
            "solar panel price in lahore today",
        ]

    monkeypatch.setattr(sources, "suggest", suggest)
    b = content.brief("solar panel price in lahore")
    heading = next((h for h in b["outline"] if "Comparing" in h), "")
    assert "hall road" not in heading.lower() and "today" not in heading.lower()


# --- a senior SEO's review: the client's market, and claims that were not true ----------------


def market_suggest(monkeypatch, phrases):
    asked = []

    def suggest(q, country="pk", language="en"):
        asked.append(country)
        return "google", phrases

    monkeypatch.setattr(sources, "suggest", suggest)
    return asked


def test_question_builder_keeps_to_the_clients_market(monkeypatch):
    asked = market_suggest(
        monkeypatch,
        [
            "how much dentist earn in pakistan",
            "dentist lahore",
            "dentist johar town",
            "emergency dentist nyc",
            "dentist jobs williamsville",
            "best dentist williamsville ny",
            "dentist near me open saturday",
        ],
    )
    _, _, r = ai_visibility.run_questions(
        {"niche": "dentist", "city": "Williamsville, NY", "country": "us"}, Context(1)
    )
    assert set(asked) == {"us"}
    assert r["searched"] == ["best dentist williamsville ny", "dentist near me open saturday"]
    assert r["dropped"] == 5
    assert "United States" in r["view"]["headline"]["subtitle"]


def test_the_country_is_a_visible_choice_on_every_autocomplete_tool():
    from rankloom.tools import TOOLS

    subs = {f"{t['slug']}/{s['slug']}": s for t in TOOLS for s in t["subtools"]}
    for key in (
        "ai-visibility/questions",
        "content-studio/keywords",
        "content-studio/brief",
        "content-studio/draft",
        "content-studio/grade",
        "site-audit/local",
    ):
        field = next(f for f in subs[key]["fields"] if f["name"] == "country")
        assert field["type"] == "select" and len(field["options"]) > 10, key
        assert any(o["value"] == "us" for o in field["options"])


def test_keyword_ideas_leave_out_other_markets_and_file_place_searches_as_local(monkeypatch):
    market_suggest(
        monkeypatch,
        [
            "emergency dentist prices nhs",
            "emergency dentist open bank holidays",
            "emergency dentist costa adeje",
            "emergency dentist nyc",
            "emergency dentist open sunday",
            "emergency dentist cost without insurance",
        ],
    )
    r = content.expand("emergency dentist", "us")
    assert r["phrases"] == [
        "emergency dentist nyc",
        "emergency dentist open sunday",
        "emergency dentist cost without insurance",
    ]
    assert r["other_market"] == 3
    assert "emergency dentist nyc" in r["groups"]["Local"]
    words = [w for w, _ in r["terms"]]
    assert "nhs" not in words and "bank" not in words and "holidays" not in words


def test_grader_reads_the_keyword_as_words_not_punctuation():
    title = "Emergency Dentist Williamsville, NY | (716) 689-8882 | Amherst Dental"
    body = "Emergency dentist Williamsville, NY: we see you today. " + "Care. " * 300
    g = content.grade(
        "emergency dentist williamsville ny", body, title, ["Emergency Dentist Williamsville, NY"]
    )
    ids = {c["id"]: c["status"] for c in g["checks"]}
    assert ids["kw-title"] == "pass" and ids["kw-h1"] == "pass" and ids["kw-intro"] == "pass"
    g = content.grade("emergency dentist", "Our dentistry team. " * 50, "Dentistry", [])
    assert {c["id"]: c["status"] for c in g["checks"]}["kw-title"] == "fail"


def test_a_brief_title_cases_its_topic(fake_suggest):
    assert content.title_case("emergency dentist williamsville ny") == (
        "Emergency Dentist Williamsville NY"
    )
    assert content.title_case("price of solar in lahore") == "Price of Solar in Lahore"
    b = content.brief("emergency dentist williamsville ny", "us")
    assert b["title"].startswith("Emergency Dentist Williamsville NY - ")


def test_the_grader_and_brief_read_the_chosen_market(monkeypatch):
    asked = market_suggest(monkeypatch, ["solar price"])
    content.run_grade({"keyword": "solar", "text": "solar " * 50, "country": "gb"}, Context(1))
    content.run_brief({"topic": "solar", "country": "gb"}, Context(1))
    assert set(asked) == {"gb"}


KATZ = (
    "<html><head><title>Human Verification</title></head><body><h1>JavaScript is disabled</h1>"
    "<p>In order to continue, we need to verify that you're not a robot.</p></body></html>"
)
CLOUDFLARE = (
    "<html><head><title>Just a moment...</title></head><body>"
    "<p>Enable JavaScript and cookies to continue</p></body></html>"
)


def test_a_bot_check_page_is_reported_as_unreadable_not_scored():
    for status, page in ((405, KATZ), (403, CLOUDFLARE)):
        fetch = site({"/": (status, page)})
        summary, score, out = site_audit.run({"url": "katz.example"}, Context(1, None, fetch))
        assert score is None and out["blocked"] and out["checks"] == []
        assert "could not read the real page" in summary
        assert "no score and no advice" in out["view"]["blocks"][0]["text"]
        _, score, out = local_seo.run({"url": "katz.example"}, Context(1, None, fetch))
        assert score is None and out["blocked"]
        _, score, out = crawl.run({"url": "katz.example"}, Context(1, None, fetch))
        assert score is None and out["blocked"]


def test_a_real_page_that_mentions_a_captcha_is_still_audited():
    page = GOOD.replace("</body>", "<p>This form is protected by reCAPTCHA.</p></body>")
    r = site_audit.audit("solar.example", site({"/": (200, page)}))
    assert not r.get("blocked") and r["score"] > 50


def test_a_bot_check_is_never_quoted_to_a_lead():
    qa = leads.quick_audit("https://bupa.example/", site({"/": (403, CLOUDFLARE)}))
    assert qa["reachable"] is False and qa["problems"] == [leads.BLOCKED]
    assert leads.opportunity({"website": "bupa.example", "audit": qa}) == 45
    email = leads.write_drafts("Bupa", "bupa.example", qa["problems"], "", "")[0]["text"]
    assert "bot" not in email and "does not load" not in email


def test_brotli_counts_as_compression_when_the_server_offers_it():
    fetch = site({"/": (200, GOOD)})
    r = site_audit.audit("solar.example", fetch, probe=lambda url: "br")
    c = {x["id"]: x for x in r["checks"]}["compression"]
    assert c["status"] == "pass" and "br" in c["detail"]
    r = site_audit.audit("solar.example", fetch, probe=lambda url: "")
    c = {x["id"]: x for x in r["checks"]}["compression"]
    assert c["status"] == "warn" and "Brotli was asked for too" in c["detail"]


def test_the_brotli_probe_keeps_the_same_address_rules():
    from rankloom import netguard

    with pytest.raises(netguard.FetchRefused):
        netguard.offered_encoding("http://localhost/")
    with pytest.raises(netguard.FetchRefused):
        netguard.offered_encoding("https://example.com:8443/")


def test_alt_text_names_the_images_and_skips_tracking_pixels():
    body = (
        '<img src="/img/hero.jpg?v=2&amp;w=800"><img src="/icons/phone-icon.png">'
        '<img src="https://pixel.example/tr?id=1" width="1" height="1">'
        '<noscript><img src="https://www.facebook.com/tr?id=2"></noscript>'
        '<img src="/a.jpg" alt="Our office">'
    )
    r = site_audit.audit("x.example", site({"/": (200, html("Page title here", body))}))
    alt = {c["id"]: c for c in r["checks"]}["alt"]
    assert alt["status"] == "warn"
    assert alt["detail"] == "2 of 3 images have no alt attribute: hero.jpg, phone-icon.png."


def test_a_plain_facebook_page_is_not_a_review_link():
    base = LOCAL.replace('<a href="https://g.page/smilecare/review">Review us</a>', "")
    base = base.replace('"aggregateRating":{"ratingValue":4.8,"reviewCount":120},', "")
    page = base.replace("</body>", '<a href="https://www.facebook.com/smilecare/">FB</a></body>')
    r = local_seo.audit("smile.example", "Lahore", site({"/": (200, page)}))
    assert {c["id"]: c["status"] for c in r["checks"]}["reviews"] == "warn"
    page = base.replace(
        "</body>", '<a href="https://www.facebook.com/smilecare/reviews">FB</a></body>'
    )
    r = local_seo.audit("smile.example", "Lahore", site({"/": (200, page)}))
    assert {c["id"]: c["status"] for c in r["checks"]}["reviews"] == "pass"


US_DENTIST = html(
    "Amherst Dental Group Williamsville",
    "<h1>Dentist in Williamsville</h1><p>Call (716) 689-8882</p><p>777 Hopkins Rd</p>",
    '<script type="application/ld+json">{"@type":"Dentist","name":"Amherst Dental Group",'
    '"telephone":"716-689-8882","address":{"@type":"PostalAddress",'
    '"streetAddress":"777 Hopkins Rd","addressLocality":"Williamsville","addressRegion":"NY"}}'
    "</script>",
)


def test_phone_numbers_are_read_whole_and_never_across_lines():
    r = local_seo.audit("amherst.example", "Williamsville", site({"/": (200, US_DENTIST)}))
    assert r["business"]["phone"] == ["(716) 689-8882"]
    assert local_seo.PHONE.findall("Open 24/7 512-400-0749 today") == ["512-400-0749"]
    assert {c["id"]: c["status"] for c in r["checks"]}["nap-match"] == "pass"


def test_whatsapp_advice_only_where_customers_message_first():
    r = local_seo.audit("amherst.example", "Williamsville", site({"/": (200, US_DENTIST)}))
    assert r["market"] == "us" and "whatsapp" not in {c["id"] for c in r["checks"]}
    no_wa = LOCAL.replace('<a href="https://wa.me/923001234567">WhatsApp</a>', "")
    r = local_seo.audit("smile.example", "Lahore", site({"/": (200, no_wa)}))
    assert r["market"] == "pk"
    wa = {c["id"]: c for c in r["checks"]}["whatsapp"]
    assert wa["status"] == "warn" and "Pakistan" in wa["fix"]
    r = local_seo.audit("plain.example", "", site({"/": (200, html("A shop", "<p>Hi</p>"))}))
    assert r["market"] == "" and "whatsapp" not in {c["id"] for c in r["checks"]}
    r = local_seo.audit("plain.example", "", site({"/": (200, html("A shop", "<p>Hi</p>"))}), "ae")
    assert "whatsapp" in {c["id"] for c in r["checks"]}


def test_a_crawl_never_passes_a_problem_it_found_and_names_the_pages():
    words = "word " * 400
    links = "".join(f"<a href=/p{i}>p</a>" for i in range(24))
    pages = {"/": (200, html("Home of the clinic", f"<h1>Home</h1>{links}<p>{words}</p>"))}
    for i in range(24):
        pages[f"/p{i}"] = (200, html(f"Page {i} title", f"<h1>P{i}</h1><p>{words}</p>"))
    pages["/p7"] = (
        200,
        "<html><head><title>Dentist Williamsville NY | Emergency Dentist Williamsville | "
        "Cosmetic Dentist Williamsville | Implants</title><meta name=description content=''>"
        f"</head><body><h1>P7</h1><p>{words}</p></body></html>",
    )
    r = crawl.crawl("https://clinic.example/", site(pages), max_pages=25)
    checks = {c["id"]: c for c in crawl.analyse(r)}
    assert checks["no-desc"]["status"] == "warn" and "/p7" in checks["no-desc"]["detail"]
    assert checks["long-title"]["status"] == "warn"
    assert (
        "1 of 25 pages" in checks["long-title"]["detail"]
        and "longest" in checks["long-title"]["detail"]
    )


def test_crawl_and_page_audit_judge_speed_by_the_same_rule():
    one = {"/": (200, GOOD)}
    audit = site_audit.audit("solar.example", site(one, ms=2544))
    assert {c["id"]: c["status"] for c in audit["checks"]}["speed"] == "fail"
    r = crawl.crawl("https://solar.example/", site(one, ms=2544), max_pages=5)
    slow = {c["id"]: c for c in crawl.analyse(r)}["slow"]
    assert slow["status"] == "fail" and "measured from this server" in slow["detail"]
    r = crawl.crawl("https://solar.example/", site(one, ms=1200), max_pages=5)
    assert {c["id"]: c["status"] for c in crawl.analyse(r)}["slow"] == "warn"


GSC_PAGES = "Top pages,Clicks,Impressions,CTR,Position\nhttps://a.example/,100,1000,10%,3\n"
GSC_QUERIES = (
    "Top queries,Clicks,Impressions,CTR,Position\nbrand,60,500,12%,1\nservice,20,400,5%,7\n"
)
GSC_FILTERS = "Filter,Value\nSearch type,Web\nDate,Last 28 days\n"


def gsc_upload(*named):
    import base64
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in named:
            z.writestr(name, "﻿" + text)
    return [{"name": "export.zip", "data": base64.b64encode(buf.getvalue()).decode()}]


def test_search_console_totals_come_from_one_table_and_carry_the_period(tmp_path):
    from rankloom.db import Database

    db = Database(tmp_path / "t.db")
    db.run(
        "INSERT INTO users (id, email, name, pw_hash, created_at) VALUES (1, 'a@b.c', 'A', 'x', 0)"
    )
    upload = gsc_upload(
        ("Queries.csv", GSC_QUERIES), ("Pages.csv", GSC_PAGES), ("Filters.csv", GSC_FILTERS)
    )
    _, _, r = search_perf.run_import({"site": "a.example", "files": upload}, Context(1, db))
    assert r["totals"]["clicks"] == 100 and r["totals_from"] == "Pages table"
    assert r["period"] == "Last 28 days"
    view_facts = dict(r["view"]["blocks"][0]["items"])
    assert view_facts["Period"] == "Last 28 days"


def test_a_query_new_this_period_reads_new_not_zero():
    assert search_perf.position_move({"position": 12.7, "impressions": 30}) == "new at 12.7"
    row = {"position": 4.2, "impressions": 9, "prev_position": 2.8, "prev_impressions": 9}
    assert search_perf.position_move(row) == "2.8 → 4.2"
    gone = {"position": 0, "impressions": 0, "prev_position": 9.1, "prev_impressions": 40}
    assert search_perf.position_move(gone) == "gone (was 9.1)"


def test_the_work_log_reads_as_work_and_counts_repeats():
    runs = [
        {
            "tool": "search-performance",
            "subtool": "import",
            "created_at": 1_760_900_000,
            "input": {"site": "amherstdental.com"},
        },
        {
            "tool": "search-performance",
            "subtool": "import",
            "created_at": 1_760_800_000,
            "input": {"site": "amherstdental.com"},
        },
        {
            "tool": "ai-visibility",
            "subtool": "questions",
            "created_at": 1_760_700_000,
            "input": {"niche": "dentist"},
        },
        {
            "tool": "lead-finder",
            "subtool": "outreach",
            "created_at": 1_760_600_000,
            "input": {"site": "amherstdental.com"},
        },
    ]
    log = reports.work_log(runs)
    assert len(log) == 2
    assert log[0].startswith("Imported Google Search Console data of amherstdental.com (")
    assert log[0].endswith(", 2 times)")
    assert log[1].startswith("Researched the questions customers ask AI assistants: “dentist”")


def test_branches_of_a_chain_are_not_told_they_have_no_website():
    from rankloom.engines import leads
    from rankloom.engines.common import Context

    found = [
        {"name": "Gourmet", "website": "https://gourmetpakistan.com", "phone": "", "email": "",
         "address": "Gulberg", "city": "Lahore", "category": "bakery", "source": "osm"},
        {"name": "Gourmet", "website": "", "phone": "", "email": "", "address": "Johar Town",
         "city": "Lahore", "category": "bakery", "source": "osm"},
        {"name": "mydentist", "website": "", "brand": "mydentist",
         "brand_website": "https://www.mydentist.co.uk", "phone": "", "email": "",
         "address": "Chorlton", "city": "Manchester", "category": "dentist", "source": "osm"},
        {"name": "Corner Bakery", "website": "", "phone": "", "email": "", "address": "Model Town",
         "city": "Lahore", "category": "bakery", "source": "osm"},
    ]
    ctx = Context(user_id=0, fetch=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no fetch")))
    r = leads.search("bakery", "Lahore", ctx, find=lambda *a, **k: [dict(b) for b in found],
                     audit_limit=0)
    by = {(b["name"], b["address"]): b for b in r["leads"]}
    branch = next(b for b in r["leads"] if b["name"] == "Gourmet" and not b["website"])
    assert "gourmetpakistan.com" in branch["problems"][0] and branch["opportunity"] < 50
    chain = next(b for b in r["leads"] if b["name"] == "mydentist")
    assert "mydentist.co.uk" in chain["problems"][0]
    alone = next(b for b in r["leads"] if b["name"] == "Corner Bakery")
    assert alone["opportunity"] == 50 and "not listed" in alone["problems"][0]
    assert len(by) == 4


def test_same_name_branches_without_a_website_stay_separate_leads(tmp_path):
    from rankloom.db import Database
    from rankloom.engines import leads

    db = Database(tmp_path / "r.db")
    db.run("INSERT INTO users (email, name, pw_hash, created_at) VALUES ('a@b.co','A','x',0)")
    uid = db.one("SELECT id FROM users")["id"]
    for addr in ("Gulberg", "Johar Town", "DHA"):
        leads.save_lead(db, uid, {"name": "Gourmet", "website": "", "address": addr})
    leads.save_lead(db, uid, {"name": "Chain", "website": "chain.example", "address": "One"})
    leads.save_lead(db, uid, {"name": "Chain", "website": "chain.example", "address": "Two"})
    assert db.one("SELECT COUNT(*) FROM leads WHERE name = 'Gourmet'")[0] == 3
    assert db.one("SELECT COUNT(*) FROM leads WHERE name = 'Chain'")[0] == 1  # one site to fix


def test_the_whatsapp_greeting_fits_the_country():
    from rankloom.engines import leads

    uk = leads.write_drafts("Avalon", "", [], "", "", "Chorlton, Manchester, England, UK")[2]
    pk = leads.write_drafts("Gourmet", "", [], "", "", "Gulberg, Lahore, Punjab, Pakistan")[2]
    assert not uk["text"].startswith("Assalam") and pk["text"].startswith("Assalam o Alaikum")


def test_no_padlock_is_only_said_when_the_secure_site_does_not_work():
    from rankloom.engines import leads
    from rankloom.netguard import FetchFailed

    page = (b"<html><head><title>Brooklyn Court Dental</title></head>"
            b"<body><h1>Dentist</h1></body></html>")

    def fetcher(secure_ok):
        def fetch(url):
            if url.startswith("https://") and not secure_ok:
                raise FetchFailed("no TLS")
            return Response(url=url, status=200, headers={"content-type": "text/html"},
                            body=page, elapsed_ms=100)
        return fetch

    works = leads.quick_audit("http://brooklyn.example/", fetcher(True))["problems"]
    assert leads.HTTPS_NO_REDIRECT in works and leads.PLAIN["https"] not in works
    broken = leads.quick_audit("http://brooklyn.example/", fetcher(False))["problems"]
    assert leads.PLAIN["https"] in broken


def test_a_seed_naming_its_town_keeps_other_towns_and_fillers_out():
    from rankloom.engines import ai_visibility, content, market

    city = content.seed_city("emergency dentist williamsville ny")
    assert city == "williamsville ny"
    assert market.foreign("emergency dentist nyc", "us", city)
    assert not market.foreign("emergency dentist open tomorrow", "us", city)
    assert "there" in content.STOP
    assert content.intent("emergency dentist louisville ky") == "Local"
    for q in ("how much dentist make a year", "how much dentist make per hour"):
        assert ai_visibility._NOT_A_CUSTOMER.search(q), q
    for q in ("how much does a dentist cost", "make an appointment with a dentist"):
        assert not ai_visibility._NOT_A_CUSTOMER.search(q), q
