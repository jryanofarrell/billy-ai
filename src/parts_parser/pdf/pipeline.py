import dataclasses
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from parts_parser.llm import LLMClient, LLMError, get_client
from parts_parser.models import PartRecord
from parts_parser.output.filtering import FilterSheet, MatchReport, match_parts
from parts_parser.pdf.extract import PdfError, extract_text, is_digital
from parts_parser.pdf.pages import PageResult, extract_page_parts, extract_suspicious_lines
from parts_parser.pdf.tables import parse_page_tables
from parts_parser.pdf.toc import find_toc_pages, parse_toc, section_for_page
from parts_parser.pdf.validate import validate_parts
from parts_parser.store import RunStore, hash_file

logger = logging.getLogger(__name__)


@dataclass
class PdfRunResult:
    parts: list[PartRecord]
    match_report: MatchReport | None
    validation: dict
    stopped_early: str | None = None


class _Cancelled(Exception):
    """Signal that page extraction stopped at the operator's request."""


def run_pdf(
    path: Path,
    *,
    store: RunStore,
    llm: LLMClient | None = None,
    filter_sheet: FilterSheet | None = None,
    progress: Callable[[str, float], None] = lambda m, f: None,
    cancel: threading.Event | None = None,
) -> PdfRunResult:
    file_hash = hash_file(path)
    cached = store.get_pdf_cache(file_hash)
    cache_hit = bool(cached and cached.get("complete") is True)
    stopped_early: str | None = None

    if cache_hit:
        assert cached is not None
        parts = [PartRecord(**d) for d in cached["parts"]]
        validation = cached["validation"]
    else:
        pages = extract_text(path)

        if not is_digital(pages):
            raise PdfError(
                "This PDF looks like scanned images, not text. "
                "Scanned catalogs aren't supported yet."
            )

        toc_idx = find_toc_pages(pages)
        if toc_idx:
            llm = llm or get_client()
            sections = parse_toc(llm, "\n".join(pages[i] for i in toc_idx), len(pages))
        else:
            sections = []

        page_results: list[PageResult] = []
        current_page = 1
        try:
            for i, text in enumerate(pages):
                current_page = i + 1
                if cancel is not None and cancel.is_set():
                    raise _Cancelled
                progress(f"Reading page {current_page} of {len(pages)}…", i / len(pages))
                if len("".join(text.split())) < 40:
                    logger.debug("page %d/%d: skipped (blank)", current_page, len(pages))
                    page_results.append(
                        PageResult(
                            page_no=current_page,
                            subcategory="",
                            parts=[],
                            skipped=True,
                            skip_reason="blank",
                        )
                    )
                    continue
                section = section_for_page(sections, current_page)
                category = section.category if section is not None else ""
                page_title = next(
                    (line.strip() for line in text.splitlines() if line.strip()),
                    "",
                )
                scan = parse_page_tables(text)
                suspicious_count = len(scan.suspicious)
                fallback_reasons = list(
                    dict.fromkeys(line.reason for line in scan.suspicious)
                )
                use_page_ai = (
                    not scan.parts and scan.word_count >= 40
                ) or (
                    suspicious_count >= 3
                    and suspicious_count / (len(scan.parts) + suspicious_count) >= 0.2
                )

                if use_page_ai:
                    if not fallback_reasons:
                        fallback_reasons = ["substantial page text produced no parts"]
                    logger.info(
                        "page %d/%d: AI page fallback — %s "
                        "(deterministic pass found %d parts)",
                        current_page,
                        len(pages),
                        "; ".join(fallback_reasons),
                        len(scan.parts),
                    )
                    progress(
                        f"Reading page {current_page} of {len(pages)} (AI)…",
                        i / len(pages),
                    )
                    llm = llm or get_client()
                    page_result = extract_page_parts(llm, text, current_page, category)
                    page_result.ai_mode = "page"
                    page_result.fallback_reasons = fallback_reasons
                elif suspicious_count:
                    line_reasons = [
                        f"line {line.line_no}: {line.reason}"
                        for line in scan.suspicious
                    ]
                    logger.info(
                        "page %d/%d: AI lines fallback — %s "
                        "(deterministic pass found %d parts)",
                        current_page,
                        len(pages),
                        "; ".join(line_reasons),
                        len(scan.parts),
                    )
                    progress(
                        f"Reading page {current_page} of {len(pages)} (AI)…",
                        i / len(pages),
                    )
                    llm = llm or get_client()
                    extra = extract_suspicious_lines(
                        llm,
                        current_page,
                        category,
                        page_title,
                        scan.header_line,
                        scan.suspicious,
                    )
                    positioned_parts = list(zip(scan.part_lines, scan.parts))
                    positioned_parts.extend(extra)
                    positioned_parts.sort(key=lambda item: item[0])
                    merged_parts = [part for _, part in positioned_parts]
                    page_result = PageResult(
                        page_no=current_page,
                        subcategory=page_title,
                        parts=merged_parts,
                        skipped=not merged_parts,
                        skip_reason=None,
                        ai_mode="lines",
                        fallback_reasons=line_reasons,
                    )
                else:
                    logger.debug(
                        "page %d/%d: deterministic, %d parts",
                        current_page,
                        len(pages),
                        len(scan.parts),
                    )
                    page_result = PageResult(
                        page_no=current_page,
                        subcategory=page_title,
                        parts=scan.parts,
                        skipped=not scan.parts,
                        skip_reason=None,
                    )
                page_results.append(page_result)
        except _Cancelled:
            stopped_early = f"Cancelled on page {current_page} of {len(pages)}."
        except LLMError as error:
            if not page_results:
                raise
            stopped_early = f"Stopped on page {current_page} of {len(pages)} ({error})."

        parts, report = validate_parts(page_results, pages, sections)
        logger.info(
            "%s: %d pages — %d deterministic, %d AI page, %d AI lines, %d blank",
            path.name,
            len(pages),
            report.pages_deterministic,
            report.pages_ai_page,
            report.pages_ai_lines,
            report.pages_blank,
        )
        validation = dataclasses.asdict(report)
        store.save_pdf_cache(
            file_hash,
            {
                "parts": [dataclasses.asdict(p) for p in parts],
                "validation": validation,
                "complete": stopped_early is None,
            },  # type: ignore[arg-type]
        )

    run_record = {
        "source": path.name,
        "kind": "pdf",
        "parts": len(parts),
        "cache_hit": cache_hit,
    }
    if stopped_early is not None:
        run_record["stopped_early"] = stopped_early
    store.record_run(run_record)

    if filter_sheet is not None:
        matched, match_report = match_parts(filter_sheet, parts)
        return PdfRunResult(
            parts=matched,
            match_report=match_report,
            validation=validation,
            stopped_early=stopped_early,
        )

    return PdfRunResult(
        parts=parts,
        match_report=None,
        validation=validation,
        stopped_early=stopped_early,
    )
