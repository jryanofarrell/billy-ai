import os
import sys

if getattr(sys, "frozen", False):
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")

from PySide6.QtWidgets import QApplication

from parts_parser.gui.main_window import MainWindow
from parts_parser.logging_setup import setup_logging


def main() -> int:
    setup_logging()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
