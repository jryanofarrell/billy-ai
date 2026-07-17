import json
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest

from parts_parser.output.filtering import FilterEntry, FilterSheet, normalize_key
from parts_parser.store import RunStore
from parts_parser.web import pipeline as pipeline_module
from parts_parser.web.discovery import ConfigValidation
from parts_parser.web.generic import PartRecord as GenericPartRecord
from parts_parser.web.pipeline import resolve_site_config, run_generic, run_web
from parts_parser.web.session import WebError
from parts_parser.web.site_config import SiteConfig

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
    def __init__(
        self,
        responses: dict[str, dict] | None = None,
        *,
        html: dict[str, str] | None = None,
        text: dict[str, str] | None = None,
    ) -> None:
        self._responses = responses or {}
        self._html = html or {}
        self._text = text or {}
        self.calls: list[str] = []

    def establish(self, url: str) -> None:
        pass

    def get_json(self, url: str) -> dict:
        self.calls.append(url)
        for key, value in self._responses.items():
            if key in url:
                return value
        raise WebError(f"No fixture for {url}")

    def get_html(self, url: str) -> str:
        self.calls.append(url)
        if url in self._html:
            return self._html[url]
        raise WebError(f"No fixture for {url}")

    def get_text(self, url: str) -> str:
        self.calls.append(url)
        if url in self._text:
            return self._text[url]
        raise WebError(f"No fixture for {url}")


class ListingFailureSession(FakeSession):
    def __init__(
        self,
        responses: dict[str, dict],
        *,
        successful_listing_calls: int,
        cancel: threading.Event | None = None,
    ) -> None:
        super().__init__(responses)
        self.successful_listing_calls = successful_listing_calls
        self.listing_calls = 0
        self.cancel = cancel

    def get_json(self, url: str) -> dict:
        if "/api/v2/products?categoryId=" in url:
            if self.listing_calls >= self.successful_listing_calls:
                raise WebError("The catalog stopped responding.")
            self.listing_calls += 1
            response = super().get_json(url)
            if self.cancel is not None:
                self.cancel.set()
            return response
        return super().get_json(url)


