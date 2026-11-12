"""Site profiles: the site-specific half of the scraper."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ListingPage:
    item_urls: list[str]
    next_url: str | None


@dataclass
class ItemResult:
    item: dict | None  # None when the page couldn't be turned into a valid item
    reasons: list[str] = field(default_factory=list)


class Profile(Protocol):
    name: str
    default_start_url: str

    def parse_listing(self, body: bytes, encoding: str | None, url: str) -> ListingPage: ...
    def parse_item(self, body: bytes, encoding: str | None, url: str) -> ItemResult: ...


def get_profile(name: str) -> Profile:
    from .books import BooksProfile

    profiles = {"books": BooksProfile}
    if name not in profiles:
        raise SystemExit(f"unknown profile {name!r}; choose from {sorted(profiles)}")
    return profiles[name]()
