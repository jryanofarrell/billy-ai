from parts_parser.pdf.pages import PageResult, RawPart
from parts_parser.pdf.toc import Section
from parts_parser.pdf.validate import validate_parts


def _make_result(page_no: int, parts: list[RawPart], skipped: bool = False) -> PageResult:
    return PageResult(
        page_no=page_no,
        subcategory="Valves",
        parts=parts,
        skipped=skipped,
        skip_reason="marketing" if skipped else None,
    )


def test_hallucinated_part_dropped_and_reported():
    pages_text = ["Real part AB-100 is here"]
    page_result = _make_result(
        1,
        [
            RawPart(part_no="AB-100", series="", description=""),
            RawPart(part_no="GHOST-999", series="", description=""),
        ],
    )
    sections = [Section(name="S1", category="Fittings", start_page=1, end_page=1)]

    parts, report = validate_parts([page_result], pages_text, sections)

    assert len(parts) == 1
    assert parts[0].part_no == "AB-100"
    assert (1, "GHOST-999") in report.dropped_not_on_page


def test_part_number_with_internal_space_survives_whitespace_collapsed_check():
    # "HAB-NOSE BOX-1" should match because whitespace-collapsed check squashes both
    pages_text = ["HAB-NOSEBOX-1 is listed here"]
    page_result = _make_result(1, [RawPart(part_no="HAB-NOSE BOX-1", series="", description="")])
    sections = [Section(name="S1", category="Fittings", start_page=1, end_page=1)]

    parts, report = validate_parts([page_result], pages_text, sections)

    assert len(parts) == 1
    assert parts[0].part_no == "HAB-NOSE BOX-1"
    assert report.dropped_not_on_page == []


def test_duplicate_across_pages_kept_once_and_reported():
    pages_text = ["DUP-001 here", "DUP-001 again"]
    results = [
        _make_result(1, [RawPart(part_no="DUP-001", series="", description="")]),
        _make_result(2, [RawPart(part_no="DUP-001", series="", description="")]),
    ]
    sections = [Section(name="S1", category="Fittings", start_page=1, end_page=2)]

    parts, report = validate_parts(results, pages_text, sections)

    assert len(parts) == 1
    assert parts[0].part_no == "DUP-001"
    assert "DUP-001" in report.duplicates


def test_sequence_has_no_gaps_after_drops():
    pages_text = ["GOOD-1 text", "REAL-2 text"]
    results = [
        _make_result(
            1,
            [
                RawPart(part_no="GOOD-1", series="", description=""),
                RawPart(part_no="GHOST", series="", description=""),
            ],
        ),
        _make_result(2, [RawPart(part_no="REAL-2", series="", description="")]),
    ]
    sections = [Section(name="S1", category="Fittings", start_page=1, end_page=2)]

    parts, report = validate_parts(results, pages_text, sections)

    assert [p.sequence for p in parts] == [1, 2]
    assert len(report.dropped_not_on_page) == 1


def test_category_comes_from_page_section():
    pages_text = ["VALVE-1 here", "PIPE-1 here"]
    results = [
        _make_result(1, [RawPart(part_no="VALVE-1", series="", description="")]),
        _make_result(2, [RawPart(part_no="PIPE-1", series="", description="")]),
    ]
    sections = [
        Section(name="Valves", category="Valves", start_page=1, end_page=1),
        Section(name="Pipes", category="Pipes", start_page=2, end_page=2),
    ]

    parts, report = validate_parts(results, pages_text, sections)

    assert parts[0].category == "Valves"
    assert parts[1].category == "Pipes"


def test_skipped_pages_counted_and_excluded():
    pages_text = ["marketing page", "PART-1 here"]
    results = [
        _make_result(1, [], skipped=True),
        _make_result(2, [RawPart(part_no="PART-1", series="", description="")]),
    ]
    sections = [Section(name="S1", category="Cat", start_page=1, end_page=2)]

    parts, report = validate_parts(results, pages_text, sections)

    assert len(parts) == 1
    assert report.pages_skipped == 1
    assert report.pages_processed == 1
