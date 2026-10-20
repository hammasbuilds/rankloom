"""Tool engines. Each takes the run form's fields and returns (summary, score, output)."""

from __future__ import annotations

from collections.abc import Callable

from . import site_audit

ENGINES: dict[str, Callable[[dict], tuple[str, int | None, dict]]] = {
    "site-audit": site_audit.run,
}
