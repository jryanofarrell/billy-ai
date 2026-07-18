import pytest

from parts_parser.pdf.tables import RawPart, is_code, parse_page_tables


def test_part_code_shape_accepts_catalog_codes_and_rejects_measurements():
    assert is_code("1460-4")
    assert is_code("S3749-2A")
    assert is_code("GO9-72")

    assert not is_code("3/8")
    assert not is_code(".122")
    assert not is_code("1-1/4")


def test_single_size_table_labels_pipe_description():
    text = """Synthetic Couplings
PART No.  Pipe
XX-100-A  1/2
XX-100-b  3/4
"""

    scan = parse_page_tables(text)

    assert scan.parts == [
        RawPart("XX-100-A", "Synthetic Couplings", "Pipe: 1/2"),
        RawPart("XX-100-b", "Synthetic Couplings", "Pipe: 3/4"),
    ]
    assert scan.suspicious == []


def test_two_size_table_labels_tube_and_pipe_description():
    text = """Synthetic Adapters
PART No.  Tube  Pipe
YY-200-A  3/8  1/2
YY-200-B  1/2  3/4
"""

    scan = parse_page_tables(text)

    assert scan.parts == [
        RawPart("YY-200-A", "Synthetic Adapters", "Tube: 3/8, Pipe: 1/2"),
        RawPart("YY-200-B", "Synthetic Adapters", "Tube: 1/2, Pipe: 3/4"),
    ]
    assert scan.suspicious == []


def test_description_and_qty_table_keeps_free_text_and_captures_quantity():
    text = """Synthetic Repair Kits
PART No.  Description  Qty
KIT-300-A  Replacement seal and spring assortment  6
KIT-300-B  Handle hardware pack  12
"""

    scan = parse_page_tables(text)

    assert scan.parts == [
        RawPart(
            "KIT-300-A",
            "Synthetic Repair Kits",
            "Replacement seal and spring assortment, Qty: 6",
        ),
        RawPart("KIT-300-B", "Synthetic Repair Kits", "Handle hardware pack, Qty: 12"),
    ]
    assert scan.suspicious == []


def test_mirrored_part_number_table_extracts_both_sides_and_skips_placeholder():
    text = """Synthetic Valves
PART No.  Pipe    PART No.  Pipe
MV-400-L  1/2    MV-400-R  3/4
MV-401-L  1      --        1-1/4
"""

    scan = parse_page_tables(text)

    assert [part.part_no for part in scan.parts] == ["MV-400-L", "MV-400-R", "MV-401-L"]
    assert all(part.series == "Synthetic Valves" for part in scan.parts)
    assert scan.suspicious == []


def test_prose_page_returns_no_parts_with_substantial_word_count():
    text = """This synthetic catalog page explains how a family of components is
selected and installed. It contains ordinary prose about materials, compatible
connections, operating conditions, maintenance, inspection, and safe handling.
The paragraph deliberately contains enough words to represent a substantial
page, but it has no catalog part codes or regular product table rows at all.
"""

    scan = parse_page_tables(text)

    assert scan.parts == []
    assert scan.suspicious == []
    assert scan.word_count >= 40


@pytest.mark.parametrize(
    "excluded_line",
    [
        "• BEND GUARD: Page 248",
        "Width: 14.5 In.",
        "1/4 3/8 1/2 3/4 1",
        "1/2 NPT",
        "1-5/16 FEMALE",
        "Height 6-3/4 inches",
        "FERRULES-BRASS .....60",
    ],
)
def test_excluded_line_shapes_are_not_suspicious(excluded_line):
    text = f"""Synthetic Fittings
PART No. Size Qty
ZX-100-A 1/4 5
{excluded_line}
ZX-100-B 1/2 8
"""

    scan = parse_page_tables(text)

    assert [part.part_no for part in scan.parts] == ["ZX-100-A", "ZX-100-B"]
    assert scan.suspicious == []


def test_unknown_code_shape_in_tabular_row_is_suspicious_with_source_context():
    text = """Synthetic Fittings
PART No. Size Qty
ZX-200-A 1/4 5
ZZZZ 1/4 1/2 3.50
ZX-200-B 1/2 8
"""

    scan = parse_page_tables(text)

    assert len(scan.suspicious) == 1
    suspicious = scan.suspicious[0]
    assert suspicious.line_no == 4
    assert suspicious.text == "ZZZZ 1/4 1/2 3.50"
    assert suspicious.headings == "Synthetic Fittings"
    assert suspicious.reason == "unrecognized part-number shape"


