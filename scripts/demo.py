"""The demo: crawl the local test site, crawl it again, let it change, crawl a third time.

    make demo            # 1,000 books, writes examples/
    python3 scripts/demo.py --quick   # 100 books, for CI

Everything printed here is real output; examples/ keeps a copy.
"""

from __future__ import annotations

import io
import re
import shutil
import sys
import tempfile
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scraper.cli import main as cli  # noqa: E402
from scraper.config import Settings  # noqa: E402
from scraper.crawler import crawl  # noqa: E402
from scraper.profiles import get_profile  # noqa: E402
from scraper.report import build_summary, pounds, write_reports  # noqa: E402
from scraper.storage import Store  # noqa: E402
from testsite.server import TestSite  # noqa: E402


def say(text: str = "") -> None:
    print(text, flush=True)


def demo(n_books: int, out: Path) -> str:
    buf = io.StringIO()
    with (redirect_stdout(buf), TestSite(seed=0, n_books=n_books) as site,
          tempfile.TemporaryDirectory() as tmp):
        start = site.base + "/catalogue/page-1.html"
        say(f"$ scraper robots {start}")
        cli(["robots", start])
        say(f"\n$ scraper fetch {site.base}/admin/stats.html")
        cli(["fetch", f"{site.base}/admin/stats.html"])
        say(f"\n$ scraper fetch {start}")
        cli(["fetch", start])

        db = str(Path(tmp) / "demo.db")
        settings = replace(Settings(), min_delay_s=0.0)  # our own local server; the CLI refuses 0 elsewhere
        books = get_profile("books")

        say("\n--- run 1: first visit ---")
        store = Store(db)
        s1 = crawl(start, books, store, settings)
        say(s1.line())
        say("  outcomes: " + ", ".join(f"{k} {v}" for k, v in sorted(s1.outcomes.items())))

        say("\n--- run 2: same site, nothing changed ---")
        s2 = crawl(start, books, store, settings)
        say(s2.line())
        say("  outcomes: " + ", ".join(f"{k} {v}" for k, v in sorted(s2.outcomes.items())))

        say("\n--- the shop changes some prices and stock ---")
        site.set_version(2)
        s3 = crawl(start, books, store, settings)
        say(s3.line())
        summary = build_summary(store.conn, s3.run_id)
        for p in summary["changes"]["price_changes"][:5]:
            say(f"  {p['title'][:40]:40}  {pounds(p['old_pence']):>9} -> {pounds(p['new_pence']):>9}")
        say(f"  ...{len(summary['changes']['price_changes'])} price changes in total")

        out.mkdir(parents=True, exist_ok=True)
        paths = write_reports(summary, out, settings)
        say("\nReports: " + ", ".join(str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else p.name
                                       for p in paths))
        store.close()
    return buf.getvalue()


if __name__ == "__main__":
    quick = "--quick" in sys.argv
    out = Path(tempfile.mkdtemp()) if quick else ROOT / "examples"
    text = demo(100 if quick else 1000, out)
    print(text)
    if quick:
        shutil.rmtree(out)
    else:  # the test site ran on a random free port; show the usual one in the saved copies
        (out / "demo_output.txt").write_text(text)
        for f in out.iterdir():
            f.write_text(re.sub(r"127\.0\.0\.1:\d+", "127.0.0.1:8000", f.read_text(encoding="utf-8-sig")),
                         encoding="utf-8-sig" if f.suffix == ".csv" else "utf-8")
