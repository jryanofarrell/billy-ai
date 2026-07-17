from dataclasses import dataclass, field

from parts_parser.models import PartRecord
from parts_parser.pdf.pages import PageResult
from parts_parser.pdf.toc import Section, section_for_page


@dataclass
class ValidationReport:
    total_parts: int
    pages_processed: int
    pages_skipped: int
    pages_deterministic: int
    pages_ai_page: int
    pages_ai_lines: int
    pages_blank: int
    dropped_not_on_page: list[tuple[int, str]] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)


def validate_parts(
    page_results: list[PageResult],
    pages_text: list[str],
    sections: list[Section],
) -> tuple[list[PartRecord], ValidationReport]:
    def squash(s: str) -> str:
        return "".join(s.split())

    emitted: list[PartRecord] = []
    seen_part_nos: set[str] = set()
    dropped_not_on_page: list[tuple[int, str]] = []
    duplicates: list[str] = []
    pages_skipped = 0

    for result in page_results:
        if result.skipped:
            pages_skipped += 1
            continue

        page_squashed = squash(pages_text[result.page_no - 1])
        section = section_for_page(sections, result.page_no)
        category = section.category if section else ""

        for raw in result.parts:
            if squash(raw.part_no) not in page_squashed:
                dropped_not_on_page.append((result.page_no, raw.part_no))
                continue
            if raw.part_no in seen_part_nos:
                duplicates.append(raw.part_no)
                continue
            seen_part_nos.add(raw.part_no)
            emitted.append(
                PartRecord(
                    part_no=raw.part_no,
                    category=category,
                    subcategory=result.subcategory,
                    series=raw.series,
                    description=raw.description,
                )
            )

    for i, record in enumerate(emitted, start=1):
        record.sequence = i

    pages_processed = sum(1 for r in page_results if not r.skipped)
    pages_ai_page = sum(1 for r in page_results if r.ai_mode == "page")
    pages_ai_lines = sum(1 for r in page_results if r.ai_mode == "lines")
    pages_blank = sum(1 for r in page_results if r.ai_mode is None and r.skipped and not r.parts)
    pages_deterministic = sum(1 for r in page_results if r.ai_mode is None and not r.skipped)

    report = ValidationReport(
        total_parts=len(emitted),
        pages_processed=pages_processed,
        pages_skipped=pages_skipped,
        pages_deterministic=pages_deterministic,
        pages_ai_page=pages_ai_page,
        pages_ai_lines=pages_ai_lines,
        pages_blank=pages_blank,
        dropped_not_on_page=dropped_not_on_page,
        duplicates=duplicates,
    )
    return emitted, report
