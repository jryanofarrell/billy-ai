import dataclasses
import re
from dataclasses import dataclass
from typing import Callable

from bs4 import BeautifulSoup

from parts_parser.llm import LLMClient
from parts_parser.web.generic import (
    PartRecord,
    iter_crawl_product_urls,
    iter_sitemap_product_urls,
    parse_product_page,
    scan_sitemap,
)
from parts_parser.web.session import BrowserSession, WebError
from parts_parser.web.site_config import SiteConfig, validate_schema

_SYSTEM_URL_STRUCTURE = (
    "You reverse-engineer the URL structure of product-catalog websites. Respond with JSON only."
)

_SYSTEM_SELECTORS = (
    "You identify CSS selectors on a product page of a parts catalog. Respond with JSON only."
)


def _sample_html(html: str, limit: int = 30_000) -> str:
    html = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
    html = re.sub(r"<style[\s\S]*?</style>", " ", html, flags=re.IGNORECASE)
    html = re.sub(r"\s+", " ", html)
    return html[:limit].rstrip("<")


def _find_sitemap(session: BrowserSession, base: str) -> str | None:
    sitemap_url = base.rstrip("/") + "/sitemap.xml"
    try:
        session.get_text(sitemap_url)
        return sitemap_url
    except WebError:
        pass
    robots_url = base.rstrip("/") + "/robots.txt"
    try:
        robots = session.get_text(robots_url)
    except WebError:
        return None
    for line in robots.splitlines():
        if line.lower().startswith("sitemap:"):
            return line.split(":", 1)[1].strip()
    return None


def discover_site_config(
    session: BrowserSession,
    llm: LLMClient,
    base: str,
    progress: Callable[[str, float], None] = lambda m, f: None,
    force_llm: bool = False,
) -> SiteConfig:
    progress("Checking for sitemap…", 0.1)
    sitemap_url = _find_sitemap(session, base)

    sitemap_scan = None
    if sitemap_url:
        try:
            sitemap_scan = scan_sitemap(session, sitemap_url)
        except WebError:
            sitemap_url = None

    image_tagged = sitemap_scan.image_tagged if sitemap_scan else []
    other = sitemap_scan.other if sitemap_scan else []
    total = len(image_tagged) + len(other)
    use_sitemap_images = bool(
        sitemap_url
        and not force_llm
        and image_tagged
        and len(image_tagged) / total < 0.9
    )

    call1: dict = {}
    if use_sitemap_images:
        product_url_example = image_tagged[0]
    else:
        progress("Reading home page…", 0.2)
        home_html = _sample_html(session.get_html(base))

        if sitemap_url and sitemap_scan:
            if image_tagged:
                image_samples = "\n".join(
                    f"- {url} (includes a product image)" for url in image_tagged[:5]
                )
                other_samples = "\n".join(f"- {url} (no image)" for url in other[:5])
                samples = "\n".join(part for part in (image_samples, other_samples) if part)
            else:
                step = max(1, len(other) // 15)
                samples = "\n".join(f"- {url}" for url in other[::step][:15])
            sitemap_context = f"A sitemap exists at {sitemap_url}. Sample URLs:\n{samples}"
        else:
            sitemap_context = "No sitemap was found."

        user_prompt_1 = (
            f"Site: {base}. {sitemap_context}\n\n"
            "Home page content follows.\n\n"
            f"{home_html}\n\n"
            'Return {"product_url_example": str, "product_url_pattern": str, '
            '"category_link_pattern": str|null, "pagination_param": str|null, '
            '"search_url_template": str|null, "strategy": "sitemap"|"category_crawl"}. '
            "Rules: patterns are Python regexes matched against absolute URLs; "
            '"product_url_example" must be a real product URL visible in the provided '
            "content or sitemap; "
            '"search_url_template" uses {query} as the placeholder; '
            'choose "sitemap" only if a sitemap exists and product pages appear in it.'
        )

        progress("Analysing site structure…", 0.35)
        call1 = llm.complete_json(system=_SYSTEM_URL_STRUCTURE, user=user_prompt_1)
        product_url_example = call1.get("product_url_example", "")

    progress("Fetching a sample product page…", 0.5)
    try:
        product_html = _sample_html(session.get_html(product_url_example))
    except (WebError, Exception):
        raise WebError("Couldn't figure out this website's structure automatically.")

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

    progress("Identifying page selectors…", 0.65)
    call2 = llm.complete_json(system=_SYSTEM_SELECTORS, user=user_prompt_2)

    enumeration: dict
    if use_sitemap_images:
        enumeration = {
            "strategy": "sitemap_images",
            "sitemap_url": sitemap_url,
        }
    elif call1.get("strategy", "category_crawl") == "sitemap" and sitemap_url:
        enumeration = {
            "strategy": "sitemap",
            "sitemap_url": sitemap_url,
            "product_url_pattern": call1.get("product_url_pattern", ""),
        }
    else:
        enumeration = {
            "strategy": "category_crawl",
            "start_urls": [base],
            "product_link_pattern": call1.get("product_url_pattern", ""),
        }
        if call1.get("category_link_pattern"):
            enumeration["category_link_pattern"] = call1["category_link_pattern"]
        if call1.get("pagination_param"):
            enumeration["pagination_param"] = call1["pagination_param"]

    config = SiteConfig(
        platform="generic",
        enumeration=enumeration,
        selectors=call2,
        search_url_template=None if use_sitemap_images else call1.get("search_url_template"),
    )

    problems = validate_schema(config)
    if problems:
        joined = "; ".join(problems)
        raise WebError(f"Couldn't figure out this website's structure automatically. ({joined})")

    progress("Site config ready.", 1.0)
    return config


@dataclass
class ConfigValidation:
    sample_parts: list[PartRecord]
    problems: list[str]  # empty = config is trustworthy


def validate_site_config(
    session: BrowserSession,
    config: SiteConfig,
    base: str,
    sample_size: int = 5,
) -> ConfigValidation:
    strategy = config.enumeration.get("strategy", "category_crawl")

    if strategy == "sitemap":
        url_iter = iter_sitemap_product_urls(session, config, base)
    else:
        probe_config = dataclasses.replace(config, page_budget=20)
        url_iter = iter_crawl_product_urls(
            session,
            probe_config,
            base,
            progress=lambda msg, frac: None,
            cancel=None,
        )

    urls: list[str] = []
    for url in url_iter:
        urls.append(url)
        if len(urls) >= sample_size:
            break

    if not urls:
        return ConfigValidation(sample_parts=[], problems=["no product pages found"])

    sample_parts: list[PartRecord] = []
    parsing_failures: list[str] = []
    verbatim_problems: list[str] = []

    for url in urls:
        html = session.get_html(url)
        record = parse_product_page(html, url, config)
        if record is None:
            parsing_failures.append(url)
        else:
            soup = BeautifulSoup(html, "html.parser")
            page_text = "".join(soup.get_text().split())
            part_no_stripped = "".join(record.part_no.split())
            if part_no_stripped not in page_text:
                verbatim_problems.append(f"part number {record.part_no} not visible on {url}")
            else:
                sample_parts.append(record)

    pass_threshold = min(3, len(urls))
    problems: list[str] = list(verbatim_problems)

    if len(sample_parts) < pass_threshold:
        for url in parsing_failures:
            problems.append(f"no part number found on {url}")

    return ConfigValidation(sample_parts=sample_parts, problems=problems)
