import pytest

from parts_parser.web import discovery
from parts_parser.web.discovery import discover_site_config, validate_site_config
from parts_parser.web.generic import PartRecord
from parts_parser.web.session import WebError
from parts_parser.web.site_config import SiteConfig


BASE = "https://example.test"


class FakeLLM:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def complete_json(self, *, system, user, max_output_tokens=4096):
        self.calls.append({"system": system, "user": user})
        return self.responses.pop(0)


class FakeSession:
    def __init__(self, *, html=None, text=None):
        self.html = html or {}
        self.text = text or {}
        self.html_calls = []
        self.text_calls = []

    @staticmethod
    def _get(responses, url):
        if url not in responses:
            raise WebError(f"No fake response for {url}")
        response = responses[url]
        if isinstance(response, Exception):
            raise response
        return response

    def get_html(self, url):
        self.html_calls.append(url)
        return self._get(self.html, url)

    def get_text(self, url):
        self.text_calls.append(url)
        return self._get(self.text, url)


def _crawl_config(*, part_selector=".sku"):
    return SiteConfig(
        platform="generic",
        enumeration={
            "strategy": "category_crawl",
            "start_urls": [BASE],
            "product_link_pattern": r"/product/",
        },
        selectors={"part_no": part_selector},
    )


def _validation_session(count=5, *, parseable=None):
    parseable = set(range(count)) if parseable is None else set(parseable)
    urls = [f"{BASE}/product/{index}" for index in range(count)]
    home = "".join(f'<a href="{url}">Product</a>' for url in urls)
    html = {BASE: home}
    for index, url in enumerate(urls):
        if index in parseable:
            html[url] = f'<div class="sku">PN-{index}</div>'
        else:
            html[url] = "<p>Product details unavailable</p>"
    return FakeSession(html=html), urls


def test_sample_html_strips_scripts_and_styles_and_truncates():
    html = "<p>keep</p><script>secret()</script><style>.hidden{}</style><p>tail</p>"

    sample = discovery._sample_html(html, limit=20)

    assert sample == "<p>keep</p> <p>tail"
    assert "secret" not in sample
    assert "hidden" not in sample


def test_find_sitemap_reads_sitemap_directive_from_robots_txt():
    session = FakeSession(
        text={
            f"{BASE}/sitemap.xml": WebError("missing"),
            f"{BASE}/robots.txt": "User-agent: *\nSitemap: https://cdn.example.test/catalog.xml\n",
        }
    )

    assert discovery._find_sitemap(session, BASE) == "https://cdn.example.test/catalog.xml"


def test_discover_site_config_assembles_config_from_two_llm_calls():
    sitemap_url = f"{BASE}/catalog-sitemap.xml"
    product_url = f"{BASE}/product/gx-100"
    session = FakeSession(
        html={
            BASE: '<a href="/product/gx-100">GX-100</a>',
            product_url: '<b class="sku">GX-100</b>',
        },
        text={
            f"{BASE}/sitemap.xml": WebError("missing"),
            f"{BASE}/robots.txt": f"Sitemap: {sitemap_url}",
            sitemap_url: f"<urlset><loc>{product_url}</loc></urlset>",
        },
    )
    llm = FakeLLM(
        {
            "product_url_example": product_url,
            "product_url_pattern": r"/product/",
            "category_link_pattern": None,
            "pagination_param": None,
            "search_url_template": f"{BASE}/search?q={{query}}",
            "strategy": "sitemap",
        },
        {"part_no": ".sku", "breadcrumb": None, "attributes": None},
    )

    config = discover_site_config(session, llm, BASE)

    assert config == SiteConfig(
        platform="generic",
        enumeration={
            "strategy": "sitemap",
            "sitemap_url": sitemap_url,
            "product_url_pattern": r"/product/",
        },
        selectors={"part_no": ".sku", "breadcrumb": None, "attributes": None},
        search_url_template=f"{BASE}/search?q={{query}}",
    )
    assert len(llm.calls) == 2
    assert product_url in llm.calls[0]["user"]
    assert "GX-100" in llm.calls[1]["user"]


def test_discover_site_config_rejects_invented_product_url():
    invented_url = f"{BASE}/product/invented"
    session = FakeSession(
        html={BASE: "<h1>Catalog</h1>"},
        text={
            f"{BASE}/sitemap.xml": WebError("missing"),
            f"{BASE}/robots.txt": WebError("missing"),
        },
    )
    llm = FakeLLM(
        {
            "product_url_example": invented_url,
            "product_url_pattern": r"/product/",
            "strategy": "category_crawl",
        }
    )

    with pytest.raises(WebError, match="Couldn't figure out this website's structure"):
        discover_site_config(session, llm, BASE)


def test_discover_site_config_reports_schema_problems_from_llm_output():
    product_url = f"{BASE}/product/one"
    session = FakeSession(
        html={BASE: f'<a href="{product_url}">One</a>', product_url: "<h1>One</h1>"},
        text={
            f"{BASE}/sitemap.xml": WebError("missing"),
            f"{BASE}/robots.txt": WebError("missing"),
        },
    )
    llm = FakeLLM(
        {
            "product_url_example": product_url,
            "product_url_pattern": "",
            "strategy": "category_crawl",
        },
        {"breadcrumb": ".crumb"},
    )

    with pytest.raises(WebError) as exc_info:
        discover_site_config(session, llm, BASE)

    message = str(exc_info.value)
    assert "selectors.part_no" in message
    assert "enumeration.product_link_pattern" in message


def test_validate_site_config_passes_when_all_five_samples_parse():
    session, urls = _validation_session()

    result = validate_site_config(session, _crawl_config(), BASE)

    assert result.problems == []
    assert [part.url for part in result.sample_parts] == urls
    assert [part.part_no for part in result.sample_parts] == [f"PN-{i}" for i in range(5)]


def test_validate_site_config_rejects_hallucinated_part_number(monkeypatch):
    session, urls = _validation_session(count=1)

    monkeypatch.setattr(
        discovery,
        "parse_product_page",
        lambda html, url, config: PartRecord(part_no="MADE-UP-999", url=url),
    )
    result = validate_site_config(session, _crawl_config(), BASE)

    assert result.sample_parts == []
    assert result.problems == [f"part number MADE-UP-999 not visible on {urls[0]}"]


def test_validate_site_config_fails_when_fewer_than_three_of_five_parse():
    session, urls = _validation_session(parseable={0, 1})

    result = validate_site_config(session, _crawl_config(), BASE)

    assert [part.part_no for part in result.sample_parts] == ["PN-0", "PN-1"]
    assert result.problems == [
        f"no part number found on {urls[2]}",
        f"no part number found on {urls[3]}",
        f"no part number found on {urls[4]}",
    ]


def test_validate_site_config_passes_proportionally_with_two_of_two():
    session, _ = _validation_session(count=2)

    result = validate_site_config(session, _crawl_config(), BASE)

    assert result.problems == []
    assert [part.part_no for part in result.sample_parts] == ["PN-0", "PN-1"]


def test_validate_site_config_reports_when_no_product_pages_are_found():
    session = FakeSession(html={BASE: "<h1>Empty catalog</h1>"})

    result = validate_site_config(session, _crawl_config(), BASE)

    assert result.sample_parts == []
    assert result.problems == ["no product pages found"]
