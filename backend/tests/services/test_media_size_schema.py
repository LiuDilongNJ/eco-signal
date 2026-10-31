import pytest

from app.schemas.media import (
    AudioFileMetadataPublic,
    MediaBrowseGalleryItem,
    MediaListPublic,
    MediaPublic,
)


@pytest.mark.parametrize("schema", [MediaListPublic, MediaBrowseGalleryItem, MediaPublic])
def test_media_size_schema_describes_bytes_without_renaming_field(schema):
    field = schema.model_json_schema()["properties"]["size_b"]
    assert field["description"] == "File size in bytes"
    assert field["default"] is None


def test_audio_metadata_preserves_exact_byte_count():
    response = AudioFileMetadataPublic(
        media_id=201, schema_version=1, source={}, stored={"size_b": 153604158},
    )
    assert response.model_dump()["stored"] == {"size_b": 153604158}
    assert "size_b is the file size in bytes" in response.model_json_schema()["properties"]["stored"]["description"]
