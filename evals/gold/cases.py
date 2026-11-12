"""The gold set: hand-written cases in formats the test-site generator never produces.

FROZEN. Written and committed before the scraper was run on any of them. Never
edit an expectation to make a case pass; fix the code or document the failure.

Two kinds:
  PARSE_CASES   real-world variations of product and listing HTML
  ROBOTS_CASES  robots.txt rules, with the answer RFC 9309 (the standard) gives

Expectations are partial: only the fields listed are checked.
"""

# A product page in the exact shape of books.toscrape.com; cases tweak one thing each.
PRODUCT = """<!DOCTYPE html>
<html lang="en-us"><head>{head}<title>{title_tag} | Books to Scrape - Sandbox</title></head><body>
<ul class="breadcrumb">
<li><a href="../../index.html">Home</a></li>
<li><a href="../category/books_1/index.html">Books</a></li>
<li><a href="../category/books/poetry_23/index.html">Poetry</a></li>
<li class="active">{title_tag}</li>
</ul>
<article class="product_page"><div class="row">
<div class="col-sm-6 product_main">
{h1}
{price}
<p class="instock availability">
    <i class="icon-ok"></i>
    {avail}
</p>
{rating}
</div></div>
<div id="product_description" class="sub-header"><h2>Product Description</h2></div>
<p>It's hard to imagine a world without A Light in the Attic. ...more</p>
<div class="sub-header"><h2>Product Information</h2></div>
<table class="table table-striped">
<tr><th>{upc_label}</th><td>a897fe39b1053632</td></tr>
<tr><th>Product Type</th><td>Books</td></tr>
<tr><th>Price (excl. tax)</th><td>£51.77</td></tr>
<tr><th>Availability</th><td>In stock (22 available)</td></tr>
</table>
</article></body></html>"""

DEFAULTS = dict(
    head='<meta http-equiv="content-type" content="text/html; charset=UTF-8" />',
    title_tag="A Light in the Attic",
    h1="<h1>A Light in the Attic</h1>",
    price='<p class="price_color">£51.77</p>',
    avail="In stock (22 available)",
    rating='<p class="star-rating Three"><i class="icon-star"></i></p>',
    upc_label="UPC",
)


def product(**overrides) -> str:
    return PRODUCT.format(**{**DEFAULTS, **overrides})


URL = "http://shop.test/catalogue/a-light-in-the-attic_1000/index.html"

PARSE_CASES = [
    # --- baseline: the real site's markup ----------------------------------------------
    dict(id="p01_real_markup", kind="item", html=product(),
         expect={"title": "A Light in the Attic", "price_pence": 5177, "rating": 3, "in_stock": True,
                 "stock_count": 22, "category": "Poetry", "upc": "a897fe39b1053632"}),

    # --- encodings ---------------------------------------------------------------------
    dict(id="p02_latin1_page_with_meta", kind="item", encoding_bytes="iso-8859-1",
         html=product(head='<meta charset="iso-8859-1">', h1="<h1>Café Poems</h1>"),
         expect={"title": "Café Poems", "price_pence": 5177}),
    dict(id="p03_cp1252_smart_quote", kind="item", encoding_bytes="cp1252",
         html=product(head='<meta charset="windows-1252">', h1="<h1>Don’t Look Back</h1>"),
         expect={"title": "Don’t Look Back"}),
    dict(id="p04_utf8_bom_no_meta", kind="item", encoding_bytes="utf-8-sig",
         html=product(head="", h1="<h1>Über Café</h1>"), expect={"title": "Über Café"}),
    dict(id="p05_header_says_latin1_but_ascii_title", kind="item", header_charset="iso-8859-1",
         html=product(), expect={"title": "A Light in the Attic", "price_pence": 5177}),

    # --- prices ------------------------------------------------------------------------
    dict(id="p06_price_no_pence", kind="item", html=product(price='<p class="price_color">£12</p>'),
         expect={"price_pence": 1200}),
    dict(id="p07_price_space_after_symbol", kind="item",
         html=product(price='<p class="price_color">£ 12.99</p>'), expect={"price_pence": 1299}),
    dict(id="p08_price_gbp_prefix", kind="item",
         html=product(price='<p class="price_color">GBP 12.99</p>'), expect={"price_pence": 1299}),
    dict(id="p09_sale_price_was_now", kind="item",
         html=product(price='<p class="price_color"><del>£20.00</del> <ins>£15.00</ins></p>'),
         expect={"price_pence": 1500}),
    dict(id="p10_price_nbsp_thousands", kind="item",
         html=product(price='<p class="price_color">£1,299.00 </p>'), expect={"price_pence": 129900}),

    # --- ratings and stock -------------------------------------------------------------
    dict(id="p11_rating_extra_classes", kind="item",
         html=product(rating='<p class="star-rating Four pull-right"></p>'), expect={"rating": 4}),
    dict(id="p12_rating_missing_is_ok", kind="item", html=product(rating=""),
         expect={"rating": None, "title": "A Light in the Attic"}),
    dict(id="p13_only_n_left", kind="item", html=product(avail="Only 3 left in stock"),
         expect={"in_stock": True, "stock_count": 3}),
    dict(id="p14_one_available", kind="item", html=product(avail="In stock (1 available)"),
         expect={"in_stock": True, "stock_count": 1}),
    dict(id="p15_out_of_stock_caps", kind="item", html=product(avail="OUT OF STOCK"),
         expect={"in_stock": False, "stock_count": 0}),

    # --- titles and structure ----------------------------------------------------------
    dict(id="p16_entities_in_title", kind="item",
         html=product(h1="<h1>Salt &amp; Smoke: Rock &#39;n&#39; Roll</h1>"),
         expect={"title": "Salt & Smoke: Rock 'n' Roll"}),
    dict(id="p17_nested_tag_in_title", kind="item",
         html=product(h1="<h1>Night Garden <small>(Hardback)</small></h1>"),
         expect={"title": "Night Garden (Hardback)"}),
    dict(id="p18_upc_label_with_colon", kind="item", html=product(upc_label="UPC:"),
         expect={"upc": "a897fe39b1053632"}),
    dict(id="p19_upc_label_lowercase", kind="item", html=product(upc_label="upc"),
         expect={"upc": "a897fe39b1053632"}),
    dict(id="p20_no_breadcrumb", kind="item",
         html=product().replace('<li><a href="../category/books/poetry_23/index.html">Poetry</a></li>\n', "")
                       .replace('<li><a href="../category/books_1/index.html">Books</a></li>\n', ""),
         expect={"title": "A Light in the Attic"}),
    dict(id="p21_no_h1_rejected", kind="item", html=product(h1=""), expect="reject"),

    # --- listings ----------------------------------------------------------------------
    dict(id="l01_base_href", kind="listing", url="http://shop.test/index.html",
         html='<html><head><base href="http://shop.test/catalogue/"></head><body>'
              '<article class="product_pod"><h3><a href="a_1/index.html">A</a></h3></article></body></html>',
         expect={"item_urls": ["http://shop.test/catalogue/a_1/index.html"], "next_url": None}),
    dict(id="l02_rel_next_link", kind="listing", url="http://shop.test/catalogue/page-1.html",
         html='<html><body><article class="product_pod"><h3><a href="a_1/index.html">A</a></h3></article>'
              '<nav><a rel="next" href="page-2.html">Next page</a></nav></body></html>',
         expect={"next_url": "http://shop.test/catalogue/page-2.html"}),
    dict(id="l03_href_with_whitespace", kind="listing", url="http://shop.test/catalogue/page-1.html",
         html='<html><body><article class="product_pod"><h3><a href="\n  a_1/index.html  ">A</a></h3>'
              "</article></body></html>",
         expect={"item_urls": ["http://shop.test/catalogue/a_1/index.html"]}),
    dict(id="l04_query_string_next", kind="listing", url="http://shop.test/catalogue/?page=1",
         html='<html><body><ul class="pager"><li class="next"><a href="?page=2">next</a></li></ul></body></html>',
         expect={"next_url": "http://shop.test/catalogue/?page=2"}),
    dict(id="l05_javascript_link_skipped", kind="listing", url="http://shop.test/catalogue/page-1.html",
         html='<html><body><article class="product_pod"><h3><a href="javascript:void(0)">A</a></h3></article>'
              '<article class="product_pod"><h3><a href="b_2/index.html">B</a></h3></article></body></html>',
         expect={"item_urls": ["http://shop.test/catalogue/b_2/index.html"]}),
]

