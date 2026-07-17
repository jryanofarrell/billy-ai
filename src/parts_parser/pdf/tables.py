"""Deterministic extraction of the regular tables found on PDF pages."""

import re
from dataclasses import dataclass


PARTNO = re.compile(r"PART\s*No\.?", re.I)
FRACTION = re.compile(r"^\d+(-\d+)?/\d+$")
_COLUMN_GAP = re.compile(r"\s{2,}|\t+")
_SIZE = re.compile(r"^(?:\d+(?:\.\d+)?|\.\d+|\d+(?:-\d+)?/\d+)(?:[\"']|in\.?)?$", re.I)
_QTY = re.compile(r"^\d+(?:\.\d+)?$")


@dataclass
class RawPart:
    """A part exactly as it appeared in the source page."""

    part_no: str
    series: str
    description: str


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


def parse_page_tables(text: str) -> tuple[list[RawPart], list[str]]:
    """Extract regular table rows and report reasons an AI fallback is warranted."""

    parts: list[RawPart] = []
    reasons: list[str] = []
    before_labels: list[str] = []
    after_labels: list[str] = []
    mirrored = False
    headings: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        matches = list(PARTNO.finditer(line))
        if matches:
            mirrored = len(matches) >= 2
            sections = PARTNO.split(line)
            before_labels = _labels(sections[0]) if sections[0].strip() else []
            after_labels = _labels(sections[1]) if len(sections) > 1 else []
            continue

        tokens = line.split()
        if not tokens:
            continue

        expected_code_position = len(before_labels)
        if (
            expected_code_position + 1 < len(tokens)
            and not is_code(tokens[expected_code_position])
            and not is_code(tokens[expected_code_position + 1])
            and "-" in tokens[expected_code_position] + tokens[expected_code_position + 1]
            and is_code(tokens[expected_code_position] + tokens[expected_code_position + 1])
        ):
            reasons.append("possible spaced part number")

        code_positions = [index for index, token in enumerate(tokens) if is_code(token)]
        if not mirrored:
            code_positions = [
                position for position in code_positions if position == expected_code_position
            ]
        if code_positions and (before_labels or after_labels or mirrored):
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
                        series=" ".join(headings),
                        description=_descriptions(before_labels, after_labels, before, after),
                    )
                )
            continue

        if _looks_tabular(tokens) and not is_code(tokens[0]):
            reasons.append("unrecognized part-number shape in tabular row")

        if len(tokens) <= 8 and not any(character.isdigit() for character in line):
            headings.append(line)
            headings = headings[-2:]

    if len(text.split()) >= 40 and not parts:
        reasons.append("substantial page text produced no parts")

    return parts, list(dict.fromkeys(reasons))
