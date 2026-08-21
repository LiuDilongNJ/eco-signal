"""Unit tests for media worker tasks."""
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import Session

from app.models import (
    AudioSetting,
    Collection,
    FileUpload,
    Media,
    MediaCollection,
    PhotoSetting,
    Role,
    User,
)
from app.workers.tasks.media import _find_duplicate_media, _md5_file, process_media


def test_md5_file_reads_incrementally(tmp_path: Path):
    path = tmp_path / "large.bin"
    path.write_bytes(b"a" * (2 * 1024 * 1024 + 17))
    assert _md5_file(path) == "35de9c6a8ff96d68db9e284d3f7c6aa7"


def test_find_duplicate_media_scoped_to_collection(db: Session):
    """Duplicate detection only matches identical MD5 within the same collection."""
    role = Role(name="DupRole_" + str(datetime.now().timestamp()))
    db.add(role)
    db.flush()
    user = User(username="dup_u", role_id=role.role_id, email="dup@e.com", password="p", name="D")
    db.add(user)
    db.flush()
    col_a = Collection(name="Dup Col A", creator_id=user.user_id)
    col_b = Collection(name="Dup Col B", creator_id=user.user_id)
    db.add_all([col_a, col_b])
    db.flush()
    audio_setting = AudioSetting(duration_s=1.0)
    db.add(audio_setting)
    db.flush()
    media = Media(
        media_type="audio",
        md5_hash="abc123",
        uploader_id=user.user_id,
        audio_setting_id=audio_setting.audio_setting_id,
    )
    db.add(media)
    db.flush()
    db.add(
        MediaCollection(
            media_id=media.media_id,
            collection_id=col_a.collection_id,
            added_by=user.user_id,
        )
    )
    db.flush()

    assert _find_duplicate_media(db, "abc123", col_a.collection_id) == media.media_id
    assert _find_duplicate_media(db, "abc123", col_b.collection_id) is None
    assert _find_duplicate_media(db, "nomatch", col_a.collection_id) is None
    assert _find_duplicate_media(db, None, col_a.collection_id) is None


