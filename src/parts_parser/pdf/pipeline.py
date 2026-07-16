import dataclasses
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from parts_parser.llm import LLMClient, LLMError, get_client
from parts_parser.models import PartRecord
from parts_parser.output.filtering import FilterSheet, MatchReport, match_parts
from parts_parser.pdf.extract import PdfError, extract_text, is_digital
from parts_parser.pdf.pages import PageResult, extract_page_parts
from parts_parser.pdf.tables import parse_page_tables
from parts_parser.pdf.toc import find_toc_pages, parse_toc, section_for_page
from parts_parser.pdf.validate import validate_parts
from parts_parser.store import RunStore, hash_file


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
                det_parts, reasons = parse_page_tables(text)
                if reasons:
                    progress(
                        f"Reading page {current_page} of {len(pages)} (AI)…",
                        i / len(pages),
                    )
                    llm = llm or get_client()
                    page_result = extract_page_parts(llm, text, current_page, category)
                else:
                    page_title = next(
                        (line.strip() for line in text.splitlines() if line.strip()),
                        "",
                    )
                    page_result = PageResult(
                        page_no=current_page,
                        subcategory=page_title,
                        parts=det_parts,
                        skipped=not det_parts,
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
