import dataclasses
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from parts_parser.llm import LLMClient, get_client
from parts_parser.models import PartRecord
from parts_parser.output.filtering import FilterSheet, MatchReport, match_parts
from parts_parser.pdf.extract import PdfError, extract_text, is_digital
from parts_parser.pdf.pages import PageResult, extract_page_parts
from parts_parser.pdf.toc import find_toc_pages, parse_toc, section_for_page
from parts_parser.pdf.validate import validate_parts
from parts_parser.store import RunStore, hash_file


@dataclass
class PdfRunResult:
    parts: list[PartRecord]
    match_report: MatchReport | None
    validation: dict


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

    if cached:
        parts = [PartRecord(**d) for d in cached["parts"]]
        validation = cached["validation"]
    else:
        llm = llm or get_client()
        pages = extract_text(path)

        if not is_digital(pages):
            raise PdfError(
                "This PDF looks like scanned images, not text. "
                "Scanned catalogs aren't supported yet."
            )

        toc_idx = find_toc_pages(pages)
        sections = (
            parse_toc(llm, "\n".join(pages[i] for i in toc_idx), len(pages))
            if toc_idx
            else []
        )

        page_results: list[PageResult] = []
        for i, text in enumerate(pages):
            if cancel is not None and cancel.is_set():
                raise PdfError("Cancelled.")
            progress(f"Reading page {i + 1} of {len(pages)}…", i / len(pages))
            if len("".join(text.split())) < 40:
                page_results.append(
                    PageResult(
                        page_no=i + 1,
                        subcategory="",
                        parts=[],
                        skipped=True,
                        skip_reason="blank",
                    )
                )
                continue
            section = section_for_page(sections, i + 1)
            category = section.category if section is not None else ""
            page_results.append(extract_page_parts(llm, text, i + 1, category))

        parts, report = validate_parts(page_results, pages, sections)
        validation = dataclasses.asdict(report)
        store.save_pdf_cache(
            file_hash,
            {"parts": [dataclasses.asdict(p) for p in parts], "validation": validation},  # type: ignore[arg-type]
        )

    store.record_run(
        {
            "source": path.name,
            "kind": "pdf",
            "parts": len(parts),
            "cache_hit": bool(cached),
        }
    )

    if filter_sheet is not None:
        matched, match_report = match_parts(filter_sheet, parts)
        return PdfRunResult(parts=matched, match_report=match_report, validation=validation)

    return PdfRunResult(parts=parts, match_report=None, validation=validation)