class CancelAfterProductSession(FakeSession):
    def __init__(self, *args, cancel: threading.Event, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.cancel = cancel

    def get_html(self, url: str) -> str:
        html = super().get_html(url)
        if "/products/" in url:
            self.cancel.set()
        return html


class FakeLLM:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses
        self.calls = 0

    def complete_json(self, *, system: str, user: str) -> dict:
        response = self.responses[self.calls]
        self.calls += 1
        return response


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


def _generic_config(**changes) -> SiteConfig:
    values = {
        "platform": "generic",
        "enumeration": {
            "strategy": "sitemap",
            "sitemap_url": "https://example.com/sitemap.xml",
            "product_url_pattern": r"/products/",
        },
        "selectors": {"part_no": ".part-number"},
    }
    values.update(changes)
    return SiteConfig(**values)


def _cached_part(part_no: str, *, attributes: dict[str, str] | None = None) -> dict:
    return {
        "part_no": part_no,
        "category": "Synthetic",
        "subcategory": "",
        "series": "",
        "description": "",
        "attributes": attributes or {},
    }


def _save_cache(
    store: RunStore,
    parts: list[dict],
    *,
    complete: bool = True,
    progress: list[str] | None = None,
    fetched_at: str = "2026-01-01T00:00:00+00:00",
) -> None:
    payload = {
        "fetched_at": fetched_at,
        "crawl_seconds": 120.0,
        "complete": complete,
        "parts": parts,
    }
    if progress is not None:
        payload["progress"] = progress
    store.save_web_cache("example.com", payload)


def _generic_sitemap_fixture() -> tuple[list[str], str, dict[str, str]]:
    urls = [f"https://example.com/products/P-{index}" for index in range(1, 4)]
    sitemap = "<urlset>" + "".join(f"<url><loc>{url}</loc></url>" for url in urls) + "</urlset>"
    html = {url: f'<div class="part-number">P-{index}</div>' for index, url in enumerate(urls, 1)}
    return urls, sitemap, html


def _discovery_fixture() -> tuple[FakeSession, FakeLLM]:
    urls = [f"https://example.com/products/P-{i}" for i in range(1, 6)]
    sitemap = "<urlset>" + "".join(f"<url><loc>{url}</loc></url>" for url in urls) + "</urlset>"
    html = {"https://example.com": f'<a href="{urls[0]}">sample</a>'}
    html.update({url: f'<div class="part-number">P-{i}</div>' for i, url in enumerate(urls, 1)})
    session = FakeSession(
        html=html,
        text={"https://example.com/sitemap.xml": sitemap},
    )
    llm = FakeLLM(
        [
            {
                "product_url_example": urls[0],
                "product_url_pattern": r"/products/",
                "category_link_pattern": None,
                "pagination_param": None,
                "search_url_template": None,
                "strategy": "sitemap",
            },
            {"part_no": ".part-number", "breadcrumb": None, "attributes": None},
        ]
    )
    return session, llm


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


def test_cache_hit_with_hook_returns_parts_report_without_constructing_session(tmp_path):
    store = RunStore(root=tmp_path)
    _save_cache(store, [_cached_part("AB- 123"), _cached_part("OTHER")])
    choices = []

    def forbidden_factory():
        raise AssertionError("BrowserSession must not be constructed for cache reuse")

    result = run_web(
        "https://WWW.Example.COM/catalog",
        store=store,
        filter_sheet=_filter_sheet("AB123", "MISSING"),
        session_factory=forbidden_factory,
        choose_cached=lambda info: choices.append(info) or True,
    )

    assert [part.part_no for part in result.parts] == ["AB- 123"]
    assert result.match_report is not None
    assert [item.match_type for item in result.match_report.results] == [
        "normalized",
        "unmatched",
    ]
    assert choices[0].part_count == 2
    assert choices[0].complete is True
    assert choices[0].fetched_at == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert choices[0].estimated_crawl_seconds == 120.0
    assert store.list_runs()[0]["data_source"] == "cache"


def test_cache_hit_without_hook_reuses_cache(tmp_path):
    store = RunStore(root=tmp_path)
    _save_cache(store, [_cached_part("SAVED-1")])

    def forbidden_factory():
        raise AssertionError("headless cache reuse must not construct a session")

    result = run_web("https://example.com", store=store, session_factory=forbidden_factory)

    assert [part.part_no for part in result.parts] == ["SAVED-1"]


def test_incomplete_cache_reuse_fetches_only_remaining_units_and_upgrades_cache(
    tmp_path,
):
    store = RunStore(root=tmp_path)
    store.save_site_config("example.com", _generic_config().to_dict())
    urls, sitemap, html = _generic_sitemap_fixture()
    _save_cache(
        store,
        [_cached_part("P-1")],
        complete=False,
        progress=[urls[0]],
    )
    session = FakeSession(
        html={urls[1]: html[urls[1]], urls[2]: html[urls[2]]},
        text={"https://example.com/sitemap.xml": sitemap},
    )

    result = run_web(
        "https://example.com",
        store=store,
        session_factory=_factory(session),
        choose_cached=lambda info: True,
    )

    assert urls[0] not in session.calls
    assert [url for url in urls if url in session.calls] == urls[1:]
    assert {part.part_no for part in result.parts} == {"P-1", "P-2", "P-3"}
    assert result.progress == urls
    cache = store.get_web_cache("example.com")
    assert cache is not None
    assert cache["complete"] is True
    assert "progress" not in cache
    assert {part["part_no"] for part in cache["parts"]} == {"P-1", "P-2", "P-3"}
    assert store.list_runs()[0]["data_source"] == "cache+resume"


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


def test_small_filter_search_path_does_not_write_web_cache(
    tmp_path, search_data, catalogpages_data
):
    store = RunStore(root=tmp_path)
    session = FakeSession(
        {
            "websites/current": {"id": "site-1"},
            "search": search_data,
            "catalogpages": catalogpages_data,
        }
    )

    run_web(
        "https://example.com",
        store=store,
        filter_sheet=_filter_sheet("28002"),
        session_factory=_factory(session),
    )

    assert store.get_web_cache("example.com") is None


def test_large_filter_crawls_and_writes_complete_cache(
    tmp_path, categories_data, page1_data, page2_data
):
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
        "https://example.com",
        store=store,
        filter_sheet=_filter_sheet(*(f"SYNTH-{index}" for index in range(501))),
        session_factory=_factory(session),
    )

    cache = store.get_web_cache("example.com")
    assert cache is not None
    assert cache["complete"] is True
    assert cache["parts"]
    assert not any("?search=" in call for call in session.calls)


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