def test_numeric_star_code_is_parsed_only_under_part_number_header():
    under_header = parse_page_tables(
        """Synthetic Adapters
PART No. Size Connection
2368* 1-3/4 Female Acme
"""
    )
    without_header = parse_page_tables(
        """Synthetic Adapters
2368* 1-3/4 Female Acme
"""
    )

    assert [part.part_no for part in under_header.parts] == ["2368*"]
    assert without_header.parts == []


def test_part_lines_are_parallel_to_parts_in_source_line_order():
    text = """Synthetic Nipples
PART No. Size Qty
NP-300-C 3/4 3
NP-300-A 1/4 1
NP-300-B 1/2 2
"""

    scan = parse_page_tables(text)

    assert [part.part_no for part in scan.parts] == ["NP-300-C", "NP-300-A", "NP-300-B"]
    assert scan.part_lines == [3, 4, 5]
    assert len(scan.part_lines) == len(scan.parts)


def test_series_uses_full_contiguous_heading_run_above_header():
    text = """TUBE
COUPLING
Swivel Flare
(FORGED NUTS)
PART No.  Tube
34-4  1/4
34-5  5/16
"""
    scan = parse_page_tables(text)
    assert [p.series for p in scan.parts] == [
        "TUBE COUPLING Swivel Flare (FORGED NUTS)",
        "TUBE COUPLING Swivel Flare (FORGED NUTS)",
    ]


def test_heading_may_contain_digits_like_angle_degrees():
    text = """90° ELBOW
PART No.  Pipe
BI-116-A  1/8
"""
    scan = parse_page_tables(text)
    assert scan.parts[0].series == "90° ELBOW"


def test_variant_subheading_merges_onto_parent_block():
    text = """FORGED NUT
Short Standard Type
PART No.  Tube
40-8  1/2
Reducing
PART No.  Tube
40R-64  3/8 to 1/4
"""
    scan = parse_page_tables(text)
    assert scan.parts[0].series == "FORGED NUT Short Standard Type"
    assert scan.parts[1].series == "FORGED NUT Short Standard Type / Reducing"


def test_code_bearing_cross_reference_does_not_erase_pending_heading():
    text = """BUSHING
Steel merchant see BI-110MC
PART No.  Pipe
BI-110-BA  1/4
"""
    scan = parse_page_tables(text)
    assert scan.parts[0].series == "BUSHING"


def test_prose_note_is_excluded_from_series():
    text = """PLUG
Note: supplied in steel with a zinc coating for corrosion resistance.
PART No.  Pipe
BI-109-A  1/8
"""
    scan = parse_page_tables(text)
    assert scan.parts[0].series == "PLUG"


def test_empty_heading_run_carries_the_previous_series_forward():
    text = """ELBOW
PART No.  Pipe
BI-100-A  1/8
PART No.  Pipe
BI-100-B  1/4
"""
    scan = parse_page_tables(text)
    assert [p.series for p in scan.parts] == ["ELBOW", "ELBOW"]


def test_bare_part_no_subheader_still_emits_parts_without_bleeding_heading():
    text = """FORGED NUT
Short Standard Type
PART No.  Hex Size  Tube
40-8  15/16  1/2
Lead Free
Part No.
LF-40-12  1-5/16  3/4
MILLED NUT
Short Type
PART No.  Length  Tube
41S-3  5/8  3/16
"""
    scan = parse_page_tables(text)
    by_no = {p.part_no: p for p in scan.parts}
    assert "LF-40-12" in by_no
    assert by_no["LF-40-12"].series == "FORGED NUT Short Standard Type / Lead Free"
    assert by_no["41S-3"].series == "MILLED NUT Short Type"


def test_wrapped_lowercase_prose_is_not_a_heading():
    text = """water systems that have a weighted
average lead content less than or
equal to 0.25%.
UNION
COUPLING
Tube to Tube
PART No.  Tube
42-2  1/8
"""
    scan = parse_page_tables(text)
    assert scan.parts[0].series == "UNION COUPLING Tube to Tube"
