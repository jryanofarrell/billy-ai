import re
import urllib.parse
import xml.etree.ElementTree as ET
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from parts_parser.web.site_config import SiteConfig
from parts_parser.web.session import WebError


@dataclass
class PartRecord:
    part_no: str
    url: str
    category: str = ""
    subcategory: str = ""
    series: str = ""
    attributes: dict[str, str] = field(default_factory=dict)


def normalize_url(
    href: str,
    base: str,
    *,
    pagination_param: str | None,
    strip_query: bool = True,
) -> str | None:
    joined = urllib.parse.urljoin(base, href)
    parsed = urllib.parse.urlparse(joined)
    base_parsed = urllib.parse.urlparse(base)

    if parsed.netloc != base_parsed.netloc:
        return None

    # Drop fragment always
    if strip_query:
        if pagination_param:
            qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            kept = {pagination_param: qs[pagination_param]} if pagination_param in qs else {}
            new_query = urllib.parse.urlencode(kept, doseq=True)
        else:
            new_query = ""
        parsed = parsed._replace(query=new_query, fragment="")
    else:
        parsed = parsed._replace(fragment="")

    return urllib.parse.urlunparse(parsed)


def parse_product_page(html: str, url: str, config: SiteConfig) -> PartRecord | None:
    soup = BeautifulSoup(html, "html.parser")
    selectors = config.selectors

    el = soup.select_one(selectors["part_no"])
    if el is None or not el.get_text(strip=True):
        return None

    part_no = el.get_text(strip=True)

    category = ""
    subcategory = ""
    series = ""

    breadcrumb_sel = selectors.get("breadcrumb")
    if breadcrumb_sel:
        items = [el.get_text(strip=True) for el in soup.select(breadcrumb_sel)]
        if items and items[0].lower() == "home":
            items = items[1:]
        if len(items) >= 1:
            category = items[0]
        if len(items) >= 2:
            subcategory = items[1]
        if len(items) >= 3:
            series = " / ".join(items[2:])

    attributes: dict[str, str] = {}
    attrs_cfg = selectors.get("attributes")
    if attrs_cfg:
        for row in soup.select(attrs_cfg["row"]):
            label_el = row.select_one(attrs_cfg["label"])
            value_el = row.select_one(attrs_cfg["value"])
            if label_el is None or value_el is None:
                continue
            label_text = label_el.get_text(strip=True)
            if not label_text:
                continue
            label = label_text.rstrip(":").strip()
            attributes[label] = value_el.get_text(" ", strip=True)

    return PartRecord(
        part_no=part_no,
        url=url,
        category=category,
        subcategory=subcategory,
        series=series,
        attributes=attributes,
    )


def iter_sitemap_product_urls(session, config: SiteConfig, base: str) -> Iterator[str]:
    enumeration = config.enumeration
    xml_text = session.get_text(enumeration["sitemap_url"])
    root = ET.fromstring(xml_text)
    pattern = enumeration["product_url_pattern"]

    def local(tag: str) -> str:
        return tag.split("}")[-1] if "}" in tag else tag

    yielded: set[str] = set()

    def _process_urlset(urlset_root: ET.Element) -> Iterator[str]:
        for element in urlset_root.iter():
            if local(element.tag) == "loc":
                loc = (element.text or "").strip()
                if loc and re.search(pattern, loc) and loc not in yielded:
                    yielded.add(loc)
                    yield loc

    if local(root.tag) == "sitemapindex":
        for child in root:
            if local(child.tag) == "sitemap":
                loc_el = next(
                    (c for c in child if local(c.tag) == "loc"), None
                )
                if loc_el is None:
                    continue
                child_url = (loc_el.text or "").strip()
                if not child_url:
                    continue
                child_xml = session.get_text(child_url)
                child_root = ET.fromstring(child_xml)
                if local(child_root.tag) == "urlset":
                    yield from _process_urlset(child_root)
    elif local(root.tag) == "urlset":
        yield from _process_urlset(root)


def iter_crawl_product_urls(
    session,
    config: SiteConfig,
    base: str,
    progress,
    cancel,
) -> Iterator[str]:
    enumeration = config.enumeration
    pagination_param: str | None = enumeration.get("pagination_param")
    product_link_pattern = enumeration["product_link_pattern"]
    category_link_pattern: str | None = enumeration.get("category_link_pattern")

    start_urls = [
        normalize_url(u, base, pagination_param=pagination_param, strip_query=True)
        for u in enumeration.get("start_urls", [])
    ]
    queue: deque[str] = deque(u for u in start_urls if u is not None)
    visited: set[str] = set(queue)
    yielded: set[str] = set()
    pages_visited = 0

    while queue and pages_visited < config.page_budget:
        if cancel and cancel.is_set():
            raise WebError("Cancelled.")

        url = queue.popleft()
        html = session.get_html(url)
        pages_visited += 1
        progress(f"Scanning {url}…", -1.0)

        soup = BeautifulSoup(html, "html.parser")
        page_yielded_new = False

        for a in soup.find_all("a", href=True):
            href = a["href"]
            n = normalize_url(href, base, pagination_param=pagination_param, strip_query=True)
            if n is None:
                continue

            if re.search(product_link_pattern, n) and n not in yielded:
                yielded.add(n)
                page_yielded_new = True
                yield n
            elif (
                category_link_pattern
                and re.search(category_link_pattern, n)
                and n not in visited
            ):
                visited.add(n)
                queue.append(n)

        if pagination_param and page_yielded_new:
            parsed = urllib.parse.urlparse(url)
            qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            current_val = int(qs.get(pagination_param, ["1"])[0])
            qs[pagination_param] = [str(current_val + 1)]
            next_url = urllib.parse.urlunparse(
                parsed._replace(query=urllib.parse.urlencode(qs, doseq=True))
            )
            if next_url not in visited:
                visited.add(next_url)
                queue.appendleft(next_url)


def search_product_urls(
    session,
    config: SiteConfig,
    base: str,
    part_no: str,
) -> list[str]:
    template = config.search_url_template
    assert template is not None, "caller must check search_url_template is set"
    search_url = template.format(query=urllib.parse.quote(part_no))
    html = session.get_html(search_url)
    soup = BeautifulSoup(html, "html.parser")

    enumeration = config.enumeration
    product_link_pattern = enumeration.get("product_link_pattern")
    product_url_pattern = enumeration.get("product_url_pattern")
    pattern = product_link_pattern or product_url_pattern

    results: list[str] = []
    seen: set[str] = set()
    pagination_param: str | None = enumeration.get("pagination_param")

    for a in soup.find_all("a", href=True):
        if len(results) >= 10:
            break
        href = a["href"]
        n = normalize_url(href, base, pagination_param=pagination_param, strip_query=True)
        if n is None or n in seen:
            continue
        if pattern and re.search(pattern, n):
            seen.add(n)
            results.append(n)

    return results
