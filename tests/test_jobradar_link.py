"""The Job Radar link against a fixture job-radar folder: its database read-only, its crawl run
as a child process. Never the real job-radar data."""

import json
import sqlite3
import sys
import time

import pytest
from test_server import (  # noqa: F401 - fixtures by import
    Client,
    app,  # noqa: F401
    register,
)

from rankloom import jobradar_link as jr


def lens_row(i, **kw):
    base = dict(
        id=f"id{i}",
        source="greenhouse",
        company="Acme",
        title="ML Engineer",
        location="Berlin, Germany",
        url=f"https://x/{i}",
        posted=f"2026-10-{10 + i:02d}",
        family="Machine Learning",
        track="Engineer",
        countries=["Germany"],
        regions=["europe"],
        workplace="Onsite",
        terms="Full-time",
        years=None,
        level="mid",
        route="sponsorship,europe",
        auth="sponsors",
        score=0.8,
        excerpt="",
        at="2026-10-20",
    )
    base.update(kw)
    base["countries"] = json.dumps(base["countries"])
    base["regions"] = json.dumps(base["regions"])
    return base


@pytest.fixture
def radar(tmp_path, monkeypatch):
    home = build(tmp_path / "job-radar")
    monkeypatch.setenv("RANKLOOM_JOBRADAR_DIR", str(home))
    monkeypatch.delenv("JOBRADAR_DB", raising=False)
    return home


