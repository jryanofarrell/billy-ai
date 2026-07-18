"""Deterministic extraction of the regular tables found on PDF pages."""

import re
from dataclasses import dataclass


PARTNO = re.compile(r"PART\s*No\.?", re.I)
FRACTION = re.compile(r"^\d+(-\d+)?/\d+$")
_COLUMN_GAP = re.compile(r"\s{2,}|\t+")
_SIZE = re.compile(r"^(?:\d+(?:\.\d+)?|\.\d+|\d+(?:-\d+)?/\d+)(?:[\"']|in\.?)?$", re.I)
_QTY = re.compile(r"^\d+(?:\.\d+)?$")
_NUMERIC_CODE = re.compile(r"\d{2,}[*†]")
# A sub-heading that modifies the block above it rather than naming a new product.
_VARIANT = re.compile(r"^(reducing|lead free|forged nuts?)$", re.I)
# A prose line ending like a sentence: lowercase word, then a period at the end.
_SENTENCE = re.compile(r"[a-z].*[a-z]\.\s*$")


@dataclass
class RawPart:
    """A part exactly as it appeared in the source page."""

    part_no: str
    series: str
    description: str


@dataclass
class SuspiciousLine:
    """A source line that may contain a part requiring AI extraction."""

    line_no: int
    text: str
    reason: str
    headings: str


@dataclass
class PageScan:
    """The deterministic table scan and its page-level metadata."""

    parts: list[RawPart]
    part_lines: list[int]
    suspicious: list[SuspiciousLine]
    header_line: str
    word_count: int


def is_code(value: str) -> bool:
    """Return whether *value* has the catalog's ordinary part-code shape."""

    return (
        any(character.isdigit() for character in value)
        and ("-" in value or any(character.isalpha() for character in value))
        and FRACTION.fullmatch(value) is None
    )


def _columns(line: str) -> list[str]:
    return [column.strip() for column in _COLUMN_GAP.split(line.strip()) if column.strip()]


def _labels(header: str) -> list[str]:
    columns = _columns(header)
    if len(columns) > 1:
        return columns
    return header.split()


def _label_values(labels: list[str], values: list[str]) -> str:
    if not values:
        return ""
    if len(labels) == len(values):
        return ", ".join(f"{label}: {value}" for label, value in zip(labels, values, strict=True))
    return " ".join(values)


def _descriptions(
    before_labels: list[str], after_labels: list[str], before: list[str], after: list[str]
) -> str:
    """Apply the five regular-table description rules, in priority order."""

    # 1. A Description column is free text; Qty, when present, is its last value.
    lowered = [label.casefold() for label in after_labels]
    if "description" in lowered:
        description_at = lowered.index("description")
        qty_at = next(
            (index for index, label in enumerate(lowered) if label in {"qty", "quantity"}), None
        )
        prefix_labels = after_labels[:description_at]
        prefix_count = len(prefix_labels)
        prefix = _label_values(prefix_labels, after[:prefix_count])
        remainder = after[prefix_count:]
        if qty_at is not None and remainder and _QTY.fullmatch(remainder[-1]):
            free_text = " ".join(remainder[:-1])
            pieces = [prefix, free_text, f"{after_labels[qty_at]}: {remainder[-1]}"]
        else:
            pieces = [prefix, " ".join(remainder)]
        return ", ".join(piece for piece in pieces if piece)

    # 2. Values on both sides of PART No. retain the labels from both sides.
    if before and after:
        pieces = [
            _label_values(before_labels, before),
            _label_values(after_labels, after),
        ]
        return ", ".join(piece for piece in pieces if piece)

    # 3. Ordinary columns following PART No. become Label: value pairs.
    if after:
        return _label_values(after_labels, after)

    # 4. Some tables put all size columns before PART No.
    if before:
        return _label_values(before_labels, before)

    # 5. A part-only row has an intentionally empty description.
    return ""


def _looks_tabular(tokens: list[str]) -> bool:
    return len(tokens) >= 2 and any(_SIZE.fullmatch(token.rstrip(",;")) for token in tokens[-2:])


def _is_note(line: str, tokens: list[str]) -> bool:
    """Prose (a real sentence or an editorial note), not a product heading."""
    lowered = line.lower()
    if lowered.startswith(("note", "for ", "see ", "marked ")) or "refers to" in lowered:
        return True
    return bool(_SENTENCE.search(line)) and len(tokens) >= 4


def _is_heading(line: str, tokens: list[str]) -> bool:
    """A short block/sub-heading line. Digits are allowed (e.g. ``90° ELBOW``,
    ``S.A.E. 45°``); part rows, size rows, page numbers, and prose are not."""
    if not tokens or len(tokens) > 6:
        return False
    if line.strip().isdigit():
        return False
    # Catalog headings start with a capital (or a digit, e.g. 90° ELBOW); a line
    # whose first letter is lowercase is wrapped prose, not a heading.
    first_alpha = next((char for char in line if char.isalpha()), "")
    if first_alpha.islower():
        return False
    if any(is_code(token) for token in tokens):
        return False
    if all(_SIZE.fullmatch(token) or _QTY.fullmatch(token) for token in tokens):
        return False
    return not _is_note(line, tokens)


