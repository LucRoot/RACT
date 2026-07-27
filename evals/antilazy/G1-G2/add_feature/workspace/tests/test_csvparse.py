from csvparse import parse_csv_line


def test_parse_simple() -> None:
    assert parse_csv_line("a,b,c") == ("a", "b", "c")
