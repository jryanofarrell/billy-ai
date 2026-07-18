from parts_parser.pdf.extract import _page_number


def test_page_number_reads_bottom_corner_integer():
    words = [
        {"text": "40-3", "x0": 36, "top": 200},
        {"text": "1/2", "x0": 200, "top": 200},
        {"text": "2", "x0": 36, "top": 775},
    ]
    assert _page_number(words, 612, 792) == "2"


def test_page_number_reads_bottom_right_corner():
    words = [{"text": "33", "x0": 571, "top": 775}]
    assert _page_number(words, 612, 792) == "33"


def test_page_number_ignores_table_and_top_margin_integers():
    words = [
        {"text": "40", "x0": 311, "top": 30},
        {"text": "3", "x0": 300, "top": 400},
    ]
    assert _page_number(words, 612, 792) == ""