def build(home):
    """A small job-radar folder: its tables, a handful of rows of each kind."""
    (home / "data").mkdir(parents=True)
    (home / "scripts").mkdir()
    db = home / "data" / "radar.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE lens (id TEXT PRIMARY KEY, source TEXT, company TEXT, title TEXT,
          location TEXT, url TEXT, posted TEXT, family TEXT, track TEXT, countries TEXT,
          regions TEXT, workplace TEXT, terms TEXT, years INTEGER, level TEXT, route TEXT,
          auth TEXT, score REAL, excerpt TEXT, at TEXT);
        CREATE TABLE directory (kind TEXT, name TEXT, url TEXT, jobs_url TEXT, region TEXT,
          what TEXT, pay TEXT, pay_source TEXT, who TEXT, match TEXT, live INTEGER, at TEXT);
        CREATE TABLE yc_recent (slug TEXT PRIMARY KEY, name TEXT, batch TEXT, batch_year INT,
          website TEXT, yc_url TEXT, jobs_url TEXT, hiring INT, status TEXT, one_liner TEXT,
          industry TEXT, location TEXT, team_size INT, tags TEXT, is_ai INT, linkedin TEXT,
          linkedin_source TEXT, at TEXT);
        CREATE TABLE run (id INTEGER PRIMARY KEY, at TEXT, fetched INT, kept INT, funnel TEXT);
    """)
    rows = [
        lens_row(1),
        lens_row(
            2,
            company="Grab",
            location="Singapore",
            countries=["Singapore"],
            regions=["asia"],
            family="Computer Vision",
            track="Researcher",
            workplace="Hybrid",
            years=1,
            route="asia",
        ),
        lens_row(
            3,
            company="Mercor",
            location="Remote",
            countries=[],
            regions=[],
            workplace="Remote",
            terms="Small contract",
            years=None,
            route="remote",
        ),
        lens_row(
            4,
            company="Zaizi",
            location="London, UK",
            countries=["United Kingdom"],
            years=2,
            route="refuses sponsorship",
        ),
        lens_row(
            5,
            company="PITB",
            location="Lahore, Pakistan",
            countries=["Pakistan"],
            regions=["pakistan"],
            family="Pakistan public sector (CS/IT/AI)",
            title="Assistant Director (IT)",
            route="pakistan",
        ),
    ]
    cols = list(rows[0])
    conn.executemany(
        f"INSERT INTO lens ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        [tuple(r[c] for c in cols) for r in rows],
    )
    conn.executemany(
        "INSERT INTO directory VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                "AI work platform",
                "Mercor",
                "https://www.mercor.com",
                "",
                "global",
                "expert work",
                "check the official page",
                "",
                "",
                "mercor",
                1,
                "t",
            ),
            (
                "Fellowship / paid programme",
                "Anthropic Fellows Program",
                "https://a",
                "",
                "global",
                "safety research",
                "$3,850/week",
                "Greenhouse 2026-10-20",
                "US/UK/CA",
                "anthropic",
                0,
                "t",
            ),
        ],
    )
    conn.executemany(
        "INSERT INTO yc_recent VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                "stormy",
                "Stormy",
                "Summer 2025",
                2025,
                "https://stormy.ai",
                "https://yc/stormy",
                "https://yc/stormy/jobs",
                1,
                "Active",
                "Runs the office",
                "B2B",
                "SF",
                5,
                "AI",
                1,
                "https://www.linkedin.com/company/stormy-ai/",
                "yc page",
                "t",
            ),
            (
                "quiet",
                "Quiet Co",
                "Winter 2024",
                2024,
                "https://q.co",
                "https://yc/quiet",
                "https://yc/quiet/jobs",
                0,
                "Active",
                "Payroll",
                "Fintech",
                "NYC",
                3,
                "Fintech",
                0,
                "https://www.linkedin.com/search/results/companies/?keywords=Quiet",
                "search",
                "t",
            ),
        ],
    )
    conn.execute(
        "INSERT INTO run VALUES (1, '2026-10-20T10:00:00+00:00', 100, 5, ?)",
        (json.dumps({"lines": ["100 fetched", "5 kept"]}),),
    )
    conn.commit()
    conn.close()
    return home


def test_jobs_filter_by_each_dimension_with_facets_that_ignore_their_own_filter(radar):
    everything = jr.jobs({})
    assert everything["total"] == 5
    assert dict(everything["facets"]["country"])["Not stated"] == 1
    sg = jr.jobs({"country": "Singapore"})
    assert [r["company"] for r in sg["rows"]] == ["Grab"]
    # The country facet still lists every country while one is chosen.
    assert {c for c, _ in sg["facets"]["country"]} >= {"Germany", "Singapore"}
    assert [r["company"] for r in jr.jobs({"track": "Researcher"})["rows"]] == ["Grab"]
    assert [r["company"] for r in jr.jobs({"terms": "Small contract"})["rows"]] == ["Mercor"]
    assert [r["company"] for r in jr.jobs({"workplace": "Hybrid"})["rows"]] == ["Grab"]
    one = {r["company"] for r in jr.jobs({"years": "1"})["rows"]}
    assert one == {"Grab"}
    two = {r["company"] for r in jr.jobs({"years": "2"})["rows"]}
    assert two == {"Grab", "Zaizi"}
    assert {r["company"] for r in jr.jobs({"years": "unstated"})["rows"]} == {
        "Acme",
        "Mercor",
        "PITB",
    }
    reachable = {r["company"] for r in jr.jobs({"reachable": "1"})["rows"]}
    assert "Zaizi" not in reachable and "Acme" in reachable
    assert [r["company"] for r in jr.jobs({"country": "Not stated"})["rows"]] == ["Mercor"]
    assert [r["company"] for r in jr.jobs({"q": "assistant director"})["rows"]] == ["PITB"]


def test_directory_and_yc(radar):
    assert jr.directory("AI work platform")[0]["name"] == "Mercor"
    assert jr.lens_family("Pakistan public sector (CS/IT/AI)")[0]["company"] == "PITB"
    y = jr.yc({})
    assert y["total"] == 2 and y["hiring"] == 1 and y["linkedin_read"] == 1
    assert [r["slug"] for r in jr.yc({"hiring": "0"})["rows"]] == ["quiet"]
    assert [r["slug"] for r in jr.yc({"ai": "1"})["rows"]] == ["stormy"]
    assert [r["slug"] for r in jr.yc({"batch": "Winter 2024"})["rows"]] == ["quiet"]


def test_the_database_is_opened_read_only(radar):
    conn = jr.connect()
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM lens")
    conn.close()


def test_a_missing_job_radar_is_reported_not_crashed(tmp_path, monkeypatch):
    monkeypatch.setenv("RANKLOOM_JOBRADAR_DIR", str(tmp_path / "nowhere"))
    assert jr.status()["connected"] is False
    with pytest.raises(jr.NotConnected):
        jr.jobs({})


def test_endpoints_need_a_session_and_serve_the_lists(radar, app):  # noqa: F811
    anon = Client(app.port)
    assert anon.get("/api/jobradar/jobs")[0] == 401
    c = register(app)
    st, body, _ = c.get("/api/jobradar/jobs?country=Singapore&track=Researcher")
    assert st == 200 and body["matched"] == 1
    st, body, _ = c.get("/api/jobradar/directory?kind=Fellowship%20%2F%20paid%20programme")
    assert body["entries"][0]["pay_source"]
    st, body, _ = c.get("/api/jobradar/directory?kind=x&with=pakistan")
    assert body["postings"][0]["company"] == "PITB"
    st, body, _ = c.get("/api/jobradar/status")
    assert body["connected"] and body["funnel"] == ["100 fetched", "5 kept"]
    assert body["counts"]["lens"] == 5


def test_a_crawl_runs_job_radars_script_once_at_a_time(radar, app):  # noqa: F811
    (radar / "scripts" / "fetch.py").write_text(
        "import time\nprint('asking boards', flush=True)\ntime.sleep(1.5)\nprint('done')\n",
        encoding="utf-8",
    )
    c = register(app)
    st, body, _ = c.post("/api/jobradar/crawl", {"what": "jobs"})
    assert st == 200 and body["crawl"]["running"]
    st, body, _ = c.post("/api/jobradar/crawl", {"what": "jobs"})
    assert st == 409 and "already running" in body["error"]
    assert c.post("/api/jobradar/crawl", {"what": "rm -rf"})[0] == 409
    deadline = time.time() + 20
    while app.crawler.running() and time.time() < deadline:
        time.sleep(0.2)
    state = app.crawler.state()
    assert state["exit"] == 0 and state["log"][-1] == "done"
    assert app.crawler.python() == sys.executable or app.crawler.python().endswith("python.exe")