# (id, robots.txt text, path, expected allowed?). User agent: "web-scraper/0.1".
# Expectations from RFC 9309 sections 2.2.2 (longest match wins, Allow wins ties),
# 2.2.3 (* and $), 2.2.1 (user-agent match is case-insensitive).
ROBOTS_CASES = [
    ("r01_prefix_match", "User-agent: *\nDisallow: /admin\n", "/administrator/x", False),
    ("r02_paths_case_sensitive", "User-agent: *\nDisallow: /Admin/\n", "/admin/x", True),
    ("r03_longest_match_allow_wins", "User-agent: *\nDisallow: /\nAllow: /catalogue/\n",
     "/catalogue/page-1.html", True),
    ("r04_longest_match_disallow_wins", "User-agent: *\nAllow: /catalogue/\nDisallow: /catalogue/private/\n",
     "/catalogue/private/x.html", False),
    ("r05_wildcard_extension_end", "User-agent: *\nDisallow: /*.pdf$\n", "/files/report.pdf", False),
    ("r06_dollar_means_end", "User-agent: *\nDisallow: /*.pdf$\n", "/files/report.pdf?download=1", True),
    ("r07_wildcard_query", "User-agent: *\nDisallow: /*?sort=\n", "/catalogue/page-1.html?sort=price", False),
    ("r08_ua_case_insensitive", "User-agent: WEB-SCRAPER\nDisallow: /\n", "/x", False),
    ("r09_specific_group_only", "User-agent: web-scraper\nDisallow: /a/\n\nUser-agent: *\nDisallow: /\n",
     "/b/page.html", True),
    ("r10_grouped_user_agents", "User-agent: otherbot\nUser-agent: web-scraper\nDisallow: /x/\n",
     "/x/1", False),
    ("r11_empty_disallow", "User-agent: *\nDisallow:\n", "/anything", True),
    ("r12_comments", "User-agent: * # everyone\nDisallow: /tmp/ # scratch\n", "/tmp/a", False),
    ("r13_percent_encoding", "User-agent: *\nDisallow: /%7Ejoe/\n", "/~joe/index.html", False),
    ("r14_utf8_bom", "﻿User-agent: *\nDisallow: /\n", "/x", False),
    ("r15_crlf_line_endings", "User-agent: *\r\nDisallow: /private/\r\n", "/private/a", False),
]

# (id, robots.txt text, expected crawl delay in seconds)
CRAWL_DELAY_CASES = [
    ("c01_integer", "User-agent: *\nCrawl-delay: 5\n", 5.0),
    ("c02_decimal", "User-agent: *\nCrawl-delay: 2.5\n", 2.5),
    ("c03_specific_group", "User-agent: web-scraper\nCrawl-delay: 3\n\nUser-agent: *\nCrawl-delay: 1\n", 3.0),
]
