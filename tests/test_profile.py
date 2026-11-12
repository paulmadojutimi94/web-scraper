from scraper.profiles.books import BooksProfile
from testsite import pages
from testsite.generator import generate

P = BooksProfile()
BASE = "http://shop.test/catalogue/"


def test_listing_finds_20_items_and_next():
    books = generate(1, 45)
    page = P.parse_listing(pages.listing_page(books, 1).encode(), None, BASE + "page-1.html")
    assert len(page.item_urls) == 20
    assert page.item_urls[0].startswith("http://shop.test/catalogue/")
    assert page.next_url == BASE + "page-2.html"


def test_last_listing_page_has_no_next():
    books = generate(1, 45)
    page = P.parse_listing(pages.listing_page(books, 3).encode(), None, BASE + "page-3.html")
    assert len(page.item_urls) == 5 and page.next_url is None


def test_item_fields():
    b = next(b for b in generate(2, 200) if not b.broken and b.stock and b.show_count and b.description)
    body = pages.product_page(b, 5).encode()
    item = P.parse_item(body, None, "http://shop.test" + b.path).item
    assert item == {
        "url": "http://shop.test" + b.path, "upc": b.upc, "title": b.title, "category": b.category,
        "price_pence": b.price_pence, "rating": b.rating, "in_stock": True,
        "stock_count": b.stock, "description": b.description,
    }


def test_utf8_page_without_header_charset_is_read_correctly():
    b = next(b for b in generate(2, 200) if not b.broken)
    item = P.parse_item(pages.product_page(b, 1).encode("utf-8"), None, "http://x").item
    assert "Â" not in item["title"]


def test_broken_pages_are_rejected_with_reasons():
    for kind, reason in [("no_price", "missing price_pence"), ("no_upc", "missing upc"),
                         ("no_title", "missing title")]:
        b = generate(3, 1)[0]
        b.broken = kind
        result = P.parse_item(pages.product_page(b, 1).encode(), None, "http://x")
        assert result.item is None and reason in result.reasons


def test_empty_page_is_rejected_not_crashed():
    result = P.parse_item(b"", None, "http://x")
    assert result.item is None and len(result.reasons) == 3
