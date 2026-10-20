"""Search Performance: read a Google Search Console export and say where the clicks are, where
they are being left on the table, and what changed.

Search Console > Performance > Export > Download CSV gives a zip of Queries.csv, Pages.csv and
more; this reads that zip, or the CSV files on their own. When the report was set to compare two
periods, each measure has two columns and the Changes sub-tool compares them.
"""

from __future__ import annotations

import base64
import binascii
import csv
import io
import json
import zipfile

from ..db import now
from .common import FAIL, PASS, Context, InputProblem, facts, headline, table, view

MAX_ROWS = 5000
# Average click-through rate by position on page one. Industry studies differ by a few points;
# the tool flags only CTRs under half of these, so the exact curve does not decide the result.
EXPECTED_CTR = {
    1: 0.28,
    2: 0.15,
    3: 0.11,
    4: 0.08,
    5: 0.065,
    6: 0.05,
    7: 0.04,
    8: 0.032,
    9: 0.027,
    10: 0.024,
}


def _num(raw: str) -> float:
    s = str(raw).strip().replace(",", "")
    if s.endswith("%"):
        return float(s[:-1] or 0) / 100
    return float(s or 0)


def parse_csv(text: str) -> dict | None:
    """One Search Console table: its key column and current (and previous) measures."""
    text = text.lstrip("﻿")
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration:
        return None
    lower = [h.strip().lower() for h in header]
    key_col = next(
        (
            i
            for i, h in enumerate(lower)
            if h in ("top queries", "query", "queries", "top pages", "page", "pages")
        ),
        None,
    )
    if key_col is None:
        return None
    kind = "queries" if "quer" in lower[key_col] else "pages"
    measures = {}
    for m in ("clicks", "impressions", "ctr", "position"):
        cols = [i for i, h in enumerate(lower) if h == m or h.endswith(" " + m)]
        if cols:
            measures[m] = cols
    if "clicks" not in measures or "impressions" not in measures:
        return None
    compare = all(len(v) >= 2 for v in measures.values())
    labels = []
    if compare:
        labels = [
            header[measures["clicks"][0]].rsplit(" ", 1)[0],
            header[measures["clicks"][1]].rsplit(" ", 1)[0],
        ]
    rows = []
    for rec in reader:
        if len(rec) <= key_col or not rec[key_col].strip():
            continue
        try:
            row = {"key": rec[key_col].strip()}
            for m, cols in measures.items():
                row[m] = _num(rec[cols[0]]) if cols[0] < len(rec) else 0.0
                if compare:
                    row[f"prev_{m}"] = _num(rec[cols[1]]) if cols[1] < len(rec) else 0.0
        except ValueError:
            continue
        rows.append(row)
        if len(rows) >= MAX_ROWS:
            break
    return {"kind": kind, "rows": rows, "compare": compare, "labels": labels}