def test_completed_crawl_writes_complete_cache(tmp_path, categories_data, page1_data, page2_data):
    store = RunStore(root=tmp_path)
    session = FakeSession(
        {
            "websites/current": {"id": "site-1"},
            "categories": categories_data,
            "&page=1": page1_data,
            "&page=2": page2_data,
        }
    )

    result = run_web("https://example.com", store=store, session_factory=_factory(session))

    cache = store.get_web_cache("example.com")
    assert cache is not None
    assert cache["complete"] is True
    assert [part["part_no"] for part in cache["parts"]] == [part.part_no for part in result.parts]


# --- unsupported site ---


def test_unreadable_unknown_site_raises_readable_web_error(tmp_path):
    session = FakeSession(html={"https://example.com": "<p>Catalog</p>"})
    llm = FakeLLM([{}])
    with pytest.raises(WebError, match="Couldn't figure out this website"):
        run_web(
            "https://example.com/",
            store=RunStore(root=tmp_path),
            session_factory=_factory(session),
            llm_factory=lambda: llm,
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
    assert runs[0]["data_source"] == "live"


def test_crawl_error_after_collection_returns_partial_and_records_reason(tmp_path, categories_data):
    store = RunStore(root=tmp_path)
    _save_cache(store, [_cached_part("OLD")], complete=True)
    old_cache = store.get_web_cache("example.com")
    session = ListingFailureSession(
        {
            "websites/current": {"id": "site-1"},
            "categories": categories_data,
            "&page=1": _SINGLE_PAGE_PRODUCTS,
        },
        successful_listing_calls=1,
    )

    result = run_web(
        "https://example.com/",
        store=store,
        session_factory=_factory(session),
        choose_cached=lambda info: False,
    )

    assert [part.part_no for part in result.parts] == ["28001"]
    assert result.stopped_early is not None
    assert "Coupling" in result.stopped_early
    assert store.list_runs()[0]["stopped_early"] == result.stopped_early
    cache = store.get_web_cache("example.com")
    assert cache is not None
    assert cache["complete"] is False
    assert [part["part_no"] for part in cache["parts"]] == ["28001"]
    assert cache["fetched_at"] != old_cache["fetched_at"]


def test_refresh_replaces_cache_and_records_live_source(
    tmp_path, categories_data, page1_data, page2_data
):
    store = RunStore(root=tmp_path)
    _save_cache(store, [_cached_part("OLD")])
    old_fetched_at = store.get_web_cache("example.com")["fetched_at"]
    session = FakeSession(
        {
            "websites/current": {"id": "site-1"},
            "categories": categories_data,
            "&page=1": page1_data,
            "&page=2": page2_data,
        }
    )

    result = run_web(
        "https://example.com",
        store=store,
        session_factory=_factory(session),
        choose_cached=lambda info: False,
    )

    cache = store.get_web_cache("example.com")
    assert cache["fetched_at"] != old_fetched_at
    assert datetime.fromisoformat(cache["fetched_at"]) <= datetime.now(timezone.utc)
    assert [part["part_no"] for part in cache["parts"]] == [part.part_no for part in result.parts]
    assert store.list_runs()[0]["data_source"] == "live"


def test_resumed_crawl_stopped_again_unions_progress_and_preserves_parts(tmp_path):
    store = RunStore(root=tmp_path)
    store.save_site_config("example.com", _generic_config().to_dict())
    urls, sitemap, html = _generic_sitemap_fixture()
    prior_parts = [_cached_part("P-1")]
    _save_cache(store, prior_parts, complete=False, progress=[urls[0]])
    cancel = threading.Event()
    session = CancelAfterProductSession(
        html={urls[1]: html[urls[1]]},
        text={"https://example.com/sitemap.xml": sitemap},
        cancel=cancel,
    )

    result = run_web(
        "https://example.com",
        store=store,
        cancel=cancel,
        session_factory=_factory(session),
        choose_cached=lambda info: True,
    )

    assert urls[0] not in session.calls
    assert urls[1] in session.calls
    assert urls[2] not in session.calls
    assert result.stopped_early is not None
    assert result.progress == urls[:2]
    assert {part.part_no for part in result.parts} == {"P-1", "P-2"}
    cache = store.get_web_cache("example.com")
    assert cache is not None
    assert cache["complete"] is False
    assert cache["progress"] == urls[:2]
    assert {part["part_no"] for part in cache["parts"]}.issuperset(
        part["part_no"] for part in prior_parts
    )
    assert store.list_runs()[0]["data_source"] == "cache+resume"


def test_get_fresh_ignores_partial_cache_progress_and_fetches_every_unit(tmp_path):
    store = RunStore(root=tmp_path)
    store.save_site_config("example.com", _generic_config().to_dict())
    urls, sitemap, html = _generic_sitemap_fixture()
    _save_cache(
        store,
        [_cached_part("STALE")],
        complete=False,
        progress=urls[:2],
    )
    session = FakeSession(
        html=html,
        text={"https://example.com/sitemap.xml": sitemap},
    )

    result = run_web(
        "https://example.com",
        store=store,
        session_factory=_factory(session),
        choose_cached=lambda info: False,
    )

    assert [url for url in urls if url in session.calls] == urls
    assert {part.part_no for part in result.parts} == {"P-1", "P-2", "P-3"}
    assert "STALE" not in {part.part_no for part in result.parts}
    assert result.progress == urls
    cache = store.get_web_cache("example.com")
    assert cache is not None
    assert cache["complete"] is True
    assert "progress" not in cache
    assert store.list_runs()[0]["data_source"] == "live"


def test_drift_notice_only_on_complete_to_complete_refresh(tmp_path, monkeypatch):
    def collect_ten(*args, records, **kwargs):
        records.extend(
            GenericPartRecord(f"NEW-{index}", f"https://example.com/products/{index}")
            for index in range(10)
        )
        return records

    monkeypatch.setattr(
        pipeline_module,
        "resolve_site_config",
        lambda *args, **kwargs: _generic_config(),
    )
    monkeypatch.setattr(pipeline_module, "run_generic", collect_ten)

    for old_complete, expect_notice in ((True, True), (False, False)):
        store = RunStore(root=tmp_path / str(old_complete))
        _save_cache(
            store,
            [_cached_part(f"OLD-{index}") for index in range(100)],
            complete=old_complete,
        )
        result = run_web(
            "https://example.com",
            store=store,
            session_factory=_factory(FakeSession()),
            choose_cached=lambda info: False,
        )

        assert bool(result.notices) is expect_notice
        assert len(store.get_web_cache("example.com")["parts"]) == 10


def test_crawl_error_before_collection_still_raises(tmp_path, categories_data):
    session = ListingFailureSession(
        {
            "websites/current": {"id": "site-1"},
            "categories": categories_data,
        },
        successful_listing_calls=0,
    )

    with pytest.raises(WebError, match="catalog stopped responding"):
        run_web(
            "https://example.com/",
            store=RunStore(root=tmp_path),
            session_factory=_factory(session),
        )


# --- generic discovery pipeline ---


def test_unknown_site_discovers_validates_runs_and_caches_with_probe(tmp_path):
    store = RunStore(root=tmp_path)
    session, llm = _discovery_fixture()

    result = run_web(
        "https://example.com/",
        store=store,
        session_factory=_factory(session),
        llm_factory=lambda: llm,
        confirm=lambda sample: len(sample) == 5,
    )

    assert [part.part_no for part in result.parts] == [f"P-{i}" for i in range(1, 6)]
    assert llm.calls == 2
    saved = store.get_site_config("example.com")
    assert saved is not None
    assert saved["probe"] == {
        "url": "https://example.com/products/P-1",
        "part_no": "P-1",
    }

    second = run_web(
        "https://example.com/",
        store=store,
        session_factory=_factory(session),
        llm_factory=lambda: llm,
    )

    assert len(second.parts) == 5
    assert llm.calls == 2


def test_resolve_site_config_cached_generic_probe_mismatch_rediscovers(tmp_path, monkeypatch):
    store = RunStore(root=tmp_path)
    cached = _generic_config(probe={"url": "https://example.com/products/old", "part_no": "OLD"})
    store.save_site_config("example.com", cached.to_dict())
    session = FakeSession(
        html={"https://example.com/products/old": '<div class="part-number">CHANGED</div>'}
    )
    discovered = _generic_config()
    discoveries = []
    monkeypatch.setattr(pipeline_module.insite, "detect", lambda session, base: False)
    monkeypatch.setattr(
        pipeline_module,
        "discover_site_config",
        lambda *args: discoveries.append(args) or discovered,
    )
    sample = GenericPartRecord("NEW", "https://example.com/products/new")
    monkeypatch.setattr(
        pipeline_module,
        "validate_site_config",
        lambda *args: ConfigValidation([sample], []),
    )

    resolved = resolve_site_config(
        session,
        store,
        "example.com",
        "https://example.com",
        llm_factory=lambda: FakeLLM([]),
        confirm=None,
        progress=lambda message, fraction: None,
    )

    assert resolved is discovered
    assert len(discoveries) == 1
    assert store.get_site_config("example.com")["probe"]["part_no"] == "NEW"


def test_resolve_site_config_retries_failed_gate_once_then_raises(tmp_path, monkeypatch):
    discoveries = []
    monkeypatch.setattr(pipeline_module.insite, "detect", lambda session, base: False)
    monkeypatch.setattr(
        pipeline_module,
        "discover_site_config",
        lambda *args: discoveries.append(args) or _generic_config(),
    )
    monkeypatch.setattr(
        pipeline_module,
        "validate_site_config",
        lambda *args: ConfigValidation([], ["not enough sample parts"]),
    )

    with pytest.raises(WebError, match="Couldn't reliably read this website"):
        resolve_site_config(
            FakeSession(),
            RunStore(root=tmp_path),
            "example.com",
            "https://example.com",
            llm_factory=lambda: FakeLLM([]),
            confirm=None,
            progress=lambda message, fraction: None,
        )

    assert len(discoveries) == 2


def test_resolve_site_config_declined_preview_does_not_cache(tmp_path, monkeypatch):
    store = RunStore(root=tmp_path)
    sample = GenericPartRecord("P-1", "https://example.com/products/P-1")
    monkeypatch.setattr(pipeline_module.insite, "detect", lambda session, base: False)
    monkeypatch.setattr(pipeline_module, "discover_site_config", lambda *args: _generic_config())
    monkeypatch.setattr(
        pipeline_module,
        "validate_site_config",
        lambda *args: ConfigValidation([sample], []),
    )

    with pytest.raises(WebError, match="Cancelled after preview"):
        resolve_site_config(
            FakeSession(),
            store,
            "example.com",
            "https://example.com",
            llm_factory=lambda: FakeLLM([]),
            confirm=lambda parts: False,
            progress=lambda message, fraction: None,
        )

    assert store.get_site_config("example.com") is None


def test_run_generic_search_template_keeps_only_normalized_equal_hits():
    config = _generic_config(search_url_template="https://example.com/search?q={query}")
    session = FakeSession(
        html={
            "https://example.com/search?q=AB-12": (
                '<a href="/products/exact">exact</a><a href="/products/near">near</a>'
            ),
            "https://example.com/products/exact": '<span class="part-number">AB 12</span>',
            "https://example.com/products/near": '<span class="part-number">AB-123</span>',
        }
    )

    records = run_generic(
        session,
        config,
        "https://example.com",
        filter_sheet=_filter_sheet("AB-12"),
        progress=lambda message, fraction: None,
        cancel=None,
    )

    assert [record.part_no for record in records] == ["AB 12"]


def test_run_generic_crawl_skips_pages_without_part_number():
    config = _generic_config(
        enumeration={
            "strategy": "category_crawl",
            "start_urls": ["https://example.com/catalog"],
            "product_link_pattern": r"/products/",
        }
    )
    session = FakeSession(
        html={
            "https://example.com/catalog": (
                '<a href="/products/good">good</a><a href="/products/missing">missing</a>'
            ),
            "https://example.com/products/good": '<span class="part-number">GOOD-1</span>',
            "https://example.com/products/missing": "<p>No number here</p>",
        }
    )

    records = run_generic(
        session,
        config,
        "https://example.com",
        filter_sheet=None,
        progress=lambda message, fraction: None,
        cancel=None,
    )

    assert [record.part_no for record in records] == ["GOOD-1"]


# --- cancel ---


def test_cancel_after_collection_returns_partial_result(tmp_path, categories_data):
    cancel = threading.Event()
    session = ListingFailureSession(
        {
            "websites/current": {"id": "site-1"},
            "categories": categories_data,
            "&page=1": _SINGLE_PAGE_PRODUCTS,
        },
        successful_listing_calls=1,
        cancel=cancel,
    )

    result = run_web(
        "https://example.com/",
        store=RunStore(root=tmp_path),
        cancel=cancel,
        session_factory=_factory(session),
    )

    assert [part.part_no for part in result.parts] == ["28001"]
    assert result.stopped_early is not None
    assert "Cancelled" in result.stopped_early
