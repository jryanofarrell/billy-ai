import threading
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
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

FILTER_SEARCH_MAX_ENTRIES = 500


@dataclass
class CachedDataInfo:
    fetched_at: datetime
    part_count: int
    complete: bool
    estimated_crawl_seconds: float | None


@dataclass
class WebRunResult:
    parts: list[PartRecord]
    match_report: MatchReport | None
    stopped_early: str | None = None
    notices: list[str] = field(default_factory=list)


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
    force_enumeration: bool = False,
    early_stopped_event: threading.Event | None = None,
) -> list[GenericPartRecord]:
    """Collect PartRecords from a non-Insite site per its discovered config."""
    if records is None:
        records = []
    strategy = config.enumeration.get("strategy", "category_crawl")

    if filter_sheet:
        entries = filter_sheet.entries
        wanted = {entry.normalized for entry in entries}
        if config.search_url_template and not force_enumeration:
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
                    found = {normalize_key(item.part_no) for item in records}
                    if wanted <= found:
                        if early_stopped_event is not None:
                            early_stopped_event.set()
                        break
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
    choose_cached: Callable[[CachedDataInfo], bool] | None = None,
) -> WebRunResult:
    domain = urlparse(url).netloc.lower()
    base = f"https://{domain}"
    outgoing_cache = store.get_web_cache(domain)

    if outgoing_cache is not None:
        fetched_at = datetime.fromisoformat(outgoing_cache["fetched_at"])
        info = CachedDataInfo(
            fetched_at=fetched_at,
            part_count=len(outgoing_cache["parts"]),
            complete=outgoing_cache["complete"],
            estimated_crawl_seconds=outgoing_cache.get("crawl_seconds"),
        )
        use_cache = choose_cached(info) if choose_cached is not None else True
        if use_cache:
            cached_parts = [PartRecord(**part) for part in outgoing_cache["parts"]]
            if filter_sheet:
                matched, report = match_parts(filter_sheet, cached_parts)
                result = WebRunResult(matched, report)
                if not outgoing_cache["complete"]:
                    result.notices.append(
                        "Matched against saved data that is incomplete "
                        "(an earlier crawl stopped early) — any unmatched parts may simply "
                        "not have been downloaded yet. Choose 'Get fresh data' for a full crawl."
                    )
            else:
                result = WebRunResult(cached_parts, None)
            store.record_run(
                {
                    "source": domain,
                    "kind": "web",
                    "mode": "filter" if filter_sheet else "crawl",
                    "parts": len(result.parts),
                    "data_source": "cache",
                }
            )
            return result

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
        early_stopped_event = threading.Event()
        full_site_collection = not filter_sheet
        collection_started_at = time.monotonic()

        def set_current_unit(unit: str) -> None:
            nonlocal current_unit
            current_unit = unit

        try:
            if config.platform == "insite":
                use_search = bool(
                    filter_sheet
                    and len(filter_sheet.entries) <= FILTER_SEARCH_MAX_ENTRIES
                )
                full_site_collection = not use_search
                if use_search:
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
                    wanted = (
                        {entry.normalized for entry in filter_sheet.entries}
                        if filter_sheet
                        else set()
                    )
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
                        if wanted and wanted <= {
                            normalize_key(record.part_no) for record in records_insite
                        }:
                            early_stopped_event.set()
                            break
            else:
                use_search = bool(
                    filter_sheet
                    and len(filter_sheet.entries) <= FILTER_SEARCH_MAX_ENTRIES
                    and config.search_url_template
                )
                full_site_collection = not use_search
                try:
                    run_generic(
                        session, config, base,
                        filter_sheet=filter_sheet,
                        progress=progress,
                        cancel=cancel,
                        records=generic_records,
                        set_current_unit=set_current_unit,
                        force_enumeration=full_site_collection,
                        early_stopped_event=early_stopped_event,
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

        collection_seconds = time.monotonic() - collection_started_at
        all_collected_parts: list[PartRecord]
        if config.platform == "insite":
            all_collected_parts = records_insite
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
            all_collected_parts = [
                PartRecord(
                    part_no=record.part_no,
                    category=record.category,
                    subcategory=record.subcategory,
                    series=record.series,
                    attributes=record.attributes,
                )
                for record in deduped
            ]
            if filter_sheet:
                matched_generic, report_generic = match_parts(
                    filter_sheet, all_collected_parts
                )
                result = WebRunResult(matched_generic, report_generic, stopped_early)
            else:
                result = WebRunResult(all_collected_parts, None, stopped_early)

        cache_complete = stopped_early is None and not early_stopped_event.is_set()
        if full_site_collection:
            if (
                outgoing_cache is not None
                and outgoing_cache.get("complete")
                and cache_complete
            ):
                old_parts = outgoing_cache["parts"]
                old_count = len(old_parts)
                new_count = len(all_collected_parts)
                if new_count < old_count * 0.5:
                    result.notices.append(
                        f"This site returned {new_count} parts where the saved copy had "
                        f"{old_count} — its layout may have changed."
                    )
                old_with_attributes = sum(
                    bool(part.get("attributes")) for part in old_parts
                )
                if (
                    old_parts
                    and old_with_attributes > len(old_parts) * 0.5
                    and not any(part.attributes for part in all_collected_parts)
                ):
                    result.notices.append(
                        "Part specifications came back empty — the site may have "
                        "changed its layout."
                    )
            store.save_web_cache(
                domain,
                {
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "crawl_seconds": collection_seconds,
                    "complete": cache_complete,
                    "parts": [asdict(part) for part in all_collected_parts],
                },
            )

        run_record = {
            "source": domain,
            "kind": "web",
            "mode": "filter" if filter_sheet else "crawl",
            "parts": len(result.parts),
            "platform": config.platform,
            "data_source": "live",
        }
        if stopped_early is not None:
            run_record["stopped_early"] = stopped_early
        store.record_run(run_record)
        return result
