import threading
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402

from parts_parser.gui import worker as worker_module  # noqa: E402
from parts_parser.gui.worker import PipelineWorker, output_path_for  # noqa: E402
from parts_parser.pdf.extract import PdfError  # noqa: E402


@pytest.fixture(autouse=True)
def fake_keep_awake(monkeypatch):
    monkeypatch.setattr(worker_module, "keep_awake", nullcontext)


def test_output_path_for_uses_downloads_and_name(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    output_path = output_path_for("catalog.example.com")

    assert output_path == tmp_path / "Downloads" / "catalog.example.com-parts.xlsx"


def test_output_path_for_uses_next_available_collision_number(tmp_path, monkeypatch):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    (downloads / "example.com-parts.xlsx").touch()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    second_path = output_path_for("example.com")
    second_path.touch()
    third_path = output_path_for("example.com")

    assert second_path == downloads / "example.com-parts (2).xlsx"
    assert third_path == downloads / "example.com-parts (3).xlsx"


def test_worker_clean_success_emits_path_part_count_and_empty_warning(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    pdf_path = tmp_path / "catalog.pdf"
    parts = [object(), object()]
    result = SimpleNamespace(parts=parts, match_report=None, stopped_early=None)
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
    worker.succeeded.connect(
        lambda path, count, warning: succeeded.append((path, count, warning))
    )

    worker.run()

    expected_path = tmp_path / "Downloads" / "catalog-parts.xlsx"
    assert succeeded == [(str(expected_path), 2, "")]
    assert writes == [((parts, expected_path), {"mode": "pdf", "match_report": None})]
    assert expected_path.parent.is_dir()  # worker creates Downloads when missing


def test_worker_partial_success_writes_workbook_and_emits_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    pdf_path = tmp_path / "catalog.pdf"
    parts = [object()]
    warning = "Stopped on page 2 of 3."
    result = SimpleNamespace(parts=parts, match_report=None, stopped_early=warning)
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
    worker.succeeded.connect(
        lambda path, count, emitted_warning: succeeded.append(
            (path, count, emitted_warning)
        )
    )

    worker.run()

    expected_path = tmp_path / "Downloads" / "catalog-parts.xlsx"
    assert succeeded == [(str(expected_path), 1, warning)]
    assert writes == [((parts, expected_path), {"mode": "pdf", "match_report": None})]


def test_worker_joins_stopped_early_warning_and_result_notices(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    stopped_early = "Stopped after the website stopped responding."
    notice = "The site may have changed its layout."
    result = SimpleNamespace(
        parts=[object()],
        match_report=None,
        stopped_early=stopped_early,
        notices=[notice],
    )
    monkeypatch.setattr(worker_module, "RunStore", object)
    monkeypatch.setattr(worker_module, "run_pdf", lambda *args, **kwargs: result)
    monkeypatch.setattr(worker_module, "write_workbook", lambda *args, **kwargs: None)
    worker = PipelineWorker(
        url=None, pdf_path=str(tmp_path / "catalog.pdf"), filter_path=None
    )
    succeeded = []
    worker.succeeded.connect(
        lambda path, count, warning: succeeded.append((path, count, warning))
    )

    worker.run()

    assert succeeded[0][1:] == (1, f"{stopped_early}\n{notice}")


def test_worker_partial_result_without_parts_emits_failure(tmp_path, monkeypatch):
    warning = "Cancelled before any parts were collected."
    result = SimpleNamespace(parts=[], match_report=None, stopped_early=warning)
    writes = []
    monkeypatch.setattr(worker_module, "RunStore", object)
    monkeypatch.setattr(worker_module, "run_pdf", lambda *args, **kwargs: result)
    monkeypatch.setattr(
        worker_module,
        "write_workbook",
        lambda *args, **kwargs: writes.append(args),
    )
    worker = PipelineWorker(
        url=None, pdf_path=str(tmp_path / "catalog.pdf"), filter_path=None
    )
    failed = []
    succeeded = []
    worker.failed.connect(failed.append)
    worker.succeeded.connect(
        lambda path, count, emitted_warning: succeeded.append(
            (path, count, emitted_warning)
        )
    )

    worker.run()

    assert failed == [warning]
    assert succeeded == []
    assert writes == []


def test_worker_pdf_error_emits_plain_language_message(tmp_path, monkeypatch):
    message = "This PDF could not be read."
    monkeypatch.setattr(worker_module, "RunStore", object)

    def fail_pdf(*args, **kwargs):
        raise PdfError(message)

    monkeypatch.setattr(worker_module, "run_pdf", fail_pdf)
    worker = PipelineWorker(url=None, pdf_path=str(tmp_path / "catalog.pdf"), filter_path=None)
    failed = []
    worker.failed.connect(failed.append)

    worker.run()

    assert failed == [message]


def test_worker_unexpected_error_emits_exception_type(monkeypatch):
    monkeypatch.setattr(worker_module, "RunStore", object)

    def fail_web(*args, **kwargs):
        raise ValueError("internal detail")

    monkeypatch.setattr(worker_module, "run_web", fail_web)
    worker = PipelineWorker(url="https://example.com/catalog", pdf_path=None, filter_path=None)
    failed = []
    worker.failed.connect(failed.append)

    worker.run()

    assert len(failed) == 1
    assert "ValueError" in failed[0]


@pytest.mark.parametrize("answer", [True, False])
def test_confirm_blocks_until_preview_answer_and_returns_it(answer):
    worker = PipelineWorker(url="https://example.com", pdf_path=None, filter_path=None)
    preview_ready = threading.Event()
    worker.previewReady.connect(
        lambda sample: preview_ready.set(), Qt.ConnectionType.DirectConnection
    )
    returned = []
    thread = threading.Thread(target=lambda: returned.append(worker._confirm([])))

    thread.start()
    assert preview_ready.wait(timeout=1)
    assert thread.is_alive()
    worker.answer_preview(answer)
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert returned == [answer]


def test_cancel_during_pending_preview_releases_confirm_with_false():
    worker = PipelineWorker(url="https://example.com", pdf_path=None, filter_path=None)
    preview_ready = threading.Event()
    worker.previewReady.connect(
        lambda sample: preview_ready.set(), Qt.ConnectionType.DirectConnection
    )
    returned = []
    thread = threading.Thread(target=lambda: returned.append(worker._confirm([])))

    thread.start()
    assert preview_ready.wait(timeout=1)
    worker.cancel()
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert returned == [False]


@pytest.mark.parametrize("answer", [True, False])
def test_choose_cached_blocks_until_cache_answer_and_returns_it(answer):
    worker = PipelineWorker(url="https://example.com", pdf_path=None, filter_path=None)
    decision_ready = threading.Event()
    info = SimpleNamespace(part_count=12)
    emitted = []
    worker.cacheDecision.connect(
        lambda value: (emitted.append(value), decision_ready.set()),
        Qt.ConnectionType.DirectConnection,
    )
    returned = []
    thread = threading.Thread(
        target=lambda: returned.append(worker._choose_cached(info))
    )

    thread.start()
    assert decision_ready.wait(timeout=1)
    assert thread.is_alive()
    worker.answer_cache_decision(answer)
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert emitted == [info]
    assert returned == [answer]


def test_cancel_during_pending_cache_decision_releases_wait():
    worker = PipelineWorker(url="https://example.com", pdf_path=None, filter_path=None)
    decision_ready = threading.Event()
    worker.cacheDecision.connect(
        lambda info: decision_ready.set(), Qt.ConnectionType.DirectConnection
    )
    returned = []
    thread = threading.Thread(
        target=lambda: returned.append(worker._choose_cached(SimpleNamespace()))
    )

    thread.start()
    assert decision_ready.wait(timeout=1)
    assert thread.is_alive()
    worker.cancel()
    thread.join(timeout=1)

    assert not thread.is_alive()
    assert returned == [True]
