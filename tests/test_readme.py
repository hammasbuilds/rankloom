"""The README's Input / Output block is demo.py's real output; a stale copy fails here."""

import contextlib
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_readme_output_block_matches_demo(monkeypatch):
    sys.path.insert(0, str(ROOT))
    import demo

    monkeypatch.setattr(sys, "argv", ["demo.py"])
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        demo.main()
    printed = out.getvalue().splitlines()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    block = re.search(r"```\n(Input : https://solar\.example/.*?)```", readme, re.S).group(1)
    shown = [line for line in block.splitlines() if line.strip() and line.strip() != "..."]
    assert len(shown) >= 10
    for line in shown:
        assert line in printed, line


def test_readme_test_count_is_the_collected_count():
    import subprocess

    collected = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).stdout
    n = int(re.search(r"(\d+) tests? collected", collected).group(1))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"# {n} tests" in readme
