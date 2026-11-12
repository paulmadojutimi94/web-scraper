"""The crawl loop: listing page -> its items -> next listing page -> ... -> stop.

Stops for exactly one of these reasons (saved on the run as stop_reason):
  done          the last listing page had no 'next' link
  loop          'next' pointed at a listing page we've already fetched
  no_progress   a listing page added no new items (an endless 'next' trap)
  max_pages     hit the hard request cap
  listing_error a listing page couldn't be fetched, so we can't find 'next'
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .config import Settings
from .fetcher import Fetcher
from .profiles import Profile
from .storage import Store


@dataclass
class CrawlStats:
    run_id: int = 0
    stop_reason: str = ""
    listing_pages: int = 0
    item_pages: int = 0
    new: int = 0
    changed: int = 0
    unchanged: int = 0
    rejected: int = 0
    blocked: int = 0  # robots.txt said no, or the URL was out of scope
    failed: int = 0
    seconds: float = 0.0
    outcomes: dict = field(default_factory=dict)

    def line(self) -> str:
        return (f"run {self.run_id}: {self.listing_pages} listing + {self.item_pages} item pages | "
                f"{self.new} new, {self.changed} changed, {self.unchanged} unchanged, "
                f"{self.rejected} rejected, {self.blocked} blocked, {self.failed} failed | "
                f"stop: {self.stop_reason} | {self.seconds:.1f}s")


def crawl(start_url: str, profile: Profile, store: Store, settings: Settings,
          fetcher: Fetcher | None = None, progress=None) -> CrawlStats:
    fetcher = fetcher or Fetcher(settings, start_url, cache=store)
    stats = CrawlStats()
    stats.run_id = run_id = store.start_run(start_url, profile.name, settings.as_dict())
    started = time.perf_counter()

    seen_listings: set[str] = set()
    seen_items: set[str] = set()
    fetches = 0
    url: str | None = start_url

    def note(outcome: str) -> None:
        stats.outcomes[outcome] = stats.outcomes.get(outcome, 0) + 1

    while True:
        if url is None:
            stats.stop_reason = "done"
            break
        if settings.guard_visited and url in seen_listings:
            stats.stop_reason = "loop"
            break
        if fetches >= settings.max_pages:
            stats.stop_reason = "max_pages"
            break
        seen_listings.add(url)

        page = fetcher.fetch(url)
        fetches += 1
        store.log_fetch(run_id, "listing", page)
        note(page.outcome)
        if not page.ok:
            stats.stop_reason = "listing_error"
            break
        stats.listing_pages += 1
        listing = profile.parse_listing(page.body, page.encoding, page.final_url)

        new_items = [u for u in dict.fromkeys(listing.item_urls) if u not in seen_items]
        for item_url in new_items:
            if fetches >= settings.max_pages:
                break
            seen_items.add(item_url)
            result = fetcher.fetch(item_url)
            fetches += 1
            store.log_fetch(run_id, "item", result)
            note(result.outcome)
            if result.outcome in ("robots_blocked", "out_of_scope"):
                stats.blocked += 1
                continue
            if not result.ok:
                stats.failed += 1
                continue
            stats.item_pages += 1
            seen_items.add(result.final_url)  # after a redirect, the final URL is the book's real address
            parsed = profile.parse_item(result.body, result.encoding, result.final_url)
            if parsed.item is None:
                stats.rejected += 1
                store.log_reject(run_id, result.final_url, parsed.reasons)
                continue
            status = store.upsert_book(run_id, parsed.item)
            setattr(stats, status, getattr(stats, status) + 1)
        store.commit()  # one commit per listing page: a crash loses at most one page of work
        if progress:
            progress(stats)

        if fetches >= settings.max_pages:
            stats.stop_reason = "max_pages"
            break
        if settings.guard_no_progress and not new_items:
            stats.stop_reason = "no_progress"
            break
        url = listing.next_url

    stats.seconds = time.perf_counter() - started
    store.finish_run(run_id, stats.stop_reason)
    return stats
