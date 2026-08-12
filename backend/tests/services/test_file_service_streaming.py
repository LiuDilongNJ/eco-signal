from io import BytesIO
from uuid import UUID
from unittest.mock import Mock

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image

from app.core.config import settings
from app.models import Project, User
from app.repositories import project_repository
from app.services.file_service import FileService
from app.services import permission_service


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


@pytest.mark.anyio
async def test_project_picture_upload_restores_existing_file_when_commit_fails(tmp_path, monkeypatch) -> None:
    service = FileService(str(tmp_path))
    project_dir = tmp_path / "projects"
    project_dir.mkdir()
    project = Project(
        project_id=11,
        creator_id=1,
        name="Project",
        uuid=UUID("550e8400-e29b-41d4-a716-446655440000"),
        picture_id="previous-cover.png",
    )
    old_path = project_dir / project.picture_id
    old_path.write_bytes(b"previous-cover")
    session = Mock()
    session.commit.side_effect = RuntimeError("database unavailable")
    monkeypatch.setattr(project_repository, "get", lambda _session, _project_id: project)
    monkeypatch.setattr(permission_service, "is_admin", lambda _user: True)

    buffer = BytesIO()
    Image.new("RGB", (2, 2), "green").save(buffer, "PNG")
    upload = UploadFile(file=BytesIO(buffer.getvalue()), filename="new-cover.png", headers={"content-type": "image/png"})

    with pytest.raises(RuntimeError, match="database unavailable"):
        await service.upload_project_picture(session, project.project_id, User(user_id=1, email="admin@example.com"), upload)

    expected_path = project_dir / "550e8400e29b41d4a716446655440000.png"
    assert old_path.read_bytes() == b"previous-cover"
    assert not expected_path.exists()
    assert project.picture_id == "previous-cover.png"
    session.rollback.assert_called_once()
