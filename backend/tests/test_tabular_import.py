import pytest
from fastapi import HTTPException

from app.csv_import import parse_csv, parse_import_upload


@pytest.mark.parametrize("delimiter", [",", "\t", ";", "|"])
def test_parse_import_upload_detects_supported_delimiters(delimiter: str) -> None:
    content = f"name{delimiter}brand\nDevice{delimiter}Example\n".encode()

    parsed = parse_import_upload("devices.txt", content)

    assert parsed.source_format == "delimited_text"
    assert parsed.delimiter == delimiter
    assert parse_csv(parsed.text) == [["name", "brand"], ["Device", "Example"]]


def test_parse_import_upload_accepts_json_in_txt() -> None:
    parsed = parse_import_upload(
        "devices.txt",
        b'[{"name":"Device","brand":"Example"}]',
    )

    assert parsed.source_format == "json"
    assert parsed.delimiter is None
    assert parse_csv(parsed.text) == [["name", "brand"], ["Device", "Example"]]


def test_parse_import_upload_accepts_json_file() -> None:
    parsed = parse_import_upload("devices.json", b'[{"name":"Device"}]')

    assert parsed.source_format == "json"
    assert parse_csv(parsed.text) == [["name"], ["Device"]]


def test_parse_import_upload_rejects_json_in_csv() -> None:
    with pytest.raises(HTTPException) as exc_info:
        parse_import_upload("devices.csv", b'[{"name":"Device"}]')

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "file_type_mismatch"


@pytest.mark.parametrize(
    ("filename", "content", "detail"),
    [
        ("devices.yaml", b"name: Device", "unsupported_file_type"),
        ("devices.json", b'{"name":"Device"}', "json_array_required"),
        ("devices.json", b'["Device"]', "json_object_rows_required"),
        ("devices.txt", b"single-column\nvalue", "unknown_delimiter"),
    ],
)
def test_parse_import_upload_rejects_invalid_sources(
    filename: str,
    content: bytes,
    detail: str,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        parse_import_upload(filename, content)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == detail


def test_parse_csv_preserves_quoted_newline() -> None:
    assert parse_csv('name,description\nSite,"line one\nline two"\n') == [
        ["name", "description"],
        ["Site", "line one\nline two"],
    ]


def test_parse_import_upload_preserves_quoted_newline() -> None:
    parsed = parse_import_upload(
        "sites.csv",
        b'name,description\nSite,"line one\nline two"\n',
    )

    assert parsed.delimiter == ","
    assert parse_csv(parsed.text)[1] == ["Site", "line one\nline two"]


def test_parse_import_upload_rejects_ambiguous_delimiter() -> None:
    with pytest.raises(HTTPException) as exc_info:
        parse_import_upload("devices.txt", b"name,brand;version\nA,B;C\n")

    assert exc_info.value.detail == "ambiguous_delimiter"
