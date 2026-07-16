import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from urllib.parse import urlparse

from parts_parser.llm import LLMClient, get_client
from parts_parser.models import PartRecord
from parts_parser.output.filtering import FilterSheet, MatchReport, match_parts, normalize_key
from parts_parser.store import RunStore
from parts_parser.web import insite
from parts_parser.web.discovery import discover_site_config, validate_site_config
from parts_parser.web.generic import (
    PartRecord as GenericPartRecord,
    iter_crawl_product_urls,
    iter_sitemap_product_urls,
    parse_product_page,
    search_product_urls,
)
from parts_parser.web.session import BrowserSession, WebError
from parts_parser.web.site_config import SiteConfig


@dataclass
class WebRunResult:
    parts: list[PartRecord]
    match_report: MatchReport | None
    stopped_early: str | None = None


class _Cancelled(Exception):
    """Signal that collection stopped at the operator's request."""


def resolve_site_config(
    session,
    store: RunStore,
    domain: str,
    base: str,
    *,
    llm_factory: Callable[[], LLMClient],
    confirm: Callable[[list[GenericPartRecord]], bool] | None,
    progress: Callable[[str, float], None],
) -> SiteConfig:
    """Return a usable SiteConfig for the domain — load-and-self-heal a cached
    config, else detect Insite, else AI-discover + validate + confirm + save a
    generic one. Raises WebError if the site can't be read or the user cancels
    at preview. This absorbs the config lookup, the staleness probe, and
    insite.detect that previously sat inline in run_web."""
    raw = store.get_site_config(domain)
    config: SiteConfig | None = SiteConfig.from_dict(raw) if raw is not None else None

    if config is not None:
        probe = config.probe
        if probe:
            try:
                if config.platform == "insite":
                    data = session.get_json(
                        f"{base}/api/v2/products/{probe['product_id']}?expand=attributes"
                    )
                    if data.get("productNumber") != probe["part_no"]:
                        config = None
                else:
                    html = session.get_html(probe["url"])
                    record = parse_product_page(html, probe["url"], config)
                    if record is None or record.part_no != probe["part_no"]:
                        config = None
            except WebError:
                config = None
        else:
            config = None

    if config is not None:
        return config

    if insite.detect(session, base):
        return SiteConfig(platform="insite")

    progress("Learning this website's structure…", -1.0)
    config = discover_site_config(session, llm_factory(), base, progress)
    validation = validate_site_config(session, config, base)
    if validation.problems:
        config = discover_site_config(session, llm_factory(), base, progress)
        validation = validate_site_config(session, config, base)
        if validation.problems:
            raise WebError(
                "Couldn't reliably read this website. Details: "
                + "; ".join(validation.problems)
            )

    if confirm is not None and not confirm(validation.sample_parts):
        raise WebError("Cancelled after preview.")

    first_sample = validation.sample_parts[0] if validation.sample_parts else None
    if first_sample is not None:
        config.probe = {"url": first_sample.url, "part_no": first_sample.part_no}

    store.save_site_config(domain, config.to_dict())
    return config


def run_generic(
    session,
    config: SiteConfig,
    base: str,
    *,
    filter_sheet: FilterSheet | None,
    progress: Callable[[str, float], None],
    cancel: threading.Event | None,
    records: list[GenericPartRecord] | None = None,
    set_current_unit: Callable[[str], None] = lambda unit: None,
) -> list[GenericPartRecord]:
    """Collect PartRecords from a non-Insite site per its discovered config."""
    if records is None:
        records = []
    strategy = config.enumeration.get("strategy", "category_crawl")

    if filter_sheet:
        entries = filter_sheet.entries
        if config.search_url_template:
            for i, entry in enumerate(entries):
                if cancel and cancel.is_set():
                    raise _Cancelled
                set_current_unit(entry.raw)
                progress(f"Searching {entry.raw}…", i / len(entries))
                urls = search_product_urls(session, config, base, entry.raw)
                for url in urls:
                    html = session.get_html(url)
                    record = parse_product_page(html, url, config)
                    if record is not None and normalize_key(record.part_no) == entry.normalized:
                        records.append(record)
        else:
            if strategy == "sitemap":
                url_iter = iter_sitemap_product_urls(session, config, base)
            else:
                url_iter = iter_crawl_product_urls(session, config, base, progress, cancel)
            for url in url_iter:
                if cancel and cancel.is_set():
                    raise _Cancelled
                set_current_unit(url)
                html = session.get_html(url)
                record = parse_product_page(html, url, config)
                if record is not None:
                    records.append(record)
    else:
        if strategy == "sitemap":
            url_iter = iter_sitemap_product_urls(session, config, base)
        else:
            url_iter = iter_crawl_product_urls(session, config, base, progress, cancel)
        for url in url_iter:
            if cancel and cancel.is_set():
                raise _Cancelled
            set_current_unit(url)
            progress(f"Reading {url}…", -1.0)
            html = session.get_html(url)
            record = parse_product_page(html, url, config)
            if record is not None:
                records.append(record)

    return records