@pytest.mark.anyio
class TestProcessMediaTask:
    """Tests for the process_media ARQ task."""

    @pytest.fixture(autouse=True)
    def mock_streaming_md5(self):
        with patch("app.workers.tasks.media._md5_file", return_value="streamed-md5"), patch(
            "app.workers.tasks.media._find_duplicate_media", return_value=None
        ):
            yield

    async def test_file_upload_not_found(self):
        """Returns error if FileUpload record does not exist."""
        mock_session = MagicMock()
        mock_session.get.return_value = None
        
        with patch("app.workers.tasks.media.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            
            result = await process_media(ctx={}, file_upload_id=1, collection_id=10)
            
        assert result == {"error": "FileUpload not found"}

    @patch("app.workers.tasks.media.generate_thumbnail")
    @patch("app.workers.tasks.media.file_service.ensure_audio_is_flac")
    @patch("mutagen.File")
    @patch("hashlib.md5")
    @patch("shutil.move")
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.is_file")
    @patch("pathlib.Path.stat")
    @patch("pathlib.Path.read_bytes")
    async def test_process_media_success(
        self,
        mock_read_bytes,
        mock_stat,
        mock_is_file,
        mock_mkdir,
        mock_move,
        mock_md5,
        mock_mutagen,
        mock_ensure_flac,
        mock_generate_thumbnail,
    ):
        """Successful media processing flow."""
        mock_session = MagicMock()
        mock_ensure_flac.return_value = (Path("/tmp/test.flac"), "test.flac")
        mock_generate_thumbnail.return_value = b"\x89PNG\r\nfake"
        
        # Mock FileUpload record
        file_upload = FileUpload(
            file_upload_id=1,
            filename="test.wav",
            path="/tmp/test.wav",
            status=1,
            uploader_id=1,
            directory="dir1",
            name="Test File"
        )
        mock_session.get.return_value = file_upload
        
        # Mock Path interactions
        mock_is_file.return_value = True
        mock_stat.return_value.st_mode = 33188  # regular file
        mock_stat.return_value.st_size = 1000
        mock_read_bytes.return_value = b"fake-audio-data"
        
        # Mock MD5
        mock_md5.return_value.hexdigest.return_value = "fake-md5-hash"
        
        # Mock Mutagen
        mock_audio = MagicMock()
        mock_audio.info.length = 10.5
        mock_audio.info.sample_rate = 48000
        mock_audio.info.channels = 2
        mock_audio.info.bits_per_sample = 24
        mock_mutagen.return_value = mock_audio
        
        # Ensure session.add assigns IDs
        def mock_add(obj):
            if isinstance(obj, AudioSetting):
                obj.audio_setting_id = 100
            elif isinstance(obj, Media):
                obj.media_id = 200
        mock_session.add.side_effect = mock_add

        with patch("app.workers.tasks.media.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            
            result = await process_media(
                ctx={},
                file_upload_id=1,
                collection_id=10,
                site_id=5,
                sensor_id=2,
                license_id=1,
                medium="air",
                file_date="2024-03-10",
                file_time="12:00:00"
            )
            
        assert result["status"] == "completed"
        assert result["media_id"] == 200
        assert file_upload.status == 3 # completed
        assert file_upload.media_id == 200
        assert file_upload.filename == "test.flac"
        assert file_upload.path == "tmp/test.flac"
        
        # Verify database calls
        assert mock_session.commit.call_count >= 2
        
        # Verify file move
        mock_move.assert_called_once()
        mock_ensure_flac.assert_called_once()

    @patch("app.workers.tasks.media.generate_media_previews")
    @patch("app.workers.tasks.media._photo_metadata")
    @patch("shutil.move")
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.is_file")
    @patch("pathlib.Path.stat")
    async def test_process_photo_creates_only_photo_settings(
        self,
        mock_stat,
        mock_is_file,
        mock_mkdir,
        mock_move,
        mock_photo_metadata,
        mock_generate_previews,
    ):
        mock_session = MagicMock()
        file_upload = FileUpload(
            file_upload_id=1,
            filename="photo.png",
            path="/tmp/photo.png",
            status=1,
            uploader_id=1,
            directory="dir1",
            name="Photo",
        )
        mock_session.get.return_value = file_upload
        mock_is_file.return_value = True
        mock_stat.return_value.st_size = 1000
        mock_photo_metadata.return_value = (
            {"exposure_ms": 2.5, "aperture": 4.0, "iso": 200},
            None,
            (100, 100),
        )
        mock_generate_previews.return_value = MagicMock(warnings=[])

        created: list[object] = []

        def mock_add(obj):
            created.append(obj)
            if isinstance(obj, PhotoSetting):
                obj.photo_setting_id = 100
            elif isinstance(obj, Media):
                obj.media_id = 200

        mock_session.add.side_effect = mock_add

        with patch("app.workers.tasks.media.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            result = await process_media(
                ctx={},
                file_upload_id=1,
                collection_id=10,
                creator_id=99,
                media_type="photo",
                recording_gain_db=8,
                duty_cycle_recording=10,
                duty_cycle_period=60,
            )

        created_media = next(obj for obj in created if isinstance(obj, Media))
        assert result == {"file_upload_id": 1, "media_id": 200, "status": "completed"}
        assert any(isinstance(obj, PhotoSetting) for obj in created)
        assert not any(isinstance(obj, AudioSetting) for obj in created)
        assert created_media.audio_setting_id is None
        assert created_media.photo_setting_id == 100
        assert created_media.uploader_id == 1
        assert created_media.creator_id == 99
        assert created_media.duty_cycle_recording is None
        assert created_media.duty_cycle_period is None
        mock_move.assert_called_once()

    @patch("app.workers.tasks.media._find_duplicate_media", return_value=999)
    @patch("app.workers.tasks.media.file_service.ensure_audio_is_flac")
    @patch("mutagen.File")
    @patch("pathlib.Path.unlink")
    @patch("pathlib.Path.is_file")
    @patch("pathlib.Path.stat")
    async def test_process_media_skips_duplicate_audio(
        self,
        mock_stat,
        mock_is_file,
        mock_unlink,
        mock_mutagen,
        mock_ensure_flac,
        mock_find_dup,
    ):
        """Audio with an existing MD5 in the collection is skipped, not inserted."""
        mock_session = MagicMock()
        mock_ensure_flac.return_value = (Path("/tmp/test.flac"), "test.flac")
        file_upload = FileUpload(
            file_upload_id=1,
            filename="test.wav",
            path="/tmp/test.wav",
            status=1,
            uploader_id=1,
            directory="dir1",
            name="Test File",
        )
        mock_session.get.return_value = file_upload
        mock_is_file.return_value = True
        mock_stat.return_value.st_size = 1000

        created: list[object] = []
        mock_session.add.side_effect = lambda obj: created.append(obj)

        with patch("app.workers.tasks.media.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            result = await process_media(
                ctx={},
                file_upload_id=1,
                collection_id=10,
                media_type="audio",
            )

        assert result["status"] == "duplicate"
        assert result["existing_media_id"] == 999
        assert result["file_upload_id"] == 1
        assert file_upload.status == 5
        assert file_upload.media_id == 999
        assert not any(isinstance(obj, (Media, AudioSetting)) for obj in created)
        mock_mutagen.assert_not_called()
        mock_unlink.assert_called_once()

    @patch("app.workers.tasks.media._find_duplicate_media", return_value=555)
    @patch("app.workers.tasks.media._photo_metadata")
    @patch("pathlib.Path.unlink")
    @patch("pathlib.Path.is_file")
    @patch("pathlib.Path.stat")
    async def test_process_media_skips_duplicate_photo(
        self,
        mock_stat,
        mock_is_file,
        mock_unlink,
        mock_photo_metadata,
        mock_find_dup,
    ):
        """Photo with an existing MD5 in the collection is skipped before validation."""
        mock_session = MagicMock()
        file_upload = FileUpload(
            file_upload_id=2,
            filename="photo.png",
            path="/tmp/photo.png",
            status=1,
            uploader_id=1,
            directory="dir1",
            name="Photo",
        )
        mock_session.get.return_value = file_upload
        mock_is_file.return_value = True
        mock_stat.return_value.st_size = 1000

        created: list[object] = []
        mock_session.add.side_effect = lambda obj: created.append(obj)

        with patch("app.workers.tasks.media.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            result = await process_media(
                ctx={},
                file_upload_id=2,
                collection_id=10,
                media_type="photo",
            )

        assert result["status"] == "duplicate"
        assert result["existing_media_id"] == 555
        assert file_upload.status == 5
        assert file_upload.media_id == 555
        assert not any(isinstance(obj, (Media, PhotoSetting)) for obj in created)
        mock_photo_metadata.assert_not_called()
        mock_unlink.assert_called_once()

    @patch("app.workers.tasks.media.generate_thumbnail")
    @patch("app.workers.tasks.media.file_service.ensure_audio_is_flac")
    @patch("mutagen.File")
    @patch("hashlib.md5")
    @patch("shutil.move")
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.is_file")
    @patch("pathlib.Path.stat")
    @patch("pathlib.Path.read_bytes")
    async def test_process_media_uses_display_filename_as_logical_name(
        self,
        mock_read_bytes,
        mock_stat,
        mock_is_file,
        mock_mkdir,
        mock_move,
        mock_md5,
        mock_mutagen,
        mock_ensure_flac,
        mock_generate_thumbnail,
    ):
        """Audio stores prefixed FLAC filename while keeping original display name in media.name."""
        mock_session = MagicMock()
        mock_generate_thumbnail.return_value = b"\x89PNG\r\nfake"
        mock_ensure_flac.return_value = (Path("/tmp/LEGACY_test.flac"), "LEGACY_test.flac")

        file_upload = FileUpload(
            file_upload_id=1,
            filename="test.wav",
            path="/tmp/test.wav",
            status=1,
            uploader_id=1,
            directory="dir1",
            name="test.wav",
        )
        mock_session.get.return_value = file_upload
        mock_is_file.return_value = True
        mock_stat.return_value.st_size = 1000
        mock_read_bytes.return_value = b"fake-audio-data"
        mock_md5.return_value.hexdigest.return_value = "fake-md5-hash"

        mock_audio = MagicMock()
        mock_audio.info.length = 10.5
        mock_audio.info.sample_rate = 48000
        mock_audio.info.channels = 2
        mock_audio.info.bits_per_sample = 24
        mock_mutagen.return_value = mock_audio

        media_holder: dict[str, Media] = {}

        def mock_add(obj):
            if isinstance(obj, AudioSetting):
                obj.audio_setting_id = 100
            elif isinstance(obj, Media):
                obj.media_id = 200
                media_holder["media"] = obj

        mock_session.add.side_effect = mock_add

        with patch("app.workers.tasks.media.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)

            result = await process_media(
                ctx={},
                file_upload_id=1,
                collection_id=10,
                display_filename="LEGACY_test.wav",
            )

        assert result["status"] == "completed"
        assert file_upload.filename == "LEGACY_test.flac"
        assert file_upload.path == "tmp/LEGACY_test.flac"
        assert media_holder["media"].filename == "LEGACY_test.flac"
        assert media_holder["media"].name == "test.wav"

    @patch("pathlib.Path.is_file")
    async def test_process_media_file_not_found(self, mock_is_file):
        """Sets status to error if physical file is missing."""
        mock_session = MagicMock()
        file_upload = FileUpload(file_upload_id=1, path="/tmp/missing.wav", status=1)
        mock_session.get.return_value = file_upload
        mock_is_file.return_value = False
        
        with patch("app.workers.tasks.media.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            
            result = await process_media(ctx={}, file_upload_id=1, collection_id=10)
            
        assert "error" in result
        assert file_upload.status == 4 # error
        assert "File not found" in file_upload.error

    async def test_process_photo_without_merged_path_returns_error(self):
        mock_session = MagicMock()
        file_upload = FileUpload(file_upload_id=1, path="", status=1)
        mock_session.get.return_value = file_upload

        with patch("app.workers.tasks.media.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)

            result = await process_media(
                ctx={}, file_upload_id=1, collection_id=10, media_type="photo"
            )

        assert result == {"error": "Photo upload is incomplete"}
        assert file_upload.status == 4
        mock_session.commit.assert_called_once()

    @patch("app.workers.tasks.media.generate_thumbnail")
    @patch("app.workers.tasks.media.file_service.ensure_audio_is_flac")
    @patch("mutagen.File")
    @patch("pathlib.Path.is_file")
    @patch("pathlib.Path.stat")
    @patch("pathlib.Path.read_bytes")
    async def test_process_media_mutagen_fail(
        self,
        mock_read_bytes,
        mock_stat,
        mock_is_file,
        mock_mutagen,
        mock_ensure_flac,
        mock_generate_thumbnail,
    ):
        """Continues with defaults if mutagen fails."""
        mock_session = MagicMock()
        mock_ensure_flac.return_value = (Path("/tmp/test.flac"), "test.flac")
        mock_generate_thumbnail.return_value = b"\x89PNG\r\nfake"
        file_upload = FileUpload(file_upload_id=1, path="/tmp/test.wav", filename="test.wav")
        mock_session.get.return_value = file_upload
        mock_is_file.return_value = True
        mock_stat.return_value.st_mode = 33188
        mock_read_bytes.return_value = b"data"
        
        mock_mutagen.side_effect = Exception("Mutagen crash")
        
        with patch("app.workers.tasks.media.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            with patch("shutil.move"):
                with patch("pathlib.Path.mkdir"):
                    result = await process_media(ctx={}, file_upload_id=1, collection_id=10)
                    
        assert result["status"] == "completed"

    @patch("app.workers.tasks.media.file_service.ensure_audio_is_flac")
    @patch("mutagen.File")
    @patch("pathlib.Path.is_file")
    @patch("pathlib.Path.stat")
    @patch("pathlib.Path.read_bytes")
    async def test_process_media_invalid_datetime(
        self,
        mock_read_bytes,
        mock_stat,
        mock_is_file,
        mock_mutagen,
        mock_ensure_flac,
    ):
        """Handles invalid date/time strings without crashing."""
        mock_session = MagicMock()
        mock_ensure_flac.return_value = (Path("/tmp/test.flac"), "test.flac")
        file_upload = FileUpload(file_upload_id=1, path="/tmp/test.wav", filename="test.wav")
        mock_session.get.return_value = file_upload
        mock_is_file.return_value = True
        mock_stat.return_value.st_mode = 33188
        mock_read_bytes.return_value = b"data"
        
        with patch("app.workers.tasks.media.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            with patch("shutil.move"):
                with patch("pathlib.Path.mkdir"):
                    result = await process_media(
                        ctx={}, 
                        file_upload_id=1, 
                        collection_id=10,
                        file_date="invalid-date",
                        file_time="12:00:00"
                    )
        
        assert result["status"] == "completed"

    @patch("app.workers.tasks.media.file_service.ensure_audio_is_flac")
    @patch("mutagen.File")
    @patch("pathlib.Path.is_file")
    @patch("pathlib.Path.stat")
    @patch("pathlib.Path.read_bytes")
    async def test_process_media_mutagen_none(
        self,
        mock_read_bytes,
        mock_stat,
        mock_is_file,
        mock_mutagen,
        mock_ensure_flac,
    ):
        """Handles mutagen returning None."""
        mock_session = MagicMock()
        mock_ensure_flac.return_value = (Path("/tmp/test.flac"), "test.flac")
        file_upload = FileUpload(file_upload_id=1, path="/tmp/test.wav", filename="test.wav")
        mock_session.get.return_value = file_upload
        mock_is_file.return_value = True
        mock_stat.return_value.st_mode = 33188
        mock_read_bytes.return_value = b"data"
        mock_mutagen.return_value = None
        
        with patch("app.workers.tasks.media.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            with patch("shutil.move"):
                with patch("pathlib.Path.mkdir"):
                    await process_media(ctx={}, file_upload_id=1, collection_id=10)

    @patch("app.workers.tasks.media.file_service.ensure_audio_is_flac")
    @patch("mutagen.File")
    @patch("pathlib.Path.is_file")
    @patch("pathlib.Path.stat")
    @patch("pathlib.Path.read_bytes")
    async def test_process_media_mutagen_info_none(
        self,
        mock_read_bytes,
        mock_stat,
        mock_is_file,
        mock_mutagen,
        mock_ensure_flac,
    ):
        """Handles mutagen returning object with None info."""
        mock_session = MagicMock()
        mock_ensure_flac.return_value = (Path("/tmp/test.flac"), "test.flac")
        file_upload = FileUpload(file_upload_id=1, path="/tmp/test.wav", filename="test.wav")
        mock_session.get.return_value = file_upload
        mock_is_file.return_value = True
        mock_stat.return_value.st_mode = 33188
        mock_read_bytes.return_value = b"data"
        
        mock_audio = MagicMock()
        mock_audio.info = None
        mock_mutagen.return_value = mock_audio
        
        with patch("app.workers.tasks.media.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)
            with patch("shutil.move"):
                with patch("pathlib.Path.mkdir"):
                    await process_media(ctx={}, file_upload_id=1, collection_id=10)


    # ------------------------------------------------------------------
    # Thumbnail generation tests
    # ------------------------------------------------------------------

    @patch("app.workers.tasks.media.file_service.ensure_audio_is_flac")
    @patch("app.workers.tasks.media.generate_thumbnail")
    @patch("app.workers.tasks.media.generate_player_spectrogram")
    @patch("mutagen.File")
    @patch("hashlib.md5")
    @patch("shutil.move")
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.is_file")
    @patch("pathlib.Path.stat")
    @patch("pathlib.Path.read_bytes")
    @patch("pathlib.Path.write_bytes")
    async def test_thumbnail_created_on_success(
        self,
        mock_write_bytes,
        mock_read_bytes,
        mock_stat,
        mock_is_file,
        mock_mkdir,
        mock_move,
        mock_md5,
        mock_mutagen,
        mock_generate_player_spectrogram,
        mock_generate_thumbnail,
        mock_ensure_flac,
    ):
        """A Preview record is added when audio processing succeeds."""
        from app.models.media import Preview

        mock_generate_thumbnail.return_value = b"\x89PNG\r\nfake"
        mock_generate_player_spectrogram.return_value = b"\x89PNG\r\nplayer"
        mock_ensure_flac.return_value = (Path("/tmp/test.flac"), "test.flac")

        mock_session = MagicMock()
        file_upload = FileUpload(
            file_upload_id=1,
            filename="test.wav",
            path="/tmp/test.wav",
            status=1,
            uploader_id=1,
            directory="dir1",
            name="Test File",
        )
        mock_session.get.return_value = file_upload

        mock_is_file.return_value = True
        mock_stat.return_value.st_size = 1000
        mock_read_bytes.return_value = b"fake-audio-data"
        mock_md5.return_value.hexdigest.return_value = "abc123"

        mock_audio = MagicMock()
        mock_audio.info.length = 5.0
        mock_audio.info.sample_rate = 22050
        mock_audio.info.channels = 1
        mock_audio.info.bits_per_sample = 16
        mock_mutagen.return_value = mock_audio

        added_objects = []

        def capture_add(obj):
            if isinstance(obj, AudioSetting):
                obj.audio_setting_id = 10
            elif isinstance(obj, Media):
                obj.media_id = 20
            added_objects.append(obj)

        mock_session.add.side_effect = capture_add

        with patch("app.workers.tasks.media.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)

            result = await process_media(ctx={}, file_upload_id=1, collection_id=10)

        assert result["status"] == "completed"
        mock_move.assert_called_once_with(
            "/tmp/test.flac",
            "/app/sounds/sounds/10/dir1/test.flac",
        )
        mock_generate_thumbnail.assert_called_once()
        mock_generate_player_spectrogram.assert_called_once_with(
            "/app/sounds/sounds/10/dir1/test.flac",
            channel_num=1,
            fft_size=1024,
        )
        preview_objects = [o for o in added_objects if isinstance(o, Preview)]
        assert len(preview_objects) == 2
        assert {preview.type for preview in preview_objects} == {"thumbnail", "spectrogram"}
        assert any("test_thumbnail.png" in preview.filename for preview in preview_objects)
        assert any("test_player_s.png" in preview.filename for preview in preview_objects)
        assert mock_write_bytes.call_count == 2

    @patch("app.workers.tasks.media.file_service.ensure_audio_is_flac")
    @patch("app.workers.tasks.media.generate_thumbnail")
    @patch("mutagen.File")
    @patch("hashlib.md5")
    @patch("shutil.move")
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.is_file")
    @patch("pathlib.Path.stat")
    @patch("pathlib.Path.read_bytes")
    @patch("pathlib.Path.write_bytes")
    async def test_thumbnail_failure_does_not_abort_media(
        self,
        mock_write_bytes,
        mock_read_bytes,
        mock_stat,
        mock_is_file,
        mock_mkdir,
        mock_move,
        mock_md5,
        mock_mutagen,
        mock_generate_thumbnail,
        mock_ensure_flac,
    ):
        """If thumbnail generation raises, the media record is still created."""
        mock_generate_thumbnail.side_effect = RuntimeError("librosa exploded")
        mock_ensure_flac.return_value = (Path("/tmp/test.flac"), "test.flac")

        mock_session = MagicMock()
        file_upload = FileUpload(
            file_upload_id=1,
            filename="test.wav",
            path="/tmp/test.wav",
            status=1,
            uploader_id=1,
            directory="dir1",
            name="Test File",
        )
        mock_session.get.return_value = file_upload

        mock_is_file.return_value = True
        mock_stat.return_value.st_size = 500
        mock_read_bytes.return_value = b"data"
        mock_md5.return_value.hexdigest.return_value = "deadbeef"

        mock_audio = MagicMock()
        mock_audio.info.length = 3.0
        mock_audio.info.sample_rate = 44100
        mock_audio.info.channels = 2
        mock_audio.info.bits_per_sample = 16
        mock_mutagen.return_value = mock_audio

        def mock_add(obj):
            if isinstance(obj, AudioSetting):
                obj.audio_setting_id = 11
            elif isinstance(obj, Media):
                obj.media_id = 21

        mock_session.add.side_effect = mock_add

        with patch("app.workers.tasks.media.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)

            result = await process_media(ctx={}, file_upload_id=1, collection_id=10)

        assert result["status"] == "completed"
        assert result["media_id"] == 21

    @patch("app.workers.tasks.media.file_service.ensure_audio_is_flac")
    @patch("pathlib.Path.is_file")
    async def test_process_media_flac_conversion_failure_sets_error(
        self,
        mock_is_file,
        mock_ensure_flac,
    ):
        """Audio conversion failures stop processing and persist the error."""
        mock_session = MagicMock()
        file_upload = FileUpload(
            file_upload_id=1,
            filename="broken.mp3",
            path="/tmp/broken.mp3",
            status=1,
            uploader_id=1,
            directory="dir1",
            name="Broken",
        )
        mock_session.get.return_value = file_upload
        mock_is_file.return_value = True
        mock_ensure_flac.side_effect = RuntimeError("ffmpeg conversion failed: decoder error")

        with patch("app.workers.tasks.media.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)

            result = await process_media(ctx={}, file_upload_id=1, collection_id=10)

        assert result == {"error": "ffmpeg conversion failed: decoder error"}
        assert file_upload.status == 4
        assert file_upload.error == "ffmpeg conversion failed: decoder error"

    @patch("app.workers.tasks.media.generate_thumbnail")
    @patch("app.workers.tasks.media.file_service.ensure_audio_is_flac")
    @patch("mutagen.File")
    @patch("hashlib.md5")
    @patch("shutil.move")
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.is_file")
    @patch("pathlib.Path.stat")
    @patch("pathlib.Path.read_bytes")
    async def test_process_media_flac_input_keeps_flac_filename(
        self,
        mock_read_bytes,
        mock_stat,
        mock_is_file,
        mock_mkdir,
        mock_move,
        mock_md5,
        mock_mutagen,
        mock_ensure_flac,
        mock_generate_thumbnail,
    ):
        """Existing FLAC uploads stay on the FLAC filename after normalization."""
        mock_session = MagicMock()
        mock_generate_thumbnail.return_value = b"\x89PNG\r\nfake"
        file_upload = FileUpload(
            file_upload_id=1,
            filename="field.flac",
            path="/tmp/field.flac",
            status=1,
            uploader_id=1,
            directory="dir1",
            name="Field",
        )
        mock_session.get.return_value = file_upload
        mock_is_file.return_value = True
        mock_stat.return_value.st_size = 123
        mock_read_bytes.return_value = b"flac-data"
        mock_md5.return_value.hexdigest.return_value = "flac-hash"
        mock_ensure_flac.return_value = (Path("/tmp/field.flac"), "field.flac")

        mock_audio = MagicMock()
        mock_audio.info.length = 1.0
        mock_audio.info.sample_rate = 48000
        mock_audio.info.channels = 1
        mock_audio.info.bits_per_sample = 16
        mock_mutagen.return_value = mock_audio

        def mock_add(obj):
            if isinstance(obj, AudioSetting):
                obj.audio_setting_id = 100
            elif isinstance(obj, Media):
                obj.media_id = 200

        mock_session.add.side_effect = mock_add

        with patch("app.workers.tasks.media.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)

            result = await process_media(ctx={}, file_upload_id=1, collection_id=10)

        assert result["status"] == "completed"
        assert file_upload.filename == "field.flac"
        mock_ensure_flac.assert_called_once_with(
            Path("/app/sounds/tmp/field.flac"),
            source_filename="field.flac",
        )

    @patch("app.workers.tasks.media.generate_thumbnail")
    @patch("mutagen.File")
    @patch("hashlib.md5")
    @patch("shutil.move")
    @patch("pathlib.Path.mkdir")
    @patch("pathlib.Path.is_file")
    @patch("pathlib.Path.stat")
    @patch("pathlib.Path.read_bytes")
    @patch("pathlib.Path.write_bytes")
    async def test_invalid_photo_content_is_rejected(
        self,
        mock_write_bytes,
        mock_read_bytes,
        mock_stat,
        mock_is_file,
        mock_mkdir,
        mock_move,
        mock_md5,
        mock_mutagen,
        mock_generate_thumbnail,
    ):
        """Photo uploads must contain decodable image bytes."""
        mock_session = MagicMock()
        created_media: list[Media] = []
        file_upload = FileUpload(
            file_upload_id=1,
            filename="photo.jpg",
            path="/tmp/photo.jpg",
            status=1,
            uploader_id=1,
            directory="dir1",
            name="Photo",
        )
        mock_session.get.return_value = file_upload

        mock_is_file.return_value = True
        mock_stat.return_value.st_size = 200
        mock_read_bytes.return_value = b"img"
        mock_md5.return_value.hexdigest.return_value = "cafebabe"

        def mock_add(obj):
            if isinstance(obj, Media):
                obj.media_id = 22
                created_media.append(obj)

        mock_session.add.side_effect = mock_add

        with patch("app.workers.tasks.media.Session", return_value=mock_session):
            mock_session.__enter__ = MagicMock(return_value=mock_session)
            mock_session.__exit__ = MagicMock(return_value=False)

            result = await process_media(
                ctx={}, file_upload_id=1, collection_id=10, media_type="photo"
            )

        assert "valid image" in result["error"]
        mock_generate_thumbnail.assert_not_called()
        assert not created_media
        mock_mutagen.assert_not_called()
