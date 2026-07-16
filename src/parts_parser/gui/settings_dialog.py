"""Settings dialog for the desktop interface."""

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from parts_parser.config import Settings, load_settings, save_settings

DEFAULT_MODEL = "gpt-5-mini"


class SettingsDialog(QDialog):
    """Allow the user to edit and persist application settings."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")

        settings = load_settings()

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.api_key_edit = QLineEdit(settings.openai_api_key or "", self)
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("OpenAI API key", self.api_key_edit)

        self.model_edit = QLineEdit(settings.model or DEFAULT_MODEL, self)
        form.addRow("Model", self.model_edit)
        layout.addLayout(form)

        layout.addWidget(QLabel("The key is stored only on this computer.", self))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        """Persist the entered settings and close the dialog."""
        key = self.api_key_edit.text().strip()
        model = self.model_edit.text().strip()
        save_settings(
            Settings(
                openai_api_key=key or None,
                model=model or DEFAULT_MODEL,
            )
        )
        super().accept()
