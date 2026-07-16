import re
from dataclasses import dataclass

from parts_parser.llm import LLMClient
from parts_parser.pdf.extract import PdfError

_TOC_DOTTED_RE = re.compile(r"\.{5,}\s*\d+\s*$", re.MULTILINE)
_TOC_HEADER_RE = re.compile(r"table of contents", re.IGNORECASE)

_SYSTEM = "You extract the section structure of a product-catalog table of contents. Respond with JSON only."
_USER_SUFFIX = (
    '\nReturn {"sections": [{"name": str, "category": str, "start_page": int, "end_page": int|null}]}.'
    ' "category" is the human product category the section covers'
    ' (e.g. "SECTION A FITTINGS" -> "Fittings").'
    " Use the page numbers printed in the contents. Order sections by start_page."
)


@dataclass
class Section:
    name: str
    category: str
    start_page: int
    end_page: int


def find_toc_pages(pages: list[str]) -> list[int]:
    """Return 0-based indices of TOC pages within the first 15 pages."""
    indices = []
    for i, text in enumerate(pages[:15]):
        if _TOC_HEADER_RE.search(text):
            indices.append(i)
        elif len(_TOC_DOTTED_RE.findall(text)) >= 10:
            indices.append(i)
    return indices


def parse_toc(llm: LLMClient, toc_text: str, total_pages: int) -> list[Section]:
    """Call the LLM once to parse TOC text into an ordered list of Sections."""
    user_prompt = toc_text + _USER_SUFFIX
    try:
        raw = llm.complete_json(system=_SYSTEM, user=user_prompt)
        raw_sections = raw["sections"]
        if not isinstance(raw_sections, list):
            raise ValueError("sections is not a list")
    except (KeyError, ValueError, TypeError) as exc:
        raise PdfError("Couldn't understand this catalog's table of contents.") from exc

    valid: list[dict] = []
    for item in raw_sections:
        try:
            start = int(item["start_page"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (1 <= start <= total_pages):
            continue
        valid.append(item)

    valid.sort(key=lambda s: int(s["start_page"]))

    sections: list[Section] = []
    for idx, item in enumerate(valid):
        start = int(item["start_page"])
        raw_end = item.get("end_page")
        if raw_end is None:
            end = None
        else:
            try:
                end = int(raw_end)
            except (TypeError, ValueError):
                end = None

        if end is None:
            if idx + 1 < len(valid):
                end = int(valid[idx + 1]["start_page"]) - 1
            else:
                end = total_pages
        else:
            end = min(end, total_pages)

        sections.append(
            Section(
                name=str(item.get("name", "")),
                category=str(item.get("category", "")),
                start_page=start,
                end_page=end,
            )
        )

    return sections


def section_for_page(sections: list[Section], page_no: int) -> "Section | None":
    """Return the Section containing 1-based page_no, or None."""
    for section in sections:
        if section.start_page <= page_no <= section.end_page:
            return section
    return None
