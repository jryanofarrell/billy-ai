import urllib.parse
from collections.abc import Iterator
from typing import Any

from parts_parser.models import PartRecord
from parts_parser.web.session import WebError

PAGE_SIZE = 48


def detect(session: Any, base: str) -> bool:
    try:
        data = session.get_json(f"{base}/api/v1/websites/current?expand=languages%2Ccurrencies")
        return isinstance(data, dict) and ("id" in data or "websiteId" in data)
    except WebError:
        return False


def get_category_tree(session: Any, base: str) -> list[dict]:
    data = session.get_json(f"{base}/api/v1/categories/?maxDepth=3&includeStartCategory=false")
    return data["categories"]


def iter_leaf_categories(
    tree: list[dict],
) -> Iterator[tuple[list[str], dict]]:
    def _walk(nodes: list[dict], path: list[str]) -> Iterator[tuple[list[str], dict]]:
        for node in nodes:
            name_path = path + [node["shortDescription"]]
            children = node.get("subCategories") or []
            if children:
                yield from _walk(children, name_path)
            else:
                yield (name_path, node)

    yield from _walk(tree, [])


def list_category_products(session: Any, base: str, category_id: str) -> Iterator[dict]:
    page = 1
    while True:
        data = session.get_json(
            f"{base}/api/v2/products"
            f"?categoryId={category_id}&page={page}&pageSize={PAGE_SIZE}&expand=attributes"
        )
        products = data.get("products") or []
        yield from products
        if not products or page >= data["pagination"]["numberOfPages"]:
            break
        page += 1


def search_products(session: Any, base: str, term: str) -> list[dict]:
    data = session.get_json(
        f"{base}/api/v2/products"
        f"?search={urllib.parse.quote(term)}&expand=attributes&pageSize={PAGE_SIZE}"
    )
    return data.get("products") or []


def get_breadcrumb(session: Any, base: str, url_segment: str) -> list[str]:
    data = session.get_json(
        f"{base}/api/v1/catalogpages?path=%2Fproduct%2F{urllib.parse.quote(url_segment)}"
    )
    crumbs = data.get("breadCrumbs") or []
    return [c["text"] for c in crumbs if c.get("text") != "Home"]


def product_to_record(product: dict, breadcrumb: list[str]) -> PartRecord:
    category = breadcrumb[0] if len(breadcrumb) > 0 else ""
    subcategory = breadcrumb[1] if len(breadcrumb) > 1 else ""
    series = " / ".join(breadcrumb[2:]) if len(breadcrumb) > 2 else ""

    attributes = {
        t["label"]: ", ".join(v["valueDisplay"] for v in (t.get("attributeValues") or []))
        for t in (product.get("attributeTypes") or [])
    }

    return PartRecord(
        part_no=product["productNumber"],
        category=category,
        subcategory=subcategory,
        series=series,
        description=product.get("productTitle") or "",
        attributes=attributes,
    )
