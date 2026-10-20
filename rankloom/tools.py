"""The nine tools: what each one does, what it takes, what it gives back, and whether it runs yet.

The sidebar, each tool's About panel and the run form are all rendered from this list, so a
tool's description lives in one place. `status` is "live" only when an engine exists and is
tested; every other tool says plainly that its engine is being built, rather than returning
something that looks like a result.
"""

from __future__ import annotations

TOOLS: list[dict] = [
    {
        "slug": "site-audit",
        "name": "Site Audit",
        "tagline": "Find out what stops a page from ranking, and how to fix each thing.",
        "about": (
            "Fetches a page the way a search crawler does and checks the things that decide "
            "whether it can be found at all: the title and description, the heading outline, "
            "canonical and robots rules, mobile viewport, image alt text, structured data, "
            "social preview tags, HTTPS, compression, robots.txt and the sitemap. Every check "
            "comes back as pass, warning or fail with the exact fix, and the page gets a score "
            "out of 100 so a re-run after the fixes shows the difference."
        ),
        "does": [
            "Fetches the page and follows its redirects",
            "Runs 21 on-page and technical checks",
            "Explains the fix for every warning and failure",
            "Scores the page out of 100 and keeps the history",
        ],
        "input": "A page address, e.g. example.com or https://example.com/pricing",
        "output": "A score, each check with pass / warning / fail, and the fix for each",
        "status": "live",
        "fields": [
            {
                "name": "url",
                "label": "Page address",
                "type": "url",
                "placeholder": "example.com",
                "required": True,
            }
        ],
    },
    {
        "slug": "ai-visibility",
        "name": "AI Visibility",
        "tagline": "See whether AI answer engines mention your business when customers ask.",
        "about": (
            "Customers now ask an assistant instead of a search box. This tool asks the "
            "questions your customers ask - 'best dentist in Lahore', 'cheapest CRM for "
            "clinics' - and records whether your brand appears in the answer, which competitors "
            "appear instead, and which pages are cited. It then lists what to change on your "
            "site so the next answer is more likely to include you."
        ),
        "does": [
            "Builds the questions a customer would ask in your niche",
            "Records who is mentioned and which pages are cited",
            "Compares your share of mentions with competitors",
            "Suggests content and structured-data changes",
        ],
        "input": "Your brand, your website and the niche or city you serve",
        "output": "Mention rate, competitors named, cited pages and a fix list",
        "status": "building",
        "fields": [
            {"name": "brand", "label": "Brand name", "type": "text", "placeholder": "Acme Dental"},
            {"name": "site", "label": "Website", "type": "url", "placeholder": "acmedental.pk"},
            {
                "name": "niche",
                "label": "Niche and city",
                "type": "text",
                "placeholder": "dentist, Lahore",
            },
        ],
    },
    {
        "slug": "keyword-radar",
        "name": "Keyword Radar",
        "tagline": "Turn one seed topic into the searches worth writing for.",
        "about": (
            "Expands a seed topic into the questions and phrases people really search for, "
            "groups them by intent (learning, comparing, buying, local), and ranks the groups "
            "by how much a small site can win. Includes Urdu and Roman Urdu phrasings for "
            "Pakistani audiences, which most keyword tools miss entirely."
        ),
        "does": [
            "Expands a seed into hundreds of real search phrasings",
            "Groups them by intent and by topic",
            "Adds Urdu and Roman Urdu variants",
            "Ranks groups by opportunity for a small site",
        ],
        "input": "A seed topic and a target country",
        "output": "Keyword groups with intent, variants and an opportunity rank",
        "status": "building",
        "fields": [
            {"name": "seed", "label": "Seed topic", "type": "text", "placeholder": "home solar"},
            {"name": "country", "label": "Country", "type": "text", "placeholder": "Pakistan"},
        ],
    },
    {
        "slug": "trend-watch",
        "name": "Trend Watch",
        "tagline": "Spot what your audience is starting to talk about before it peaks.",
        "about": (
            "Watches public trend sources - search interest, Reddit, YouTube and news - for a "
            "set of topics, and flags terms whose interest is rising faster than their usual "
            "range. Each rising term comes with the posts and pages driving it, so you can "
            "decide whether to write about it this week."
        ),
        "does": [
            "Tracks interest over time for your topics",
            "Flags terms rising faster than their normal range",
            "Shows the posts and pages behind each rise",
            "Sends a weekly digest of what moved",
        ],
        "input": "Up to ten topics and a region",
        "output": "Rising terms with their trend line and the sources driving them",
        "status": "building",
        "fields": [
            {
                "name": "topics",
                "label": "Topics (comma separated)",
                "type": "text",
                "placeholder": "ai tools, freelancing, solar",
            },
            {"name": "region", "label": "Region", "type": "text", "placeholder": "PK"},
        ],
    },
    {
        "slug": "lead-finder",
        "name": "Lead Finder",
        "tagline": "Find local businesses whose websites are losing them customers.",
        "about": (
            "Searches public business listings for a trade in a city, quickly audits each "
            "business's website, and ranks them by how much a fix would help them: no "
            "website, a slow site, no mobile layout, missing from maps. You get a short, "
            "checked list of businesses worth contacting and the specific problem to mention."
        ),
        "does": [
            "Lists businesses for a trade and a city from public listings",
            "Runs a quick audit on each website",
            "Ranks them by how much a fix would help",
            "Exports the list with the problem found for each",
        ],
        "input": "A trade and a city, e.g. 'dental clinic, Karachi'",
        "output": "Ranked businesses with website, problem found and contact page",
        "status": "building",
        "fields": [
            {"name": "trade", "label": "Trade", "type": "text", "placeholder": "dental clinic"},
            {"name": "city", "label": "City", "type": "text", "placeholder": "Karachi"},
        ],
    },
    {
        "slug": "outreach-writer",
        "name": "Outreach Writer",
        "tagline": "Write a first message that quotes the prospect's own problem.",
        "about": (
            "Takes one lead and its audit and writes a short, personal first message - email or "
            "LinkedIn - that names the specific problem found on their site and what fixing it "
            "would do. It writes drafts for you to review and send yourself; it never sends in "
            "bulk, because bulk messages get accounts and domains blocked."
        ),
        "does": [
            "Drafts a personal message from a lead's audit",
            "Writes email, LinkedIn and WhatsApp versions",
            "Keeps every draft for you to edit and send",
            "Tracks which drafts you sent and who replied",
        ],
        "input": "A lead from Lead Finder, or a business name and website",
        "output": "Message drafts in three formats, ready to edit",
        "status": "building",
        "fields": [
            {
                "name": "business",
                "label": "Business",
                "type": "text",
                "placeholder": "Smile Care Clinic",
            },
            {
                "name": "site",
                "label": "Their website",
                "type": "url",
                "placeholder": "smilecare.pk",
            },
        ],
    },
    {
        "slug": "content-studio",
        "name": "Content Studio",
        "tagline": "Go from a keyword group to a publishable article brief and draft.",
        "about": (
            "Turns a keyword group into a content brief - the questions to answer, the "
            "headings, the facts to check, the internal links to add - and then a first draft "
            "written to be cited by AI answer engines as well as ranked by search. Every "
            "factual claim in a draft is marked so it can be checked before publishing."
        ),
        "does": [
            "Builds a brief from a keyword group",
            "Writes a structured first draft",
            "Marks every factual claim for checking",
            "Suggests internal links and structured data",
        ],
        "input": "A keyword group or a topic, plus your site",
        "output": "A brief, a draft and a list of claims to verify",
        "status": "building",
        "fields": [
            {
                "name": "topic",
                "label": "Topic or keyword",
                "type": "text",
                "placeholder": "how much does rooftop solar cost in Lahore",
            },
        ],
    },
    {
        "slug": "social-planner",
        "name": "Social Planner",
        "tagline": "Plan a month of posts for X, LinkedIn and Instagram from your content.",
        "about": (
            "Breaks an article, a product update or a trend into a calendar of posts sized for "
            "each network, with the best posting times for your audience. Posts are scheduled "
            "on your own connected accounts and nothing is posted without your approval."
        ),
        "does": [
            "Splits one piece of content into many posts",
            "Sizes each post for X, LinkedIn and Instagram",
            "Lays them out on a calendar",
            "Waits for your approval before anything goes out",
        ],
        "input": "An article, a link or a short product update",
        "output": "A post calendar with a draft per network",
        "status": "building",
        "fields": [
            {
                "name": "source",
                "label": "Article link or update",
                "type": "text",
                "placeholder": "https://example.com/blog/launch",
            },
        ],
    },
    {
        "slug": "launch-kit",
        "name": "Launch Kit",
        "tagline": "Promote a GitHub project: README fixes, launch posts and where to share.",
        "about": (
            "Imports one of your GitHub repositories, reads its README and code, and prepares "
            "its launch: a sharper README opening, a description and topics that help it be "
            "found, launch posts for X, LinkedIn, Reddit and Hacker News, and a list of the "
            "communities where this kind of project is welcome."
        ),
        "does": [
            "Imports a repository from your connected GitHub",
            "Suggests a sharper README opening and topics",
            "Writes launch posts for each community",
            "Lists where this kind of project is welcome",
        ],
        "input": "An imported GitHub repository",
        "output": "README suggestions, launch posts and a sharing plan",
        "status": "building",
        "fields": [
            {"name": "repo", "label": "Repository", "type": "repo", "placeholder": "owner/name"},
        ],
    },
]

BY_SLUG = {t["slug"]: t for t in TOOLS}


def public_catalog() -> list[dict]:
    return [dict(t) for t in TOOLS]
