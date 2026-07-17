import threading
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse

from parts_parser.llm import LLMClient, get_client
from parts_parser.models import PartRecord
from parts_parser.output.filtering import FilterSheet, MatchReport, match_parts, normalize_key
from parts_parser.store import RunStore
from parts_parser.web import insite, magento
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
    progress: list[str] = field(default_factory=list)


class _Cancelled(Exception):
    """Signal that collection stopped at the operator's request."""


def collect_insite_crawl(
    session,
    base: str,
    *,
    skip_keys: set[str],
    progress: Callable[[str, float], None],
    cancel: threading.Event | None,
    on_product: Callable[[dict], None] = lambda product: None,
    on_unit: Callable[[str], None] = lambda unit: None,
) -> Iterator[tuple[str, list[PartRecord]]]:
    """Yield each completed Insite leaf category and its part records."""
    tree = insite.get_category_tree(session, base)
    leaves = list(insite.iter_leaf_categories(tree))
    seen: set[str] = set()

    for index, (name_path, leaf) in enumerate(leaves):
        category_id = str(leaf["id"])
        if category_id in skip_keys:
            continue
        if cancel and cancel.is_set():
            raise _Cancelled

        category_name = " / ".join(name_path)
        on_unit(category_name)
        progress(f"Reading {category_name}…", index / len(leaves))
        records: list[PartRecord] = []
        for product in insite.list_category_products(session, base, category_id):
            on_product(product)
            part_number = product["productNumber"]
            if part_number not in seen:
                seen.add(part_number)
                records.append(insite.product_to_record(product, name_path))
        yield category_id, records


