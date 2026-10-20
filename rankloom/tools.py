"""The six tools and their sub-tools: what each does, what it takes, what it gives back.

The sidebar, every About panel and every run form are rendered from this list, so a description
lives in one place. A sub-tool marked `needs_ai` runs only when an AI engine is configured
(see ai.py); the catalogue reports that per request instead of pretending it always runs.
"""

from __future__ import annotations

from . import ai
from .engines.market import COUNTRIES


def F(
    name,
    label,
    type="text",
    placeholder="",
    required=False,
    hint="",
    options=None,  # noqa: A002, N802
    accept="",
):
    f = {
        "name": name,
        "label": label,
        "type": type,
        "placeholder": placeholder,
        "required": required,
    }
    if hint:
        f["hint"] = hint
    if options:
        f["options"] = options
    if accept:
        f["accept"] = accept
    return f


def market_field(detect: bool = False) -> dict:
    """The country searches are read for. A visible choice, never a silent default: a US dentist
    run through Pakistani autocomplete was handed "dentist lahore"."""
    options = [{"value": c, "label": f"{name} ({c})"} for c, name in COUNTRIES]
    if detect:
        options.insert(0, {"value": "", "label": "Detect from the page"})
    return F(
        "country",
        "Country",
        "select",
        options=options,
        hint="Where the customers are. Searches and advice are for this market."
        if not detect
        else "Where the business is. WhatsApp advice applies only where customers message first.",
    )


