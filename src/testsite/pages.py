"""HTML for the test site, shaped like books.toscrape.com's real markup."""

from __future__ import annotations

from html import escape

from .generator import PER_PAGE, RATING_WORDS, Book

HEAD = ('<!DOCTYPE html>\n<html lang="en-us"><head>'
        '<meta http-equiv="content-type" content="text/html; charset=UTF-8" />'
        "<title>{title} | Books to Scrape - Sandbox</title></head><body>\n")


def money(pence: int) -> str:
    return f"£{pence / 100:,.2f}"


def availability(b: Book) -> str:
    if b.stock == 0:
        return "\n\n    Out of stock\n\n"
    return f"\n\n    In stock ({b.stock} available)\n\n" if b.show_count else "\n\n    In stock\n\n"


def pod(b: Book) -> str:
    href = b.listed_path.removeprefix("/catalogue/")
    shown = b.title if len(b.title) <= 40 else b.title[:37] + "..."
    return (
        '<li class="col-xs-6 col-sm-4 col-md-3 col-lg-3"><article class="product_pod">\n'
        f'<div class="image_container"><a href="{href}"><img src="../media/{b.id}.jpg" '
        f'alt="{escape(b.title)}" class="thumbnail"></a></div>\n'
        f'<p class="star-rating {RATING_WORDS[b.rating - 1]}"><i class="icon-star"></i></p>\n'
        f'<h3><a href="{href}" title="{escape(b.title)}">{escape(shown)}</a></h3>\n'
        f'<div class="product_price"><p class="price_color">{money(b.price_pence)}</p>\n'
        f'<p class="instock availability"><i class="icon-ok"></i>{availability(b)}</p></div>\n'
        "</article></li>\n"
    )


def listing_page(books: list[Book], page: int) -> str:
    pages = max(1, -(-len(books) // PER_PAGE))
    chunk = books[(page - 1) * PER_PAGE: page * PER_PAGE]
    pager = f'<li class="current">Page {page} of {pages}</li>'
    if page > 1:
        pager = f'<li class="previous"><a href="page-{page - 1}.html">previous</a></li>' + pager
    if page < pages:
        pager += f'<li class="next"><a href="page-{page + 1}.html">next</a></li>'
    return (
        HEAD.format(title="All products")
        + '<ul class="breadcrumb"><li><a href="../index.html">Home</a></li>'
        '<li class="active">All products</li></ul>\n'
        f"<form class=\"form-horizontal\"><strong>{len(books)}</strong> results - showing "
        f"<strong>{(page - 1) * PER_PAGE + 1}</strong> to <strong>{(page - 1) * PER_PAGE + len(chunk)}"
        "</strong>.</form>\n<ol class=\"row\">\n"
        + "".join(pod(b) for b in chunk)
        + f'</ol>\n<div><ul class="pager">{pager}</ul></div>\n'
        '<footer><a href="/admin/stats.html">Admin</a></footer></body></html>\n'
    )


def product_page(b: Book, category_index: int) -> str:
    rows = [("UPC", b.upc), ("Product Type", "Books"),
            ("Price (excl. tax)", money(b.price_pence)), ("Price (incl. tax)", money(b.price_pence)),
            ("Tax", "£0.00"), ("Availability", availability(b).strip()), ("Number of reviews", "0")]
    if b.broken == "no_upc":
        rows = rows[1:]
    if b.broken == "no_price":
        rows = [r for r in rows if not r[0].startswith("Price")]
    table = "".join(f"<tr>\n<th>{k}</th><td>{escape(v)}</td>\n</tr>\n" for k, v in rows)
    h1 = "" if b.broken == "no_title" else f"<h1>{escape(b.title)}</h1>\n"
    price = "" if b.broken == "no_price" else f'<p class="price_color">{money(b.price_pence)}</p>\n'
    desc = ""
    if b.description:
        desc = ('<div id="product_description" class="sub-header"><h2>Product Description</h2></div>\n'
                f"<p>{escape(b.description)}</p>\n")
    cat_slug = b.category.lower().replace(" ", "-")
    return (
        HEAD.format(title=escape(b.title))
        + '<ul class="breadcrumb">\n<li><a href="../../index.html">Home</a></li>\n'
        '<li><a href="../category/books_1/index.html">Books</a></li>\n'
        f'<li><a href="../category/books/{cat_slug}_{category_index}/index.html">{b.category}</a></li>\n'
        f'<li class="active">{escape(b.title)}</li>\n</ul>\n'
        '<article class="product_page"><div class="row">'
        '<div class="col-sm-6 product_main">\n'
        + h1 + price
        + f'<p class="instock availability">\n    <i class="icon-ok"></i>{availability(b)}</p>\n'
        f'<p class="star-rating {RATING_WORDS[b.rating - 1]}">\n<i class="icon-star"></i>\n</p>\n'
        "</div></div>\n"
        + desc
        + '<div class="sub-header"><h2>Product Information</h2></div>\n'
        f'<table class="table table-striped">\n{table}</table>\n</article></body></html>\n'
    )
