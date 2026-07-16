import json
from pathlib import Path

import pytest

from parts_parser.web.insite import (
    detect,
    get_breadcrumb,
    iter_leaf_categories,
    list_category_products,
    product_to_record,
)
from parts_parser.web.session import WebError

FIXTURES = Path(__file__).parent / "fixtures" / "insite"


class FakeSession:
    def __init__(self, responses: dict[str, dict]) -> None:
        self._responses = responses
        self.calls: list[str] = []

    def get_json(self, url: str) -> dict:
        self.calls.append(url)
        for key, value in self._responses.items():
            if key in url:
                return value
        raise WebError(f"No fixture for {url}")


@pytest.fixture
def categories():
    return json.loads((FIXTURES / "categories.json").read_text())["categories"]


@pytest.fixture
def products_page1():
    return json.loads((FIXTURES / "products_page1.json").read_text())


@pytest.fixture
def products_page2():
    return json.loads((FIXTURES / "products_page2.json").read_text())


@pytest.fixture
def product_detail():
    return json.loads((FIXTURES / "product_detail.json").read_text())


@pytest.fixture
def catalogpages():
    return json.loads((FIXTURES / "catalogpages.json").read_text())


# --- detect ---


def test_detect_true():
    session = FakeSession({"websites/current": {"id": "site-1"}})
    assert detect(session, "https://example.com") is True


def test_detect_true_website_id():
    session = FakeSession({"websites/current": {"websiteId": "site-1"}})
    assert detect(session, "https://example.com") is True


def test_detect_false_on_web_error():
    session = FakeSession({})
    assert detect(session, "https://example.com") is False


def test_detect_false_on_unrecognized_response():
    session = FakeSession({"websites/current": {"name": "something"}})
    assert detect(session, "https://example.com") is False


# --- iter_leaf_categories ---


def test_iter_leaf_categories_count(categories):
    leaves = list(iter_leaf_categories(categories))
    assert len(leaves) == 2


def test_iter_leaf_categories_name_paths(categories):
    leaves = list(iter_leaf_categories(categories))
    paths = [p for p, _ in leaves]
    assert ["Brass Fittings", "Pipe", "90-Deg Female Elbow"] in paths
    assert ["Brass Fittings", "Pipe", "Coupling"] in paths


def test_iter_leaf_categories_yields_node(categories):
    leaves = list(iter_leaf_categories(categories))
    nodes = [n for _, n in leaves]
    ids = {n["id"] for n in nodes}
    assert ids == {"cat-1-1-1", "cat-1-1-2"}


# --- list_category_products ---


def test_list_category_products_yields_all(products_page1, products_page2):
    session = FakeSession(
        {
            "&page=1": products_page1,
            "&page=2": products_page2,
        }
    )
    products = list(list_category_products(session, "https://example.com", "cat-1-1-1"))
    assert len(products) == 4
    part_nos = {p["productNumber"] for p in products}
    assert part_nos == {"28001", "28002", "28003", "28004"}


def test_list_category_products_fetches_each_page_once(products_page1, products_page2):
    session = FakeSession(
        {
            "&page=1": products_page1,
            "&page=2": products_page2,
        }
    )
    list(list_category_products(session, "https://example.com", "cat-1-1-1"))
    assert sum(1 for c in session.calls if "&page=1" in c) == 1
    assert sum(1 for c in session.calls if "&page=2" in c) == 1


# --- product_to_record ---


def test_product_to_record_verbatim_part_no(product_detail):
    record = product_to_record(product_detail, ["Brass Fittings", "Pipe", "90-Deg Female Elbow"])
    assert record.part_no == "28002"
    assert record.description == product_detail.get("productTitle", "")


def test_product_to_record_breadcrumb_category(product_detail):
    record = product_to_record(product_detail, ["Brass Fittings", "Pipe", "90-Deg Female Elbow"])
    assert record.category == "Brass Fittings"
    assert record.subcategory == "Pipe"
    assert record.series == "90-Deg Female Elbow"


def test_product_to_record_breadcrumb_blank_when_absent(product_detail):
    record = product_to_record(product_detail, ["Brass Fittings"])
    assert record.subcategory == ""
    assert record.series == ""


def test_product_to_record_multi_value_joined(product_detail):
    record = product_to_record(product_detail, [])
    assert record.attributes["Size"] == '1/2", 3/4"'


def test_product_to_record_single_value_attribute(product_detail):
    record = product_to_record(product_detail, [])
    assert record.attributes["Material"] == "Brass"


# --- get_breadcrumb ---


def test_get_breadcrumb_drops_home(catalogpages):
    session = FakeSession({"catalogpages": catalogpages})
    crumbs = get_breadcrumb(session, "https://example.com", "28002-segment")
    assert crumbs == ["Brass Fittings", "Pipe", "90-Deg Female Elbow"]


def test_get_breadcrumb_no_home_in_result(catalogpages):
    session = FakeSession({"catalogpages": catalogpages})
    crumbs = get_breadcrumb(session, "https://example.com", "28002-segment")
    assert "Home" not in crumbs


def test_get_breadcrumb_records_call(catalogpages):
    session = FakeSession({"catalogpages": catalogpages})
    get_breadcrumb(session, "https://example.com", "28002-segment")
    assert any("catalogpages" in c for c in session.calls)
