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

    parts, reasons = parse_page_tables(text)

    assert parts == [
        RawPart("XX-100-A", "Synthetic Couplings", "Pipe: 1/2"),
        RawPart("XX-100-b", "Synthetic Couplings", "Pipe: 3/4"),
    ]
    assert reasons == []


def test_two_size_table_labels_tube_and_pipe_description():
    text = """Synthetic Adapters
PART No.  Tube  Pipe
YY-200-A  3/8  1/2
YY-200-B  1/2  3/4
"""

    parts, reasons = parse_page_tables(text)

    assert parts == [
        RawPart("YY-200-A", "Synthetic Adapters", "Tube: 3/8, Pipe: 1/2"),
        RawPart("YY-200-B", "Synthetic Adapters", "Tube: 1/2, Pipe: 3/4"),
    ]
    assert reasons == []


def test_description_and_qty_table_keeps_free_text_and_captures_quantity():
    text = """Synthetic Repair Kits
PART No.  Description  Qty
KIT-300-A  Replacement seal and spring assortment  6
KIT-300-B  Handle hardware pack  12
"""

    parts, reasons = parse_page_tables(text)

    assert parts == [
        RawPart(
            "KIT-300-A",
            "Synthetic Repair Kits",
            "Replacement seal and spring assortment, Qty: 6",
        ),
        RawPart("KIT-300-B", "Synthetic Repair Kits", "Handle hardware pack, Qty: 12"),
    ]
    assert reasons == []


def test_mirrored_part_number_table_extracts_both_sides_and_skips_placeholder():
    text = """Synthetic Valves
PART No.  Pipe    PART No.  Pipe
MV-400-L  1/2    MV-400-R  3/4
MV-401-L  1      --        1-1/4
"""

    parts, reasons = parse_page_tables(text)

    assert [part.part_no for part in parts] == ["MV-400-L", "MV-400-R", "MV-401-L"]
    assert all(part.series == "Synthetic Valves" for part in parts)
    assert reasons == []


def test_prose_page_returns_no_parts_and_requests_fallback():
    text = """This synthetic catalog page explains how a family of components is
selected and installed. It contains ordinary prose about materials, compatible
connections, operating conditions, maintenance, inspection, and safe handling.
The paragraph deliberately contains enough words to represent a substantial
page, but it has no catalog part codes or regular product table rows at all.
"""

    parts, reasons = parse_page_tables(text)

    assert parts == []
    assert reasons == ["substantial page text produced no parts"]


def test_good_table_with_junk_measurement_row_keeps_parts_and_requests_fallback():
    text = """Synthetic Connectors
PART No.  Pipe
MX-500-A  1/2
3/8  3/4
"""

    parts, reasons = parse_page_tables(text)

    assert parts == [RawPart("MX-500-A", "Synthetic Connectors", "Pipe: 1/2")]
    assert reasons == ["unrecognized part-number shape in tabular row"]