TOOLS: list[dict] = [
    {
        "slug": "site-audit",
        "name": "Site Audit",
        "tagline": "Find what stops a site from ranking, and how to fix each thing.",
        "about": (
            "Reads a site the way a search crawler does and lists what is wrong, worst first, "
            "with the exact fix for each problem. Use it as the free audit that opens a "
            "conversation with a prospect, and as the paid audit-and-fix job."
        ),
        "subtools": [
            {
                "slug": "page",
                "name": "Page Audit",
                "tagline": "21 checks on one page, scored out of 100.",
                "about": (
                    "Fetches one page and checks the things that decide whether it can be "
                    "found: title and description, heading outline, canonical and robots rules, "
                    "mobile viewport, image alt text, structured data, social preview tags, "
                    "HTTPS, speed, compression, robots.txt and the sitemap."
                ),
                "does": [
                    "Runs 21 on-page and technical checks",
                    "Explains the fix for each",
                    "Scores the page and keeps the history",
                ],
                "input": "A page address",
                "output": "A score and every check with its fix",
                "fields": [F("url", "Page address", "url", "example.com", True)],
            },
            {
                "slug": "crawl",
                "name": "Site Crawl",
                "tagline": "Follow the site's own links and find problems across every page.",
                "about": (
                    "Starts at the home page and the sitemap, follows the site's own links, and "
                    "reports broken pages, duplicate titles and descriptions, missing H1s, "
                    "noindex pages, thin and slow pages - with every page it read listed."
                ),
                "does": [
                    "Reads up to 50 pages of a site",
                    "Finds broken pages and who links to them",
                    "Finds duplicates and thin pages across the site",
                ],
                "input": "The site's address and how many pages to read",
                "output": "Site-wide checks, broken pages and a per-page table",
                "fields": [
                    F("url", "Site address", "url", "example.com", True),
                    F(
                        "pages",
                        "Pages to read",
                        "select",
                        options=[
                            {"value": "25", "label": "25 pages"},
                            {"value": "10", "label": "10 pages (quick)"},
                            {"value": "50", "label": "50 pages"},
                        ],
                    ),
                ],
            },
            {
                "slug": "local",
                "name": "Local SEO Check",
                "tagline": "Is the business ready for maps and 'near me' searches?",
                "about": (
                    "Checks what local search and maps need from a business's page: "
                    "LocalBusiness data with name, address and phone; the same phone on the "
                    "page and in the data; click-to-call; a map; a link to the Google Business "
                    "Profile; reviews; opening hours; WhatsApp; and the city in the title."
                ),
                "does": [
                    "Checks LocalBusiness data and NAP consistency",
                    "Checks call, map, review and WhatsApp links",
                    "Checks the city is in the title and heading",
                ],
                "input": "The business page and its city",
                "output": "A local score and every check with its fix",
                "fields": [
                    F("url", "Business page", "url", "smilecare.pk", True),
                    F("city", "City", placeholder="Lahore"),
                    market_field(detect=True),
                ],
            },
        ],
    },
    {
        "slug": "ai-visibility",
        "name": "AI Visibility",
        "tagline": "Get named when customers ask ChatGPT-style assistants.",
        "about": (
            "Customers now ask an assistant instead of a search box. This tool checks whether "
            "AI answer engines can read a site, builds the questions customers really ask, and "
            "records whether the business is named in the answers - and who is named instead."
        ),
        "subtools": [
            {
                "slug": "readiness",
                "name": "AI Readiness",
                "tagline": "Can AI crawlers read, understand and quote the site?",
                "about": (
                    "Reads robots.txt for 13 AI and search crawlers (ChatGPT, Perplexity, "
                    "Claude, Google, Bing and the training crawlers), checks the text arrives "
                    "in the HTML rather than by script, that the business is described as an "
                    "entity, that questions are answered directly, and that nothing stops "
                    "answers quoting the page."
                ),
                "does": [
                    "Checks 13 AI crawlers against robots.txt",
                    "Checks the page can be read without JavaScript",
                    "Checks entity data, FAQs and llms.txt",
                ],
                "input": "A page address",
                "output": "A readiness score, checks and crawler access",
                "fields": [F("url", "Page address", "url", "example.com", True)],
            },
            {
                "slug": "questions",
                "name": "Question Builder",
                "tagline": "The questions that decide whether you get recommended.",
                "about": (
                    "Builds the questions a customer would ask an assistant about your kind of "
                    "business, and adds the real phrasings people type into search for it."
                ),
                "does": [
                    "Writes the standard recommendation questions",
                    "Adds real search phrasings from autocomplete",
                ],
                "input": "The service, the city and the brand",
                "output": "Questions to test in Answer Check",
                "fields": [
                    F("niche", "Service or product", placeholder="dentist", required=True),
                    F("city", "City", placeholder="Lahore"),
                    market_field(),
                    F("brand", "Brand", placeholder="Smile Care Clinic"),
                ],
            },
            {
                "slug": "answers",
                "name": "Answer Check",
                "tagline": "Ask the AI engine and see who it names.",
                "needs_ai": True,
                "about": (
                    "Asks the AI engine configured on this server each question, records "
                    "whether your brand or website is named, which businesses are named "
                    "instead, and your mention rate. Configure a web-grounded service to "
                    "measure what customers see in those assistants."
                ),
                "does": [
                    "Asks up to 8 questions",
                    "Records whether you are named",
                    "Ranks the businesses named instead",
                ],
                "input": "Brand, website and niche, or your own questions",
                "output": "Mention rate, each answer and the competitors named",
                "fields": [
                    F("brand", "Brand", placeholder="Smile Care Clinic", required=True),
                    F("site", "Website", "url", "smilecare.pk"),
                    F("niche", "Service or product", placeholder="dentist"),
                    F("city", "City", placeholder="Lahore"),
                    F(
                        "questions",
                        "Questions (one per line, optional)",
                        "textarea",
                        hint="Leave empty to use the standard questions.",
                    ),
                ],
            },
        ],
    },
    {
        "slug": "lead-finder",
        "name": "Lead Finder",
        "tagline": "Find businesses that need your help, and the first message to send.",
        "about": (
            "Finds businesses of a trade in a city, checks each website, and ranks them by how "
            "much your help would change for them. Every lead is kept in one list with its "
            "status, and each gets a first message that quotes its own problems."
        ),
        "subtools": [
            {
                "slug": "search",
                "name": "Business Search",
                "tagline": "A trade and a city in, ranked leads out.",
                "about": (
                    "Searches OpenStreetMap for businesses of a trade in a city, quickly "
                    "audits each website, and ranks them: no website first, then the weakest "
                    "sites. Every result is saved to Lead List."
                ),
                "does": [
                    "Finds up to 50 businesses",
                    "Quick-audits each website",
                    "Ranks by opportunity and saves them",
                ],
                "input": "A trade and a city",
                "output": "Ranked leads with the problem found",
                "fields": [
                    F(
                        "trade",
                        "Trade",
                        placeholder="dentists",
                        required=True,
                        hint="Plural works best: dentists, restaurants, schools.",
                    ),
                    F("city", "City", placeholder="Lahore", required=True),
                    F(
                        "country",
                        "Country code",
                        placeholder="pk",
                        hint="Two letters (pk, gb, us, ae) so a city name means one place.",
                    ),
                ],
            },
            {
                "slug": "list",
                "name": "Lead List",
                "kind": "page",
                "tagline": "Every lead, its status and your notes.",
                "about": (
                    "All saved leads in one place: mark each as new, contacted, replied, won "
                    "or lost, keep notes, import a CSV from anywhere and export the list."
                ),
                "does": [
                    "Tracks status and notes",
                    "Imports and exports CSV",
                    "Opens a message draft for any lead",
                ],
                "input": "Leads from Business Search or a CSV",
                "output": "A pipeline you can filter and export",
                "fields": [],
            },
            {
                "slug": "outreach",
                "name": "Outreach Drafts",
                "tagline": "A first message that quotes their own problems.",
                "about": (
                    "Checks the business's website and writes an email, a short LinkedIn or "
                    "Instagram message and a WhatsApp message, each naming what was found in "
                    "words an owner understands. Drafts only - you review and send them "
                    "yourself, one at a time."
                ),
                "does": [
                    "Re-checks the website",
                    "Writes three message formats",
                    "Never sends anything",
                ],
                "input": "A lead, or a business name and website",
                "output": "Three drafts ready to edit",
                "fields": [
                    F("lead", "Lead", "hidden"),
                    F("business", "Business", placeholder="Smile Care Clinic"),
                    F("site", "Their website", "url", "smilecare.pk"),
                    F("sender", "Your name", placeholder="Ayesha, Rankloom"),
                    F("offer", "What you offer", placeholder="a free full audit"),
                ],
            },
        ],
    },
    {
        "slug": "search-performance",
        "name": "Search Performance",
        "tagline": "Real Google numbers: what brings clicks and what is being missed.",
        "about": (
            "Reads a site's own Google Search Console report - real clicks, impressions and "
            "positions, free - and shows where the traffic comes from, where clicks are being "
            "left on the table, and what changed between two periods."
        ),
        "subtools": [
            {
                "slug": "import",
                "name": "Import Report",
                "tagline": "Upload a Search Console export.",
                "about": (
                    "In Search Console open Performance, choose Export, then Download CSV, and "
                    "upload the zip (or Queries.csv and Pages.csv). Choose Date > Compare "
                    "first to unlock Changes."
                ),
                "does": [
                    "Reads the zip or the CSV files",
                    "Totals clicks, impressions, CTR and position",
                    "Lists top queries and pages",
                ],
                "input": "A Search Console export",
                "output": "Totals and top queries and pages",
                "fields": [
                    F("site", "Site name", placeholder="smilecare.pk", required=True),
                    F("files", "Export file(s)", "file", accept=".zip,.csv", required=True),
                ],
            },
            {
                "slug": "opportunities",
                "name": "Opportunities",
                "tagline": "Queries close to page one, and titles nobody clicks.",
                "about": (
                    "Finds queries ranking 8-20 that a better page could lift onto page one, "
                    "queries clicked far less than their position should earn (rewrite the "
                    "title), and queries seen often but never clicked."
                ),
                "does": [
                    "Finds striking-distance queries",
                    "Estimates clicks a better title would win",
                    "Lists seen-but-never-clicked searches",
                ],
                "input": "An imported report",
                "output": "Three ranked lists of opportunities",
                "fields": [F("dataset", "Report", "dataset", required=True)],
            },
            {
                "slug": "changes",
                "name": "Changes",
                "tagline": "Which pages and queries gained or lost clicks.",
                "about": (
                    "Compares the two periods of a comparison export: total clicks before and "
                    "after, the pages and queries that lost the most, and those that gained."
                ),
                "does": [
                    "Compares two periods",
                    "Ranks the biggest losers and winners",
                    "Shows position moves",
                ],
                "input": "An imported comparison report",
                "output": "Losers and winners",
                "fields": [F("dataset", "Report", "dataset", required=True)],
            },
        ],
    },
    {
        "slug": "content-studio",
        "name": "Content Studio",
        "tagline": "From what people search to a page that answers it.",
        "about": (
            "Finds what people actually type about a topic, turns it into a brief, drafts the "
            "page with every checkable claim marked, and grades any page or text against the "
            "keyword it should rank for. This is the monthly retainer work."
        ),
        "subtools": [
            {
                "slug": "keywords",
                "name": "Keyword Ideas",
                "tagline": "Real search phrasings, grouped by what the searcher wants.",
                "about": (
                    "Expands a topic through search-box autocomplete for the chosen country - "
                    "with Roman Urdu phrasings for Pakistan - leaves out searches naming another "
                    "country's places, and groups the results into questions, "
                    "comparing and buying, local, and learning. Autocomplete shows what people "
                    "type, not how often; no free source gives real volumes."
                ),
                "does": [
                    "Runs 20-50 autocomplete lookups",
                    "Groups phrases by intent",
                    "Finds the words that keep recurring",
                ],
                "input": "A topic",
                "output": "Grouped real search phrasings",
                "fields": [
                    F("seed", "Topic", placeholder="rooftop solar", required=True),
                    market_field(),
                    F(
                        "depth",
                        "Depth",
                        "select",
                        options=[
                            {"value": "normal", "label": "Normal (about 25 lookups)"},
                            {"value": "deep", "label": "Deep (about 50 lookups)"},
                        ],
                    ),
                ],
            },
            {
                "slug": "brief",
                "name": "Content Brief",
                "tagline": "Title, outline, questions and words for one page.",
                "about": (
                    "Builds a brief from real searches: the search title and description, an "
                    "outline whose headings are the questions people ask, the words to use, "
                    "a length target and a pre-publishing checklist."
                ),
                "does": [
                    "Writes the title and description",
                    "Builds the outline from real questions",
                    "Lists the words to include",
                ],
                "input": "A topic",
                "output": "A brief a writer can follow",
                "fields": [
                    F("topic", "Topic", placeholder="solar panel price in lahore", required=True),
                    market_field(),
                ],
            },
            {
                "slug": "draft",
                "name": "Draft Writer",
                "tagline": "A first draft with every claim marked for checking.",
                "needs_ai": True,
                "about": (
                    "Writes a first draft from the brief with the AI engine configured on this "
                    "server, then lists every sentence holding a number, price, date or "
                    "superlative so nothing is published unchecked."
                ),
                "does": [
                    "Follows the brief's outline",
                    "Avoids invented statistics",
                    "Lists claims to verify",
                ],
                "input": "A topic and the business publishing it",
                "output": "A draft and its claims to check",
                "fields": [
                    F("topic", "Topic", placeholder="solar panel price in lahore", required=True),
                    market_field(),
                    F("business", "Published by", placeholder="Sun Power Lahore"),
                ],
            },
            {
                "slug": "grade",
                "name": "Content Grader",
                "tagline": "Score a page or text against its keyword.",
                "about": (
                    "Grades a live page or pasted text for one keyword: in the title, H1 and "
                    "opening; used naturally; long enough; broken into sections; readable; and "
                    "covering the words searchers use around it."
                ),
                "does": [
                    "Checks keyword placement",
                    "Checks length, sections and readability",
                    "Checks coverage of related searches",
                ],
                "input": "A keyword and a page address or text",
                "output": "A content score with fixes",
                "fields": [
                    F("keyword", "Keyword", placeholder="rooftop solar lahore", required=True),
                    market_field(),
                    F("url", "Page address", "url", "example.com/solar"),
                    F("text", "Or paste the text", "textarea"),
                ],
            },
        ],
    },
    {
        "slug": "client-reports",
        "name": "Client Reports",
        "tagline": "Monthly reports that show clients what they are paying for.",
        "about": (
            "Keeps your clients in one list and turns fresh checks of each client's site, "
            "their Search Console numbers and the work you did into one monthly report, ready "
            "to print or save as PDF."
        ),
        "subtools": [
            {
                "slug": "clients",
                "name": "Clients",
                "kind": "page",
                "tagline": "Who you work for, their site and their report settings.",
                "about": "Add each client with their website, city, niche, contact and the "
                "Search Console report to use in their monthly report.",
                "does": [
                    "Stores each client's details",
                    "Links a Search Console report",
                    "Opens the monthly report in one click",
                ],
                "input": "Client details",
                "output": "Your client list",
                "fields": [],
            },
            {
                "slug": "report",
                "name": "Monthly Report",
                "tagline": "One printable page per client per month.",
                "about": (
                    "Runs a fresh Page Audit, Local SEO Check and AI Readiness on the client's "
                    "site, compares each score with the last time, adds their Search Console "
                    "numbers and every piece of work recorded for the site this month, and "
                    "lists what to fix next."
                ),
                "does": [
                    "Re-checks the site and shows the change",
                    "Adds Google search numbers",
                    "Lists the month's work and next fixes",
                ],
                "input": "A client",
                "output": "A printable monthly report",
                "fields": [F("client", "Client", "client", required=True)],
            },
        ],
    },
]


