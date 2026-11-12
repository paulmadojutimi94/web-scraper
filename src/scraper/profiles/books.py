"""Site profile for books.toscrape.com (and the local test site, which copies its HTML).

A profile is the only site-specific code: which CSS selectors find the items,
the next-page link, and each field. Point the scraper at a different site by
writing another profile with the same two methods.
"""

from __future__ import annotations

from bs4 import BeautifulSoup, Tag

from ..fields import clean_text, parse_availability, parse_price_pence, parse_rating
from ..urls import normalize
from . import ItemResult, ListingPage

REQUIRED = ("title", "upc", "price_pence")


def make_soup(body: bytes, encoding: str | None) -> BeautifulSoup:
    # Bytes in, not text: if the server didn't name a charset, BeautifulSoup reads
    # the page's own <meta charset> instead of guessing.
    return BeautifulSoup(body, "lxml", from_encoding=encoding)


def base_url(soup: BeautifulSoup, page_url: str) -> str:
    """Relative links resolve against <base href> if the page has one, else the page URL."""
    base = soup.find("base", href=True)
    return normalize(base["href"], page_url) if base else page_url


def current_price_text(tag: Tag) -> str:
    """'<del>£20.00</del> <ins>£15.00</ins>' -> ' £15.00': ignore struck-out old prices."""
    return "".join(t for t in tag.find_all(string=True) if not t.find_parent(["del", "s", "strike"]))


def table_key(label: str | None) -> str:
    """'UPC:' / 'upc' / ' UPC ' -> 'upc'. Labels are written by humans; normalise them."""
    return (label or "").strip().rstrip(":").strip().lower()


class BooksProfile:
    name = "books"
    default_start_url = "https://books.toscrape.com/catalogue/page-1.html"

    def parse_listing(self, body: bytes, encoding: str | None, url: str) -> ListingPage:
        soup = make_soup(body, encoding)
        base = base_url(soup, url)
        item_urls = []
        for link in soup.select("article.product_pod h3 a[href]"):
            absolute = normalize(link["href"], base)  # relative href -> absolute URL
            if absolute.startswith(("http://", "https://")):  # skip javascript:, mailto: ...
                item_urls.append(absolute)
        # the site's own pager first, then the standard rel="next" hint (<a> or <link>)
        next_link = (soup.select_one("ul.pager li.next a[href]")
                     or soup.select_one('a[rel~="next"][href], link[rel~="next"][href]'))
        next_url = normalize(next_link["href"], base) if next_link else None
        return ListingPage(item_urls=item_urls, next_url=next_url)

    def parse_item(self, body: bytes, encoding: str | None, url: str) -> ItemResult:
        soup = make_soup(body, encoding)
        main = soup.select_one("div.product_main")

        table = {}  # the "Product Information" table: {'upc': 'a897...', ...}
        for row in soup.select("table.table-striped tr"):
            th, td = row.find("th"), row.find("td")
            if th and td:
                table[table_key(th.get_text())] = clean_text(td.get_text())

        title = clean_text(main.h1.get_text()) if main and main.h1 else None

        price_tag = main.select_one("p.price_color") if main else None
        price_text = current_price_text(price_tag) if price_tag else table.get("price (excl. tax)")

        rating_tag = main.select_one("p.star-rating") if main else None
        avail_tag = main.select_one("p.availability") if main else None
        avail_text = avail_tag.get_text() if avail_tag else table.get("availability")
        in_stock, stock_count = parse_availability(avail_text)

        crumbs = soup.select("ul.breadcrumb li")
        category = clean_text(crumbs[-2].get_text()) if len(crumbs) >= 3 else None

        desc_tag = soup.select_one("#product_description ~ p")
        description = clean_text(desc_tag.get_text()) if desc_tag else None

        item = {
            "url": url,
            "upc": table.get("upc"),
            "title": title,
            "category": category,
            "price_pence": parse_price_pence(price_text),
            "rating": parse_rating(rating_tag.get("class") if rating_tag else None),
            "in_stock": in_stock,
            "stock_count": stock_count,
            "description": description,
        }
        reasons = [f"missing {field}" for field in REQUIRED if item[field] in (None, "")]
        return ItemResult(item=None if reasons else item, reasons=reasons)