def _clean_heading(tokens: list[str]) -> str:
    """Drop leading size/qty tokens — column-index noise (e.g. the ``1 2`` of a
    ``1 2 3`` size header) that pdfplumber merges onto a heading sharing its row."""
    start = 0
    while start < len(tokens) and (_QTY.fullmatch(tokens[start]) or _SIZE.fullmatch(tokens[start])):
        start += 1
    return " ".join(tokens[start:])


def _series_for_row(pending: list[str], primary: str, current: str) -> tuple[str, str, str]:
    """Resolve a row's series from the heading run collected just above it.

    Returns ``(series, primary, current)``. A run of only variant sub-headings
    (Reducing, Lead Free, …) merges onto the last full block heading; any other
    run becomes the new block heading; an empty run carries the current series
    forward (continuation tables).
    """
    if not pending:
        return current, primary, current
    run = " ".join(pending)
    if primary and all(_VARIANT.fullmatch(line.strip()) for line in pending):
        series = f"{primary} / {run}"
    else:
        series = run
        primary = run
    return series, primary, series


def parse_page_tables(text: str) -> PageScan:
    """Extract regular table rows and identify lines that may require AI."""

    parts: list[RawPart] = []
    part_lines: list[int] = []
    suspicious: list[SuspiciousLine] = []
    before_labels: list[str] = []
    after_labels: list[str] = []
    mirrored = False
    seen_header = False  # a PART No. header has appeared, even a bare "Part No."
    pending: list[str] = []  # contiguous heading lines not yet applied to a row
    primary = ""  # last full (non-variant) block heading
    current_series = ""  # series applied to rows until the next heading run
    header_line = ""

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        matches = list(PARTNO.finditer(line))
        if matches:
            header_line = raw_line
            seen_header = True
            mirrored = len(matches) >= 2
            sections = PARTNO.split(line)
            before_labels = _labels(sections[0]) if sections[0].strip() else []
            after_labels = _labels(sections[1]) if len(sections) > 1 else []
            continue

        tokens = line.split()
        if not tokens:
            continue

        expected_code_position = len(before_labels)
        suspicious_reason = ""
        excluded_spaced_pair = False
        if (
            expected_code_position + 1 < len(tokens)
            and not is_code(tokens[expected_code_position])
            and not is_code(tokens[expected_code_position + 1])
            and "-" in tokens[expected_code_position] + tokens[expected_code_position + 1]
            and is_code(tokens[expected_code_position] + tokens[expected_code_position + 1])
        ):
            fragments = tokens[expected_code_position : expected_code_position + 2]
            excluded_spaced_pair = any(
                _SIZE.fullmatch(fragment) or ".." in fragment for fragment in fragments
            )
            if not excluded_spaced_pair:
                suspicious_reason = "possible spaced part number"

        code_positions = [index for index, token in enumerate(tokens) if is_code(token)]
        # A bare "Part No." sub-header (Lead Free, Forged Nuts) carries no column
        # labels; gate emission on having seen any header, not on label presence,
        # so those rows are extracted instead of dropped (which also stops their
        # heading from bleeding onto the next block).
        header_seen = seen_header
        if (
            header_seen
            and expected_code_position < len(tokens)
            and _NUMERIC_CODE.fullmatch(tokens[expected_code_position])
            and expected_code_position not in code_positions
        ):
            code_positions.append(expected_code_position)
            code_positions.sort()
        if not mirrored:
            code_positions = [
                position for position in code_positions if position == expected_code_position
            ]
        if code_positions and header_seen:
            series, primary, current_series = _series_for_row(pending, primary, current_series)
            pending = []
            positions = code_positions[:2] if mirrored else code_positions[:1]
            for position_index, position in enumerate(positions):
                end = (
                    positions[position_index + 1]
                    if position_index + 1 < len(positions)
                    else len(tokens)
                )
                before = tokens[:position] if position_index == 0 else []
                after = tokens[position + 1 : end]
                parts.append(
                    RawPart(
                        part_no=tokens[position],
                        series=series,
                        description=_descriptions(before_labels, after_labels, before, after),
                    )
                )
                part_lines.append(line_no)
            continue

        if (
            not suspicious_reason
            and not excluded_spaced_pair
            and _looks_tabular(tokens)
            and not is_code(tokens[0])
            and len(tokens) >= 3
            and not line.startswith(("•", "-"))
            and not tokens[0].endswith(":")
            and re.search(r"\bpage\b", line, re.I) is None
            and not all(_SIZE.fullmatch(token) or _QTY.fullmatch(token) for token in tokens)
        ):
            suspicious_reason = "unrecognized part-number shape"

        if suspicious_reason:
            suspicious.append(
                SuspiciousLine(
                    line_no=line_no,
                    text=raw_line,
                    reason=suspicious_reason,
                    headings=" ".join(pending) or current_series,
                )
            )

        if _is_heading(line, tokens):
            pending.append(_clean_heading(tokens))
        # Non-heading lines (notes, cross-references, page numbers) are skipped, not
        # cleared: only a part row consumes the pending run, so a heading survives an
        # intervening note or cross-reference down to the table it labels.

    return PageScan(
        parts=parts,
        part_lines=part_lines,
        suspicious=suspicious,
        header_line=header_line,
        word_count=len(text.split()),
    )