def collect_magento_crawl(
    session,
    base: str,
    *,
    skip_keys: set[str],
    progress: Callable[[str, float], None],
    cancel: threading.Event | None,
    on_product: Callable[[dict], None] = lambda product: None,
    on_unit: Callable[[str], None] = lambda unit: None,
    attribute_selectors: dict | None = None,
) -> Iterator[tuple[str, list[PartRecord]]]:
    """Yield each completed Magento leaf category and its part records."""
    tree = magento.get_category_tree(session, base)
    leaves = list(magento.iter_leaf_categories(tree))
    seen: set[str] = set()
    attr_config = (
        SiteConfig(
            platform="generic",
            selectors={"part_no": "h1", "attributes": attribute_selectors},
        )
        if attribute_selectors
        else None
    )

    for index, (name_path, leaf) in enumerate(leaves):
        category_id = str(leaf["id"])
        if category_id in skip_keys:
            continue
        if cancel and cancel.is_set():
            raise _Cancelled

        category_name = " / ".join(name_path)
        on_unit(category_name)
        progress(f"Reading {category_name}…", index / len(leaves))
        records: list[PartRecord] = []
        for product in magento.list_category_products(session, base, category_id):
            on_product(product)
            sku = product["sku"]
            if sku not in seen:
                seen.add(sku)
                attributes: dict[str, str] = {}
                if attr_config is not None:
                    canonical = product.get("canonical_url", "")
                    if canonical:
                        product_url = (
                            canonical
                            if canonical.startswith("http")
                            else f"{base}/{canonical.lstrip('/')}"
                        )
                        try:
                            html = session.get_html(product_url)
                            page_record = parse_product_page(html, product_url, attr_config)
                            if page_record is not None:
                                attributes = page_record.attributes
                        except WebError:
                            pass
                records.append(magento.product_to_record(product, name_path, attributes))
        yield category_id, records


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
        # Older saved configs may predate staleness probes. They remain usable;
        # newly learned configs receive a probe below.

    if config is not None:
        return config

    if insite.detect(session, base):
        return SiteConfig(platform="insite")

    if magento.detect(session, base):
        progress("Discovering Magento attribute selectors…", -1.0)
        tree = magento.get_category_tree(session, base)
        first_leaf = next(magento.iter_leaf_categories(tree), None)
        product_url: str | None = None
        if first_leaf is not None:
            _, leaf = first_leaf
            first_product_m = next(
                magento.list_category_products(session, base, str(leaf["id"])), None
            )
            if first_product_m is not None:
                canonical = first_product_m.get("canonical_url", "")
                if canonical:
                    product_url = (
                        canonical
                        if canonical.startswith("http")
                        else f"{base}/{canonical.lstrip('/')}"
                    )
        attribute_selectors = (
            magento.discover_attribute_selectors(llm_factory(), session, product_url)
            if product_url
            else None
        )
        return SiteConfig(platform="magento", selectors={"attributes": attribute_selectors})

    progress("Learning this website's structure…", -1.0)
    config = discover_site_config(session, llm_factory(), base, progress)
    validation = validate_site_config(session, config, base)
    if validation.problems:
        config = discover_site_config(session, llm_factory(), base, progress)
        validation = validate_site_config(session, config, base)
        if validation.problems:
            raise WebError(
                "Couldn't reliably read this website. Details: " + "; ".join(validation.problems)
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
    skip_keys: set[str] | None = None,
    completed_keys: list[str] | None = None,
    set_current_unit: Callable[[str], None] = lambda unit: None,
    force_enumeration: bool = False,
    early_stopped_event: threading.Event | None = None,
) -> list[GenericPartRecord]:
    """Collect records, skipping and reporting product-URL crawl units."""
    if records is None:
        records = []
    if skip_keys is None:
        skip_keys = set()
    if completed_keys is None:
        completed_keys = []
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
                if url in skip_keys:
                    continue
                if cancel and cancel.is_set():
                    raise _Cancelled
                set_current_unit(url)
                html = session.get_html(url)
                record = parse_product_page(html, url, config)
                if record is not None:
                    records.append(record)
                completed_keys.append(url)
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
            if url in skip_keys:
                continue
            if cancel and cancel.is_set():
                raise _Cancelled
            set_current_unit(url)
            progress(f"Reading {url}…", -1.0)
            html = session.get_html(url)
            record = parse_product_page(html, url, config)
            if record is not None:
                records.append(record)
            completed_keys.append(url)

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
    resume_parts: list[PartRecord] = []
    resume_progress: list[str] = []
    resuming = False

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
            if outgoing_cache["complete"]:
                if filter_sheet:
                    matched, report = match_parts(filter_sheet, cached_parts)
                    result = WebRunResult(matched, report)
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
            resume_parts = cached_parts
            resume_progress = list(outgoing_cache.get("progress", []))
            resuming = True

    with session_factory() as session:
        session.establish(base)

        config = resolve_site_config(
            session,
            store,
            domain,
            base,
            llm_factory=llm_factory,
            confirm=confirm,
            progress=progress,
        )

        first_product: dict | None = None
        stopped_early: str | None = None
        current_unit: str | None = None
        records_insite: list[PartRecord] = []
        generic_records: list[GenericPartRecord] = []
        completed_keys = list(resume_progress)
        early_stopped_event = threading.Event()
        full_site_collection = not filter_sheet
        collection_started_at = time.monotonic()

        def set_current_unit(unit: str) -> None:
            nonlocal current_unit
            current_unit = unit

        try:
            if config.platform == "insite":
                use_search = bool(
                    not resuming
                    and filter_sheet
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
                                    breadcrumb_cache[seg] = insite.get_breadcrumb(
                                        session, base, seg
                                    )
                                if product["productNumber"] not in seen:
                                    seen[product["productNumber"]] = insite.product_to_record(
                                        product, breadcrumb_cache[seg]
                                    )
                                    records_insite.append(seen[product["productNumber"]])
                                    if first_product is None:
                                        first_product = product
                else:
                    wanted = (
                        {entry.normalized for entry in filter_sheet.entries}
                        if filter_sheet
                        else set()
                    )

                    def remember_first_product(product: dict) -> None:
                        nonlocal first_product
                        if first_product is None:
                            first_product = product

                    for category_id, category_records in collect_insite_crawl(
                        session,
                        base,
                        skip_keys=set(resume_progress),
                        progress=progress,
                        cancel=cancel,
                        on_product=remember_first_product,
                        on_unit=set_current_unit,
                    ):
                        records_insite.extend(category_records)
                        completed_keys.append(category_id)
                        if wanted and wanted <= {
                            normalize_key(record.part_no) for record in records_insite
                        }:
                            early_stopped_event.set()
                            break
            elif config.platform == "magento":
                full_site_collection = True
                wanted = (
                    {entry.normalized for entry in filter_sheet.entries}
                    if filter_sheet
                    else set()
                )

                def remember_first_magento_product(product: dict) -> None:
                    nonlocal first_product
                    if first_product is None:
                        first_product = product

                for category_id, category_records in collect_magento_crawl(
                    session,
                    base,
                    skip_keys=set(resume_progress),
                    progress=progress,
                    cancel=cancel,
                    on_product=remember_first_magento_product,
                    on_unit=set_current_unit,
                    attribute_selectors=config.selectors.get("attributes"),
                ):
                    records_insite.extend(category_records)
                    completed_keys.append(category_id)
                    if wanted and wanted <= {
                        normalize_key(record.part_no) for record in records_insite
                    }:
                        early_stopped_event.set()
                        break
            else:
                use_search = bool(
                    not resuming
                    and filter_sheet
                    and len(filter_sheet.entries) <= FILTER_SEARCH_MAX_ENTRIES
                    and config.search_url_template
                )
                full_site_collection = not use_search
                try:
                    run_generic(
                        session,
                        config,
                        base,
                        filter_sheet=filter_sheet,
                        progress=progress,
                        cancel=cancel,
                        records=generic_records,
                        skip_keys=set(resume_progress),
                        completed_keys=completed_keys,
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
                if config.platform in ("insite", "magento")
                else len(generic_records)
            ) + len(resume_parts)
            if not collected_count:
                raise
            location = f" while reading {current_unit}" if current_unit else ""
            stopped_early = (
                f"Stopped early after a website error{location} ({error}). "
                f"Kept {collected_count} parts."
            )

        collection_seconds = time.monotonic() - collection_started_at
        all_collected_parts: list[PartRecord]
        if config.platform in ("insite", "magento"):
            seen_insite = {part.part_no: part for part in resume_parts}
            for part in records_insite:
                seen_insite.setdefault(part.part_no, part)
            all_collected_parts = list(seen_insite.values())
            if filter_sheet:
                matched, report = match_parts(filter_sheet, all_collected_parts)
                result = WebRunResult(matched, report, stopped_early, progress=completed_keys)
            else:
                result = WebRunResult(
                    all_collected_parts, None, stopped_early, progress=completed_keys
                )

            if config.platform == "insite" and config.probe is None and first_product is not None:
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
            newly_collected_parts = [
                PartRecord(
                    part_no=record.part_no,
                    category=record.category,
                    subcategory=record.subcategory,
                    series=record.series,
                    attributes=record.attributes,
                )
                for record in deduped
            ]
            seen_parts = {part.part_no: part for part in resume_parts}
            for part in newly_collected_parts:
                seen_parts.setdefault(part.part_no, part)
            all_collected_parts = list(seen_parts.values())
            if filter_sheet:
                matched_generic, report_generic = match_parts(filter_sheet, all_collected_parts)
                result = WebRunResult(
                    matched_generic,
                    report_generic,
                    stopped_early,
                    progress=completed_keys,
                )
            else:
                result = WebRunResult(
                    all_collected_parts,
                    None,
                    stopped_early,
                    progress=completed_keys,
                )

        cache_complete = stopped_early is None and not early_stopped_event.is_set()
        if full_site_collection:
            if outgoing_cache is not None and outgoing_cache.get("complete") and cache_complete:
                old_parts = outgoing_cache["parts"]
                old_count = len(old_parts)
                new_count = len(all_collected_parts)
                if new_count < old_count * 0.5:
                    result.notices.append(
                        f"This site returned {new_count} parts where the saved copy had "
                        f"{old_count} — its layout may have changed."
                    )
                old_with_attributes = sum(bool(part.get("attributes")) for part in old_parts)
                if (
                    old_parts
                    and old_with_attributes > len(old_parts) * 0.5
                    and not any(part.attributes for part in all_collected_parts)
                ):
                    result.notices.append(
                        "Part specifications came back empty — the site may have "
                        "changed its layout."
                    )
            cache_payload = {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "crawl_seconds": collection_seconds,
                "complete": cache_complete,
                "parts": [asdict(part) for part in all_collected_parts],
            }
            if not cache_complete:
                cache_payload["progress"] = completed_keys
            store.save_web_cache(domain, cache_payload)

        run_record = {
            "source": domain,
            "kind": "web",
            "mode": "filter" if filter_sheet else "crawl",
            "parts": len(result.parts),
            "platform": config.platform,
            "data_source": "cache+resume" if resuming else "live",
        }
        if stopped_early is not None:
            run_record["stopped_early"] = stopped_early
        store.record_run(run_record)
        return result
