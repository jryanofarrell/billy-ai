"""Main window for the parts catalog parser desktop application."""

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from parts_parser.gui.drop_zone import DropZone
from parts_parser.gui.settings_dialog import SettingsDialog
from parts_parser.gui.source_panels import PdfPanel, UrlPanel
from parts_parser.gui.worker import PipelineWorker


def _display_path(path: str) -> str:
    """Shorten an output path for the status line, using ~ for the home dir."""
    p = Path(path)
    try:
        return f"~/{p.relative_to(Path.home())}"
    except ValueError:
        return str(p)


class MainWindow(QMainWindow):
    """Present source selection and run controls for both parser pipelines."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker: PipelineWorker | None = None
        self._output_path: str | None = None

        self.setWindowTitle("Parts Catalog Parser")
        self.setFixedWidth(560)

        central_widget = QWidget(self)
        layout = QVBoxLayout(central_widget)

        source_group = QGroupBox("Source", central_widget)
        source_layout = QVBoxLayout(source_group)
        self.mode_selector = QComboBox(source_group)
        self.mode_selector.addItems(["Website", "PDF catalog"])
        source_layout.addWidget(self.mode_selector)

        self.url_panel = UrlPanel(source_group)
        self.pdf_panel = PdfPanel(source_group)
        self.source_stack = QStackedWidget(source_group)
        self.source_stack.addWidget(self.url_panel)
        self.source_stack.addWidget(self.pdf_panel)
        source_layout.addWidget(self.source_stack)
        layout.addWidget(source_group)

        filter_group = QGroupBox("Only include parts from a list (optional)", central_widget)
        filter_layout = QVBoxLayout(filter_group)
        self.filter_zone = DropZone(
            extensions=(".xlsx", ".xls"),
            prompt="Drop an Excel part list here, or click to browse",
            parent=filter_group,
        )
        filter_layout.addWidget(self.filter_zone)
        layout.addWidget(filter_group)

        button_layout = QHBoxLayout()
        self.run_button = QPushButton("Run", central_widget)
        self.run_button.setEnabled(False)
        button_layout.addWidget(self.run_button)
        self.cancel_button = QPushButton("Cancel", central_widget)
        self.cancel_button.hide()
        button_layout.addWidget(self.cancel_button)
        button_layout.addStretch(1)
        self.settings_button = QPushButton("Settings…", central_widget)
        button_layout.addWidget(self.settings_button)
        layout.addLayout(button_layout)

        self.progress_bar = QProgressBar(central_widget)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        status_layout = QHBoxLayout()
        self.status_label = QLabel("Ready", central_widget)
        status_layout.addWidget(self.status_label, 1)
        self.open_button = QPushButton("Open", central_widget)
        self.open_button.hide()
        status_layout.addWidget(self.open_button)
        layout.addLayout(status_layout)

        self.setCentralWidget(central_widget)
        self._create_menu()

        self.mode_selector.currentIndexChanged.connect(self._mode_changed)
        self.url_panel.sourceChanged.connect(self._update_run_enabled)
        self.pdf_panel.sourceChanged.connect(self._update_run_enabled)
        self.run_button.clicked.connect(self._start_run)
        self.cancel_button.clicked.connect(self._cancel_run)
        self.settings_button.clicked.connect(self._open_settings)
        self.open_button.clicked.connect(self._open_output)

    def _create_menu(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        settings_action = QAction("Settings…", self)
        settings_action.triggered.connect(self._open_settings)
        file_menu.addAction(settings_action)
        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

    def _open_settings(self) -> None:
        SettingsDialog(self).exec()

    def _mode_changed(self, index: int) -> None:
        self.source_stack.setCurrentIndex(index)
        self._update_run_enabled()

    def _active_source(self) -> tuple[str | None, str | None]:
        """Return (url, pdf_path) for the currently selected mode."""
        if self.mode_selector.currentIndex() == 0:
            return self.url_panel.source, None
        return None, self.pdf_panel.source

    def _update_run_enabled(self) -> None:
        url, pdf_path = self._active_source()
        has_source = url is not None or pdf_path is not None
        self.run_button.setEnabled(has_source and self._worker is None)

    def _start_run(self) -> None:
        url, pdf_path = self._active_source()
        if url is None and pdf_path is None:
            return

        self.open_button.hide()
        self.status_label.setText("Starting…")
        self.progress_bar.setRange(0, 0)
        self._set_inputs_enabled(False)
        self.cancel_button.show()

        worker = PipelineWorker(
            url=url,
            pdf_path=pdf_path,
            filter_path=self.filter_zone.path,
            parent=self,
        )
        self._worker = worker
        worker.progressed.connect(self._show_progress)
        worker.succeeded.connect(self._run_succeeded)
        worker.failed.connect(self._run_failed)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _cancel_run(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.cancel_button.setEnabled(False)
            self.status_label.setText("Cancelling…")

    def _show_progress(self, message: str, percent: int) -> None:
        self.status_label.setText(message)
        if percent < 0:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(percent)

    def _run_succeeded(self, path: str, part_count: int) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.status_label.setText(f"Done — {part_count:,} parts · saved to {_display_path(path)}")
        self.status_label.setToolTip(path)
        self._configure_open_button(path)
        self._finish_run()

    def _run_failed(self, message: str) -> None:
        self.status_label.setText("Couldn't finish")
        QMessageBox.warning(self, "Couldn't finish", message)
        self._finish_run()

    def _configure_open_button(self, path: str) -> None:
        self._output_path = path
        self.open_button.show()

    def _open_output(self) -> None:
        if self._output_path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._output_path))

    def _finish_run(self) -> None:
        self._worker = None
        self._set_inputs_enabled(True)
        self.cancel_button.setEnabled(True)
        self.cancel_button.hide()
        self._update_run_enabled()

    def _set_inputs_enabled(self, enabled: bool) -> None:
        self.mode_selector.setEnabled(enabled)
        self.url_panel.setEnabled(enabled)
        self.pdf_panel.setEnabled(enabled)
        self.filter_zone.setEnabled(enabled)
        self.run_button.setEnabled(enabled)
        self.settings_button.setEnabled(enabled)
