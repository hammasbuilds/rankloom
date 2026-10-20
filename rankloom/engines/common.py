"""What every engine returns, so one renderer in the page can draw any sub-tool's result.

An engine returns (summary, score, output). `output["view"]` is a headline plus a list of typed
blocks; the rest of `output` is the raw result, kept for reports and for the API.

Block types:
    checks  - items: [{label, status pass|warn|fail, detail, fix}]
    facts   - items: [[label, value], ...]
    table   - columns: [...], rows: [[cell, ...]], where a cell is a str/number or
              {"text", "href"} (external link) or {"text", "route"} (a page in the app)
              or {"status": pass|warn|fail, "text"}
    list    - items: [str, ...]
    text    - text: str (paragraphs separated by blank lines)
    drafts  - items: [{label, text}] each with a copy button
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ..db import Database
from ..netguard import Response, safe_fetch


@dataclass
class Context:
    user_id: int
    db: Database | None = None
    fetch: Callable[[str], Response] = field(default=safe_fetch)


def headline(
    title: str, subtitle: str = "", score: int | None = None, counts: dict | None = None
) -> dict:
    return {"title": title, "subtitle": subtitle, "score": score, "counts": counts}


def checks(title: str, items: list[dict], note: str = "") -> dict:
    return {"type": "checks", "title": title, "note": note, "items": items}


def facts(title: str, items: list[tuple[str, object]]) -> dict:
    return {
        "type": "facts",
        "title": title,
        "items": [[k, "" if v is None else str(v)] for k, v in items],
    }


def table(title: str, columns: list[str], rows: list[list], note: str = "") -> dict:
    return {"type": "table", "title": title, "note": note, "columns": columns, "rows": rows}


def bullets(title: str, items: list[str], note: str = "") -> dict:
    return {"type": "list", "title": title, "note": note, "items": items}


def text(title: str, body: str, note: str = "") -> dict:
    return {"type": "text", "title": title, "note": note, "text": body}


def drafts(title: str, items: list[dict], note: str = "") -> dict:
    return {"type": "drafts", "title": title, "note": note, "items": items}


def view(head: dict, *blocks: dict | None) -> dict:
    return {"headline": head, "blocks": [b for b in blocks if b]}


PASS, WARN, FAIL = "pass", "warn", "fail"
CREDIT = {PASS: 1.0, WARN: 0.5, FAIL: 0.0}


def check(cid: str, label: str, status: str, detail: str, fix: str = "", weight: int = 1) -> dict:
    return {
        "id": cid,
        "label": label,
        "status": status,
        "detail": detail,
        "fix": "" if status == PASS else fix,
        "weight": weight,
    }


def score_checks(items: list[dict]) -> tuple[int, dict]:
    total = sum(c["weight"] for c in items)
    got = sum(c["weight"] * CREDIT[c["status"]] for c in items)
    counts = {s: sum(1 for c in items if c["status"] == s) for s in (PASS, WARN, FAIL)}
    return (round(100 * got / total) if total else 0), counts


def sort_checks(items: list[dict]) -> list[dict]:
    order = {FAIL: 0, WARN: 1, PASS: 2}
    return sorted(items, key=lambda c: (order[c["status"]], -c["weight"]))


class InputProblem(ValueError):
    """The form was filled in wrongly; the message says how."""
