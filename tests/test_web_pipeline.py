import json
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

from parts_parser.output.filtering import FilterEntry, FilterSheet, normalize_key
from parts_parser.store import RunStore
from parts_parser.web.pipeline import run_web
from parts_parser.web.session import WebError

FIXTURES = Path(__file__).parent / "fixtures" / "insite"

_SINGLE_PAGE_PRODUCTS = {
    "products": [
        {
            "productNumber": "28001",
            "id": "prod-1",
            "urlSegment": "28001-segment",
            "attributeTypes": [],
        }
    ],
    "pagination": {"numberOfPages": 1, "page": 1},
}


class FakeSession:
    def __init__(self, responses: dict[str, dict]) -> None:
        self._responses = responses
        self.calls: list[str] = []

    def establish(self, url: str) -> None:
        pass

    def get_json(self, url: str) -> dict:
        self.calls.append(url)
        for key, value in self._responses.items():
            if key in url:
                return value
        raise WebError(f"No fixture for {url}")


def _factory(session: FakeSession):
    @contextmanager
    def _ctx():
        yield session

    return _ctx


def _filter_sheet(*raw_keys: str) -> FilterSheet:
    entries = [
        FilterEntry(raw=k, normalized=normalize_key(k), row=i + 1) for i, k in enumerate(raw_keys)
    ]
    return FilterSheet(path=Path("fake.xlsx"), column_label="column A", entries=entries)


@pytest.fixture
def search_data():
    return json.loads((FIXTURES / "search.json").read_text())


@pytest.fixture
def categories_data():
    return json.loads((FIXTURES / "categories.json").read_text())


@pytest.fixture
def catalogpages_data():
    return json.loads((FIXTURES / "catalogpages.json").read_text())


@pytest.fixture
def page1_data():
    return json.loads((FIXTURES / "products_page1.json").read_text())


@pytest.fixture
def page2_data():
    return json.loads((FIXTURES / "products_page2.json").read_text())


# --- filter mode ---


def test_filter_mode_keeps_only_normalized_equal_hits(tmp_path, search_data, catalogpages_data):
    """Near-miss products (28002-LF, 128002) are excluded; only exact-normalized match passes."""
    session = FakeSession(
        {
            "websites/current": {"id": "site-1"},
            "search": search_data,
            "catalogpages": catalogpages_data,
        }
    )
    result = run_web(
        "https://example.com/",
        store=RunStore(root=tmp_path),
        filter_sheet=_filter_sheet("28002"),
        session_factory=_factory(session),
    )
    part_nos = {r.part_no for r in result.parts}
    assert "28002" in part_nos
    assert "28002-LF" not in part_nos
    assert "128002" not in part_nos


def test_filter_mode_fetches_each_breadcrumb_once(tmp_path, search_data, catalogpages_data):
    """Two entries resolving to the same product trigger exactly one catalogpages call."""
    session = FakeSession(
        {
            "websites/current": {"id": "site-1"},
            "search": search_data,
            "catalogpages": catalogpages_data,
        }
    )
    run_web(
        "https://example.com/",
        store=RunStore(root=tmp_path),
        filter_sheet=_filter_sheet("28002", "28002"),
        session_factory=_factory(session),
    )
    breadcrumb_calls = [c for c in session.calls if "catalogpages" in c]
    assert len(breadcrumb_calls) == 1


# --- crawl mode ---


def test_crawl_mode_makes_no_catalogpages_calls(tmp_path, categories_data, page1_data, page2_data):
    session = FakeSession(
        {
            "websites/current": {"id": "site-1"},
            "categories": categories_data,
            "&page=1": page1_data,
            "&page=2": page2_data,
        }
    )
    run_web(
        "https://example.com/",
        store=RunStore(root=tmp_path),
        session_factory=_factory(session),
    )
    assert not any("catalogpages" in c for c in session.calls)


