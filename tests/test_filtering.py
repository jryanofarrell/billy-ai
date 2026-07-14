from pathlib import Path

import pytest
from openpyxl import Workbook

from parts_parser.models import PartRecord
from parts_parser.output.filtering import (
    FilterEntry,
    FilterSheet,
    OutputError,
    load_filter_sheet,
    match_parts,
    normalize_key,
)


def _save_workbook(path: Path, rows: list[tuple[object, ...]]) -> None:
    workbook = Workbook()
    worksheet = workbook.active
    for row in rows:
        worksheet.append(row)
    workbook.save(path)
    workbook.close()


def _filter_sheet(*raw_values: str) -> FilterSheet:
    return FilterSheet(
        path=Path("synthetic-filter.xlsx"),
        column_label='column A ("Part No")',
        entries=[
            FilterEntry(raw=raw, normalized=normalize_key(raw), row=row)
            for row, raw in enumerate(raw_values, start=2)
        ],
    )


@pytest.mark.parametrize(
    "raw",
    ["bi-110-ba", " BI 110 BA ", "BI–110–BA"],
)
def test_normalize_key_uppercases_and_removes_non_alphanumerics(raw):
    assert normalize_key(raw) == "BI110BA"


def test_load_filter_sheet_detects_header_outside_column_a_and_skips_blanks(tmp_path):
    path = tmp_path / "filter.xlsx"
    _save_workbook(
        path,
        [
            ("Qty", "Part No"),
            (1, "BI-110-BA"),
            (2, None),
            (3, "  XY 20  "),
        ],
    )

    filter_sheet = load_filter_sheet(path)

    assert filter_sheet.column_label == 'column B ("Part No")'
    assert [entry.raw for entry in filter_sheet.entries] == ["BI-110-BA", "XY 20"]
    assert [entry.row for entry in filter_sheet.entries] == [2, 4]


def test_load_filter_sheet_falls_back_to_column_a_and_treats_row_one_as_data(tmp_path):
    path = tmp_path / "filter.xlsx"
    _save_workbook(path, [("BI-110-BA", "Description"), ("XY-20", "Elbow")])

    filter_sheet = load_filter_sheet(path)

    assert filter_sheet.column_label == "column A (no header found)"
    assert [entry.raw for entry in filter_sheet.entries] == ["BI-110-BA", "XY-20"]
    assert [entry.row for entry in filter_sheet.entries] == [1, 2]


def test_load_filter_sheet_converts_integral_float_to_digit_string(tmp_path):
    path = tmp_path / "filter.xlsx"
    _save_workbook(path, [("Part Number",), (28002.0,)])

    filter_sheet = load_filter_sheet(path)

    assert filter_sheet.entries[0].raw == "28002"


def test_load_filter_sheet_raises_output_error_for_empty_sheet(tmp_path):
    path = tmp_path / "empty.xlsx"
    _save_workbook(path, [])

    with pytest.raises(OutputError):
        load_filter_sheet(path)


def test_match_parts_prefers_exact_match_over_normalized_collision():
    parts = [PartRecord(part_no="BI-110-BA"), PartRecord(part_no="bi110ba")]

    matched_parts, report = match_parts(_filter_sheet("bi110ba"), parts)

    assert [part.part_no for part in matched_parts] == ["bi110ba"]
    assert report.results[0].match_type == "exact"
    assert report.results[0].matched_part_nos == ["bi110ba"]


def test_match_parts_reports_normalized_match():
    parts = [PartRecord(part_no="BI-110-BA")]

    matched_parts, report = match_parts(_filter_sheet("bi110ba"), parts)

    assert [part.part_no for part in matched_parts] == ["BI-110-BA"]
    assert report.results[0].match_type == "normalized"
    assert report.results[0].matched_part_nos == ["BI-110-BA"]


def test_match_parts_reports_all_candidates_for_normalized_collision():
    parts = [PartRecord(part_no="BI-110-BA"), PartRecord(part_no="bi110ba")]

    matched_parts, report = match_parts(_filter_sheet("BI 110 BA"), parts)

    assert [part.part_no for part in matched_parts] == ["BI-110-BA", "bi110ba"]
    assert report.results[0].match_type == "collision"
    assert report.results[0].matched_part_nos == ["BI-110-BA", "bi110ba"]
    assert report.results[0].note


def test_match_parts_reports_unmatched_entry():
    matched_parts, report = match_parts(
        _filter_sheet("NOT-A-PART"), [PartRecord(part_no="BI-110-BA")]
    )

    assert matched_parts == []
    assert report.results[0].filter_raw == "NOT-A-PART"
    assert report.results[0].match_type == "unmatched"
    assert report.results[0].matched_part_nos == []


def test_match_parts_deduplicates_matches_in_source_order():
    parts = [
        PartRecord(part_no="SECOND"),
        PartRecord(part_no="FIRST"),
        PartRecord(part_no="SECOND"),
    ]

    matched_parts, report = match_parts(
        _filter_sheet("FIRST", "SECOND", "SECOND"), parts
    )

    assert [part.part_no for part in matched_parts] == ["SECOND", "FIRST"]
    assert [result.match_type for result in report.results] == ["exact", "exact", "exact"]
