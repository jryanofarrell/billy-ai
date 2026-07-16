"""Per-mode source input components: one for websites, one for catalog PDFs."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QLineEdit, QVBoxLayout, QWidget

from parts_parser.gui.drop_zone import DropZone


class UrlPanel(QWidget):
    """Website-address input for the web pipeline."""

    sourceChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Website address:", self))
        self.url_edit = QLineEdit(self)
        self.url_edit.setPlaceholderText("https://example.com")
        self.url_edit.textEdited.connect(lambda _text: self.sourceChanged.emit())
        layout.addWidget(self.url_edit)

    @property
    def source(self) -> str | None:
        text = self.url_edit.text().strip()
        return text or None

    def clear(self) -> None:
        self.url_edit.clear()


class PdfPanel(QWidget):
    """Catalog-PDF drop zone for the PDF pipeline."""

    sourceChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.pdf_zone = DropZone(
            extensions=(".pdf",),
            prompt="Drop a catalog PDF here, or click to browse",
            parent=self,
        )
        self.pdf_zone.fileSelected.connect(lambda _path: self.sourceChanged.emit())
        self.pdf_zone.cleared.connect(self.sourceChanged.emit)
        layout.addWidget(self.pdf_zone)

    @property
    def source(self) -> str | None:
        return self.pdf_zone.path

    def clear(self) -> None:
        self.pdf_zone.clear()
