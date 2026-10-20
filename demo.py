"""Input / Output proof for the live engine, with no network: two pages whose problems are known.

uv run python demo.py                 # the two fixture pages
uv run python demo.py --live URL      # a real page, through the same address guard
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))

from test_site_audit import BAD, GOOD, fetcher  # noqa: E402

from rankloom.engines import site_audit  # noqa: E402

PAGES = {
    "https://solar.example/": (
        200,
        GOOD,
        {"content-encoding": "gzip"},
        "https://solar.example/",
        [],
    ),
    "https://solar.example/robots.txt": (200, "User-agent: *\nSitemap: /sitemap.xml", {}, "", []),
    "http://bad.example/": (
        200,
        BAD,
        {},
        "http://bad.example/",
        [(301, "http://bad.example"), (302, "http://www.bad.example/")],
    ),
    "http://bad.example/robots.txt": (200, "User-agent: *\nDisallow: /\n", {}, "", []),
}


def show(result: dict) -> None:
    c = result["counts"]
    print(f"Input : {result['url']}")
    print(f"Output: {result['score']}/100  ({c['fail']} fail, {c['warn']} warn, {c['pass']} pass)")
    for check in result["checks"]:
        if check["status"] == "pass":
            continue
        print(f"  {check['status'].upper():4}  {check['label']}: {check['detail']}")
    print()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--live", metavar="URL")
    args = p.parse_args()
    if args.live:
        show(site_audit.audit(args.live))
        return
    fetch = fetcher(PAGES)
    for url in ("solar.example", "http://bad.example/"):
        show(site_audit.audit(url, fetch=fetch))


if __name__ == "__main__":
    main()
