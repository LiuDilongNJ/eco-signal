import pytest

from app.utils import validate_optional_http_url, validate_required_http_url


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://example.com/path?key=value", "https://example.com/path?key=value"),
        ("  http://192.168.1.8:8080/api  ", "http://192.168.1.8:8080/api"),
        (None, None),
        ("   ", None),
    ],
)
def test_validate_optional_http_url_normalizes_allowed_values(
    value: str | None, expected: str | None
) -> None:
    assert validate_optional_http_url(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "example.com",
        "//example.com/path",
        "https:///missing-host",
        "https://example.com:99999",
        "https://user:pass@example.com",
        "javascript:alert(1)",
        "data:text/plain,test",
        "blob:https://example.com/id",
        "file:///tmp/file",
        "ftp://example.com/file",
        "https://example.com/has space",
    ],
)
def test_validate_optional_http_url_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        validate_optional_http_url(value)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_validate_required_http_url_rejects_empty_values(value: str | None) -> None:
    with pytest.raises(ValueError, match="required"):
        validate_required_http_url(value)
