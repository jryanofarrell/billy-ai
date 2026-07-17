import logging
import threading
from pathlib import Path

import pytest

from parts_parser.llm import LLMError
from parts_parser.output.filtering import FilterEntry, FilterSheet, MatchReport
from parts_parser.pdf.extract import PdfError
from parts_parser.pdf.pipeline import run_pdf
from parts_parser.store import RunStore, hash_file


_FIXTURES = Path(__file__).parent / "fixtures" / "pdf"


class FakeLLM:
    def __init__(
        self,
        responses: list[dict | Exception],
        *,
        cancel_after_call: tuple[threading.Event, int] | None = None,
    ) -> None:
        self._queue = list(responses)
        self.call_count = 0
        self.cancel_after_call = cancel_after_call

    def complete_json(self, *, system: str, user: str, **kwargs) -> dict:
        self.call_count += 1
        response = self._queue.pop(0)
        if self.cancel_after_call is not None:
            event, call_number = self.cancel_after_call
            if self.call_count == call_number:
                event.set()
        if isinstance(response, Exception):
            raise response
        return response


def _parts_resp(part_nos: list[str], subcategory: str = "Test Fittings") -> dict:
    return {
        "subcategory": subcategory,
        "parts": [{"part_no": pn, "series": "Series A", "description": "desc"} for pn in part_nos],
        "skip_reason": None,
    }


def _skip_resp(reason: str = "marketing page") -> dict:
    return {"subcategory": "", "parts": [], "skip_reason": reason}


def _toc_resp() -> dict:
    return {
        "sections": [
            {
                "name": "Synthetic Fittings",
                "category": "Fittings",
                "start_page": 1,
                "end_page": None,
            }
        ]
    }


def _prose_page(part_no: str) -> str:
    return f"""Synthetic specialty component

This component is selected for unusual installations where an ordinary table
does not describe the available configuration. Consult the application notes
for material compatibility, operating limits, inspection intervals, assembly
steps, and safe handling requirements. The catalog identifies the available
component as {part_no}, followed by additional prose about installation and
maintenance. This synthetic page deliberately has enough readable text to be
treated as a digital catalog page while requiring structured AI extraction.
"""


def _make_pdf(tmp_path: Path) -> Path:
    p = tmp_path / "catalog.pdf"
    p.write_bytes(b"SYNTHETIC-PDF-BYTES-FOR-HASHING")
    return p


@pytest.fixture()
def store(tmp_path):
    return RunStore(root=tmp_path / "store")


def test_all_regular_pages_use_llm_only_for_toc_and_write_deterministic_cache(
    tmp_path, store, monkeypatch
):
    single_text = (_FIXTURES / "page_single_size.txt").read_text()
    two_text = (_FIXTURES / "page_two_size.txt").read_text()
    pages = ["Table of Contents", single_text, two_text]
    monkeypatch.setattr("parts_parser.pdf.pipeline.extract_text", lambda _path: pages)

    pdf_path = _make_pdf(tmp_path)
    llm = FakeLLM([_toc_resp()])

    result = run_pdf(pdf_path, store=store, llm=llm)

    expected_part_nos = [
        "XX-100-A",
        "XX-101-A",
        "XX-200-A",
        "XX-201-A",
        "XX-210-A",
        "XX-211-A",
    ]
    assert llm.call_count == 1
    assert [part.part_no for part in result.parts] == expected_part_nos
    assert [part.sequence for part in result.parts] == list(range(1, 7))
    cache = store.get_pdf_cache(hash_file(pdf_path))
    assert cache["complete"] is True
    assert [part["part_no"] for part in cache["parts"]] == expected_part_nos


