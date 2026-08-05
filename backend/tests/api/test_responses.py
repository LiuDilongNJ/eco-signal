from app.api.responses import build_download_content_disposition, csv_response


def test_csv_response_sets_download_headers():
    response = csv_response("name\nvalue\n", "example.csv")

    assert "text/csv" in response.headers["content-type"]
    assert response.headers["content-disposition"] == (
        'attachment; filename="example.csv"; '
        "filename*=UTF-8''example.csv"
    )


def test_csv_response_supports_utf8_filename():
    response = csv_response("name\nvalue\n", "中文导出.csv")

    assert "text/csv" in response.headers["content-type"]
    assert response.headers["content-disposition"] == (
        'attachment; filename="download.csv"; '
        "filename*=UTF-8''%E4%B8%AD%E6%96%87%E5%AF%BC%E5%87%BA.csv"
    )


def test_build_download_content_disposition_keeps_ascii_names_stable():
    header = build_download_content_disposition("example report.ogg")

    assert header == (
        'attachment; filename="example report.ogg"; '
        "filename*=UTF-8''example%20report.ogg"
    )


def test_build_download_content_disposition_encodes_utf8_name():
    header = build_download_content_disposition("中文录音.ogg")

    assert 'filename="download.ogg"' in header
    assert "filename*=UTF-8''%E4%B8%AD%E6%96%87%E5%BD%95%E9%9F%B3.ogg" in header


def test_build_download_content_disposition_sanitizes_unsafe_characters():
    header = build_download_content_disposition('unsafe";\nname.wav')

    assert 'filename="unsafe_name.wav"' in header
    assert "filename*=UTF-8''unsafe%22%3B%0Aname.wav" in header


def test_build_download_content_disposition_defaults_empty_ascii_stem():
    header = build_download_content_disposition("  测试  ")

    assert 'filename="download"' in header
    assert "filename*=UTF-8''%E6%B5%8B%E8%AF%95" in header