def test_crawl_mode_fills_category_from_tree(tmp_path, categories_data, page1_data, page2_data):
    session = FakeSession(
        {
            "websites/current": {"id": "site-1"},
            "categories": categories_data,
            "&page=1": page1_data,
            "&page=2": page2_data,
        }
    )
    result = run_web(
        "https://example.com/",
        store=RunStore(root=tmp_path),
        session_factory=_factory(session),
    )
    assert result.parts
    for record in result.parts:
        assert record.category == "Brass Fittings"
        assert record.subcategory == "Pipe"
        assert record.series in ("90-Deg Female Elbow", "Coupling")


# --- unsupported site ---


def test_unsupported_site_raises_readable_web_error(tmp_path):
    session = FakeSession({})  # no websites/current → detect returns False
    with pytest.raises(WebError, match="isn't supported"):
        run_web(
            "https://example.com/",
            store=RunStore(root=tmp_path),
            session_factory=_factory(session),
        )


# --- cached config / probe ---


def test_cached_matching_probe_skips_detect(tmp_path, categories_data):
    store = RunStore(root=tmp_path)
    store.save_site_config(
        "example.com",
        {
            "platform": "insite",
            "probe": {"product_id": "prod-1", "part_no": "28001"},
        },
    )
    session = FakeSession(
        {
            "products/prod-1": _SINGLE_PAGE_PRODUCTS["products"][0],
            "categories": categories_data,
            "&page=1": _SINGLE_PAGE_PRODUCTS,
        }
    )
    run_web(
        "https://example.com/",
        store=store,
        session_factory=_factory(session),
    )
    assert not any("websites/current" in c for c in session.calls)


def test_cached_mismatched_probe_re_detects(tmp_path, categories_data):
    store = RunStore(root=tmp_path)
    store.save_site_config(
        "example.com",
        {
            "platform": "insite",
            "probe": {"product_id": "prod-1", "part_no": "28001"},
        },
    )
    # Probe returns a different part_no → cache invalidated → detect runs
    session = FakeSession(
        {
            "products/prod-1": {
                "productNumber": "WRONG",
                "id": "prod-1",
                "urlSegment": "s",
                "attributeTypes": [],
            },
            "websites/current": {"id": "site-1"},
            "categories": categories_data,
            "&page=1": _SINGLE_PAGE_PRODUCTS,
        }
    )
    run_web(
        "https://example.com/",
        store=store,
        session_factory=_factory(session),
    )
    assert any("websites/current" in c for c in session.calls)


# --- record_run ---


def test_record_run_filter_mode(tmp_path, search_data, catalogpages_data):
    store = RunStore(root=tmp_path)
    session = FakeSession(
        {
            "websites/current": {"id": "site-1"},
            "search": search_data,
            "catalogpages": catalogpages_data,
        }
    )
    run_web(
        "https://example.com/",
        store=store,
        filter_sheet=_filter_sheet("28002"),
        session_factory=_factory(session),
    )
    runs = store.list_runs()
    assert len(runs) == 1
    assert runs[0]["mode"] == "filter"
    assert isinstance(runs[0]["parts"], int)


def test_record_run_crawl_mode(tmp_path, categories_data, page1_data, page2_data):
    store = RunStore(root=tmp_path)
    session = FakeSession(
        {
            "websites/current": {"id": "site-1"},
            "categories": categories_data,
            "&page=1": page1_data,
            "&page=2": page2_data,
        }
    )
    run_web(
        "https://example.com/",
        store=store,
        session_factory=_factory(session),
    )
    runs = store.list_runs()
    assert len(runs) == 1
    assert runs[0]["mode"] == "crawl"
    assert runs[0]["parts"] > 0


# --- cancel ---


def test_cancel_aborts_with_web_error(tmp_path, categories_data):
    session = FakeSession(
        {
            "websites/current": {"id": "site-1"},
            "categories": categories_data,
            "&page=1": _SINGLE_PAGE_PRODUCTS,
        }
    )
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(WebError, match="Cancelled"):
        run_web(
            "https://example.com/",
            store=RunStore(root=tmp_path),
            cancel=cancel,
            session_factory=_factory(session),
        )
