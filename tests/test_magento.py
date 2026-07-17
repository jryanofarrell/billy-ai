import urllib.parse

from parts_parser.web.magento import (
    detect,
    discover_attribute_selectors,
    get_category_tree,
    iter_leaf_categories,
    list_category_products,
    product_to_record,
)
from parts_parser.web.session import WebError

BASE = "https://example.com"


class FakeSession:
    def __init__(self, responses: dict[str, dict], html_responses: dict[str, str] | None = None) -> None:
        self._responses = responses
        self._html_responses = html_responses or {}
        self.calls: list[str] = []

    def get_json(self, url: str) -> dict:
        self.calls.append(url)
        for key, value in self._responses.items():
            if key in url:
                return value
        raise WebError(f"No fixture for {url}")

    def get_html(self, url: str) -> str:
        self.calls.append(url)
        for key, value in self._html_responses.items():
            if key in url:
                return value
        raise WebError(f"No HTML fixture for {url}")


class FakeLLM:
    def __init__(self, response: dict) -> None:
        self._response = response
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, *, system: str, user: str) -> dict:
        self.calls.append((system, user))
        return self._response


def _graphql_url_fragment(query: str) -> str:
    return f"graphql?query={urllib.parse.quote(query)}"


DETECT_QUERY = '{ categoryList(filters: {ids: {eq: "2"}}) { id name } }'

WELL_FORMED_DETECT_RESPONSE = {
    "data": {"categoryList": [{"id": 2, "name": "Default Category"}]}
}

GRAPHQL_ERROR_RESPONSE = {
    "errors": [{"message": "Field not found"}],
    "data": None,
}


# --- detect ---


def test_detect_true_for_well_formed_response():
    session = FakeSession({"graphql": WELL_FORMED_DETECT_RESPONSE})
    assert detect(session, BASE) is True


def test_detect_false_for_graphql_error():
    session = FakeSession({"graphql": GRAPHQL_ERROR_RESPONSE})
    assert detect(session, BASE) is False


def test_detect_false_for_missing_data_key():
    session = FakeSession({"graphql": {"notdata": {}}})
    assert detect(session, BASE) is False


def test_detect_false_for_transport_error():
    session = FakeSession({})
    assert detect(session, BASE) is False


def test_detect_false_for_empty_category_list():
    session = FakeSession({"graphql": {"data": {"categoryList": []}}})
    assert detect(session, BASE) is False


# Synthetic category tree fixture:
#
# Root (id=2)
#   ├── Brass Fittings (id=10)
#   │     └── Pipe Fittings (id=11)
#   │           ├── Elbows (id=12)   <- leaf
#   │           └── Couplings (id=13) <- leaf
#   └── Valves (id=20)               <- leaf


TREE_FIXTURE = {
    "id": 2,
    "name": "Default Category",
    "url_key": "default-category",
    "children": [
        {
            "id": 10,
            "name": "Brass Fittings",
            "url_key": "brass-fittings",
            "children": [
                {
                    "id": 11,
                    "name": "Pipe Fittings",
                    "url_key": "pipe-fittings",
                    "children": [
                        {"id": 12, "name": "Elbows", "url_key": "elbows", "children": []},
                        {"id": 13, "name": "Couplings", "url_key": "couplings", "children": []},
                    ],
                }
            ],
        },
        {
            "id": 20,
            "name": "Valves",
            "url_key": "valves",
            "children": [],
        },
    ],
}

TREE_QUERY = """
{
  categoryList(filters: {ids: {eq: "2"}}) {
    id name url_key
    children {
      id name url_key
      children {
        id name url_key
        children {
          id name url_key
          children {
            id name url_key
          }
        }
      }
    }
  }
}
""".strip()

TREE_RESPONSE = {"data": {"categoryList": [TREE_FIXTURE]}}


# --- get_category_tree ---


def test_get_category_tree_returns_root_node():
    session = FakeSession({"graphql": TREE_RESPONSE})
    root = get_category_tree(session, BASE)
    assert root["id"] == 2
    assert root["name"] == "Default Category"


# --- iter_leaf_categories ---


def test_iter_leaf_categories_yields_only_leaves():
    leaves = list(iter_leaf_categories(TREE_FIXTURE))
    ids = {node["id"] for _, node in leaves}
    assert ids == {12, 13, 20}


def test_iter_leaf_categories_name_paths():
    leaves = list(iter_leaf_categories(TREE_FIXTURE))
    paths = [path for path, _ in leaves]
    assert ["Brass Fittings", "Pipe Fittings", "Elbows"] in paths
    assert ["Brass Fittings", "Pipe Fittings", "Couplings"] in paths
    assert ["Valves"] in paths


def test_iter_leaf_categories_no_intermediate_nodes():
    leaves = list(iter_leaf_categories(TREE_FIXTURE))
    names = [node["name"] for _, node in leaves]
    assert "Brass Fittings" not in names
    assert "Pipe Fittings" not in names


# --- list_category_products ---

PAGE1_RESPONSE = {
    "data": {
        "products": {
            "items": [
                {"sku": "BF-EL-90-1/2", "name": "90-Deg Elbow 1/2\"", "canonical_url": "bf-el-90-half.html"},
                {"sku": "BF-EL-90-3/4", "name": "90-Deg Elbow 3/4\"", "canonical_url": "bf-el-90-three-quarter.html"},
            ],
            "page_info": {"current_page": 1, "total_pages": 2},
        }
    }
}

