import pytest

from parts_parser.pdf.extract import PdfError
from parts_parser.pdf.toc import find_toc_pages, parse_toc


class FakeLLM:
    def __init__(self, response: dict):
        self._response = response

    def complete_json(self, *, system: str, user: str, **kwargs) -> dict:
        return self._response


def _dotted_line(page_num: int) -> str:
    return f"Section Name .......... {page_num}"


def _make_dotted_page(count: int = 12) -> str:
    return "\n".join(_dotted_line(i + 1) for i in range(count))


def test_find_toc_pages_picks_dotted_leader_page():
    prose = "This is an introduction page with no dotted leaders at all."
    toc = _make_dotted_page(12)
    pages = [prose, toc, prose]

    indices = find_toc_pages(pages)

    assert indices == [1]


def test_find_toc_pages_ignores_prose_page():
    prose = "Just regular text with some numbers 1 2 3 but no dotted patterns."
    pages = [prose, prose]

    assert find_toc_pages(pages) == []


def test_find_toc_pages_picks_table_of_contents_header():
    header_page = "TABLE OF CONTENTS\nSome sections listed here"
    pages = [header_page]

    indices = find_toc_pages(pages)

    assert indices == [0]


def test_find_toc_pages_only_searches_first_15():
    late_toc = _make_dotted_page(12)
    pages = ["prose"] * 15 + [late_toc]

    assert find_toc_pages(pages) == []


def test_parse_toc_clamps_out_of_range_pages_and_fills_end_pages():
    canned = {
        "sections": [
            {"name": "Fittings", "category": "Fittings", "start_page": 1, "end_page": None},
            {"name": "Valves", "category": "Valves", "start_page": 5, "end_page": 999},
        ]
    }
    llm = FakeLLM(canned)

    sections = parse_toc(llm, "toc text", total_pages=10)

    assert len(sections) == 2
    assert sections[0].start_page == 1
    assert sections[0].end_page == 4
    assert sections[1].start_page == 5
    assert sections[1].end_page == 10


def test_parse_toc_drops_section_with_out_of_range_start():
    canned = {
        "sections": [
            {"name": "Valid", "category": "Fittings", "start_page": 2, "end_page": 5},
            {"name": "Beyond", "category": "Valves", "start_page": 999, "end_page": None},
        ]
    }
    llm = FakeLLM(canned)

    sections = parse_toc(llm, "toc text", total_pages=10)

    assert len(sections) == 1
    assert sections[0].name == "Valid"


def test_parse_toc_sorts_by_start_page():
    canned = {
        "sections": [
            {"name": "Z-Section", "category": "Z", "start_page": 8, "end_page": 10},
            {"name": "A-Section", "category": "A", "start_page": 1, "end_page": 7},
        ]
    }
    llm = FakeLLM(canned)

    sections = parse_toc(llm, "toc text", total_pages=10)

    assert sections[0].name == "A-Section"
    assert sections[1].name == "Z-Section"


def test_parse_toc_malformed_response_raises_pdf_error():
    llm = FakeLLM({"not_sections": []})

    with pytest.raises(PdfError):
        parse_toc(llm, "toc text", total_pages=10)


def test_parse_toc_non_list_sections_raises_pdf_error():
    llm = FakeLLM({"sections": "oops"})

    with pytest.raises(PdfError):
        parse_toc(llm, "toc text", total_pages=10)
