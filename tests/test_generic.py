from pathlib import Path
from threading import Event

import pytest

from parts_parser.web.generic import (
    iter_crawl_product_urls,
    iter_sitemap_product_urls,
    normalize_url,
    parse_product_page,
    search_product_urls,
)
from parts_parser.web.session import WebError
from parts_parser.web.site_config import SiteConfig


FIXTURES = Path(__file__).parent / "fixtures" / "generic"
BASE = "https://example.test"


class FakeSession:
    def __init__(self, responses):
        self.responses = responses
        self.html_calls = []
        self.text_calls = []

    def _response(self, url):
        for url_substring, text in self.responses.items():
            if url_substring in url:
                return text
        raise AssertionError(f"Unexpected fake request: {url}")

    def get_html(self, url):
        self.html_calls.append(url)
        return self._response(url)

    def get_text(self, url):
        self.text_calls.append(url)
        return self._response(url)


@pytest.fixture
def product_html():
    return (FIXTURES / "product.html").read_text()


@pytest.fixture
def category_html():
    return (FIXTURES / "category.html").read_text()


@pytest.fixture
def sitemap_xml():
    return (FIXTURES / "sitemap.xml").read_text()


@pytest.fixture
def sitemap_index_xml():
    return (FIXTURES / "sitemap_index.xml").read_text()


@pytest.fixture
def generic_config():
    return SiteConfig(
        platform="generic",
        selectors={
            "part_no": ".sku",
            "breadcrumb": ".breadcrumb > *",
            "attributes": {"row": ".specs tr", "label": "th", "value": "td"},
        },
        enumeration={
            "strategy": "category_crawl",
            "start_urls": [f"{BASE}/category/fittings"],
            "product_link_pattern": r"/product/",
            "category_link_pattern": r"/category/elbows$",
            "pagination_param": "page",
        },
        search_url_template=f"{BASE}/search?q={{query}}",
        page_budget=2,
    )


def test_normalize_url_resolves_relative_url_and_strips_fragment_and_facets():
    assert (
        normalize_url(
            "/product/gx-100-a?color=brass#details",
            BASE,
            pagination_param="page",
        )
        == f"{BASE}/product/gx-100-a"
    )


def test_normalize_url_keeps_only_pagination_parameter():
    assert (
        normalize_url(
            "/category/fittings?color=brass&page=2&size=50#products",
            BASE,
            pagination_param="page",
        )
        == f"{BASE}/category/fittings?page=2"
    )


def test_normalize_url_rejects_off_domain_links():
    assert (
        normalize_url(
            "https://elsewhere.example/product/gx-100-a",
            BASE,
            pagination_param=None,
        )
        is None
    )


def test_parse_product_page_preserves_part_number_and_maps_page_fields(
    product_html, generic_config
):
    record = parse_product_page(product_html, f"{BASE}/product/gx-100-a", generic_config)

    assert record is not None
    assert record.part_no == "GX-100-A"
    assert record.url == f"{BASE}/product/gx-100-a"
    assert record.category == "Fittings"
    assert record.subcategory == "Elbows"
    assert record.series == ""
    assert record.attributes == {"Material": "Brass", "Connection": "Female NPT"}


def test_parse_product_page_returns_none_when_part_number_selector_misses(
    product_html, generic_config
):
    generic_config.selectors["part_no"] = ".not-present"

    assert parse_product_page(product_html, f"{BASE}/product/gx-100-a", generic_config) is None


def test_sitemap_enumerator_filters_products_and_deduplicates(sitemap_xml):
    session = FakeSession({"sitemap.xml": sitemap_xml})
    config = SiteConfig(
        platform="generic",
        selectors={"part_no": ".sku"},
        enumeration={
            "strategy": "sitemap",
            "sitemap_url": f"{BASE}/sitemap.xml",
            "product_url_pattern": r"/product/",
        },
    )

    assert list(iter_sitemap_product_urls(session, config, BASE)) == [
        f"{BASE}/product/gx-100-a",
        f"{BASE}/product/gx-200-b",
    ]


def test_sitemap_index_enumerator_reads_one_nested_urlset(sitemap_xml, sitemap_index_xml):
    session = FakeSession({"sitemap_index.xml": sitemap_index_xml, "sitemap.xml": sitemap_xml})
    config = SiteConfig(
        platform="generic",
        selectors={"part_no": ".sku"},
        enumeration={
            "strategy": "sitemap",
            "sitemap_url": f"{BASE}/sitemap_index.xml",
            "product_url_pattern": r"/product/",
        },
    )

    assert list(iter_sitemap_product_urls(session, config, BASE)) == [
        f"{BASE}/product/gx-100-a",
        f"{BASE}/product/gx-200-b",
    ]
    assert session.text_calls == [f"{BASE}/sitemap_index.xml", f"{BASE}/sitemap.xml"]


def test_crawl_enumerator_deduplicates_and_excludes_off_domain_and_facets(
    category_html, generic_config
):
    session = FakeSession({"example.test": category_html})

    urls = list(
        iter_crawl_product_urls(session, generic_config, BASE, lambda message, fraction: None, None)
    )

    assert urls == [
        f"{BASE}/product/gx-100-a",
        f"{BASE}/product/gx-200-b",
        f"{BASE}/product/gx-300-c",
    ]
    assert all("elsewhere.example" not in url for url in session.html_calls)
    assert all("color=" not in url for url in session.html_calls)
    assert len(session.html_calls) == generic_config.page_budget
    assert len(session.html_calls) == len(set(session.html_calls))
    assert f"{BASE}/category/fittings?page=2" in session.html_calls


def test_crawl_enumerator_never_fetches_more_than_page_budget(category_html, generic_config):
    generic_config.page_budget = 1
    session = FakeSession({"example.test": category_html})

    list(
        iter_crawl_product_urls(session, generic_config, BASE, lambda message, fraction: None, None)
    )

    assert session.html_calls == [f"{BASE}/category/fittings"]


def test_crawl_enumerator_checks_cancel_between_fetches(category_html, generic_config):
    cancel = Event()
    session = FakeSession({"example.test": category_html})

    def progress(message, fraction):
        cancel.set()

    with pytest.raises(WebError, match="Cancelled"):
        list(iter_crawl_product_urls(session, generic_config, BASE, progress, cancel))

    assert session.html_calls == [f"{BASE}/category/fittings"]


def test_search_product_urls_encodes_query_and_returns_normalized_deduplicated_links(
    category_html, generic_config
):
    session = FakeSession({"/search": category_html})

    urls = search_product_urls(session, generic_config, BASE, "GX 100/A")

    assert session.html_calls == [f"{BASE}/search?q=GX%20100/A"]
    assert urls == [
        f"{BASE}/product/gx-100-a",
        f"{BASE}/product/gx-200-b",
        f"{BASE}/product/gx-300-c",
    ]
