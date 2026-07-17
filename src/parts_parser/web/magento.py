import urllib.parse
from collections.abc import Iterator
from typing import Any

from parts_parser.llm import LLMClient
from parts_parser.models import PartRecord
from parts_parser.web.session import WebError


def detect(session: Any, base: str) -> bool:
    query = "{ categoryList(filters: {ids: {eq: \"2\"}}) { id name } }"
    url = f"{base}/graphql?query={urllib.parse.quote(query)}"
    try:
        data = session.get_json(url)
        category_list = data["data"]["categoryList"]
        return isinstance(category_list, list) and len(category_list) > 0
    except (WebError, KeyError, TypeError, ValueError):
        return False


def get_category_tree(session: Any, base: str) -> dict:
    query = """
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
    url = f"{base}/graphql?query={urllib.parse.quote(query)}"
    data = session.get_json(url)
    return data["data"]["categoryList"][0]


def iter_leaf_categories(root: dict) -> Iterator[tuple[list[str], dict]]:
    def _walk(nodes: list[dict], path: list[str]) -> Iterator[tuple[list[str], dict]]:
        for node in nodes:
            name_path = path + [node["name"]]
            children = node.get("children") or []
            if children:
                yield from _walk(children, name_path)
            else:
                yield (name_path, node)

    yield from _walk(root["children"], [])


def list_category_products(
    session: Any, base: str, category_id: str, page_size: int = 20
) -> Iterator[dict]:
    page = 1
    while True:
        query = (
            "{ products(filter: {category_id: {eq: \"%s\"}}, pageSize: %d, currentPage: %d)"
            " { items { sku name canonical_url } page_info { current_page total_pages } } }"
        ) % (category_id, page_size, page)
        url = f"{base}/graphql?query={urllib.parse.quote(query)}&currentPage={page}"
        data = session.get_json(url)
        products_data = data["data"]["products"]
        items = products_data.get("items") or []
        yield from items
        page_info = products_data["page_info"]
        if not items or page_info["current_page"] >= page_info["total_pages"]:
            break
        page += 1


def product_to_record(
    product: dict, name_path: list[str], attributes: dict[str, str]
) -> PartRecord:
    category = name_path[0] if name_path else ""
    subcategory = name_path[1] if len(name_path) > 1 else ""
    series = " / ".join(name_path[2:]) if len(name_path) > 2 else ""
    return PartRecord(
        part_no=product["sku"],
        category=category,
        subcategory=subcategory,
        series=series,
        description=product.get("name") or "",
        attributes=attributes,
    )


def discover_attribute_selectors(llm: LLMClient, session: Any, product_url: str) -> dict | None:
    from parts_parser.web.discovery import _sample_html, _SYSTEM_SELECTORS

    html = session.get_html(product_url)
    product_html = _sample_html(html)

    user_prompt_2 = (
        "Product page content follows.\n\n"
        f"{product_html}\n\n"
        'Return {"part_no": str, "breadcrumb": str|null, '
        '"attributes": {"row": str, "label": str, "value": str}|null}. '
        "Rules: values are CSS selectors; "
        '"part_no" selects the element whose text is the product/part number; '
        '"breadcrumb" selects the ordered breadcrumb items; '
        '"attributes.row" selects each specification row, '
        'with "label"/"value" relative to a row.'
    )

    call2 = llm.complete_json(system=_SYSTEM_SELECTORS, user=user_prompt_2)
    return call2.get("attributes") or None