def parse_upload(files: list[dict]) -> dict:
    """`files` is [{name, data(base64)}]. Returns {"queries": [...], "pages": [...], ...}."""
    tables: dict[str, dict] = {}
    texts: list[str] = []
    for f in files:
        try:
            raw = base64.b64decode(str(f.get("data", "")), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise InputProblem("A file could not be read.") from exc
        if raw[:2] == b"PK":
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as z:
                    for info in z.infolist()[:20]:
                        if info.filename.lower().endswith(".csv") and info.file_size < 20_000_000:
                            texts.append(z.read(info).decode("utf-8", errors="replace"))
            except zipfile.BadZipFile as exc:
                raise InputProblem("That zip file is damaged.") from exc
        else:
            texts.append(raw.decode("utf-8", errors="replace"))
    for t in texts:
        parsed = parse_csv(t)
        if parsed and parsed["kind"] not in tables:
            tables[parsed["kind"]] = parsed
    if not tables:
        raise InputProblem(
            "No Queries.csv or Pages.csv found. In Search Console open "
            "Performance, choose Export, then Download CSV, and upload the zip."
        )
    compare = any(t["compare"] for t in tables.values())
    labels = next((t["labels"] for t in tables.values() if t["labels"]), [])
    return {
        "queries": tables.get("queries", {}).get("rows", []),
        "pages": tables.get("pages", {}).get("rows", []),
        "compare": compare,
        "labels": labels,
    }


def totals(rows: list[dict], prefix: str = "") -> dict:
    clicks = sum(r.get(prefix + "clicks", 0) for r in rows)
    impr = sum(r.get(prefix + "impressions", 0) for r in rows)
    pos = (
        (sum(r.get(prefix + "position", 0) * r.get(prefix + "impressions", 0) for r in rows) / impr)
        if impr
        else 0
    )
    return {
        "clicks": int(clicks),
        "impressions": int(impr),
        "ctr": (clicks / impr) if impr else 0,
        "position": pos,
    }


def pct(x: float) -> str:
    return f"{100 * x:.1f}%"


def load_dataset(ctx: Context, dataset_id) -> dict:
    if ctx.db is None:
        raise InputProblem("No storage available.")
    rid = str(dataset_id or "").strip()
    row = (
        ctx.db.one("SELECT * FROM gsc_datasets WHERE id = ? AND user_id = ?", int(rid), ctx.user_id)
        if rid.isdigit()
        else ctx.db.one(
            "SELECT * FROM gsc_datasets WHERE user_id = ? ORDER BY id DESC LIMIT 1", ctx.user_id
        )
    )
    if row is None:
        raise InputProblem("Import a Search Console report first (Import Report).")
    return {
        "id": row["id"],
        "site": row["site"],
        "label": row["label"],
        **json.loads(row["data_json"]),
    }


def run_import(fields: dict, ctx: Context):
    files = fields.get("files") or []
    if not isinstance(files, list) or not files:
        raise InputProblem("Choose the Search Console export to upload.")
    data = parse_upload(files)
    site = str(fields.get("site", "")).strip() or "my site"
    label = (" vs ".join(data["labels"]) if data["labels"] else "export") + f" · {site}"
    cur = ctx.db.run(
        "INSERT INTO gsc_datasets (user_id, site, label, uploaded_at, data_json) "
        "VALUES (?, ?, ?, ?, ?)",
        ctx.user_id,
        site,
        label,
        now(),
        json.dumps(data),
    )
    did = cur.lastrowid
    q, p = data["queries"], data["pages"]
    t = totals(q or p)
    top_q = sorted(q, key=lambda r: -r["clicks"])[:15]
    top_p = sorted(p, key=lambda r: -r["clicks"])[:15]
    r = {
        "dataset": did,
        "site": site,
        "queries": len(q),
        "pages": len(p),
        "totals": t,
        "compare": data["compare"],
    }
    r["view"] = view(
        headline(
            f"Imported {site}",
            f"{len(q)} queries and {len(p)} pages"
            + (" with a comparison period" if data["compare"] else ""),
            None,
        ),
        facts(
            "Totals",
            [
                ("Clicks", f"{t['clicks']:,}"),
                ("Impressions", f"{t['impressions']:,}"),
                ("Click-through rate", pct(t["ctr"])),
                ("Average position", f"{t['position']:.1f}"),
            ],
        ),
        table(
            "Top queries",
            ["Query", "Clicks", "Impressions", "CTR", "Position"],
            [
                [
                    x["key"],
                    int(x["clicks"]),
                    int(x["impressions"]),
                    pct(x.get("ctr", 0)),
                    f"{x.get('position', 0):.1f}",
                ]
                for x in top_q
            ],
        )
        if top_q
        else None,
        table(
            "Top pages",
            ["Page", "Clicks", "Impressions", "CTR", "Position"],
            [
                [
                    {"text": x["key"], "href": x["key"]}
                    if x["key"].startswith("http")
                    else x["key"],
                    int(x["clicks"]),
                    int(x["impressions"]),
                    pct(x.get("ctr", 0)),
                    f"{x.get('position', 0):.1f}",
                ]
                for x in top_p
            ],
        )
        if top_p
        else None,
    )
    return f"Imported {site}: {len(q)} queries, {len(p)} pages", None, r


def opportunities(data: dict) -> dict:
    rows = data["queries"] or data["pages"]
    if not rows:
        raise InputProblem("The report has no rows.")
    impressions = sorted(r["impressions"] for r in rows)
    # Skip only the long tail: the lower quartile. A median floor hid half of a small
    # site's queries, including ones sitting just off page one.
    floor = int(max(30, impressions[len(impressions) // 4]))
    striking = sorted(
        [r for r in rows if 8 <= r.get("position", 0) <= 20 and r["impressions"] >= floor],
        key=lambda r: -r["impressions"],
    )[:25]
    low_ctr = []
    for r in rows:
        pos = round(r.get("position", 0))
        exp = EXPECTED_CTR.get(pos)
        if exp and r["impressions"] >= floor and r.get("ctr", 0) < exp / 2:
            gain = int(r["impressions"] * exp - r["clicks"])
            low_ctr.append({**r, "expected": exp, "gain": gain})
    low_ctr.sort(key=lambda r: -r["gain"])
    zero = sorted(
        [r for r in rows if r["clicks"] == 0 and r["impressions"] >= floor],
        key=lambda r: -r["impressions"],
    )[:15]
    return {
        "floor": floor,
        "striking": striking,
        "low_ctr": low_ctr[:25],
        "zero": zero,
        "kind": "queries" if data["queries"] else "pages",
    }


def run_opportunities(fields: dict, ctx: Context):
    data = load_dataset(ctx, fields.get("dataset"))
    o = opportunities(data)
    gain = sum(r["gain"] for r in o["low_ctr"])
    word = "Query" if o["kind"] == "queries" else "Page"
    o["view"] = view(
        headline(
            f"{len(o['striking'])} near page one, {len(o['low_ctr'])} under-clicked",
            f"{data['label']} · rows with at least {o['floor']:,} impressions",
        ),
        table(
            "Striking distance: position 8-20",
            [word, "Impressions", "Clicks", "Position"],
            [
                [r["key"], int(r["impressions"]), int(r["clicks"]), f"{r['position']:.1f}"]
                for r in o["striking"]
            ],
            "Already ranking on page one or two. Improve the page and its internal links "
            "to move it into the top results.",
        ),
        table(
            f"Low click-through for the position (about {gain:,} clicks a period to win)",
            [word, "Position", "CTR", "Typical CTR", "Clicks to win"],
            [
                [
                    r["key"],
                    f"{r['position']:.1f}",
                    {"status": FAIL, "text": pct(r["ctr"])},
                    pct(r["expected"]),
                    r["gain"],
                ]
                for r in o["low_ctr"]
            ],
            "Shown often but rarely clicked: rewrite the title and description to answer "
            "the search.",
        ),
        table(
            "Seen but never clicked",
            [word, "Impressions", "Position"],
            [[r["key"], int(r["impressions"]), f"{r['position']:.1f}"] for r in o["zero"]],
        ),
    )
    return (
        f"{len(o['striking'])} striking-distance and {len(o['low_ctr'])} low-CTR {o['kind']}",
        None,
        o,
    )


def changes(data: dict) -> dict:
    if not data.get("compare"):
        raise InputProblem(
            "This report has one period. In Search Console choose Date > "
            "Compare before exporting, then import it again."
        )
    out = {}
    for kind in ("queries", "pages"):
        rows = data[kind]
        for r in rows:
            r["delta"] = r["clicks"] - r.get("prev_clicks", 0)
        out[kind] = {
            "losers": sorted([r for r in rows if r["delta"] < 0], key=lambda r: r["delta"])[:20],
            "winners": sorted([r for r in rows if r["delta"] > 0], key=lambda r: -r["delta"])[:20],
            "lost": [r for r in rows if r.get("prev_clicks", 0) > 0 and r["clicks"] == 0][:20],
            "now": totals(rows),
            "before": totals(rows, "prev_"),
        }
    return out


def run_changes(fields: dict, ctx: Context):
    data = load_dataset(ctx, fields.get("dataset"))
    c = changes(data)
    base = c["pages"] if data["pages"] else c["queries"]
    now_t, before = base["now"], base["before"]
    diff = now_t["clicks"] - before["clicks"]
    labels = data.get("labels") or ["this period", "previous period"]

    def rows(items):
        return [
            [
                r["key"],
                int(r.get("prev_clicks", 0)),
                int(r["clicks"]),
                {"status": FAIL if r["delta"] < 0 else PASS, "text": f"{int(r['delta']):+d}"},
                f"{r.get('prev_position', 0):.1f} → {r.get('position', 0):.1f}",
            ]
            for r in items
        ]

    cols = ["", labels[1], labels[0], "Change", "Position"]
    c["view"] = view(
        headline(
            f"Clicks {before['clicks']:,} → {now_t['clicks']:,} ({diff:+,})",
            f"{labels[0]} against {labels[1]} · {data['site']}",
            None,
            {"fail": len(base["losers"]), "warn": 0, "pass": len(base["winners"])},
        ),
        table("Pages losing clicks", ["Page", *cols[1:]], rows(c["pages"]["losers"]))
        if data["pages"]
        else None,
        table("Queries losing clicks", ["Query", *cols[1:]], rows(c["queries"]["losers"]))
        if data["queries"]
        else None,
        table("Pages gaining clicks", ["Page", *cols[1:]], rows(c["pages"]["winners"]))
        if data["pages"]
        else None,
        table("Queries gaining clicks", ["Query", *cols[1:]], rows(c["queries"]["winners"]))
        if data["queries"]
        else None,
    )
    return f"Clicks {before['clicks']:,} → {now_t['clicks']:,} ({diff:+,})", None, c


def dataset_options(db, user_id: int) -> list[dict]:
    return [
        {"value": str(r["id"]), "label": r["label"]}
        for r in db.all(
            "SELECT id, label FROM gsc_datasets WHERE user_id = ? ORDER BY id DESC LIMIT 30",
            user_id,
        )
    ]
