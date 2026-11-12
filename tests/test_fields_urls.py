import pytest

from scraper.fields import clean_text, parse_availability, parse_price_pence, parse_rating
from scraper.urls import host_of, in_scope, normalize


@pytest.mark.parametrize("text, pence", [
    ("£51.77", 5177),
    ("Â£51.77", 5177),  # the classic mojibake still parses
    ("£1,234.50", 123450),
    ("£1234.5", 123450),
    ("  £12  ", 1200),
    ("£0.00", 0),
    ("free", None),
    ("", None),
    (None, None),
])
def test_price(text, pence):
    assert parse_price_pence(text) == pence


def test_price_is_exact_not_float():
    # float("1.15") * 100 == 114.99999999999999, which int() truncates to 114
    assert parse_price_pence("£1.15") == 115


@pytest.mark.parametrize("classes, rating", [
    (["star-rating", "Three"], 3), (["star-rating", "five"], 5), (["star-rating"], None), (None, None),
])
def test_rating(classes, rating):
    assert parse_rating(classes) == rating


@pytest.mark.parametrize("text, expected", [
    ("\n\n    In stock (22 available)\n\n", (True, 22)),
    ("In stock", (True, None)),
    ("Out of stock", (False, 0)),
    ("Pre-order", (None, None)),
    (None, (None, None)),
])
def test_availability(text, expected):
    assert parse_availability(text) == expected


def test_clean_text_collapses_whitespace():
    assert clean_text("  A\n\tLight in   the Attic ") == "A Light in the Attic"
    assert clean_text("   ") is None


@pytest.mark.parametrize("url, base, expected", [
    ("HTTP://Books.Example:80/a/../b/#top", None, "http://books.example/b/"),
    ("page-2.html", "http://x.test/catalogue/page-1.html", "http://x.test/catalogue/page-2.html"),
    ("../../index.html", "http://x.test/catalogue/a_1/index.html", "http://x.test/index.html"),
    ("https://x.test:443", None, "https://x.test/"),
    ("http://x.test:8080/p?q=1#f", None, "http://x.test:8080/p?q=1"),
])
def test_normalize(url, base, expected):
    assert normalize(url, base) == expected


def test_scope():
    assert host_of("http://A.test:81/x") == "a.test:81"
    assert in_scope("http://a.test/x", "a.test")
    assert not in_scope("http://b.test/x", "a.test")
    assert not in_scope("http://169.254.169.254/latest/meta-data", "a.test")
    assert not in_scope("file:///etc/passwd", "a.test")
    assert not in_scope("javascript:alert(1)", "a.test")
