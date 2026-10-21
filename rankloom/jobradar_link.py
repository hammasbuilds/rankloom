"""The link to job-radar: its database read, its crawl started, nothing of it copied.

job-radar (a separate private project) crawls the boards and judges every posting; Rankloom is
where the results are filtered and read. The database is opened **read-only** (`mode=ro`), so
nothing here can damage the personal data job-radar keeps (applications are typed by hand and
cannot be regenerated). A crawl is job-radar's own script run as a child process, one at a time.

    RANKLOOM_JOBRADAR_DIR   the job-radar checkout (default D:/github/job-radar)
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

DEFAULT_DIR = r"D:/github/job-radar"
LIMIT = 200

FAMILIES = (
    "ML/DL",
    "Machine Learning",
    "Deep Learning",
    "Computer Vision",
    "Generative AI",
    "Agentic AI",
    "Other AI",
    "Fellowship / programme",
    "Pakistan public sector (CS/IT/AI)",
)
REGION_NAMES = {
    "europe": "Europe",
    "gulf": "Gulf",
    "pakistan": "Pakistan",
    "asia": "East & Southeast Asia",
}
# job-radar's route is either the sections a role reached ("sponsorship,europe") or the reason
# it reached none ("onsite, sponsorship not mentioned"). Only the first is a way in: the old
# test here closed just two reasons, so 534 of 577 roles read as open from Pakistan.
SECTIONS = {"sponsorship", "remote", "europe", "gulf", "asia", "pakistan"}
# Reasons that say nothing either way, as opposed to a stated refusal or lock.
UNCLEAR = ("sponsorship not mentioned", "sponsorship unstated", "scope not stated",
           "no location or route stated")


def route_kind(route: str) -> str:
    """open: a stated way in (sponsorship, worldwide remote, a Pakistan job). pass: a Gulf, East
    Asia or Europe role whose employer usually arranges the work pass but did not say so.
    unclear: the posting is silent. closed: it refuses, locks to a country, or wants citizens."""
    parts = [p.strip() for p in (route or "").split(",")]
    if route and all(p in SECTIONS for p in parts):
        return "open" if {"sponsorship", "remote", "pakistan"} & set(parts) else "pass"
    if any(u in route for u in UNCLEAR):
        return "unclear"
    return "closed"
CRAWLS = {
    "jobs": (["scripts/fetch.py"], "Job boards and APIs"),
    "yc": (["scripts/fetch_yc_recent.py"], "YC batches, last three years, with LinkedIn"),
    "boards": (["scripts/discover_boards.py"], "Find more company boards (long)"),
    "portfolios": (["scripts/fetch_portfolios.py"], "Accelerator and investor portfolios"),
}


class NotConnected(Exception):
    pass


def home() -> Path:
    return Path(os.environ.get("RANKLOOM_JOBRADAR_DIR", DEFAULT_DIR))


def db_file() -> Path:
    return Path(os.environ.get("JOBRADAR_DB", home() / "data" / "radar.sqlite3"))


def connect() -> sqlite3.Connection:
    path = db_file()
    if not path.exists():
        raise NotConnected(
            f"job-radar's database was not found at {path}. Set "
            "RANKLOOM_JOBRADAR_DIR to the job-radar folder, then run a crawl."
        )
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _tables(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _need(conn, table: str) -> None:
    if table not in _tables(conn):
        raise NotConnected(
            f"job-radar has not built its '{table}' list yet. Run the crawl from the Crawl page."
        )


# --- jobs ------------------------------------------------------------------------------------


def _years_ok(years, bucket: str) -> bool:
    if not bucket:
        return True
    if bucket == "unstated":
        return years is None
    return years is not None and years <= int(bucket)


def jobs(f: dict) -> dict:
    conn = connect()
    try:
        _need(conn, "lens")
        rows = [
            dict(r) for r in conn.execute("SELECT * FROM lens ORDER BY posted DESC, score DESC")
        ]
    finally:
        conn.close()
    for r in rows:
        r["countries"] = json.loads(r["countries"] or "[]")
        r["regions"] = json.loads(r["regions"] or "[]")
        r["route_kind"] = route_kind(r["route"])
        # What the posting asks in words ("PhD required", "extensive experience"); older
        # job-radar databases have no such column.
        r["bar"] = [b for b in (r.get("bar") or "").split(",") if b]
        r["reachable"] = r["route_kind"] in ("open", "pass")
    q = (f.get("q") or "").lower().strip()

    def keep(r, skip=""):
        if (
            skip != "country"
            and f.get("country")
            and (
                f["country"] not in r["countries"]
                if f["country"] != "Not stated"
                else r["countries"]
            )
        ):
            return False
        if skip != "region" and f.get("region") and f["region"] not in r["regions"]:
            return False
        for key in ("family", "track", "workplace", "terms"):
            if skip != key and f.get(key) and r[key] != f[key]:
                return False
        if skip != "years" and not _years_ok(r["years"], f.get("years", "")):
            return False
        if f.get("reachable") == "1" and not r["reachable"]:
            return False
        if f.get("open_bar") == "1" and r["bar"]:
            return False
        if q and q not in f"{r['title']} {r['company']} {r['location']} {r['excerpt']}".lower():
            return False
        return True

    shown = [r for r in rows if keep(r)]

    def facet(key, skip):
        counts: dict[str, int] = {}
        for r in rows:
            if not keep(r, skip):
                continue
            values = r[key] if key == "countries" else [r[key]]
            for v in values or (["Not stated"] if key == "countries" else []):
                counts[v] = counts.get(v, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))

    return {
        "total": len(rows),
        "matched": len(shown),
        "reachable": sum(r["reachable"] for r in shown),
        "countries": len({c for r in shown for c in r["countries"]}),
        "rows": shown[:LIMIT],
        "facets": {
            "country": facet("countries", "country"),
            "family": facet("family", "family"),
            "track": facet("track", "track"),
            "workplace": facet("workplace", "workplace"),
            "terms": facet("terms", "terms"),
        },
    }


# --- directory, YC -----------------------------------------------------------------------------


def directory(kind: str) -> list[dict]:
    conn = connect()
    try:
        _need(conn, "directory")
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM directory WHERE kind = ? ORDER BY live DESC, region, name", (kind,)
            )
        ]
    finally:
        conn.close()


def lens_family(family: str) -> list[dict]:
    conn = connect()
    try:
        _need(conn, "lens")
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM lens WHERE family = ? ORDER BY posted DESC", (family,)
            )
        ]
    finally:
        conn.close()
    for r in rows:
        r["countries"] = json.loads(r["countries"] or "[]")
    return rows


def yc(f: dict) -> dict:
    conn = connect()
    try:
        _need(conn, "yc_recent")
        rows = [
            dict(r)
            for r in conn.execute("SELECT * FROM yc_recent ORDER BY batch_year DESC, batch, name")
        ]
    finally:
        conn.close()
    q = (f.get("q") or "").lower().strip()
    shown = [
        r
        for r in rows
        if (not f.get("batch") or r["batch"] == f["batch"])
        and (f.get("hiring") not in ("1", "0") or str(r["hiring"]) == f["hiring"])
        and (f.get("ai") != "1" or r["is_ai"])
        and (not q or q in f"{r['name']} {r['one_liner']} {r['tags']} {r['location']}".lower())
    ]
    batches: dict[str, int] = {}
    for r in rows:
        batches[r["batch"]] = batches.get(r["batch"], 0) + 1
    return {
        "total": len(rows),
        "matched": len(shown),
        "rows": shown[: LIMIT * 2],
        "hiring": sum(r["hiring"] for r in rows),
        "linkedin_read": sum(r["linkedin_source"] == "yc page" for r in rows),
        "batches": sorted(batches.items(), key=lambda kv: kv[0]),
    }


def portfolio(f: dict) -> dict:
    """One accelerator's or investor's portfolio: its companies, and the AI roles they have open."""
    conn = connect()
    try:
        _need(conn, "portfolio_programme")
        programmes = [
            dict(r)
            for r in conn.execute("SELECT * FROM portfolio_programme ORDER BY ai_roles DESC, name")
        ]
        names = [p["name"] for p in programmes]
        name = f.get("programme") if f.get("programme") in names else (names[0] if names else "")
        q = f"%{(f.get('q') or '').strip().lower()}%"
        # The job's own page, where job-radar has read it, outranks the address: it has the
        # real title (with "Staff" or "Senior"), the places, the salary - and says when a
        # job is gone. Older job-radar databases have no detail table; then the address is all.
        detail = "portfolio_detail" in _tables(conn)
        cols = ("d.title AS page_title, d.countries, d.locations, d.salary, d.posted, "
                "d.junior AS d_junior, d.gone" if detail else
                "NULL AS page_title, NULL AS countries, NULL AS locations, NULL AS salary, "
                "NULL AS posted, NULL AS d_junior, 0 AS gone")
        join = " LEFT JOIN portfolio_detail d ON d.url = j.url" if detail else ""
        raw = [dict(r) for r in conn.execute(
            f"SELECT j.company, j.title AS slug_title, j.url, j.junior AS j_junior, j.family, "
            f"j.track, j.level, {cols} FROM portfolio_job j{join} "
            "WHERE j.programme = ? AND j.ai = 1", (name,))]
        families = conn.execute(
            "SELECT family, COUNT(*) FROM portfolio_job WHERE programme = ? AND ai = 1 "
            "GROUP BY family ORDER BY COUNT(*) DESC",
            (name,),
        ).fetchall()
        companies = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM portfolio_company WHERE programme = ? AND lower(name) LIKE ? "
                "ORDER BY ai_roles DESC, roles DESC, name",
                (name, q),
            )
        ]
    finally:
        conn.close()
    needle = q.strip("%")
    grouped: dict[tuple, dict] = {}
    country_counts: dict[str, int] = {}
    gone = 0
    for r in raw:
        if r["gone"]:
            gone += 1
            continue
        title = r["page_title"] or r["slug_title"]
        junior = r["d_junior"] if r["d_junior"] is not None else r["j_junior"]
        countries = json.loads(r["countries"] or "[]")
        places = json.loads(r["locations"] or "[]")
        if f.get("junior") == "1" and not junior:
            continue
        if f.get("family") and r["family"] != f["family"]:
            continue
        if needle and needle not in f"{title} {r['company']} {' '.join(places)}".lower():
            continue
        for c in countries or (["Not read yet"] if r["page_title"] is None else ["Not stated"]):
            country_counts[c] = country_counts.get(c, 0) + 1
        if f.get("country"):
            want = f["country"]
            if want == "Not read yet":
                if r["page_title"] is not None:
                    continue
            elif want not in countries:
                continue
        g = grouped.setdefault((r["company"], title), {
            "company": r["company"], "title": title, "url": r["url"], "junior": 0,
            "family": r["family"], "track": r["track"], "level": r["level"], "postings": 0,
            "countries": [], "salary": r["salary"] or "", "posted": r["posted"] or "",
            "read": r["page_title"] is not None})
        g["postings"] += 1
        g["junior"] = max(g["junior"], int(junior or 0))
        for c in countries:
            if c not in g["countries"]:
                g["countries"].append(c)
        g["posted"] = max(g["posted"], r["posted"] or "")
    roles = sorted(grouped.values(), key=lambda g: (-g["junior"], g["company"], g["title"]))
    return {
        "programmes": programmes,
        "programme": name,
        "families": [list(r) for r in families],
        "countries": sorted(country_counts.items(), key=lambda kv: (-kv[1], kv[0])),
        "gone": gone,
        "read": sum(1 for r in raw if r["page_title"] is not None),
        "roles": roles[: LIMIT * 2],
        "roles_matched": len(roles),
        "companies": companies[: LIMIT * 2],
        "companies_matched": len(companies),
    }


# --- status and crawling -----------------------------------------------------------------------


class Crawler:
    """One child process at a time, its output kept for the page to show."""

    def __init__(self, log_dir: Path):
        self.log_dir = Path(log_dir)
        self.proc: subprocess.Popen | None = None
        self.what = ""
        self.started = 0.0
        self.log_path = self.log_dir / "jobradar-crawl.log"
        self._lock = threading.Lock()

    def python(self) -> str:
        for rel in (".venv/Scripts/python.exe", ".venv/bin/python"):
            candidate = home() / rel
            if candidate.exists():
                return str(candidate)
        return sys.executable

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, what: str) -> None:
        if what not in CRAWLS:
            raise ValueError("Unknown crawl.")
        if not (home() / CRAWLS[what][0][0]).exists():
            raise NotConnected(f"job-radar was not found at {home()}.")
        with self._lock:
            if self.running():
                raise RuntimeError(f"A crawl is already running ({self.what}).")
            self.log_dir.mkdir(parents=True, exist_ok=True)
            log = self.log_path.open("w", encoding="utf-8")
            env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self.proc = subprocess.Popen(  # noqa: S603 - fixed script, fixed interpreter
                [self.python(), *CRAWLS[what][0]],
                cwd=home(),
                stdout=log,
                stderr=subprocess.STDOUT,
                env=env,
                creationflags=flags,
            )
            self.what = what
            self.started = time.time()

    def state(self) -> dict:
        try:
            tail = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
        except OSError:
            tail = []
        return {
            "running": self.running(),
            "what": self.what,
            "label": CRAWLS.get(self.what, ("", ""))[1],
            "started": self.started,
            "exit": None if self.proc is None or self.running() else self.proc.returncode,
            "log": tail,
        }


def status() -> dict:
    out = {
        "dir": str(home()),
        "db": str(db_file()),
        "connected": False,
        "last_run": None,
        "funnel": [],
        "counts": {},
    }
    try:
        conn = connect()
    except NotConnected as exc:
        out["error"] = str(exc)
        return out
    try:
        tables = _tables(conn)
        out["connected"] = True
        if "run" in tables:
            row = conn.execute("SELECT * FROM run ORDER BY id DESC LIMIT 1").fetchone()
            if row:
                out["last_run"] = row["at"]
                out["funnel"] = json.loads(row["funnel"]).get("lines", [])
        for table in ("lens", "posting", "killed", "yc_recent", "directory", "portfolio_company"):
            if table in tables:
                out["counts"][table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()
    found = home() / "src" / "jobradar" / "boards_found.json"
    try:
        boards = json.loads(found.read_text(encoding="utf-8"))
        out["counts"]["discovered_boards"] = sum(len(v) for v in boards.values())
    except (OSError, ValueError):
        pass
    return out