def _page(slug, name, tagline, about, does, input_, output):
    return {
        "slug": slug,
        "name": name,
        "kind": "page",
        "tagline": tagline,
        "about": about,
        "does": does,
        "input": input_,
        "output": output,
        "fields": [],
    }


TOOLS.append(
    {
        "slug": "job-radar",
        "name": "Job Radar",
        "tagline": "Junior AI jobs, programmes and companies, country by country.",
        "about": (
            "Reads job-radar, the crawler that asks hundreds of company career boards and open "
            "job APIs (never LinkedIn) for ML/DL, machine learning, deep learning, computer "
            "vision, generative AI and agentic AI roles - engineer and researcher - at junior "
            "level, across "
            "Europe, the Gulf, Pakistan and East and Southeast Asia. India and Bangladesh are left "
            "out. Alongside the jobs: AI work platforms, paid fellowships, Pakistani government "
            "jobs and grants, every recent YC company and the accelerators like it."
        ),
        "subtools": [
            _page(
                "jobs",
                "Jobs",
                "Filter by country, experience, place, title and terms.",
                "Every junior posting in the target countries, with its route from Pakistan as a "
                "value to filter on: the country it is in, the title family, engineer or "
                "researcher, onsite, hybrid or remote, full-time, contract or small contract, and "
                "the experience it asks for.",
                [
                    "Counts per country, one click to filter",
                    "Title family and track filters",
                    "Workplace, terms and experience filters",
                ],
                "Filters",
                "Postings with links and reasons",
            ),
            _page(
                "platforms",
                "AI Work Platforms",
                "Mercor, DataAnnotation, Alignerr and more.",
                "Platforms that pay for expert work training and checking AI models - coding, "
                "research and domain tasks, mostly contract and small contract - with the open "
                "roles job-radar found on each.",
                ["Lists the platforms with links", "Counts their open roles from the crawl"],
                "Nothing",
                "Platforms and their open roles",
            ),
            _page(
                "fellowships",
                "Fellowships",
                "Paid AI fellowships, residencies and programmes.",
                "Fellowships and residencies at Anthropic, OpenAI, Constellation and others, with "
                "the stipend stated only where a live posting confirmed it, and every programme "
                "posting the crawl found.",
                [
                    "States verified pay with its source",
                    "Shows eligibility limits",
                    "Lists live programme postings",
                ],
                "Nothing",
                "Programmes and live postings",
            ),
            _page(
                "pakistan",
                "Pakistan Gov & Grants",
                "Government CS/IT/AI jobs, HEC and grants.",
                "Computing posts at Pakistani government, university and state employers - from "
                "the National Job Portal and the crawl - and the grants open to junior scientists "
                "and researchers.",
                ["Lists public-sector CS/IT/AI posts", "Lists HEC, Ignite and other grants"],
                "Nothing",
                "Posts and grants with links",
            ),
            _page(
                "yc",
                "YC Companies",
                "Every YC company of the last three years.",
                "All Y Combinator companies from the last three years of batches, hiring or not, "
                "with their website, LinkedIn profile (read from the YC page), YC page and jobs "
                "page.",
                ["Filters by batch, hiring and AI", "Real LinkedIn where YC links it"],
                "Filters",
                "Companies with links",
            ),
            _page(
                "accelerators",
                "Accelerators",
                "Programmes like YC, and their job boards.",
                "Accelerators and founder programmes like Y Combinator - Techstars, Antler, EF, "
                "Seedcamp, Hub71 and more - with their portfolio pages and job boards.",
                ["Lists 20+ programmes by region", "Links portfolios and job boards"],
                "Nothing",
                "Programmes with links",
            ),
            _page(
                "crawl",
                "Crawl",
                "Run job-radar and see what it found.",
                "Starts a job-radar crawl, a YC refresh or a board discovery pass, and shows the "
                "last run's funnel: how many postings were read and why each stage removed what "
                "it did.",
                ["Starts a crawl in the background", "Shows the funnel and the log"],
                "A click",
                "Counts and the funnel",
            ),
        ],
    }
)

BY_SLUG = {t["slug"]: t for t in TOOLS}


def find(tool: str, sub: str) -> tuple[dict, dict] | None:
    t = BY_SLUG.get(tool)
    if not t:
        return None
    s = next((x for x in t["subtools"] if x["slug"] == sub), None)
    return (t, s) if s else None


def status(sub: dict) -> str:
    if sub.get("needs_ai") and ai.engine() is None:
        return "needs-ai"
    return "live"


def public_catalog() -> list[dict]:
    out = []
    for t in TOOLS:
        subs = [{**s, "kind": s.get("kind", "run"), "status": status(s)} for s in t["subtools"]]
        out.append({**t, "subtools": subs})
    return out
