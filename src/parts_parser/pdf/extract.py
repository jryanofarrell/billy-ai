"""Column-aware text extraction from catalog PDFs.

Catalog pages are laid out in two or three columns. pypdf's flat ``extract_text``
returns text in content-stream order, which scrambles the visual reading order
of a multi-column page. We use pdfplumber's word boxes to recover the real order:
detect the columns, then emit page-level headings (full-width top matter) first,
followed by each column top-to-bottom, left to right.
"""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

from parts_parser.pdf.tables import PARTNO


class PdfError(Exception):
    """Plain-language, user-facing PDF error."""


@dataclass
class PageText:
    """One catalog page split into its page-level heading and table body."""

    heading: str  # page-level title (e.g. "BRASS S.A.E. 45° FLARE"), "" if none
    body: str  # column-ordered table text; page number and title removed
    page_number: str = ""  # the printed catalog page number, "" if none found


def _page_number(words: list[dict], width: float, height: float) -> str:
    """The printed catalog page number: a bare integer in a bottom outer corner."""
    for word in words:
        text = word["text"]
        if (
            text.isdigit()
            and word["top"] > height - 22
            and (word["x0"] < 55 or word["x0"] > width - 58)
        ):
            return text
    return ""


def _row_key(top: float) -> int:
    """Bucket a word's vertical position so words on one visual line group."""
    return round(top / 3)


def _column_anchors(words: list[dict]) -> list[float]:
    """Left-margin x of each column, from the ``PART No.`` header that opens each
    table. A word belongs to the column of the nearest anchor at or left of it, so
    anchors (not midpoint boundaries) avoid bisecting a narrow column's own table.
    Returns ``[0.0]`` (single column) when fewer than two headers are found.
    """
    rows: dict[int, list[dict]] = defaultdict(list)
    for word in words:
        rows[_row_key(word["top"])].append(word)

    header_xs: list[float] = []
    for row_words in rows.values():
        row_words.sort(key=lambda w: w["x0"])
        if not PARTNO.search(" ".join(w["text"] for w in row_words)):
            continue
        # Columns often share a row (e.g. "PART No. Pipe PART No. Pipe PART No.
        # Pipe"), so record the left edge of every "PART No." in the row, not just
        # the first — otherwise a page of aligned columns collapses into one.
        header_xs.extend(w["x0"] for w in row_words if w["text"].upper().startswith("PART"))

    header_xs.sort()
    clusters: list[list[float]] = []
    for x in header_xs:
        if clusters and x - clusters[-1][-1] <= 90:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    centers = [sum(c) / len(c) for c in clusters]
    return centers if len(centers) >= 2 else [0.0]


def _column_of(x: float, anchors: list[float], tolerance: float = 20.0) -> int:
    """Column of a word: the rightmost anchor at or left of ``x`` (with slack)."""
    index = 0
    for candidate, anchor in enumerate(anchors):
        if x + tolerance >= anchor:
            index = candidate
    return index


def _line_of(row_words: list[dict]) -> str:
    row_words.sort(key=lambda w: w["x0"])
    return " ".join(w["text"] for w in row_words)


def _split_title(words: list[dict]) -> tuple[str, list[dict]]:
    """Pull the page title (the distinctly-largest top-of-page text) out of the
    word list, returning ``(title, remaining_words)``.

    The page-level heading is set in a much larger font than table text; when no
    such outsized text exists the page simply has no title.
    """
    sizes = sorted(float(w.get("size", 0.0)) for w in words)
    median = sizes[len(sizes) // 2] or 1.0
    max_size = sizes[-1]
    if max_size < median * 1.4:
        return "", words

    title_words = [w for w in words if float(w.get("size", 0.0)) >= max_size - 0.5]
    top = min(w["top"] for w in title_words)
    title_row = [w for w in title_words if w["top"] - top <= 3]
    title = _line_of(title_row)
    title_ids = {id(w) for w in title_row}
    remaining = [w for w in words if id(w) not in title_ids]
    return title, remaining


def _page_text(page) -> PageText:
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False, extra_attrs=["size"])
    if not words:
        return PageText(heading="", body="")

    page_number = _page_number(words, float(page.width), float(page.height))
    heading, body_words = _split_title(words)
    if not body_words:
        return PageText(heading=heading, body="", page_number=page_number)

    anchors = _column_anchors(body_words)

    # Assign each word to a column, then group into visual rows WITHIN the column
    # so rows of different columns that share a vertical position never merge.
    per_column: dict[int, dict[int, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for word in body_words:
        per_column[_column_of(word["x0"], anchors)][_row_key(word["top"])].append(word)

    ordered: list[str] = []
    for column_index in sorted(per_column):
        for row_key in sorted(per_column[column_index]):
            ordered.append(_line_of(per_column[column_index][row_key]))

    return PageText(heading=heading, body="\n".join(ordered), page_number=page_number)


def extract_pages(path: Path) -> list[PageText]:
    """Extract one column-ordered :class:`PageText` per PDF page."""
    try:
        with pdfplumber.open(path) as pdf:
            return [_page_text(page) for page in pdf.pages]
    except PdfError:
        raise
    except Exception as error:
        raise PdfError(
            "Couldn't read this PDF. It may be corrupted or password-protected."
        ) from error


def extract_text(path: Path) -> list[str]:
    """Column-ordered body text per page (page heading excluded)."""
    return [page.body for page in extract_pages(path)]


def is_digital(pages: list[str], *, min_mean_chars: int = 200, sample: int = 20) -> bool:
    """Return whether sampled pages contain enough text to be digitally readable."""
    sampled_pages = pages[:sample]
    if not sampled_pages:
        return False
    return sum(len(page) for page in sampled_pages) / len(sampled_pages) >= min_mean_chars
