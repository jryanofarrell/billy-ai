from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from parts_parser.gui import worker as worker_module  # noqa: E402
from parts_parser.gui.worker import PipelineWorker, output_path_for  # noqa: E402
from parts_parser.pdf.extract import PdfError  # noqa: E402


def test_output_path_for_url_uses_downloads_and_domain(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    output_path = output_path_for(
        "https://catalog.example.com/products/fittings", is_url=True
    )

    assert output_path == tmp_path / "Downloads" / "catalog.example.com-parts.xlsx"


def test_output_path_for_pdf_uses_sibling_parts_suffix(tmp_path):
    pdf_path = tmp_path / "synthetic catalog.pdf"

    output_path = output_path_for(str(pdf_path), is_url=False)

    assert output_path == tmp_path / "synthetic catalog-parts.xlsx"


def test_output_path_for_uses_next_available_collision_number(tmp_path, monkeypatch):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    (downloads / "example.com-parts.xlsx").touch()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    second_path = output_path_for("https://example.com/catalog", is_url=True)
    second_path.touch()
    third_path = output_path_for("https://example.com/catalog", is_url=True)

    assert second_path == downloads / "example.com-parts (2).xlsx"
    assert third_path == downloads / "example.com-parts (3).xlsx"


def test_worker_success_emits_written_path_and_part_count(tmp_path, monkeypatch):
    pdf_path = tmp_path / "catalog.pdf"
    parts = [object(), object()]
    result = SimpleNamespace(parts=parts, match_report=None)
    writes = []
    monkeypatch.setattr(worker_module, "RunStore", object)
    monkeypatch.setattr(worker_module, "run_pdf", lambda *args, **kwargs: result)
    monkeypatch.setattr(
        worker_module,
        "write_workbook",
        lambda *args, **kwargs: writes.append((args, kwargs)),
    )
    worker = PipelineWorker(url=None, pdf_path=str(pdf_path), filter_path=None)
    succeeded = []
    worker.succeeded.connect(lambda path, count: succeeded.append((path, count)))

    worker.run()

    expected_path = tmp_path / "catalog-parts.xlsx"
    assert succeeded == [(str(expected_path), 2)]
    assert writes == [((parts, expected_path), {"mode": "pdf", "match_report": None})]


def test_worker_pdf_error_emits_plain_language_message(tmp_path, monkeypatch):
    message = "This PDF could not be read."
    monkeypatch.setattr(worker_module, "RunStore", object)

    def fail_pdf(*args, **kwargs):
        raise PdfError(message)

    monkeypatch.setattr(worker_module, "run_pdf", fail_pdf)
    worker = PipelineWorker(
        url=None, pdf_path=str(tmp_path / "catalog.pdf"), filter_path=None
    )
    failed = []
    worker.failed.connect(failed.append)

    worker.run()

    assert failed == [message]


def test_worker_unexpected_error_emits_exception_type(monkeypatch):
    monkeypatch.setattr(worker_module, "RunStore", object)

    def fail_web(*args, **kwargs):
        raise ValueError("internal detail")

    monkeypatch.setattr(worker_module, "run_web", fail_web)
    worker = PipelineWorker(
        url="https://example.com/catalog", pdf_path=None, filter_path=None
    )
    failed = []
    worker.failed.connect(failed.append)

    worker.run()

    assert len(failed) == 1
    assert "ValueError" in failed[0]