def test_fallback_page_merges_with_deterministic_parts_in_page_order_and_cache(
    tmp_path, store, monkeypatch
):
    single_text = (_FIXTURES / "page_single_size.txt").read_text()
    two_text = (_FIXTURES / "page_two_size.txt").read_text()
    prose_text = _prose_page("SPECIAL-300-A")
    pages = ["Table of Contents", single_text, prose_text, two_text]
    monkeypatch.setattr("parts_parser.pdf.pipeline.extract_text", lambda _path: pages)

    pdf_path = _make_pdf(tmp_path)
    llm = FakeLLM([_toc_resp(), _parts_resp(["SPECIAL-300-A"], "Specialty")])

    result = run_pdf(pdf_path, store=store, llm=llm)

    expected_part_nos = [
        "XX-100-A",
        "XX-101-A",
        "SPECIAL-300-A",
        "XX-200-A",
        "XX-201-A",
        "XX-210-A",
        "XX-211-A",
    ]
    assert llm.call_count == 2
    assert [part.part_no for part in result.parts] == expected_part_nos
    assert [part.sequence for part in result.parts] == list(range(1, 8))
    cache = store.get_pdf_cache(hash_file(pdf_path))
    assert cache["complete"] is True
    assert [part["part_no"] for part in cache["parts"]] == expected_part_nos
    assert [part["sequence"] for part in cache["parts"]] == list(range(1, 8))


def test_fallback_reason_and_run_summary_are_logged(tmp_path, store, monkeypatch, caplog):
    single_text = (_FIXTURES / "page_single_size.txt").read_text()
    prose_text = _prose_page("SPECIAL-300-A")
    pages = ["Table of Contents", single_text, prose_text]
    monkeypatch.setattr("parts_parser.pdf.pipeline.extract_text", lambda _path: pages)

    pdf_path = _make_pdf(tmp_path)
    llm = FakeLLM([_toc_resp(), _parts_resp(["SPECIAL-300-A"], "Specialty")])

    with caplog.at_level(logging.INFO, logger="parts_parser.pdf.pipeline"):
        run_pdf(pdf_path, store=store, llm=llm)

    messages = [record.getMessage() for record in caplog.records]
    fallback_lines = [message for message in messages if "AI fallback —" in message]
    assert fallback_lines == [
        "page 3/3: AI fallback — substantial page text produced no parts "
        "(deterministic pass found 0 parts)"
    ]
    assert "catalog.pdf: 3 pages — 1 deterministic, 1 AI fallback, 1 blank" in messages


def test_second_run_hits_cache_makes_zero_llm_calls_returns_same_parts(
    tmp_path, store, monkeypatch
):
    single_text = (_FIXTURES / "page_single_size.txt").read_text()
    two_text = (_FIXTURES / "page_two_size.txt").read_text()
    pages = [single_text, two_text]
    monkeypatch.setattr("parts_parser.pdf.pipeline.extract_text", lambda _path: pages)

    pdf_path = _make_pdf(tmp_path)
    first_llm = FakeLLM([])
    first_result = run_pdf(pdf_path, store=store, llm=first_llm)

    second_llm = FakeLLM([])
    second_result = run_pdf(pdf_path, store=store, llm=second_llm)

    assert second_llm.call_count == 0
    assert [p.part_no for p in second_result.parts] == [p.part_no for p in first_result.parts]
    assert [p.sequence for p in second_result.parts] == [p.sequence for p in first_result.parts]


def test_partial_llm_failure_is_cached_incomplete_and_reparsed_on_next_run(
    tmp_path, store, monkeypatch
):
    first_page = _prose_page("XX-100-A")
    second_page = _prose_page("XX-101-A")
    monkeypatch.setattr(
        "parts_parser.pdf.pipeline.extract_text", lambda _path: [first_page, second_page]
    )
    pdf_path = _make_pdf(tmp_path)

    failed_llm = FakeLLM(
        [_parts_resp(["XX-100-A"]), LLMError("AI service unavailable")]
    )
    partial = run_pdf(pdf_path, store=store, llm=failed_llm)

    assert [part.part_no for part in partial.parts] == ["XX-100-A"]
    assert partial.stopped_early is not None
    assert "page 2" in partial.stopped_early
    cache = store.get_pdf_cache(hash_file(pdf_path))
    assert cache["complete"] is False

    clean_llm = FakeLLM([_parts_resp(["XX-100-A"]), _parts_resp(["XX-101-A"])])
    complete = run_pdf(pdf_path, store=store, llm=clean_llm)

    assert clean_llm.call_count == 2
    assert [part.part_no for part in complete.parts] == ["XX-100-A", "XX-101-A"]
    assert complete.stopped_early is None
    assert store.get_pdf_cache(hash_file(pdf_path))["complete"] is True


