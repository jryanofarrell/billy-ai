"""File-selection drop zone used by the desktop interface."""

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent, QMouseEvent
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QLabel, QToolButton, QWidget


class DropZone(QFrame):
    """A clickable drop zone that accepts one file of an allowed type."""

    fileSelected = Signal(str)
    cleared = Signal()

    def __init__(
        self,
        *,
        extensions: tuple[str, ...],
        prompt: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._extensions = tuple(self._normalize_extension(item) for item in extensions)
        self._prompt = prompt
        self._path: str | None = None

        self.setAcceptDrops(True)
        self.setMinimumHeight(64)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._label = QLabel(prompt, self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._label)

        self._clear_button = QToolButton(self)
        self._clear_button.setText("✕")
        self._clear_button.setToolTip("Clear selected file")
        self._clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_button.clicked.connect(self.clear)
        self._clear_button.hide()
        layout.addWidget(self._clear_button)

        self._set_highlighted(False)

    @property
    def path(self) -> str | None:
        """Return the selected file's absolute path, if any."""
        return self._path

    def clear(self) -> None:
        """Clear the current selection and restore the prompt."""
        self._path = None
        self._label.setText(self._prompt)
        self._clear_button.hide()
        self._set_highlighted(False)
        self.cleared.emit()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """Accept a drag containing one local file of an allowed type."""
        path = self._path_from_mime_data(event.mimeData())
        if path is None:
            event.ignore()
            return
        self._set_highlighted(True)
        event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        """Remove drag highlighting when the pointer leaves the widget."""
        self._set_highlighted(False)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        """Select an accepted dropped file."""
        self._set_highlighted(False)
        path = self._path_from_mime_data(event.mimeData())
        if path is None:
            event.ignore()
            return
        self._select(path)
        event.acceptProposedAction()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Open a file browser when the drop zone is clicked."""
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        patterns = " ".join(f"*{extension}" for extension in self._extensions)
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Select a file",
            "",
            f"Supported files ({patterns})",
        )
        if selected:
            self._select(selected)
        event.accept()

    def _select(self, path: str) -> None:
        selected = str(Path(path).expanduser().resolve())
        self._path = selected
        self._label.setText(Path(selected).name)
        self._clear_button.show()
        self.fileSelected.emit(selected)

    def _path_from_mime_data(self, mime_data: object) -> str | None:
        if not hasattr(mime_data, "urls"):
            return None
        urls = mime_data.urls()
        if len(urls) != 1 or not urls[0].isLocalFile():
            return None
        path = urls[0].toLocalFile()
        if Path(path).suffix.lower() not in self._extensions:
            return None
        return path

    def _set_highlighted(self, highlighted: bool) -> None:
        color = "#2f80ed" if highlighted else "#888888"
        self.setStyleSheet(
            f"DropZone {{ border: 1px dashed {color}; border-radius: 4px; }}"
        )

    @staticmethod
    def _normalize_extension(extension: str) -> str:
        normalized = extension.lower()
        return normalized if normalized.startswith(".") else f".{normalized}"
