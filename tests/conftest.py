import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from scraper.config import Settings  # noqa: E402
from testsite.server import TestSite  # noqa: E402


@pytest.fixture
def fast():
    """Settings for tests: no politeness delay against our own local server, tiny backoff."""
    return replace(Settings(), min_delay_s=0.0, backoff_base_s=0.01, timeout_s=2.0)


@pytest.fixture
def site():
    with TestSite(seed=7, n_books=60) as s:
        yield s