def test_clean_cache_is_served_without_llm_calls(tmp_path, store, monkeypatch):
    page = _prose_page("XX-100-A")
    monkeypatch.setattr("parts_parser.pdf.pipeline.extract_text", lambda _path: [page])
    pdf_path = _make_pdf(tmp_path)

    run_pdf(pdf_path, store=store, llm=FakeLLM([_parts_resp(["XX-100-A"])]))
    cached_llm = FakeLLM([])
    cached = run_pdf(pdf_path, store=store, llm=cached_llm)

    assert cached_llm.call_count == 0
    assert [part.part_no for part in cached.parts] == ["XX-100-A"]
    assert store.get_pdf_cache(hash_file(pdf_path))["complete"] is True


def test_scanned_pdf_raises_pdf_error_mentioning_scanned(tmp_path, store, monkeypatch):
    monkeypatch.setattr("parts_parser.pdf.pipeline.extract_text", lambda _path: ["", "tiny"])

    pdf_path = _make_pdf(tmp_path)
    with pytest.raises(PdfError, match="scanned"):
        run_pdf(pdf_path, store=store, llm=FakeLLM([]))


def test_filter_sheet_returns_match_report_and_filters_parts(tmp_path, store, monkeypatch):
    single_text = (_FIXTURES / "page_single_size.txt").read_text()
    monkeypatch.setattr("parts_parser.pdf.pipeline.extract_text", lambda _path: [single_text])

    pdf_path = _make_pdf(tmp_path)
    llm = FakeLLM([_parts_resp(["XX-100-A", "XX-101-A"])])

    filter_sheet = FilterSheet(
        path=Path("dummy.xlsx"),
        column_label='column A ("Part No")',
        entries=[FilterEntry(raw="XX-100-A", normalized="XX100A", row=2)],
    )

    result = run_pdf(pdf_path, store=store, llm=llm, filter_sheet=filter_sheet)

    assert isinstance(result.match_report, MatchReport)
    assert len(result.parts) == 1
    assert result.parts[0].part_no == "XX-100-A"


def test_blank_page_skips_llm_call(tmp_path, store, monkeypatch):
    # A page of spaces passes is_digital (len >= 200) but fails the non-whitespace check (< 40)
    blank_page = " " * 300
    single_text = (_FIXTURES / "page_single_size.txt").read_text()
    pages = [blank_page, single_text]
    monkeypatch.setattr("parts_parser.pdf.pipeline.extract_text", lambda _path: pages)

    pdf_path = _make_pdf(tmp_path)
    llm = FakeLLM([])

    result = run_pdf(pdf_path, store=store, llm=llm)

    assert llm.call_count == 0
    assert len(result.parts) == 2


def test_cancel_mid_loop_returns_partial_and_writes_incomplete_cache(
    tmp_path, store, monkeypatch
):
    pages = [_prose_page("XX-100-A"), _prose_page("XX-101-A")]
    monkeypatch.setattr("parts_parser.pdf.pipeline.extract_text", lambda _path: pages)

    pdf_path = _make_pdf(tmp_path)
    cancel = threading.Event()
    llm = FakeLLM(
        [_parts_resp(["XX-100-A"])],
        cancel_after_call=(cancel, 1),
    )

    result = run_pdf(pdf_path, store=store, llm=llm, cancel=cancel)

    assert [part.part_no for part in result.parts] == ["XX-100-A"]
    assert result.stopped_early is not None
    assert "Cancelled" in result.stopped_early
    assert store.get_pdf_cache(hash_file(pdf_path))["complete"] is False


def test_llm_failure_on_first_content_page_raises(tmp_path, store, monkeypatch):
    page = _prose_page("XX-100-A")
    monkeypatch.setattr("parts_parser.pdf.pipeline.extract_text", lambda _path: [page])
    pdf_path = _make_pdf(tmp_path)

    with pytest.raises(LLMError, match="AI service unavailable"):
        run_pdf(
            pdf_path,
            store=store,
            llm=FakeLLM([LLMError("AI service unavailable")]),
        )
