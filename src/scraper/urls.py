"""URL helpers: one canonical spelling per page, and the 'is this in scope?' check."""

from __future__ import annotations

from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit

DEFAULT_PORTS = {"http": 80, "https": 443}


def normalize(url: str, base: str | None = None) -> str:
    """Resolve `url` against `base` and return one canonical spelling of it.

    Two spellings of the same page must become one string, or the visited-set
    can't spot that we've been there:
      HTTP://Books.Example:80/a/../b/#top  ->  http://books.example/b/
    """
    # Browsers drop whitespace around an href and tabs/newlines inside it (WHATWG URL spec)
    url = url.strip().replace("\t", "").replace("\n", "").replace("\r", "")
    if base is not None:
        url = urljoin(base, url)  # "../page-2.html" + page URL -> absolute URL
    url, _fragment = urldefrag(url)  # "#reviews" is the same page
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    netloc = host if port in (None, DEFAULT_PORTS.get(scheme)) else f"{host}:{port}"
    # urljoin against the root resolves "/a/../b/" -> "/b/" even when no base was given
    path = urlsplit(urljoin("http://x/", parts.path or "/")).path
    return urlunsplit((scheme, netloc, path, parts.query, ""))


def host_of(url: str) -> str:
    """'http://a.example:8080/x' -> 'a.example:8080' (the rate limiter's key)."""
    return urlsplit(url).netloc.lower()


def in_scope(url: str, allowed_host: str) -> bool:
    """Only http(s), and only the host we were told to crawl.

    Blocks file://, javascript:, and redirects to other hosts, including the
    classic SSRF targets like http://169.254.169.254/ (cloud metadata).
    """
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and parts.netloc.lower() == allowed_host