PAGE2_RESPONSE = {
    "data": {
        "products": {
            "items": [
                {"sku": "BF-EL-45-1/2", "name": "45-Deg Elbow 1/2\"", "canonical_url": "bf-el-45-half.html"},
            ],
            "page_info": {"current_page": 2, "total_pages": 2},
        }
    }
}


def test_list_category_products_yields_all_pages():
    session = FakeSession({"currentPage=1": PAGE1_RESPONSE, "currentPage=2": PAGE2_RESPONSE})
    products = list(list_category_products(session, BASE, "12"))
    assert len(products) == 3


def test_list_category_products_skus():
    session = FakeSession({"currentPage=1": PAGE1_RESPONSE, "currentPage=2": PAGE2_RESPONSE})
    products = list(list_category_products(session, BASE, "12"))
    skus = {p["sku"] for p in products}
    assert skus == {"BF-EL-90-1/2", "BF-EL-90-3/4", "BF-EL-45-1/2"}


def test_list_category_products_fetches_each_page_once():
    session = FakeSession({"currentPage=1": PAGE1_RESPONSE, "currentPage=2": PAGE2_RESPONSE})
    list(list_category_products(session, BASE, "12"))
    assert sum(1 for c in session.calls if "currentPage=1" in c) == 1
    assert sum(1 for c in session.calls if "currentPage=2" in c) == 1


def test_list_category_products_single_page():
    single_page = {
        "data": {
            "products": {
                "items": [{"sku": "V-001", "name": "Ball Valve", "canonical_url": "v-001.html"}],
                "page_info": {"current_page": 1, "total_pages": 1},
            }
        }
    }
    session = FakeSession({"currentPage=1": single_page})
    products = list(list_category_products(session, BASE, "20"))
    assert len(products) == 1


# --- product_to_record ---

PRODUCT_FIXTURE = {
    "sku": "BF-EL-90-1/2",
    "name": "90-Deg Elbow 1/2\"",
    "canonical_url": "bf-el-90-half.html",
}


def test_product_to_record_part_no_verbatim():
    record = product_to_record(PRODUCT_FIXTURE, ["Brass Fittings", "Pipe Fittings", "Elbows"], {})
    assert record.part_no == "BF-EL-90-1/2"


def test_product_to_record_part_no_special_characters():
    product = {"sku": "BF/EL-90 (1/2\")", "name": "Elbow", "canonical_url": ""}
    record = product_to_record(product, ["Cat"], {})
    assert record.part_no == 'BF/EL-90 (1/2")'


def test_product_to_record_description():
    record = product_to_record(PRODUCT_FIXTURE, ["Brass Fittings", "Pipe Fittings", "Elbows"], {})
    assert record.description == '90-Deg Elbow 1/2"'


def test_product_to_record_category_subcategory_series():
    record = product_to_record(PRODUCT_FIXTURE, ["Brass Fittings", "Pipe Fittings", "Elbows"], {})
    assert record.category == "Brass Fittings"
    assert record.subcategory == "Pipe Fittings"
    assert record.series == "Elbows"


def test_product_to_record_series_joins_remainder():
    record = product_to_record(PRODUCT_FIXTURE, ["A", "B", "C", "D"], {})
    assert record.series == "C / D"


def test_product_to_record_missing_subcategory_and_series():
    record = product_to_record(PRODUCT_FIXTURE, ["Brass Fittings"], {})
    assert record.subcategory == ""
    assert record.series == ""


def test_product_to_record_attributes_passed_through():
    attrs = {"Material": "Brass", "Size": "1/2\""}
    record = product_to_record(PRODUCT_FIXTURE, ["Brass Fittings", "Pipe Fittings", "Elbows"], attrs)
    assert record.attributes == attrs


# --- discover_attribute_selectors ---

SELECTORS_RESPONSE = {
    "part_no": "span.sku",
    "breadcrumb": "nav.breadcrumb li",
    "attributes": {"row": "tr.spec-row", "label": "td.spec-label", "value": "td.spec-value"},
}

PRODUCT_HTML = "<html><body><table class='specs'><tr class='spec-row'><td class='spec-label'>Material</td><td class='spec-value'>Brass</td></tr></table></body></html>"


def test_discover_attribute_selectors_makes_exactly_one_llm_call():
    session = FakeSession({}, {"bf-el-90-half.html": PRODUCT_HTML})
    llm = FakeLLM(SELECTORS_RESPONSE)
    discover_attribute_selectors(llm, session, f"{BASE}/bf-el-90-half.html")
    assert len(llm.calls) == 1


def test_discover_attribute_selectors_returns_attributes_dict():
    session = FakeSession({}, {"bf-el-90-half.html": PRODUCT_HTML})
    llm = FakeLLM(SELECTORS_RESPONSE)
    result = discover_attribute_selectors(llm, session, f"{BASE}/bf-el-90-half.html")
    assert result == {"row": "tr.spec-row", "label": "td.spec-label", "value": "td.spec-value"}


def test_discover_attribute_selectors_returns_none_when_absent():
    session = FakeSession({}, {"bf-el-90-half.html": PRODUCT_HTML})
    llm = FakeLLM({"part_no": "span.sku", "breadcrumb": None})
    result = discover_attribute_selectors(llm, session, f"{BASE}/bf-el-90-half.html")
    assert result is None
