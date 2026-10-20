"""Engines by "tool/sub-tool". Each takes (fields, Context) and returns (summary, score, output),
with output["view"] for the page (see common.py)."""

from __future__ import annotations

from collections.abc import Callable

from . import ai_visibility, content, crawl, leads, local_seo, reports, search_perf, site_audit
from .common import Context

Engine = Callable[[dict, Context], tuple[str, int | None, dict]]

ENGINES: dict[str, Engine] = {
    "site-audit/page": site_audit.run,
    "site-audit/crawl": crawl.run,
    "site-audit/local": local_seo.run,
    "ai-visibility/readiness": ai_visibility.run_readiness,
    "ai-visibility/questions": ai_visibility.run_questions,
    "ai-visibility/answers": ai_visibility.run_answers,
    "lead-finder/search": leads.run_search,
    "lead-finder/outreach": leads.run_outreach,
    "search-performance/import": search_perf.run_import,
    "search-performance/opportunities": search_perf.run_opportunities,
    "search-performance/changes": search_perf.run_changes,
    "content-studio/keywords": content.run_keywords,
    "content-studio/brief": content.run_brief,
    "content-studio/draft": content.run_draft,
    "content-studio/grade": content.run_grade,
    "client-reports/report": reports.run_report,
}
