"""Turn the text a human sees on a page into typed values.

Each function takes messy text and returns a clean value or None. None means
"couldn't read it"; the profile decides whether that's fatal for the item.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

RATING_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}

# 1,234.56 | 1234.5 | 12 -- the number part of a price
_PRICE_RE = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?")
# '(22 available)' on books.toscrape.com; 'Only 3 left' on many other shops
_COUNT_RE = re.compile(r"(\d+)\s+(?:available|left)", re.IGNORECASE)


def clean_text(text: str | None) -> str | None:
    """Collapse runs of whitespace (newlines, tabs, non-breaking spaces) into one space."""
    if text is None:
        return None
    text = unicodedata.normalize("NFC", text)
    text = " ".join(text.split())
    return text or None


def parse_price_pence(text: str | None) -> int | None:
    """'£51.77' -> 5177. 'Â£1,234.5' -> 123450. Money is whole pence, never a float."""
    if not text:
        return None
    match = _PRICE_RE.search(text)
    if not match:
        return None
    whole, frac = match.group(1).replace(",", ""), match.group(2) or "0"
    try:
        return int(Decimal(f"{whole}.{frac}") * 100)
    except InvalidOperation:
        return None


def parse_rating(classes: list[str] | None) -> int | None:
    """['star-rating', 'Three'] -> 3. The rating lives in a CSS class, not in text."""
    for cls in classes or []:
        value = RATING_WORDS.get(cls.lower())
        if value is not None:
            return value
    return None


def parse_availability(text: str | None) -> tuple[bool | None, int | None]:
    """'In stock (22 available)' -> (True, 22); 'Only 3 left in stock' -> (True, 3);
    'Out of stock' -> (False, 0)."""
    text = clean_text(text)
    if not text:
        return None, None
    lowered = text.lower()
    if "out of stock" in lowered:
        return False, 0
    if "in stock" in lowered:
        match = _COUNT_RE.search(text)
        return True, int(match.group(1)) if match else None
    return None, None
