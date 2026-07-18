from dataclasses import dataclass, field


@dataclass
class PartRecord:
    part_no: str
    category: str = ""
    subcategory: str = ""
    series: str = ""
    description: str = ""
    page_number: str = ""
    sequence: int | None = None
    attributes: dict[str, str] = field(default_factory=dict)