def run_web(
    url: str,
    *,
    store: RunStore,
    filter_sheet: FilterSheet | None = None,
    progress: Callable[[str, float], None] = lambda m, f: None,
    cancel: threading.Event | None = None,
    session_factory: Callable[[], AbstractContextManager] = BrowserSession,
    confirm: Callable[[list[GenericPartRecord]], bool] | None = None,
    llm_factory: Callable[[], LLMClient] = get_client,
) -> WebRunResult:
    domain = urlparse(url).netloc.lower()
    base = f"https://{domain}"

    with session_factory() as session:
        session.establish(base)

        config = resolve_site_config(
            session, store, domain, base,
            llm_factory=llm_factory,
            confirm=confirm,
            progress=progress,
        )

        first_product: dict | None = None
        stopped_early: str | None = None
        current_unit: str | None = None
        records_insite: list[PartRecord] = []
        generic_records: list[GenericPartRecord] = []

        def set_current_unit(unit: str) -> None:
            nonlocal current_unit
            current_unit = unit

        try:
            if config.platform == "insite":
                if filter_sheet:
                    breadcrumb_cache: dict[str, list[str]] = {}
                    seen: dict[str, PartRecord] = {}
                    entries = filter_sheet.entries
                    for i, entry in enumerate(entries):
                        if cancel and cancel.is_set():
                            raise _Cancelled
                        current_unit = entry.raw
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
                                    records_insite.append(seen[product["productNumber"]])
                                    if first_product is None:
                                        first_product = product
                else:
                    tree = insite.get_category_tree(session, base)
                    leaves = list(insite.iter_leaf_categories(tree))
                    seen_crawl: dict[str, PartRecord] = {}
                    for i, (name_path, leaf) in enumerate(leaves):
                        if cancel and cancel.is_set():
                            raise _Cancelled
                        current_unit = " / ".join(name_path)
                        progress(f"Reading {current_unit}…", i / len(leaves))
                        for product in insite.list_category_products(session, base, leaf["id"]):
                            if product["productNumber"] not in seen_crawl:
                                seen_crawl[product["productNumber"]] = insite.product_to_record(
                                    product, name_path
                                )
                                records_insite.append(
                                    seen_crawl[product["productNumber"]]
                                )
                                if first_product is None:
                                    first_product = product
            else:
                try:
                    run_generic(
                        session, config, base,
                        filter_sheet=filter_sheet,
                        progress=progress,
                        cancel=cancel,
                        records=generic_records,
                        set_current_unit=set_current_unit,
                    )
                except WebError as error:
                    if cancel and cancel.is_set() and str(error) == "Cancelled.":
                        raise _Cancelled from error
                    raise
        except _Cancelled:
            stopped_early = "Cancelled — kept the parts collected up to that point."
        except WebError as error:
            collected_count = (
                len(records_insite)
                if config.platform == "insite"
                else len(generic_records)
            )
            if not collected_count:
                raise
            location = f" while reading {current_unit}" if current_unit else ""
            stopped_early = (
                f"Stopped early after a website error{location} ({error}). "
                f"Kept {collected_count} parts."
            )

        if config.platform == "insite":
            if filter_sheet:
                matched, report = match_parts(filter_sheet, records_insite)
                result = WebRunResult(matched, report, stopped_early)
            else:
                result = WebRunResult(records_insite, None, stopped_early)

            if config.probe is None and first_product is not None:
                config.probe = {
                    "product_id": first_product["id"],
                    "part_no": first_product["productNumber"],
                }
                store.save_site_config(domain, config.to_dict())
        else:
            seen_generic: dict[str, GenericPartRecord] = {}
            for r in generic_records:
                if r.part_no not in seen_generic:
                    seen_generic[r.part_no] = r
            deduped = list(seen_generic.values())
            if filter_sheet:
                matched_generic, report_generic = match_parts(filter_sheet, deduped)
                result = WebRunResult(matched_generic, report_generic, stopped_early)
            else:
                result = WebRunResult(deduped, None, stopped_early)

        run_record = {
            "source": domain,
            "kind": "web",
            "mode": "filter" if filter_sheet else "crawl",
            "parts": len(result.parts),
            "platform": config.platform,
        }
        if stopped_early is not None:
            run_record["stopped_early"] = stopped_early
        store.record_run(run_record)
        return result
