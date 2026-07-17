import pytest

from parts_parser.web.site_config import SiteConfig, validate_schema


def test_site_config_dict_round_trip_preserves_schema_fields():
    raw = {
        "platform": "generic",
        "enumeration": {
            "strategy": "sitemap",
            "sitemap_url": "https://example.test/sitemap.xml",
            "product_url_pattern": r"/product/",
        },
        "selectors": {
            "part_no": ".sku",
            "breadcrumb": ".breadcrumb > *",
            "attributes": {"row": ".specs tr", "label": "th", "value": "td"},
        },
        "search_url_template": "https://example.test/search?q={query}",
        "probe": {"url": "https://example.test/product/gx-100-a", "part_no": "GX-100-A"},
        "page_budget": 25,
    }

    assert SiteConfig.from_dict(raw).to_dict() == raw


def test_site_config_from_dict_ignores_unknown_fields():
    config = SiteConfig.from_dict({"platform": "insite", "future_field": "ignored"})

    assert config == SiteConfig(platform="insite")


def test_validate_schema_lists_missing_part_number_and_unknown_strategy():
    problems = validate_schema(
        SiteConfig(
            platform="generic",
            selectors={},
            enumeration={"strategy": "catalog_magic"},
        )
    )

    assert "selectors.part_no must be a non-empty string" in problems
    assert any(
        "enumeration.strategy" in problem and "catalog_magic" in problem for problem in problems
    )
    assert len(problems) == 2


@pytest.mark.parametrize(
    ("enumeration", "expected_problems"),
    [
        (
            {"strategy": "sitemap"},
            {"enumeration.sitemap_url", "enumeration.product_url_pattern"},
        ),
        (
            {"strategy": "category_crawl"},
            {"enumeration.start_urls", "enumeration.product_link_pattern"},
        ),
    ],
)
def test_validate_schema_lists_every_incomplete_strategy_problem(enumeration, expected_problems):
    problems = validate_schema(
        SiteConfig(
            platform="generic",
            selectors={"part_no": ".sku"},
            enumeration=enumeration,
        )
    )

    assert len(problems) == len(expected_problems)
    assert all(any(field in problem for problem in problems) for field in expected_problems)


def test_validate_schema_accepts_complete_generic_config():
    config = SiteConfig(
        platform="generic",
        selectors={
            "part_no": ".sku",
            "attributes": {"row": "tr", "label": "th", "value": "td"},
        },
        enumeration={
            "strategy": "category_crawl",
            "start_urls": ["https://example.test/category/fittings"],
            "product_link_pattern": r"/product/",
            "category_link_pattern": r"/category/",
            "pagination_param": "page",
        },
    )

    assert validate_schema(config) == []


def test_validate_schema_accepts_sitemap_images_with_only_sitemap_url():
    config = SiteConfig(
        platform="generic",
        selectors={"part_no": ".sku"},
        enumeration={
            "strategy": "sitemap_images",
            "sitemap_url": "https://example.test/sitemap.xml",
        },
    )

    assert validate_schema(config) == []


@pytest.mark.parametrize("sitemap_url", [None, "", "   "])
def test_validate_schema_rejects_sitemap_images_without_sitemap_url(sitemap_url):
    enumeration = {"strategy": "sitemap_images"}
    if sitemap_url is not None:
        enumeration["sitemap_url"] = sitemap_url

    problems = validate_schema(
        SiteConfig(
            platform="generic",
            selectors={"part_no": ".sku"},
            enumeration=enumeration,
        )
    )

    assert len(problems) == 1
    assert "enumeration.sitemap_url" in problems[0]


def test_validate_schema_does_not_apply_generic_requirements_to_insite():
    assert validate_schema(SiteConfig(platform="insite")) == []
