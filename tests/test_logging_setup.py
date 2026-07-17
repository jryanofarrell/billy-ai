import logging
from logging.handlers import RotatingFileHandler

from parts_parser.logging_setup import setup_logging


def _package_file_handlers() -> list[RotatingFileHandler]:
    root = logging.getLogger("parts_parser")
    return [h for h in root.handlers if isinstance(h, RotatingFileHandler)]


def _detach() -> None:
    root = logging.getLogger("parts_parser")
    for handler in _package_file_handlers():
        root.removeHandler(handler)
        handler.close()


def test_setup_logging_writes_to_app_data_logs(tmp_path, monkeypatch):
    monkeypatch.setenv("PARTS_PARSER_DATA_DIR", str(tmp_path))
    try:
        target = setup_logging()
        logging.getLogger("parts_parser.test").info("hello from the test")
        for handler in _package_file_handlers():
            handler.flush()

        assert target == tmp_path / "logs" / "parts_parser.log"
        assert "hello from the test" in target.read_text(encoding="utf-8")
    finally:
        _detach()


def test_setup_logging_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("PARTS_PARSER_DATA_DIR", str(tmp_path))
    try:
        setup_logging()
        setup_logging()
        assert len(_package_file_handlers()) == 1
    finally:
        _detach()
