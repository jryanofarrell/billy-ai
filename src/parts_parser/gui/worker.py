import threading
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QObject, QThread, Signal

from parts_parser.llm import LLMError
from parts_parser.output.excel import write_workbook
from parts_parser.output.filtering import OutputError, load_filter_sheet
from parts_parser.pdf.extract import PdfError
from parts_parser.pdf.pipeline import run_pdf
from parts_parser.store import RunStore
from parts_parser.web.pipeline import run_web
from parts_parser.web.session import WebError


def output_path_for(source: str, *, is_url: bool) -> Path:
    if is_url:
        domain = urlparse(source).netloc
        candidate = Path.home() / "Downloads" / f"{domain}-parts.xlsx"
    else:
        pdf_path = Path(source)
        candidate = pdf_path.parent / f"{pdf_path.stem}-parts.xlsx"

    if not candidate.exists():
        return candidate

    counter = 2
    while True:
        numbered = candidate.with_name(f"{candidate.stem} ({counter}){candidate.suffix}")
        if not numbered.exists():
            return numbered
        counter += 1


class PipelineWorker(QThread):
    progressed = Signal(str, int)
    succeeded = Signal(str, int)
    failed = Signal(str)

    def __init__(
        self,
        *,
        url: str | None,
        pdf_path: str | None,
        filter_path: str | None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._url = url
        self._pdf_path = pdf_path
        self._filter_path = filter_path
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            store = RunStore()
            filter_sheet = (
                load_filter_sheet(Path(self._filter_path))
                if self._filter_path is not None
                else None
            )

            def report_progress(message: str, fraction: float) -> None:
                percent = int(fraction * 100) if fraction >= 0 else -1
                self.progressed.emit(message, percent)

            if self._url is not None:
                result = run_web(
                    self._url,
                    store=store,
                    filter_sheet=filter_sheet,
                    progress=report_progress,
                    cancel=self._cancel,
                )
                output_path = output_path_for(self._url, is_url=True)
                mode = "web"
            elif self._pdf_path is not None:
                pdf_path = Path(self._pdf_path)
                result = run_pdf(
                    pdf_path,
                    store=store,
                    filter_sheet=filter_sheet,
                    progress=report_progress,
                    cancel=self._cancel,
                )
                output_path = output_path_for(self._pdf_path, is_url=False)
                mode = "pdf"
            else:
                raise OutputError("Choose a website or PDF catalog to parse.")

            write_workbook(
                result.parts,
                output_path,
                mode=mode,
                match_report=result.match_report,
            )
            self.succeeded.emit(str(output_path), len(result.parts))
        except (WebError, PdfError, LLMError, OutputError) as error:
            self.failed.emit(str(error))
        except Exception as error:
            self.failed.emit(
                f"Something went wrong ({type(error).__name__}). Please try again."
            )
