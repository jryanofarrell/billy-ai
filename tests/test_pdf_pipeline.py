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
        self.calls: list[dict] = []
        self.cancel_after_call = cancel_after_call

    def complete_json(self, *, system: str, user: str, **kwargs) -> dict:
        self.call_count += 1
        self.calls.append({"system": system, "user": user, **kwargs})
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


def _line_resp(line_no: int, part_no: str) -> dict:
    return {
        "lines": [
            {
                "line_no": line_no,
                "parts": [{"part_no": part_no, "series": "", "description": "recovered"}],
            }
        ]
    }


def _table_page(*extra_lines: str) -> str:
    rows = [
        "ZX-100-A 1/4 1",
        "ZX-100-B 3/8 2",
        "ZX-100-C 1/2 3",
        "ZX-100-D 3/4 4",
        "ZX-100-E 1 5",
        "ZX-100-F 1-1/4 6",
    ]
    note = (
        "Notes: Synthetic catalog dimensions are provided only for testing and "
        "installation examples require ordinary verification before use."
    )
    return "\n".join(["Synthetic Fittings", "PART No. Size Qty", *rows, note, *extra_lines])


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
    assert llm.calls[0].get("reasoning_effort") is None
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


def test_validation_reports_each_page_decision_path(tmp_path, store, monkeypatch):
    single_text = (_FIXTURES / "page_single_size.txt").read_text()
    prose_text = _prose_page("SPECIAL-300-A")
    pages = ["Table of Contents", single_text, prose_text]
    monkeypatch.setattr("parts_parser.pdf.pipeline.extract_text", lambda _path: pages)

    pdf_path = _make_pdf(tmp_path)
    llm = FakeLLM([_toc_resp(), _parts_resp(["SPECIAL-300-A"], "Specialty")])

    result = run_pdf(pdf_path, store=store, llm=llm)

    assert llm.calls[0].get("reasoning_effort") is None
    assert llm.calls[1]["reasoning_effort"] == "minimal"
    assert [part.part_no for part in result.parts] == [
        "XX-100-A",
        "XX-101-A",
        "SPECIAL-300-A",
    ]
    assert result.validation["pages_deterministic"] == 1
    assert result.validation["pages_ai_page"] == 1
    assert result.validation["pages_ai_lines"] == 0
    assert result.validation["pages_blank"] == 1


def test_measurement_spec_line_does_not_trigger_ai(tmp_path, store, monkeypatch):
    page = _table_page("Width: 14.5 In.")
    monkeypatch.setattr("parts_parser.pdf.pipeline.extract_text", lambda _path: [page])
    llm = FakeLLM([])

    result = run_pdf(_make_pdf(tmp_path), store=store, llm=llm)

    assert llm.call_count == 0
    assert [part.part_no for part in result.parts] == [
        "ZX-100-A", "ZX-100-B", "ZX-100-C", "ZX-100-D", "ZX-100-E", "ZX-100-F"
    ]
    assert result.validation["pages_deterministic"] == 1
    assert result.validation["pages_ai_page"] == 0
    assert result.validation["pages_ai_lines"] == 0
    assert result.validation["pages_blank"] == 0


def test_suspicious_rows_use_one_numbered_line_call_and_merge_in_source_order(
    tmp_path, store, monkeypatch
):
    page = "\n".join(
        [
            "Synthetic Fittings",
            "PART No. Size Qty",
            "ZX-100-A 1/4 1",
            "ODD@CODE 3/8 2",
            "ZX-100-B 1/2 3",
            "ZX-100-C 3/4 4",
            "ZX-100-D 1 5",
            "ZX-100-E 1-1/4 6",
            "Notes: Synthetic dimensions and quantities are included only for "
            "testing this catalog workflow and require verification before use.",
        ]
    )
    monkeypatch.setattr("parts_parser.pdf.pipeline.extract_text", lambda _path: [page])
    llm = FakeLLM([_line_resp(4, "ODD@CODE")])

    result = run_pdf(_make_pdf(tmp_path), store=store, llm=llm)

    assert llm.call_count == 1
    assert '4 (under "Synthetic Fittings"): ODD@CODE 3/8 2' in llm.calls[0]["user"]
    assert llm.calls[0]["reasoning_effort"] == "minimal"
    assert [part.part_no for part in result.parts] == [
        "ZX-100-A", "ODD@CODE", "ZX-100-B", "ZX-100-C", "ZX-100-D", "ZX-100-E"
    ]
    assert result.validation["pages_ai_lines"] == 1


def test_many_suspicious_rows_use_whole_page_ai(tmp_path, store, monkeypatch):
    page = _table_page(
        "ODD@A 1/4 1", "ODD@B 3/8 2", "ODD@C 1/2 3", "ODD@D 3/4 4", "ODD@E 1 5"
    )
    monkeypatch.setattr("parts_parser.pdf.pipeline.extract_text", lambda _path: [page])
    llm = FakeLLM([_parts_resp(["ZX-100-A", "ODD@A", "ZX-100-F"])])

    result = run_pdf(_make_pdf(tmp_path), store=store, llm=llm)

    assert llm.call_count == 1
    assert llm.calls[0]["reasoning_effort"] == "minimal"
    assert [part.part_no for part in result.parts] == ["ZX-100-A", "ODD@A", "ZX-100-F"]
    assert result.validation["pages_ai_page"] == 1
    assert result.validation["pages_ai_lines"] == 0


def test_substantial_zero_part_page_uses_whole_page_ai(tmp_path, store, monkeypatch):
    page = _prose_page("SPECIAL-XyZ-7")
    monkeypatch.setattr("parts_parser.pdf.pipeline.extract_text", lambda _path: [page])
    llm = FakeLLM([_parts_resp(["SPECIAL-XyZ-7"])])

    result = run_pdf(_make_pdf(tmp_path), store=store, llm=llm)

    assert llm.call_count == 1
    assert llm.calls[0]["reasoning_effort"] == "minimal"
    assert [part.part_no for part in result.parts] == ["SPECIAL-XyZ-7"]
    assert result.validation["pages_ai_page"] == 1


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

    failed_llm = FakeLLM([_parts_resp(["XX-100-A"]), LLMError("AI service unavailable")])
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


def test_cancel_mid_loop_returns_partial_and_writes_incomplete_cache(tmp_path, store, monkeypatch):
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
