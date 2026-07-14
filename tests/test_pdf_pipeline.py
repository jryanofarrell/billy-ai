import threading
from pathlib import Path

import pytest

from parts_parser.output.filtering import FilterEntry, FilterSheet, MatchReport
from parts_parser.pdf.extract import PdfError
from parts_parser.pdf.pipeline import PdfRunResult, run_pdf
from parts_parser.store import RunStore, hash_file


_FIXTURES = Path(__file__).parent / "fixtures" / "pdf"


class FakeLLM:
    def __init__(self, responses: list[dict]) -> None:
        self._queue = list(responses)
        self.call_count = 0

    def complete_json(self, *, system: str, user: str, **kwargs) -> dict:
        self.call_count += 1
        return self._queue.pop(0)


def _parts_resp(part_nos: list[str], subcategory: str = "Test Fittings") -> dict:
    return {
        "subcategory": subcategory,
        "parts": [{"part_no": pn, "series": "Series A", "description": "desc"} for pn in part_nos],
        "skip_reason": None,
    }


def _skip_resp(reason: str = "marketing page") -> dict:
    return {"subcategory": "", "parts": [], "skip_reason": reason}


def _make_pdf(tmp_path: Path) -> Path:
    p = tmp_path / "catalog.pdf"
    p.write_bytes(b"SYNTHETIC-PDF-BYTES-FOR-HASHING")
    return p


@pytest.fixture()
def store(tmp_path):
    return RunStore(root=tmp_path / "store")


def test_full_run_produces_parts_with_sequence_and_writes_cache(tmp_path, store, monkeypatch):
    single_text = (_FIXTURES / "page_single_size.txt").read_text()
    two_text = (_FIXTURES / "page_two_size.txt").read_text()
    pages = [single_text, two_text]
    monkeypatch.setattr("parts_parser.pdf.pipeline.extract_text", lambda _path: pages)

    pdf_path = _make_pdf(tmp_path)
    llm = FakeLLM([
        _parts_resp(["XX-100-A", "XX-101-A"], "Compression Straight"),
        _parts_resp(["XX-200-A", "XX-201-A"], "Compression Elbow"),
    ])

    result = run_pdf(pdf_path, store=store, llm=llm)

    assert len(result.parts) == 4
    assert [p.sequence for p in result.parts] == [1, 2, 3, 4]
    assert [p.part_no for p in result.parts] == ["XX-100-A", "XX-101-A", "XX-200-A", "XX-201-A"]
    assert store.get_pdf_cache(hash_file(pdf_path)) is not None


def test_second_run_hits_cache_makes_zero_llm_calls_returns_same_parts(tmp_path, store, monkeypatch):
    single_text = (_FIXTURES / "page_single_size.txt").read_text()
    two_text = (_FIXTURES / "page_two_size.txt").read_text()
    pages = [single_text, two_text]
    monkeypatch.setattr("parts_parser.pdf.pipeline.extract_text", lambda _path: pages)

    pdf_path = _make_pdf(tmp_path)
    first_llm = FakeLLM([
        _parts_resp(["XX-100-A", "XX-101-A"]),
        _parts_resp(["XX-200-A", "XX-201-A"]),
    ])
    first_result = run_pdf(pdf_path, store=store, llm=first_llm)

    second_llm = FakeLLM([])
    second_result = run_pdf(pdf_path, store=store, llm=second_llm)

    assert second_llm.call_count == 0
    assert [p.part_no for p in second_result.parts] == [p.part_no for p in first_result.parts]
    assert [p.sequence for p in second_result.parts] == [p.sequence for p in first_result.parts]


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
    llm = FakeLLM([_parts_resp(["XX-100-A", "XX-101-A"])])

    result = run_pdf(pdf_path, store=store, llm=llm)

    assert llm.call_count == 1
    assert len(result.parts) == 2


def test_cancel_event_aborts_run(tmp_path, store, monkeypatch):
    single_text = (_FIXTURES / "page_single_size.txt").read_text()
    pages = [single_text, single_text]
    monkeypatch.setattr("parts_parser.pdf.pipeline.extract_text", lambda _path: pages)

    pdf_path = _make_pdf(tmp_path)
    cancel = threading.Event()
    cancel.set()

    with pytest.raises(PdfError, match="Cancelled"):
        run_pdf(pdf_path, store=store, llm=FakeLLM([]), cancel=cancel)
