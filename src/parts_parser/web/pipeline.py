import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from urllib.parse import urlparse

from parts_parser.models import PartRecord
from parts_parser.output.filtering import FilterSheet, MatchReport, match_parts, normalize_key
from parts_parser.store import RunStore
from parts_parser.web import insite
from parts_parser.web.session import BrowserSession, WebError


@dataclass
class WebRunResult:
    parts: list[PartRecord]
    match_report: MatchReport | None


def run_web(
    url: str,
    *,
    store: RunStore,
    filter_sheet: FilterSheet | None = None,
    progress: Callable[[str, float], None] = lambda m, f: None,
    cancel: threading.Event | None = None,
    session_factory: Callable[[], AbstractContextManager] = BrowserSession,
) -> WebRunResult:
    domain = urlparse(url).netloc.lower()
    base = f"https://{domain}"

    with session_factory() as session:
        session.establish(base)

        config = store.get_site_config(domain)
        if config and config.get("platform") == "insite" and config.get("probe"):
            probe = config["probe"]
            try:
                data = session.get_json(
                    f"{base}/api/v2/products/{probe['product_id']}?expand=attributes"
                )
                if data.get("productNumber") != probe["part_no"]:
                    config = None
            except WebError:
                config = None

        if config is None:
            if not insite.detect(session, base):
                raise WebError(
                    "This website isn't supported yet. Currently supported: "
                    "sites built on the Insite/Optimizely commerce platform."
                )
            config = {"platform": "insite"}

        first_product: dict | None = None

        if filter_sheet:
            breadcrumb_cache: dict[str, list[str]] = {}
            seen: dict[str, PartRecord] = {}
            entries = filter_sheet.entries
            for i, entry in enumerate(entries):
                if cancel and cancel.is_set():
                    raise WebError("Cancelled.")
                progress(f"Searching {entry.raw}…", i / len(entries))
                for product in insite.search_products(session, base, entry.raw):
                    if normalize_key(product["productNumber"]) == entry.normalized:
                        seg = product["urlSegment"]
                        if seg not in breadcrumb_cache:
                            breadcrumb_cache[seg] = insite.get_breadcrumb(session, base, seg)
                        if product["productNumber"] not in seen:
                            seen[product["productNumber"]] = insite.product_to_record(
                                product, breadcrumb_cache[seg]
                            )
                            if first_product is None:
                                first_product = product
            records = list(seen.values())
            matched, report = match_parts(filter_sheet, records)
            result = WebRunResult(matched, report)
        else:
            tree = insite.get_category_tree(session, base)
            leaves = list(insite.iter_leaf_categories(tree))
            seen_crawl: dict[str, PartRecord] = {}
            for i, (name_path, leaf) in enumerate(leaves):
                if cancel and cancel.is_set():
                    raise WebError("Cancelled.")
                progress(f"Reading {' / '.join(name_path)}…", i / len(leaves))
                for product in insite.list_category_products(session, base, leaf["id"]):
                    if product["productNumber"] not in seen_crawl:
                        seen_crawl[product["productNumber"]] = insite.product_to_record(
                            product, name_path
                        )
                        if first_product is None:
                            first_product = product
            result = WebRunResult(list(seen_crawl.values()), None)

        if "probe" not in config and first_product is not None:
            config["probe"] = {
                "product_id": first_product["id"],
                "part_no": first_product["productNumber"],
            }

        store.save_site_config(domain, config)
        store.record_run({
            "source": domain,
            "kind": "web",
            "mode": "filter" if filter_sheet else "crawl",
            "parts": len(result.parts),
        })
        return result
