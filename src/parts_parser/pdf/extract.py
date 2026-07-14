from pathlib import Path

from pypdf import PdfReader


class PdfError(Exception):
    """Plain-language, user-facing PDF error."""


def extract_text(path: Path) -> list[str]:
    """Extract one text string per page from a PDF."""
    try:
        reader = PdfReader(path)
        return [page.extract_text() or "" for page in reader.pages]
    except Exception as error:
        raise PdfError(
            "Couldn't read this PDF. It may be corrupted or password-protected."
        ) from error


def is_digital(
    pages: list[str], *, min_mean_chars: int = 200, sample: int = 20
) -> bool:
    """Return whether sampled pages contain enough text to be digitally readable."""
    sampled_pages = pages[:sample]
    if not sampled_pages:
        return False
    return sum(len(page) for page in sampled_pages) / len(sampled_pages) >= min_mean_chars
