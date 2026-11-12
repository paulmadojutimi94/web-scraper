"""Command line: crawl, report, and two learning tools (fetch, robots)."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import replace

from .config import Settings
from .crawler import crawl
from .fetcher import Fetcher
from .profiles import get_profile
from .report import build_summary, write_reports
from .storage import Store
from .urls import normalize

LOCAL_HOSTS = ("localhost", "127.0.0.1")
MIN_PUBLIC_DELAY_S = 0.5


def _settings(args) -> Settings:
    s = Settings()
    if getattr(args, "delay", None) is not None:
        s = replace(s, min_delay_s=args.delay)
    if getattr(args, "max_pages", None) is not None:
        s = replace(s, max_pages=args.max_pages)
    if getattr(args, "no_cache", False):
        s = replace(s, use_cache=False)
    return s


def _check_delay(url: str, settings: Settings) -> None:
    host = (normalize(url).split("/")[2]).split(":")[0]
    if host not in LOCAL_HOSTS and settings.min_delay_s < MIN_PUBLIC_DELAY_S:
        sys.exit(f"--delay {settings.min_delay_s} is too fast for a public site "
                 f"(minimum {MIN_PUBLIC_DELAY_S}s). Be kind to other people's servers.")


def cmd_crawl(args) -> int:
    profile = get_profile(args.profile)
    start = args.start or profile.default_start_url
    settings = _settings(args)
    _check_delay(start, settings)
    store = Store(args.db)

    def progress(stats):
        print(f"  listing {stats.listing_pages:>3} | items {stats.item_pages:>5} "
              f"| new {stats.new} changed {stats.changed} unchanged {stats.unchanged}", flush=True)

    print(f"Crawling {start} (delay {settings.min_delay_s}s/request, robots.txt respected)")
    stats = crawl(start, profile, store, settings, progress=None if args.quiet else progress)
    print(stats.line())
    if args.report_dir:
        summary = build_summary(store.conn, stats.run_id)
        for path in write_reports(summary, args.report_dir, settings):
            print(f"  wrote {path}")
    store.close()
    return 0 if stats.stop_reason in ("done", "no_progress", "max_pages") else 1


def cmd_report(args) -> int:
    conn = sqlite3.connect(args.db)
    summary = build_summary(conn, args.run)
    for path in write_reports(summary, args.out):
        print(f"wrote {path}")
    return 0


def cmd_fetch(args) -> int:
    """Fetch one URL the polite way and show what happened: a window into HTTP."""
    settings = _settings(args)
    fetcher = Fetcher(settings, args.url)
    r = fetcher.fetch(args.url)
    print(f"outcome   {r.outcome}\nstatus    {r.status}\nfinal_url {r.final_url}\n"
          f"attempts  {r.attempts}\nelapsed   {r.elapsed_ms:.0f} ms\nbytes     {r.bytes_received}\n"
          f"charset   {r.encoding or '(not in header; parser will sniff <meta charset>)'}")
    if r.error:
        print(f"error     {r.error}")
    if r.ok and args.show:
        print("-" * 60)
        print(r.body[: args.show].decode(r.encoding or "utf-8", errors="replace"))
    return 0 if r.ok else 1


def cmd_robots(args) -> int:
    settings = Settings()
    fetcher = Fetcher(settings, args.url)
    policy = fetcher.robots.policy_for(args.url)
    print(f"robots.txt status {policy.status} -> "
          f"{'allow all' if policy.allow_all else 'disallow all' if policy.disallow_all else 'rules parsed'}")
    print(f"allowed for us:   {fetcher.robots.allowed(args.url)}")
    print(f"crawl-delay:      {fetcher.robots.crawl_delay(args.url)}")
    return 0


def cmd_serve(args) -> int:
    from testsite.server import serve_forever

    serve_forever(port=args.port, seed=args.seed, n_books=args.books, version=args.version)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="scraper", description="A polite web scraper.")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("crawl", help="crawl a site, store the results, write a report")
    c.add_argument("--start", help="first listing page (default: the profile's site)")
    c.add_argument("--profile", default="books")
    c.add_argument("--db", default="scraper.db")
    c.add_argument("--delay", type=float, help="seconds between requests to one host (default 1.0)")
    c.add_argument("--max-pages", type=int)
    c.add_argument("--no-cache", action="store_true", help="don't send conditional GETs")
    c.add_argument("--report-dir", default="reports")
    c.add_argument("--quiet", action="store_true")
    c.set_defaults(func=cmd_crawl)

    r = sub.add_parser("report", help="rebuild the reports for a run")
    r.add_argument("--db", default="scraper.db")
    r.add_argument("--run", type=int, help="run id (default: latest)")
    r.add_argument("--out", default="reports")
    r.set_defaults(func=cmd_report)

    f = sub.add_parser("fetch", help="fetch one URL and explain the response")
    f.add_argument("url")
    f.add_argument("--show", type=int, default=0, help="print the first N bytes of the body")
    f.set_defaults(func=cmd_fetch)

    rb = sub.add_parser("robots", help="what does robots.txt say about this URL?")
    rb.add_argument("url")
    rb.set_defaults(func=cmd_robots)

    s = sub.add_parser("serve-testsite", help="run the local practice site")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--books", type=int, default=1000)
    s.add_argument("--version", type=int, default=1, help="2 = some prices changed")
    s.set_defaults(func=cmd_serve)

    args = p.parse_args(argv)
    return args.func(args)
