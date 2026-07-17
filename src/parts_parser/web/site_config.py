import dataclasses
import re
from dataclasses import dataclass, field


@dataclass
class SiteConfig:
    platform: str
    enumeration: dict = field(default_factory=dict)
    selectors: dict = field(default_factory=dict)
    search_url_template: str | None = None
    probe: dict | None = None
    page_budget: int = 10_000

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SiteConfig":
        known = {f.name for f in dataclasses.fields(cls)}
        filtered = {k: v for k, v in d.items() if k in known}
        return cls(**filtered)


def validate_schema(config: SiteConfig) -> list[str]:
    if config.platform != "generic":
        return []

    problems: list[str] = []

    part_no = config.selectors.get("part_no")
    if not isinstance(part_no, str) or not part_no.strip():
        problems.append("selectors.part_no must be a non-empty string")

    attrs = config.selectors.get("attributes")
    if attrs is not None:
        if not isinstance(attrs, dict) or not {"row", "label", "value"}.issubset(attrs):
            problems.append("selectors.attributes must be a dict with row, label, and value keys")

    strategy = config.enumeration.get("strategy")
    if strategy == "sitemap":
        sitemap_url = config.enumeration.get("sitemap_url", "")
        if not isinstance(sitemap_url, str) or not sitemap_url.strip():
            problems.append(
                "enumeration.sitemap_url must be a non-empty string for sitemap strategy"
            )
        pattern = config.enumeration.get("product_url_pattern", "")
        if not isinstance(pattern, str) or not pattern.strip():
            problems.append(
                "enumeration.product_url_pattern must be a non-empty string for sitemap strategy"
            )
        else:
            try:
                re.compile(pattern)
            except re.error as exc:
                problems.append(f"enumeration.product_url_pattern is not a valid regex: {exc}")
    elif strategy == "category_crawl":
        start_urls = config.enumeration.get("start_urls")
        if not isinstance(start_urls, list) or len(start_urls) == 0:
            problems.append(
                "enumeration.start_urls must be a non-empty list for category_crawl strategy"
            )
        link_pattern = config.enumeration.get("product_link_pattern", "")
        if not isinstance(link_pattern, str) or not link_pattern.strip():
            problems.append(
                "enumeration.product_link_pattern must be a non-empty string for category_crawl strategy"
            )
        else:
            try:
                re.compile(link_pattern)
            except re.error as exc:
                problems.append(f"enumeration.product_link_pattern is not a valid regex: {exc}")
        for opt_key in ("category_link_pattern", "pagination_param"):
            val = config.enumeration.get(opt_key)
            if val is not None and opt_key == "category_link_pattern":
                try:
                    re.compile(val)
                except re.error as exc:
                    problems.append(f"enumeration.{opt_key} is not a valid regex: {exc}")
    elif strategy == "sitemap_images":
        sitemap_url = config.enumeration.get("sitemap_url", "")
        if not isinstance(sitemap_url, str) or not sitemap_url.strip():
            problems.append(
                "enumeration.sitemap_url must be a non-empty string for sitemap_images strategy"
            )
    else:
        problems.append(
            f"enumeration.strategy must be 'sitemap', 'category_crawl', or 'sitemap_images', got {strategy!r}"
        )

    return problems
