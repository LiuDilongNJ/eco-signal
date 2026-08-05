from app.csv_import import effective_header_width


def test_effective_header_width_drops_single_trailing_blank() -> None:
    header = ["Date Time", "Duration(s)", "Name", ""]
    assert effective_header_width(header) == 3


def test_effective_header_width_drops_multiple_trailing_blanks() -> None:
    header = ["A", "B", "", " ", ""]
    assert effective_header_width(header) == 2


def test_effective_header_width_keeps_clean_header() -> None:
    header = ["A", "B", "C"]
    assert effective_header_width(header) == len(header)


def test_effective_header_width_all_blank_returns_zero() -> None:
    assert effective_header_width(["", " ", "\t"]) == 0
