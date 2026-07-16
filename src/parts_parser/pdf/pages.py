from dataclasses import dataclass

from parts_parser.llm import LLMClient, LLMError  # noqa: F401 — re-exported for callers


@dataclass
class RawPart:
    part_no: str
    series: str
    description: str


@dataclass
class PageResult:
    page_no: int
    subcategory: str
    parts: list[RawPart]
    skipped: bool
    skip_reason: str | None


_SYSTEM = (
    "You extract product listings from plumbing-parts catalog pages. "
    "A part exists ONLY where an explicit part number is printed. "
    "Copy part numbers character-for-character. "
    "Never invent parts from prose. "
    "Respond with JSON only."
)


def extract_page_parts(llm: LLMClient, page_text: str, page_no: int, category: str) -> PageResult:
    """Call the LLM once to extract parts from a single catalog page."""
    user_prompt = (
        f"Catalog category for this page: {category or 'unknown'}. "
        f"Page {page_no} text follows.\n\n{page_text}\n\n"
        'Return {"subcategory": str, "parts": [{"part_no": str, "series": str, "description": str}], "skip_reason": str|null}. '
        'Rules: "subcategory" is the page-level heading (e.g. "BLACK IRON PIPE FITTINGS SCHEDULE 40"); '
        '"series" is the block heading a part sits under, including qualifiers (e.g. "90° ELBOW Male JIC To Male Pipe"); '
        '"description" combines the part\'s remaining table columns as "Label: value" pairs separated by ", " '
        '(e.g. "Tube: 1/4, Pipe: 1/8") or, for parts described in bullets, the bullets joined by "; ". '
        "If the page has no part numbers at all (cover, marketing, index), return parts: [] and a short skip_reason."
    )

    raw = llm.complete_json(system=_SYSTEM, user=user_prompt, max_output_tokens=16_000)

    subcategory = str(raw.get("subcategory", ""))
    skip_reason_raw = raw.get("skip_reason")
    skip_reason = str(skip_reason_raw) if skip_reason_raw is not None else None

    raw_parts = raw.get("parts", [])
    if not isinstance(raw_parts, list):
        raw_parts = []

    parts = [
        RawPart(
            part_no=str(p.get("part_no", "")),
            series=str(p.get("series", "")),
            description=str(p.get("description", "")),
        )
        for p in raw_parts
        if isinstance(p, dict)
    ]

    skipped = not parts and skip_reason is not None

    return PageResult(
        page_no=page_no,
        subcategory=subcategory,
        parts=parts,
        skipped=skipped,
        skip_reason=skip_reason,
    )
