from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile

from app.core.config import settings
from app.services.file_service import FileService


@pytest.mark.anyio
async def test_save_chunk_streams_to_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MAX_CHUNK_SIZE", 8)
    service = FileService(str(tmp_path))
    upload = UploadFile(file=BytesIO(b"12345678"), filename="chunk")

    result = await service.save_chunk(upload, "audio.wav", 0, 1, "batch")

    assert result["is_complete"] is True
    assert (tmp_path / "tmp" / "chunks" / "batch" / "audio.wav" / "00000").read_bytes() == b"12345678"


@pytest.mark.anyio
async def test_save_chunk_removes_temporary_file_when_too_large(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MAX_CHUNK_SIZE", 4)
    service = FileService(str(tmp_path))
    upload = UploadFile(file=BytesIO(b"12345"), filename="chunk")

    with pytest.raises(HTTPException) as exc_info:
        await service.save_chunk(upload, "audio.wav", 0, 1, "batch")

    assert exc_info.value.status_code == 413
    chunk_dir = tmp_path / "tmp" / "chunks" / "batch" / "audio.wav"
    assert not list(chunk_dir.glob("*"))


def test_merge_chunks_streams_in_order(tmp_path):
    service = FileService(str(tmp_path))
    chunk_dir = service.get_chunk_dir("audio.wav", "batch")
    chunk_dir.mkdir(parents=True)
    (chunk_dir / "00001").write_bytes(b"world")
    (chunk_dir / "00000").write_bytes(b"hello ")

    result = service.merge_chunks("audio.wav", "tmp/merged", "batch")

    assert result.read_bytes() == b"hello world"
    assert not chunk_dir.exists()
