"""A deterministic fake bookshop whose HTML copies books.toscrape.com.

Same seed -> same 1,000 books -> same HTML, byte for byte. Every book's true
values are kept, so the scraper's output can be checked field by field (the
"answer key"). Real-world mess is planted on purpose, each at a known rate:

  titles with & < " é ü, and long titles truncated in the listing
  prices of £1,000+ with a thousands comma
  'Out of stock', and 'In stock' with no count
  missing descriptions; whitespace and newlines around values
  1% of pages broken (no price / no UPC / no title) -> must be rejected
  1% of links go through a 301 redirect from an old URL
  1% of links point under /catalogue/hidden/, which robots.txt disallows
  1% of pages answer 503 the first time; 0.5% answer 429 + Retry-After: 1
  version=2: 5% of prices and 3% of stock counts change (for the rerun eval)
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import asdict, dataclass

PER_PAGE = 20
RATING_WORDS = ["One", "Two", "Three", "Four", "Five"]
CATEGORIES = [
    "Travel", "Mystery", "Historical Fiction", "Sequential Art", "Classics", "Philosophy",
    "Romance", "Womens Fiction", "Fiction", "Childrens", "Religion", "Nonfiction", "Music",
    "Science Fiction", "Sports and Games", "Fantasy", "Young Adult", "Science", "Poetry",
    "Food and Drink", "Self Help", "Business", "Art", "Psychology", "Health",
]
ADJ = ["Silent", "Broken", "Golden", "Hidden", "Last", "Wild", "Little", "Secret", "Burning",
       "Distant", "Northern", "Paper", "Crimson", "Quiet", "Hungry", "Electric", "Lonely"]
NOUN = ["River", "Garden", "Empire", "Letters", "Kingdom", "Orchard", "Lighthouse", "Machine",
        "Winter", "Harbour", "Cartographer", "Daughter", "Atlas", "Station", "Fox", "Library"]
TRICKY = [
    "Salt & Smoke", "The <Unclosed> Tag", 'Who Said "Enough"?', "Café Society",
    "Über Alles: A Memoir", "Señor Nobody", "Rock 'n' Roll Kitchen", "50% Off Everything",
    "C++ for Cats", "Ærø and Back", "Naïve Café Stories",
]
WORDS = ("a an the story of time city love war light dark memory journey family secret world "
         "night home truth river voice house road garden years letters sea friend").split()


@dataclass
class Book:
    id: int
    slug: str
    title: str
    category: str
    price_pence: int
    rating: int
    stock: int  # 0 = out of stock
    show_count: bool  # False -> page says just "In stock"
    upc: str
    description: str | None
    broken: str | None  # None, 'no_price', 'no_upc', 'no_title'
    link: str  # 'normal', 'redirect' or 'hidden'
    fault: str | None  # None, '503' or '429'

    @property
    def path(self) -> str:
        return f"/catalogue/{self.slug}_{self.id}/index.html"

    @property
    def listed_path(self) -> str:
        if self.link == "redirect":
            return f"/catalogue/old/{self.slug}_{self.id}.html"
        if self.link == "hidden":
            return f"/catalogue/hidden/{self.slug}_{self.id}/index.html"
        return self.path


def _slug(title: str) -> str:
    out = "".join(c.lower() if c.isascii() and c.isalnum() else "-" for c in title)
    return "-".join(p for p in out.split("-") if p)[:60] or "book"


def generate(seed: int = 0, n_books: int = 1000, version: int = 1) -> list[Book]:
    rng = random.Random(seed)
    books = []
    for i in range(1, n_books + 1):
        roll = rng.random()
        if roll < 0.04:
            title = rng.choice(TRICKY)
        elif roll < 0.10:  # long title: the listing will show it truncated
            title = " ".join(rng.choice(WORDS).capitalize() for _ in range(rng.randint(9, 14)))
        else:
            title = f"The {rng.choice(ADJ)} {rng.choice(NOUN)}"
            if rng.random() < 0.3:
                title += f" ({rng.choice(['A Novel', 'Book 2', 'Revised Edition', 'Vol. 3'])})"
        price = rng.randint(1000, 5999) if rng.random() > 0.02 else rng.randint(100_000, 450_000)
        stock = 0 if rng.random() < 0.15 else rng.randint(1, 22)
        books.append(Book(
            id=i,
            slug=_slug(title),
            title=title,
            category=rng.choice(CATEGORIES),
            price_pence=price,
            rating=rng.randint(1, 5),
            stock=stock,
            show_count=rng.random() > 0.05,
            upc=hashlib.md5(f"{seed}-{i}".encode()).hexdigest()[:16],
            description=None if rng.random() < 0.10 else " ".join(
                rng.choice(WORDS) for _ in range(rng.randint(20, 60))).capitalize() + ".",
            broken=rng.choice(["no_price", "no_upc", "no_title"]) if rng.random() < 0.01 else None,
            link=("redirect" if (r := rng.random()) < 0.01 else "hidden" if r < 0.02 else "normal"),
            fault=("503" if (f := rng.random()) < 0.01 else "429" if f < 0.015 else None),
        ))
    if version >= 2:  # a later visit: some prices and stock counts moved
        change = random.Random(seed * 1000 + version)
        for b in books:
            if change.random() < 0.05:
                b.price_pence = max(100, round(b.price_pence * change.uniform(0.8, 1.2)))
            if change.random() < 0.03:
                b.stock = change.randint(0, 22)
    return books


def answer_key(books: list[Book], host: str) -> dict[str, dict | None]:
    """What a perfect scraper should store: {url: fields} (None = must be rejected).

    Books behind a robots-disallowed link are absent: a polite scraper never sees them.
    """
    key = {}
    for b in books:
        if b.link == "hidden":
            continue
        url = f"http://{host}{b.path}"
        if b.broken:
            key[url] = None
            continue
        key[url] = {
            "url": url, "upc": b.upc, "title": b.title, "category": b.category,
            "price_pence": b.price_pence, "rating": b.rating, "in_stock": b.stock > 0,
            "stock_count": (b.stock if b.show_count else None) if b.stock > 0 else 0,
            "description": b.description,
        }
    return key


def book_dict(b: Book) -> dict:
    return asdict(b)
