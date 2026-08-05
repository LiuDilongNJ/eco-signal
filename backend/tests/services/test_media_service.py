"""Unit tests for MediaService."""
import csv
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest
import soundfile as sf
from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.config import settings
from app.enums import WorkerTaskType
from app.models import (
    AudioSetting,
    Camera,
    Collection,
    FileUpload,
    License,
    Lens,
    Media,
    MediaCollection,
    PhotoSetting,
    Project,
    ProjectCollection,
    Role,
    Setting,
    Sensor,
    User,
    UserPreference,
)
from app.models.label import Label, LabelMedia
from app.models.media import Preview
from app.schemas.media import MediaCreate, MediaUpdate
from app.services import media_service


def _write_audio_fixture(
    path: Path,
    *,
    sample_rate: int,
    channel_num: int = 1,
    duration_s: float = 1.0,
) -> None:
    frames = int(sample_rate * duration_s)
    t = np.arange(frames, dtype=np.float32) / sample_rate
    left = 0.6 * np.sin(2 * np.pi * 440 * t)
    if channel_num >= 2:
        right = 0.6 * np.sin(2 * np.pi * 880 * t)
        data = np.column_stack((left, right)).astype(np.float32)
    else:
        data = left.astype(np.float32)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), data, sample_rate)


def _create_photo_sensor(db: Session, name: str) -> Sensor:
    camera = Camera(name=f"{name} Camera")
    lens = Lens(name=f"{name} Lens")
    db.add_all([camera, lens])
    db.flush()
    sensor = Sensor(
        name=name,
        sensor_type="photo",
        camera_id=camera.camera_id,
        lens_id=lens.lens_id,
    )
    db.add(sensor)
    db.flush()
    return sensor


@pytest.fixture
def setup_data(db: Session):
    # Setup Roles
    admin_role = db.exec(select(Role).where(Role.name == "Administrator")).first()
    if not admin_role:
        admin_role = Role(name="Administrator")
        db.add(admin_role)

    user_role_name = "Media_Service_Role_Final_" + str(datetime.now().timestamp())
    user_role = Role(name=user_role_name)
    db.add_all([user_role])
    db.flush()

    user = User(username="ms_user_z", role_id=user_role.role_id, email="msz@e.com", password="p", name="M")
    admin = User(username="ms_admin_z", role_id=admin_role.role_id, email="msaz@e.com", password="p", name="MA")
    db.add_all([user, admin])
    db.flush()

    col = Collection(name="MSZ Col", creator_id=user.user_id)
    db.add(col)
    db.flush()
    project = Project(name="MSZ Project", creator_id=user.user_id, url="https://media-service.test")
    db.add(project)
    db.flush()
    db.add(ProjectCollection(project_id=project.project_id, collection_id=col.collection_id))
    db.flush()

    lic = License(name="LscZ", link="http://l.com")
    db.add(lic)
    db.flush()

    return {"user": user, "admin": admin, "role": user_role, "collection": col, "project": project, "license": lic}


@pytest.mark.anyio
class TestMediaService:
    def test_sox_selection_command_trims_with_sample_units(self, tmp_path: Path):
        audio_path = tmp_path / "stereo.wav"
        _write_audio_fixture(audio_path, sample_rate=48_000, channel_num=2)

        command = media_service._sox_selection_command(
            audio_path,
            tmp_path / "selection.wav",
            start_sample=60_000,
            duration_sample=108_000,
        )

        assert command[-3:] == ["trim", "60000s", "108000s"]
        assert "remix" not in command

    def test_sox_selection_command_does_not_remix_audio(self, tmp_path: Path):
        audio_path = tmp_path / "mono.wav"
        _write_audio_fixture(audio_path, sample_rate=48_000, channel_num=1)

        command = media_service._sox_selection_command(
            audio_path,
            tmp_path / "selection.wav",
            start_sample=0,
            duration_sample=None,
        )

        assert "remix" not in command

    @pytest.mark.parametrize(
        ("min_freq", "max_freq", "expected"),
        [
            (0, 24_000, "0-23999"),
            (0, 8_000, "0-8000"),
            (1_000, 24_000, "1000-23999"),
            (1_000, 8_000, "1000-8000"),
        ],
    )
    def test_sox_filter_command_builds_frequency_band(
        self,
        tmp_path: Path,
        min_freq: float,
        max_freq: float,
        expected: str | None,
    ):
        command = media_service._sox_filter_command(
            tmp_path / "source.wav",
            tmp_path / "filtered.wav",
            sample_rate=48_000,
            min_freq=min_freq,
            max_freq=max_freq,
        )

        assert command[-2:] == ["sinc", expected]

    def test_run_sox_reports_nonzero_exit(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            media_service.subprocess,
            "run",
            lambda *args, **kwargs: SimpleNamespace(
                returncode=2,
                stderr="invalid effect",
                stdout="",
            ),
        )

        with pytest.raises(RuntimeError, match="invalid effect"):
            media_service._run_sox(["sox", "input.wav", "output.wav"])

    def test_run_sox_reports_missing_executable(self, monkeypatch: pytest.MonkeyPatch):
        def _missing(*args, **kwargs):
            raise FileNotFoundError("sox")

        monkeypatch.setattr(media_service.subprocess, "run", _missing)

        with pytest.raises(RuntimeError, match="SoX is required"):
            media_service._run_sox(["sox", "input.wav", "output.wav"])

    def test_run_sox_reports_timeout(self, monkeypatch: pytest.MonkeyPatch):
        def _timeout(*args, **kwargs):
            raise media_service.subprocess.TimeoutExpired(args[0], 300)

        monkeypatch.setattr(media_service.subprocess, "run", _timeout)

        with pytest.raises(RuntimeError, match="timed out"):
            media_service._run_sox(["sox", "input.wav", "output.wav"])

    @pytest.mark.parametrize(
        ("output_format", "expected_prefix"),
        [
            ("mp3", ["lame", "--noreplaygain", "-f", "-b", "128"]),
            ("ogg", ["sox"]),
        ],
    )
    def test_write_playback_atomically_uses_configured_encoder_commands(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        output_format: str,
        expected_prefix: list[str],
    ):
        source_path = tmp_path / "source.wav"
        source_path.write_bytes(b"audio")
        target_path = tmp_path / f"playback.{output_format}"
        commands: list[list[str]] = []

        def _record_command(command: list[str]) -> None:
            commands.append(command)
            Path(command[-1]).write_bytes(b"encoded")

        monkeypatch.setattr(media_service, "_run_lame", _record_command)
        monkeypatch.setattr(media_service, "_run_sox", _record_command)
        monkeypatch.setattr(media_service, "_validate_cached_audio", lambda *_args, **_kwargs: True)

        media_service._write_playback_atomically(source_path, target_path, output_format)

        assert target_path.read_bytes() == b"encoded"
        assert commands
        assert commands[0][: len(expected_prefix)] == expected_prefix
        if output_format == "ogg":
            assert commands[0][2:4] == ["-C", "10"]

    def test_detail_output_format_uses_mp3_for_standard_audio(self):
        assert media_service._detail_output_format(
            sample_rate=44_100,
            source_path=Path("source.flac"),
        ) == "mp3"

    """Tests for MediaService."""

    async def test_create_media_success(self, db: Session, setup_data):
        user = setup_data["user"]
        col = setup_data["collection"]
        lic = setup_data["license"]

        fu = FileUpload(
            filename="2024-01-01_120000.wav",
            name="rec.wav",
            directory=1,
            path="/tmp/rec.wav",
            size=1024,
            status=1,
            uploader_id=user.user_id
        )
        db.add(fu)
        db.flush()

        mock_redis = AsyncMock()
        request = MediaCreate(
            collection_id=col.collection_id,
            file_upload_ids=[fu.file_upload_id],
            date_from_filename=True,
            media_type="audio",
            license_id=lic.license_id,
            medium="air",
        )

        res = await media_service.create_media(db, request, user, mock_redis)
        assert len(res.queued) == 1
        mock_redis.enqueue_task.assert_called_once()
        kwargs = mock_redis.enqueue_task.call_args.kwargs
        assert kwargs["items"] == [{
            "file_upload_id": fu.file_upload_id,
            "file_date": "2024-01-01",
            "file_time": "12:00:00",
            "display_filename": "rec.wav",
        }]
        assert mock_redis.enqueue_task.call_args.args[0] == WorkerTaskType.PROCESS_MEDIA_BATCH

    async def test_create_media_reports_upload_time_duplicate_from_status(
        self, db: Session, setup_data
    ):
        """A FileUpload already flagged as a duplicate at upload time (status=5,
        media_id set by the early MD5 check in upload_chunk) should be reported
        in `duplicates`, not as a generic "status is not pending" failure."""
        user = setup_data["user"]
        col = setup_data["collection"]

        photo_setting = PhotoSetting()
        db.add(photo_setting)
        db.flush()
        existing_media = Media(
            media_type="photo",
            md5_hash="deadbeefcafefeed00000000000dead",
            uploader_id=user.user_id,
            photo_setting_id=photo_setting.photo_setting_id,
        )
        db.add(existing_media)
        db.flush()

        fu = FileUpload(
            filename="already_flagged_dup.jpg",
            name="already_flagged_dup.jpg",
            directory=1,
            path="",
            status=5,  # duplicate/skipped, set at upload time
            media_id=existing_media.media_id,
            uploader_id=user.user_id,
        )
        db.add(fu)
        db.flush()

        request = MediaCreate(
            collection_id=col.collection_id,
            file_upload_ids=[fu.file_upload_id],
            media_type="photo",
        )

        res = await media_service.create_media(db, request, user, AsyncMock())
        assert res.queued == []
        assert len(res.failed) == 1
        assert res.failed[0].file_upload_id == fu.file_upload_id
        assert "status is not pending" in res.failed[0].reason

    def test_create_photo_rejects_explicit_null_audio_fields(self):
        with pytest.raises(ValueError, match="Photo media must not include audio-only fields"):
            MediaCreate(
                collection_id=1,
                file_upload_ids=[1],
                media_type="photo",
                recording_gain_db=None,
            )

    async def test_create_media_rejects_sensor_type_mismatch(self, db: Session, setup_data):
        photo_sensor = _create_photo_sensor(db, "Photo Create Sensor")
        db.commit()
        db.refresh(photo_sensor)

        request = MediaCreate(
            collection_id=setup_data["collection"].collection_id,
            file_upload_ids=[1],
            media_type="audio",
            sensor_id=photo_sensor.sensor_id,
            date_from_filename=True,
        )
        with pytest.raises(HTTPException) as exc_info:
            await media_service.create_media(
                db,
                request,
                setup_data["user"],
                AsyncMock(),
            )

        assert exc_info.value.status_code == 422
        assert "cannot be used for audio media" in str(exc_info.value.detail)

    async def test_create_media_date_parsing(self, db: Session, setup_data):
        """Test date parsing patterns in filename."""
        user = setup_data["user"]
        col = setup_data["collection"]

        fu = FileUpload(filename="S4A_20231225_235959.wav", name="x", directory=1, path="x", size=0, status=1, uploader_id=user.user_id)
        db.add(fu)
        db.flush()

        mock_redis = AsyncMock()
        request = MediaCreate(
            collection_id=col.collection_id,
            file_upload_ids=[fu.file_upload_id],
            date_from_filename=True,
            media_type="audio",
        )

        await media_service.create_media(db, request, user, mock_redis)
        kwargs = mock_redis.enqueue_task.call_args.kwargs
        assert kwargs["items"][0] == {
            "file_upload_id": fu.file_upload_id,
            "file_date": "2023-12-25",
            "file_time": "23:59:59",
            "display_filename": "x",
        }

    async def test_create_media_date_from_filename_falls_back_to_default_datetime(
        self, db: Session, setup_data
    ):
        """Unparseable filenames should keep the configured default datetime fallback."""
        user = setup_data["user"]
        col = setup_data["collection"]

        fu = FileUpload(
            filename="plain_recording.wav",
            name="plain_recording.wav",
            directory=1,
            path="/tmp/plain_recording.wav",
            size=1024,
            status=1,
            uploader_id=user.user_id,
        )
        db.add(fu)
        db.flush()

        mock_redis = AsyncMock()
        request = MediaCreate(
            collection_id=col.collection_id,
            file_upload_ids=[fu.file_upload_id],
            date_from_filename=True,
            media_type="audio",
        )

        await media_service.create_media(db, request, user, mock_redis)
        kwargs = mock_redis.enqueue_task.call_args.kwargs
        assert kwargs["items"][0]["file_date"] == "1970-01-01"
        assert kwargs["items"][0]["file_time"] == "00:00:00"

    async def test_create_media_applies_filename_prefix(self, db: Session, setup_data):
        """Batch-level filename_prefix should be prepended to logical filename."""
        user = setup_data["user"]
        col = setup_data["collection"]

        fu = FileUpload(
            filename="origin.wav",
            name="origin.wav",
            directory=1,
            path="/tmp/origin.wav",
            size=1024,
            status=1,
            uploader_id=user.user_id,
        )
        db.add(fu)
        db.flush()

        mock_redis = AsyncMock()
        request = MediaCreate(
            collection_id=col.collection_id,
            filename_prefix="ABC_",
            file_upload_ids=[fu.file_upload_id],
            date_from_filename=True,
            media_type="audio",
        )

        res = await media_service.create_media(db, request, user, mock_redis)
        assert len(res.queued) == 1
        kwargs = mock_redis.enqueue_task.call_args.kwargs
        assert kwargs["items"][0]["display_filename"] == "ABC_origin.wav"

    async def test_import_metadata_csv_success(self, db: Session, setup_data):
        user = setup_data["user"]
        col = setup_data["collection"]
        csv_content = (
            "date_time,duration_s,sampling_rate_hz,name,bit_depth,channel_num,duty_cycle_recording,duty_cycle_period\n"
            "2022/1/1 12:12,10.5,48000,FullRecZ,16,1,60,120\n"
            "2022-01-01T12:12:00,11.5,48000,FullRecT,16,1,60,120\n"
        )

        res = media_service.import_metadata_csv(db, csv_content, col.collection_id, user)
        assert res.succeeded == 2

        media = db.exec(select(Media).where(Media.name == "FullRecZ")).first()
        assert media is not None
        assert media.date_time.replace(tzinfo=None) == datetime(2022, 1, 1, 12, 12, 0)

    async def test_import_metadata_csv_empty_file(self, db: Session, setup_data):
        user = setup_data["user"]
        col = setup_data["collection"]
        result = media_service.import_metadata_csv(db, "", col.collection_id, user)
        assert result.committed is False
        assert result.global_errors == ["CSV file is empty"]

    async def test_import_metadata_csv_row_width_mismatch(self, db: Session, setup_data):
        """A data row whose field count differs from the header is rejected (anti column-shift)."""
        user = setup_data["user"]
        col = setup_data["collection"]
        # Header declares 4 columns; the data row only has 3 -> abnormal width.
        csv_content = (
            "date_time,duration_s,sampling_rate_hz,name\n"
            "2024-05-01 08:00:00,10.5,48000\n"
        )
        before = len(db.exec(select(Media)).all())

        result = media_service.import_metadata_csv(db, csv_content, col.collection_id, user)
        assert result.committed is False
        assert result.global_errors and "expected 4 columns" in result.global_errors[0]
        assert len(db.exec(select(Media)).all()) == before

    async def test_import_metadata_csv_unclosed_quote(self, db: Session, setup_data):
        """An unclosed quote must not silently swallow the next row."""
        user = setup_data["user"]
        col = setup_data["collection"]
        # The open quote on row 1 swallows row 2 into one merged record whose
        # field count no longer matches the header -> rejected.
        csv_content = (
            "date_time,duration_s,sampling_rate_hz,name\n"
            '2024-05-01 08:00:00,10.5,48000,"Unclosed\n'
            "2024-05-01 09:00:00,11.5,48000,Next\n"
        )
        before = len(db.exec(select(Media)).all())

        result = media_service.import_metadata_csv(db, csv_content, col.collection_id, user)
        assert result.committed is False
        assert result.global_errors
        assert len(db.exec(select(Media)).all()) == before

    async def test_import_metadata_csv_photo_success(self, db: Session, setup_data):
        user = setup_data["user"]
        col = setup_data["collection"]
        csv_content = (
            "date_time,name,exposure_ms,aperture,iso\n"
            "2022/1/1 12:12,FullPhotoZ,8.5,2.8,400\n"
            "2022-01-01T12:12:00,FullPhotoT,,,\n"
        )

        res = media_service.import_metadata_csv(
            db, csv_content, col.collection_id, user, media_type="photo"
        )
        assert res.succeeded == 2

        media = db.exec(select(Media).where(Media.name == "FullPhotoZ")).first()
        assert media is not None
        assert media.media_type == "photo"
        assert media.is_metadata is True
        assert media.audio_setting_id is None
        assert media.photo_setting is not None
        assert media.photo_setting.exposure_ms == 8.5
        assert media.photo_setting.aperture == 2.8
        assert media.photo_setting.iso == 400
        assert media.date_time.replace(tzinfo=None) == datetime(2022, 1, 1, 12, 12, 0)

        media_no_settings = db.exec(select(Media).where(Media.name == "FullPhotoT")).first()
        assert media_no_settings is not None
        assert media_no_settings.photo_setting is not None
        assert media_no_settings.photo_setting.exposure_ms is None
        assert media_no_settings.photo_setting.aperture is None
        assert media_no_settings.photo_setting.iso is None

    async def test_import_metadata_csv_photo_empty_file(self, db: Session, setup_data):
        user = setup_data["user"]
        col = setup_data["collection"]
        result = media_service.import_metadata_csv(
            db, "", col.collection_id, user, media_type="photo"
        )
        assert result.committed is False
        assert result.global_errors == ["CSV file is empty"]

    async def test_import_metadata_csv_reimport_dedup(self, db: Session, setup_data):
        """Re-importing the same audio CSV skips all rows."""
        user = setup_data["user"]
        col = setup_data["collection"]
        csv_content = (
            "date_time,duration_s,sampling_rate_hz,name,bit_depth,channel_num,duty_cycle_recording,duty_cycle_period\n"
            "2024-03-01 08:00:00,10.5,48000,DedupSvcA,16,1,60,120\n"
            "2024-03-01 09:00:00,11.5,48000,DedupSvcB,,,,\n"
        )

        res1 = media_service.import_metadata_csv(db, csv_content, col.collection_id, user)
        assert res1.succeeded == 2
        assert res1.skipped == 0

        res2 = media_service.import_metadata_csv(db, csv_content, col.collection_id, user)
        assert res2.total == 2
        assert res2.succeeded == 0
        assert res2.skipped == 2

        medias = db.exec(select(Media).where(Media.name == "DedupSvcA")).all()
        assert len(medias) == 1

    async def test_import_metadata_csv_internal_duplicate_rows(self, db: Session, setup_data):
        """Identical rows within one CSV file are written only once."""
        user = setup_data["user"]
        col = setup_data["collection"]
        csv_content = (
            "date_time,duration_s,sampling_rate_hz,name\n"
            "2024-03-02 08:00:00,10.5,48000,DedupInternal\n"
            "2024-03-02 08:00:00,10.5,48000,DedupInternal\n"
        )

        res = media_service.import_metadata_csv(db, csv_content, col.collection_id, user)
        assert res.total == 2
        assert res.succeeded == 1
        assert res.skipped == 1
        assert len(db.exec(select(Media).where(Media.name == "DedupInternal")).all()) == 1

    async def test_import_metadata_csv_near_duplicate_not_skipped(self, db: Session, setup_data):
        """Rows are only skipped when every stored field matches exactly."""
        user = setup_data["user"]
        col = setup_data["collection"]
        # Row 2 differs in bit_depth; row 3 differs in duty_cycle_recording (NULL vs value).
        # Row 4 duplicates row 1 exactly: blank bit_depth stores the column default 16.
        csv_content = (
            "date_time,duration_s,sampling_rate_hz,name,bit_depth,duty_cycle_recording\n"
            "2024-03-03 08:00:00,10.5,48000,NearDup,16,60\n"
            "2024-03-03 08:00:00,10.5,48000,NearDup,24,60\n"
            "2024-03-03 08:00:00,10.5,48000,NearDup,16,\n"
            "2024-03-03 08:00:00,10.5,48000,NearDup,,60\n"
        )

        res = media_service.import_metadata_csv(db, csv_content, col.collection_id, user)
        assert res.succeeded == 3
        assert res.skipped == 1
        assert len(db.exec(select(Media).where(Media.name == "NearDup")).all()) == 3

    async def test_import_metadata_csv_dedup_links_across_collections(self, db: Session, setup_data):
        """Identical content imported to another collection reuses the Media via a link."""
        user = setup_data["user"]
        col = setup_data["collection"]
        other_col = Collection(name="Dedup Other Col", creator_id=user.user_id)
        db.add(other_col)
        db.flush()

        csv_content = (
            "date_time,duration_s,sampling_rate_hz,name\n"
            "2024-03-04 08:00:00,10.5,48000,DedupScope\n"
        )
        res1 = media_service.import_metadata_csv(db, csv_content, col.collection_id, user)
        assert res1.succeeded == 1
        assert res1.skipped == 0

        res2 = media_service.import_metadata_csv(db, csv_content, other_col.collection_id, user)
        assert res2.succeeded == 1
        assert res2.skipped == 0

        # Only one Media row exists, linked to both collections (true M2M reuse).
        media_rows = db.exec(select(Media).where(Media.name == "DedupScope")).all()
        assert len(media_rows) == 1
        linked_collections = {
            mc.collection_id
            for mc in db.exec(
                select(MediaCollection).where(
                    MediaCollection.media_id == media_rows[0].media_id
                )
            ).all()
        }
        assert linked_collections == {col.collection_id, other_col.collection_id}

    async def test_import_metadata_csv_photo_links_across_collections(self, db: Session, setup_data):
        """Photo metadata identical across collections reuses one Media via a link."""
        user = setup_data["user"]
        col = setup_data["collection"]
        other_col = Collection(name="Dedup Photo Other Col", creator_id=user.user_id)
        db.add(other_col)
        db.flush()

        csv_content = (
            "date_time,name,exposure_ms,aperture,iso\n"
            "2024-03-06 12:00:00,PhotoScope,8.5,2.8,400\n"
        )
        res1 = media_service.import_metadata_csv(
            db, csv_content, col.collection_id, user, media_type="photo"
        )
        assert res1.succeeded == 1

        res2 = media_service.import_metadata_csv(
            db, csv_content, other_col.collection_id, user, media_type="photo"
        )
        assert res2.succeeded == 1
        assert res2.skipped == 0

        media_rows = db.exec(select(Media).where(Media.name == "PhotoScope")).all()
        assert len(media_rows) == 1
        linked_collections = {
            mc.collection_id
            for mc in db.exec(
                select(MediaCollection).where(
                    MediaCollection.media_id == media_rows[0].media_id
                )
            ).all()
        }
        assert linked_collections == {col.collection_id, other_col.collection_id}

    async def test_import_metadata_csv_photo_reimport_dedup(self, db: Session, setup_data):
        """Re-importing the same photo CSV skips all rows."""
        user = setup_data["user"]
        col = setup_data["collection"]
        csv_content = (
            "date_time,name,exposure_ms,aperture,iso\n"
            "2024-03-05 12:00:00,PhotoDedup1,8.5,2.8,400\n"
            "2024-03-05 13:00:00,PhotoDedup2,,,\n"
        )

        res1 = media_service.import_metadata_csv(
            db, csv_content, col.collection_id, user, media_type="photo"
        )
        assert res1.succeeded == 2
        assert res1.skipped == 0

        res2 = media_service.import_metadata_csv(
            db, csv_content, col.collection_id, user, media_type="photo"
        )
        assert res2.total == 2
        assert res2.succeeded == 0
        assert res2.skipped == 2
        assert len(db.exec(select(Media).where(Media.name == "PhotoDedup1")).all()) == 1

    async def test_import_metadata_csv_photo_header_missing_required(self, db: Session, setup_data):
        """Photo CSV without the capture_time header column is rejected."""
        user = setup_data["user"]
        col = setup_data["collection"]
        csv_content = "name,exposure_ms\nNoCapture,8.5\n"
        result = media_service.import_metadata_csv(
            db, csv_content, col.collection_id, user, media_type="photo"
        )
        assert result.committed is False
        assert result.global_errors and "missing required column" in result.global_errors[0]
        assert "date_time" in result.global_errors[0]

    def test_get_media_by_id_complex(self, db: Session, setup_data):
        user = setup_data["user"]
        col = setup_data["collection"]
        project = setup_data["project"]

        media = Media(name="M_C_Z", creator_id=user.user_id, media_type="audio", is_metadata=True)
        db.add(media)
        db.flush()
        db.add(MediaCollection(media_id=media.media_id, collection_id=col.collection_id, added_by=user.user_id))
        db.flush()

        col.public_access = True
        db.add(col)
        db.flush()
        res = media_service.get_media(db, project.project_id, media.media_id, user)
        assert res.name == "M_C_Z"

    def test_get_media_by_id_includes_md5_hash(self, db: Session, setup_data):
        user = setup_data["user"]
        col = setup_data["collection"]
        project = setup_data["project"]

        media = Media(
            name="M_MD5_Z",
            creator_id=user.user_id,
            media_type="audio", is_metadata=True,
            md5_hash="0123456789abcdef0123456789abcdef",
        )
        db.add(media)
        db.flush()
        db.add(MediaCollection(media_id=media.media_id, collection_id=col.collection_id, added_by=user.user_id))
        db.flush()

        col.public_access = True
        db.add(col)
        db.flush()

        res = media_service.get_media(db, project.project_id, media.media_id, user)
        assert res.md5_hash == "0123456789abcdef0123456789abcdef"

    def test_get_media_by_id_uses_stable_primary_collection(self, db: Session, setup_data):
        user = setup_data["user"]
        primary_collection = setup_data["collection"]
        project = Project(name="Stable Detail Project", creator_id=user.user_id, url="http://stable.test")
        secondary_collection = Collection(name="Stable Detail Secondary", creator_id=user.user_id)
        db.add_all([project, secondary_collection])
        db.flush()

        db.add(ProjectCollection(project_id=project.project_id, collection_id=primary_collection.collection_id))
        db.add(ProjectCollection(project_id=project.project_id, collection_id=secondary_collection.collection_id))

        media = Media(name="Stable Media", creator_id=user.user_id, media_type="audio", is_metadata=True)
        db.add(media)
        db.flush()

        lower_id = min(primary_collection.collection_id, secondary_collection.collection_id)
        higher_id = max(primary_collection.collection_id, secondary_collection.collection_id)
        db.add(MediaCollection(media_id=media.media_id, collection_id=higher_id, added_by=user.user_id))
        db.add(MediaCollection(media_id=media.media_id, collection_id=lower_id, added_by=user.user_id))

        primary_collection.public_access = True
        secondary_collection.public_access = True
        db.add(primary_collection)
        db.add(secondary_collection)
        db.commit()

        res = media_service.get_media(db, project.project_id, media.media_id, user)
        assert res.collection_id == lower_id

    def test_get_media_by_id_anonymous_allows_public_collection(self, db: Session, setup_data):
        user = setup_data["user"]
        col = setup_data["collection"]
        project = setup_data["project"]

        media = Media(name="M_ANON_PUBLIC_Z", creator_id=user.user_id, media_type="audio", is_metadata=True)
        db.add(media)
        db.flush()
        db.add(MediaCollection(media_id=media.media_id, collection_id=col.collection_id, added_by=user.user_id))

        col.public_access = True
        db.add(col)
        db.commit()

        res = media_service.get_media(db, project.project_id, media.media_id, None)
        assert res.media_id == media.media_id
        assert res.labels == []

    def test_get_media_by_id_anonymous_denies_private_collection(self, db: Session, setup_data):
        user = setup_data["user"]
        col = setup_data["collection"]
        project = setup_data["project"]

        media = Media(name="M_ANON_PRIVATE_Z", creator_id=user.user_id, media_type="audio", is_metadata=True)
        db.add(media)
        db.flush()
        db.add(MediaCollection(media_id=media.media_id, collection_id=col.collection_id, added_by=user.user_id))

        col.public_access = False
        db.add(col)
        db.commit()

        with pytest.raises(HTTPException) as exc_info:
            media_service.get_media(db, project.project_id, media.media_id, None)
        assert exc_info.value.status_code == 403

    def test_delete_media_rules(self, db: Session, setup_data):
        admin = setup_data["admin"]
        media = Media(name="TDelZ", creator_id=admin.user_id, media_type="audio", is_metadata=True)
        db.add(media)
        db.flush()
        res = media_service.delete_media(db, media.media_id, admin)
        assert "success" in res.message

    def test_get_media_by_id_preview_url_resolves_spectrogram_images_path(
        self, db: Session, setup_data
    ):
        user = setup_data["user"]
        project = setup_data["project"]
        col = setup_data["collection"]

        media = Media(
            name="M_PREVIEW_IMG",
            creator_id=user.user_id,
            media_type="audio", is_metadata=True,
            directory=52,
        )
        db.add(media)
        db.flush()
        db.add(MediaCollection(media_id=media.media_id, collection_id=col.collection_id, added_by=user.user_id))
        db.add(Preview(media_id=media.media_id, filename="21808571-small_s.png", type="spectrogram"))
        col.public_access = True
        db.commit()

        res = media_service.get_media(db, project.project_id, media.media_id, user)

        assert res.previews
        assert res.previews[0].url.endswith(
            f"/sounds/images/{col.collection_id}/52/21808571-small_s.png"
        )

    def test_get_media_by_id_preview_url_resolves_thumbnail_sounds_path(
        self, db: Session, setup_data
    ):
        user = setup_data["user"]
        project = setup_data["project"]
        col = setup_data["collection"]

        media = Media(
            name="M_PREVIEW_THUMB",
            creator_id=user.user_id,
            media_type="audio", is_metadata=True,
            directory=7,
        )
        db.add(media)
        db.flush()
        db.add(MediaCollection(media_id=media.media_id, collection_id=col.collection_id, added_by=user.user_id))
        db.add(Preview(media_id=media.media_id, filename="a_thumb.png", type="thumbnail"))
        col.public_access = True
        db.commit()

        res = media_service.get_media(db, project.project_id, media.media_id, user)

        assert res.previews
        assert res.previews[0].url.endswith(
            f"/sounds/sounds/{col.collection_id}/7/a_thumb.png"
        )

    def test_get_media_by_id_prefers_player_preview_for_default_url(
        self, db: Session, setup_data
    ):
        user = setup_data["user"]
        project = setup_data["project"]
        col = setup_data["collection"]

        media = Media(
            name="M_PREVIEW_PLAYER",
            creator_id=user.user_id,
            media_type="audio",
            is_metadata=True,
            directory=8,
        )
        db.add(media)
        db.flush()
        db.add(MediaCollection(media_id=media.media_id, collection_id=col.collection_id, added_by=user.user_id))
        db.add(Preview(media_id=media.media_id, filename="a_thumb.png", type="thumbnail"))
        db.add(Preview(media_id=media.media_id, filename="a_player_s.png", type="spectrogram"))
        col.public_access = True
        db.commit()

        res = media_service.get_media(db, project.project_id, media.media_id, user)

        assert res.previews
        assert res.previews[0].url.endswith(
            f"/sounds/images/{col.collection_id}/8/a_player_s.png"
        )

    def test_resolve_spectrogram_fft_size_prefers_user_preference(self, db: Session, setup_data):
        user = setup_data["user"]
        setting = db.get(Setting, "fft_window_size")
        if setting is not None:
            setting.value = "512"
        else:
            db.add(Setting(name="fft_window_size", value="512"))
        db.add(UserPreference(user_id=user.user_id, fft=2048))
        db.commit()

        assert media_service.resolve_spectrogram_fft_size(db, user) == 2048

    def test_resolve_spectrogram_fft_size_falls_back_to_global_setting(self, db: Session):
        setting = db.get(Setting, "fft_window_size")
        if setting is not None:
            setting.value = "4096"
        else:
            db.add(Setting(name="fft_window_size", value="4096"))
        db.commit()

        assert media_service.resolve_spectrogram_fft_size(db, None) == 4096

    def test_get_spectrogram_renders_dynamic_output(
        self,
        db: Session,
        setup_data,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        user = setup_data["user"]
        col = setup_data["collection"]

        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        audio_dir = tmp_path / "sounds" / str(col.collection_id) / "11"
        audio_dir.mkdir(parents=True, exist_ok=True)
        _write_audio_fixture(audio_dir / "fallback.flac", sample_rate=44100)
        audio_setting = AudioSetting(sampling_rate_hz=44100, bit_depth=16, channel_num=1, duration_s=5.0)
        db.add(audio_setting)
        db.flush()

        media = Media(
            name="M_PLAYER_DYNAMIC",
            creator_id=user.user_id,
            uploader_id=user.user_id,
            media_type="audio",
            filename="fallback.flac",
            directory=11,
            audio_setting_id=audio_setting.audio_setting_id,
        )
        db.add(media)
        db.flush()
        db.add(
            MediaCollection(
                media_id=media.media_id,
                collection_id=col.collection_id,
                added_by=user.user_id,
            )
        )
        db.commit()

        captured: dict[str, object] = {}
        render_count = 0
        rebuild_count = 0
        original_rebuild_detail_selection = media_service._rebuild_detail_selection

        def _fake_generate_spectrogram_png(**kwargs):
            nonlocal render_count
            render_count += 1
            captured.update(kwargs)
            return b"\x89PNG\r\ndynamic"

        def _counted_rebuild_detail_selection(*args, **kwargs):
            nonlocal rebuild_count
            rebuild_count += 1
            return original_rebuild_detail_selection(*args, **kwargs)

        monkeypatch.setattr(
            media_service,
            "generate_spectrogram_png",
            _fake_generate_spectrogram_png,
        )
        monkeypatch.setattr(
            media_service,
            "_rebuild_detail_selection",
            _counted_rebuild_detail_selection,
        )

        payload = media_service.get_spectrogram(
            db,
            media.media_id,
            start_time=0.0,
            end_time=None,
            min_freq=1,
            max_freq=None,
            fft_size=512,
            window="hanning",
            channel=1,
            width_px=600,
            height_px=280,
            apply_frequency_filter=True,
        )
        second_payload = media_service.get_spectrogram(
            db,
            media.media_id,
            start_time=0.0,
            end_time=None,
            min_freq=1,
            max_freq=None,
            fft_size=512,
            window="hanning",
            channel=1,
            width_px=600,
            height_px=280,
            apply_frequency_filter=True,
        )

        assert payload == b"\x89PNG\r\ndynamic"
        assert second_payload == payload
        assert render_count == 2
        assert rebuild_count == 1
        assert captured["apply_frequency_filter"] is False
        assert "/tmp/detail/" in str(captured["audio_path"]).replace("\\", "/")

    def test_get_or_create_detail_asset_bundle_reuses_same_key(
        self,
        db: Session,
        setup_data,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        user = setup_data["user"]
        col = setup_data["collection"]

        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        audio_dir = tmp_path / "sounds" / str(col.collection_id) / "22"
        _write_audio_fixture(audio_dir / "bundle.flac", sample_rate=48000)

        audio_setting = AudioSetting(sampling_rate_hz=48000, bit_depth=16, channel_num=1, duration_s=1.0)
        db.add(audio_setting)
        db.flush()
        media = Media(
            name="M_BUNDLE",
            creator_id=user.user_id,
            uploader_id=user.user_id,
            media_type="audio",
            filename="bundle.flac",
            directory=22,
            audio_setting_id=audio_setting.audio_setting_id,
        )
        db.add(media)
        db.flush()
        db.add(MediaCollection(media_id=media.media_id, collection_id=col.collection_id, added_by=user.user_id))
        db.commit()

        original_rebuild_detail_selection = media_service._rebuild_detail_selection
        rebuild_count = 0

        def _counted_rebuild_detail_selection(*args, **kwargs):
            nonlocal rebuild_count
            rebuild_count += 1
            return original_rebuild_detail_selection(*args, **kwargs)

        monkeypatch.setattr(
            media_service,
            "_rebuild_detail_selection",
            _counted_rebuild_detail_selection,
        )

        bundle_a = media_service.get_or_create_detail_asset_bundle(
            db,
            media.media_id,
            start_time=0.0,
            end_time=0.5,
            min_freq=1,
            max_freq=24_000,
            channel=1,
            filter_enabled=False,
            fft_size=512,
        )
        bundle_b = media_service.get_or_create_detail_asset_bundle(
            db,
            media.media_id,
            start_time=0.0,
            end_time=0.5,
            min_freq=1,
            max_freq=24_000,
            channel=1,
            filter_enabled=False,
            fft_size=512,
        )

        assert bundle_a.key == bundle_b.key
        assert bundle_a.source_audio_path == bundle_b.source_audio_path
        assert bundle_a.playback_audio_path == bundle_b.playback_audio_path
        assert rebuild_count == 1
        manifest_path = bundle_a.source_audio_path.parent / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["version"] == media_service._DETAIL_ASSET_MANIFEST_VERSION
        assert manifest["artifacts"]["zoomed_audio"]["size"] > 0
        assert manifest["artifacts"]["spectrogram_wav"]["size"] > 0
        assert manifest["artifacts"]["spectrogram_wav"]["format"] == "wav"
        assert manifest["artifacts"]["spectrogram_wav"]["input_format"] == "flac"

    def test_get_or_create_detail_asset_bundle_uses_wav_render_cache_for_wav_source(
        self,
        db: Session,
        setup_data,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        user = setup_data["user"]
        col = setup_data["collection"]

        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        audio_dir = tmp_path / "sounds" / str(col.collection_id) / "24"
        audio_path = audio_dir / "mounted.wav"
        _write_audio_fixture(audio_path, sample_rate=48_000)

        audio_setting = AudioSetting(sampling_rate_hz=48_000, bit_depth=16, channel_num=1, duration_s=1.0)
        db.add(audio_setting)
        db.flush()
        media = Media(
            name="M_WAV_BUNDLE",
            creator_id=user.user_id,
            uploader_id=user.user_id,
            media_type="audio",
            filename="mounted.wav",
            directory=24,
            audio_setting_id=audio_setting.audio_setting_id,
        )
        db.add(media)
        db.flush()
        db.add(MediaCollection(media_id=media.media_id, collection_id=col.collection_id, added_by=user.user_id))
        db.commit()

        bundle = media_service.get_or_create_detail_asset_bundle(
            db,
            media.media_id,
            start_time=0.0,
            end_time=None,
            min_freq=1,
            max_freq=None,
            channel=1,
            filter_enabled=False,
            fft_size=512,
            build_playback=False,
        )

        assert bundle.source_audio_path.suffix == ".wav"
        assert bundle.spectrogram_audio_path.name == "spectrogram.wav"
        assert sf.info(str(bundle.spectrogram_audio_path)).samplerate == 48_000
        manifest = json.loads(
            (bundle.spectrogram_audio_path.parent / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest["artifacts"]["spectrogram_wav"]["format"] == "wav"
        assert manifest["artifacts"]["spectrogram_wav"]["input_format"] == "wav"
        assert manifest["artifacts"]["spectrogram_wav"]["input_artifact"] == "zoomed_audio"

    def test_get_or_create_detail_asset_bundle_serializes_concurrent_builders(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        audio_path = tmp_path / "source.wav"
        _write_audio_fixture(audio_path, sample_rate=48_000)
        media = SimpleNamespace(
            media_id=991,
            filename="source.wav",
            audio_setting=SimpleNamespace(sampling_rate_hz=48_000),
        )
        monkeypatch.setattr(
            media_service.media_repository,
            "get_with_detail_relations",
            lambda _session, _media_id: media,
        )
        monkeypatch.setattr(
            media_service,
            "_get_audio_path_for_media",
            lambda _media: audio_path,
        )
        original_rebuild_detail_selection = media_service._rebuild_detail_selection
        rebuild_count = 0
        count_lock = threading.Lock()

        def _counted_rebuild_detail_selection(*args, **kwargs):
            nonlocal rebuild_count
            with count_lock:
                rebuild_count += 1
            return original_rebuild_detail_selection(*args, **kwargs)

        monkeypatch.setattr(
            media_service,
            "_rebuild_detail_selection",
            _counted_rebuild_detail_selection,
        )

        def _build_bundle():
            return media_service.get_or_create_detail_asset_bundle(
                MagicMock(),
                media.media_id,
                start_time=0.0,
                end_time=0.5,
                min_freq=100,
                max_freq=20_000,
                channel=1,
                filter_enabled=True,
                fft_size=512,
            )

        with ThreadPoolExecutor(max_workers=4) as executor:
            bundles = list(executor.map(lambda _index: _build_bundle(), range(4)))

        assert rebuild_count == 1
        assert len({bundle.source_audio_path for bundle in bundles}) == 1
        assert len({bundle.source_audio_path.read_bytes() for bundle in bundles}) == 1

    def test_get_or_create_detail_asset_bundle_rebuilds_corrupt_cache_and_changed_source(
        self,
        db: Session,
        setup_data,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        user = setup_data["user"]
        col = setup_data["collection"]
        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        audio_path = tmp_path / "sounds" / str(col.collection_id) / "27" / "refresh.wav"
        _write_audio_fixture(audio_path, sample_rate=48_000, duration_s=1.0)
        audio_setting = AudioSetting(sampling_rate_hz=48_000, bit_depth=16, channel_num=1, duration_s=1.0)
        db.add(audio_setting)
        db.flush()
        media = Media(
            name="M_CACHE_REFRESH",
            creator_id=user.user_id,
            uploader_id=user.user_id,
            media_type="audio",
            filename="refresh.wav",
            directory=27,
            audio_setting_id=audio_setting.audio_setting_id,
        )
        db.add(media)
        db.flush()
        db.add(MediaCollection(media_id=media.media_id, collection_id=col.collection_id, added_by=user.user_id))
        db.commit()

        def _build_bundle():
            return media_service.get_or_create_detail_asset_bundle(
                db,
                media.media_id,
                start_time=0.0,
                end_time=0.5,
                min_freq=1,
                max_freq=24_000,
                channel=1,
                filter_enabled=False,
                fft_size=512,
            )

        bundle = _build_bundle()
        bundle.source_audio_path.write_bytes(b"")
        repaired = _build_bundle()
        assert media_service._validate_cached_audio(repaired.source_audio_path)

        old_manifest = json.loads(
            (repaired.source_audio_path.parent / "manifest.json").read_text(encoding="utf-8")
        )
        _write_audio_fixture(audio_path, sample_rate=48_000, duration_s=0.75)
        os.utime(audio_path, None)
        refreshed = _build_bundle()
        new_manifest = json.loads(
            (refreshed.source_audio_path.parent / "manifest.json").read_text(encoding="utf-8")
        )
        assert new_manifest["source"] != old_manifest["source"]

    def test_get_or_create_detail_asset_bundle_returns_clear_error_for_unknown_format(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        audio_path = tmp_path / "sounds" / "1" / "1" / "unknown.bin"
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        audio_path.write_bytes(b"not an audio file")
        media = SimpleNamespace(
            media_id=992,
            filename="unknown.bin",
            audio_setting=None,
        )
        monkeypatch.setattr(
            media_service.media_repository,
            "get_with_detail_relations",
            lambda _session, _media_id: media,
        )
        monkeypatch.setattr(
            media_service,
            "_get_audio_path_for_media",
            lambda _media: audio_path,
        )

        with pytest.raises(HTTPException) as exc_info:
            media_service.get_or_create_detail_asset_bundle(
                MagicMock(),
                media.media_id,
                start_time=0.0,
                end_time=None,
                min_freq=1,
                max_freq=None,
                channel=1,
                filter_enabled=False,
                fft_size=512,
            )

        assert exc_info.value.status_code == 415
        assert exc_info.value.detail == "Unsupported audio format"

    def test_get_or_create_detail_asset_bundle_preserves_cache_when_rebuild_fails(
        self,
        db: Session,
        setup_data,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        user = setup_data["user"]
        col = setup_data["collection"]
        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        audio_path = tmp_path / "sounds" / str(col.collection_id) / "28" / "atomic.wav"
        _write_audio_fixture(audio_path, sample_rate=48_000)
        audio_setting = AudioSetting(sampling_rate_hz=48_000, bit_depth=16, channel_num=1, duration_s=1.0)
        db.add(audio_setting)
        db.flush()
        media = Media(
            name="M_ATOMIC_CACHE",
            creator_id=user.user_id,
            uploader_id=user.user_id,
            media_type="audio",
            filename="atomic.wav",
            directory=28,
            audio_setting_id=audio_setting.audio_setting_id,
        )
        db.add(media)
        db.flush()
        db.add(MediaCollection(media_id=media.media_id, collection_id=col.collection_id, added_by=user.user_id))
        db.commit()
        kwargs = {
            "start_time": 0.0,
            "end_time": 0.5,
            "min_freq": 1,
            "max_freq": 24_000,
            "channel": 1,
            "filter_enabled": False,
            "fft_size": 512,
        }
        bundle = media_service.get_or_create_detail_asset_bundle(db, media.media_id, **kwargs)
        cached_bytes = bundle.source_audio_path.read_bytes()
        manifest_path = bundle.source_audio_path.parent / "manifest.json"
        cached_manifest = manifest_path.read_bytes()
        _write_audio_fixture(audio_path, sample_rate=48_000, duration_s=0.75)

        original_replace = media_service.os.replace
        failed = False

        def _fail_manifest_publish(source_path, target_path):
            nonlocal failed
            if Path(target_path) == manifest_path and not failed:
                failed = True
                raise OSError("publish failed")
            return original_replace(source_path, target_path)

        monkeypatch.setattr(media_service.os, "replace", _fail_manifest_publish)
        with pytest.raises(OSError, match="publish failed"):
            media_service.get_or_create_detail_asset_bundle(db, media.media_id, **kwargs)

        assert failed is True
        assert bundle.source_audio_path.read_bytes() == cached_bytes
        assert manifest_path.read_bytes() == cached_manifest
        assert not list(bundle.source_audio_path.parent.glob(".*.tmp.*"))

    def test_get_or_create_detail_asset_bundle_lock_timeout_returns_503(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        monkeypatch.setattr(media_service, "_DETAIL_ASSET_LOCK_TIMEOUT_SECONDS", 0.05)
        audio_path = tmp_path / "timeout.wav"
        _write_audio_fixture(audio_path, sample_rate=48_000)
        media = SimpleNamespace(
            media_id=992,
            filename="timeout.wav",
            audio_setting=SimpleNamespace(sampling_rate_hz=48_000),
        )
        monkeypatch.setattr(
            media_service.media_repository,
            "get_with_detail_relations",
            lambda _session, _media_id: media,
        )
        monkeypatch.setattr(
            media_service,
            "_get_audio_path_for_media",
            lambda _media: audio_path,
        )
        key = media_service._detail_asset_key(
            media_id=media.media_id,
            start_time=0.0,
            end_time=0.5,
            min_freq=1,
            max_freq=24_000,
            channel=1,
            filter_enabled=False,
            fft_size=512,
        )
        locked = threading.Event()
        release = threading.Event()

        def _hold_lock():
            with media_service._detail_asset_lock(key):
                locked.set()
                release.wait(timeout=2)

        holder = threading.Thread(target=_hold_lock)
        holder.start()
        assert locked.wait(timeout=1)
        try:
            with pytest.raises(HTTPException) as exc_info:
                media_service.get_or_create_detail_asset_bundle(
                    MagicMock(),
                    media.media_id,
                    start_time=0.0,
                    end_time=0.5,
                    min_freq=1,
                    max_freq=24_000,
                    channel=1,
                    filter_enabled=False,
                    fft_size=512,
                )
            assert exc_info.value.status_code == 503
            assert exc_info.value.detail == "Spectrogram audio cache is busy"
            assert exc_info.value.headers == {"Retry-After": "1"}
        finally:
            release.set()
            holder.join(timeout=2)

        assert not holder.is_alive()

    def test_cleanup_stale_detail_assets_skips_locked_bundle(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        key = "a" * 24
        bundle_dir = tmp_path / "tmp" / "detail" / "993" / key
        bundle_dir.mkdir(parents=True)
        access_path = bundle_dir / media_service._DETAIL_ASSET_ACCESS_FILENAME
        access_path.touch()
        stale_at = (datetime.now() - media_service._DETAIL_ASSET_TTL - timedelta(minutes=1)).timestamp()
        os.utime(access_path, (stale_at, stale_at))
        locked = threading.Event()
        release = threading.Event()

        def _hold_lock():
            with media_service._detail_asset_lock(key):
                locked.set()
                release.wait(timeout=2)

        holder = threading.Thread(target=_hold_lock)
        holder.start()
        assert locked.wait(timeout=1)
        media_service._cleanup_stale_detail_assets()
        assert bundle_dir.exists()
        release.set()
        holder.join(timeout=2)

        media_service._cleanup_stale_detail_assets()
        assert not bundle_dir.exists()

    def test_get_or_create_detail_asset_bundle_sets_download_basename(
        self,
        db: Session,
        setup_data,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        user = setup_data["user"]
        col = setup_data["collection"]

        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        audio_dir = tmp_path / "sounds" / str(col.collection_id) / "25"
        _write_audio_fixture(audio_dir / "detail-name.flac", sample_rate=48_000, duration_s=1.0)

        audio_setting = AudioSetting(sampling_rate_hz=48_000, bit_depth=16, channel_num=1, duration_s=1.0)
        db.add(audio_setting)
        db.flush()
        media = Media(
            name="M_LEGACY_NAME",
            creator_id=user.user_id,
            uploader_id=user.user_id,
            media_type="audio",
            filename="detail-name.flac",
            directory=25,
            audio_setting_id=audio_setting.audio_setting_id,
        )
        db.add(media)
        db.flush()
        db.add(MediaCollection(media_id=media.media_id, collection_id=col.collection_id, added_by=user.user_id))
        db.commit()

        bundle = media_service.get_or_create_detail_asset_bundle(
            db,
            media.media_id,
            start_time=0.0,
            end_time=None,
            min_freq=1000,
            max_freq=None,
            channel=1,
            filter_enabled=True,
            fft_size=512,
        )

        assert bundle.download_basename == "detail-name_1000-24000_0-1_512_1_filtered"

    def test_get_or_create_detail_asset_bundle_filter_changes_source_audio(
        self,
        db: Session,
        setup_data,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        user = setup_data["user"]
        col = setup_data["collection"]

        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        audio_dir = tmp_path / "sounds" / str(col.collection_id) / "23"
        frames = 48_000
        t = np.arange(frames, dtype=np.float32) / 48_000
        data = (
            0.6 * np.sin(2 * np.pi * 400 * t)
            + 0.6 * np.sin(2 * np.pi * 2400 * t)
        ).astype(np.float32)
        audio_path = audio_dir / "filter.flac"
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(audio_path), data, 48_000)

        audio_setting = AudioSetting(sampling_rate_hz=48000, bit_depth=16, channel_num=1, duration_s=1.0)
        db.add(audio_setting)
        db.flush()
        media = Media(
            name="M_FILTER",
            creator_id=user.user_id,
            uploader_id=user.user_id,
            media_type="audio",
            filename="filter.flac",
            directory=23,
            audio_setting_id=audio_setting.audio_setting_id,
        )
        db.add(media)
        db.flush()
        db.add(MediaCollection(media_id=media.media_id, collection_id=col.collection_id, added_by=user.user_id))
        db.commit()

        unfiltered = media_service.get_or_create_detail_asset_bundle(
            db,
            media.media_id,
            start_time=0.0,
            end_time=1.0,
            min_freq=1000,
            max_freq=24_000,
            channel=1,
            filter_enabled=False,
            fft_size=512,
        )
        filtered = media_service.get_or_create_detail_asset_bundle(
            db,
            media.media_id,
            start_time=0.0,
            end_time=1.0,
            min_freq=1000,
            max_freq=24_000,
            channel=1,
            filter_enabled=True,
            fft_size=512,
        )

        raw_unfiltered, _ = sf.read(str(unfiltered.source_audio_path), dtype="float32")
        raw_filtered, _ = sf.read(str(filtered.source_audio_path), dtype="float32")

        assert filtered.source_audio_path != unfiltered.source_audio_path
        assert not np.allclose(raw_unfiltered, raw_filtered)

    def test_get_audio_stream_payload_defaults_to_ogg_output(
        self,
        db: Session,
        setup_data,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        user = setup_data["user"]
        col = setup_data["collection"]

        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        audio_dir = tmp_path / "sounds" / str(col.collection_id) / "24"
        _write_audio_fixture(audio_dir / "payload.flac", sample_rate=48000)

        audio_setting = AudioSetting(sampling_rate_hz=48000, bit_depth=16, channel_num=1, duration_s=1.0)
        db.add(audio_setting)
        db.flush()
        media = Media(
            name="M_AUDIO_PAYLOAD",
            creator_id=user.user_id,
            uploader_id=user.user_id,
            media_type="audio",
            filename="payload.flac",
            directory=24,
            audio_setting_id=audio_setting.audio_setting_id,
        )
        db.add(media)
        db.flush()
        db.add(MediaCollection(media_id=media.media_id, collection_id=col.collection_id, added_by=user.user_id))
        db.commit()

        file_path, media_type, download_filename = media_service.get_audio_stream_payload(
            db,
            media.media_id,
            start_time=0.0,
            end_time=0.25,
            min_freq=None,
            max_freq=None,
            channel=1,
            filter_enabled=False,
            fft_size=512,
        )

        assert file_path is not None
        assert file_path.is_file()
        assert media_type == "audio/ogg"
        assert (
            download_filename
            == "payload_0-24000_0-0.25_512_1.ogg"
        )

    def test_get_spectrogram_download_filename_matches_audio_bundle_basename(
        self,
        db: Session,
        setup_data,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ):
        user = setup_data["user"]
        col = setup_data["collection"]

        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        audio_dir = tmp_path / "sounds" / str(col.collection_id) / "26"
        _write_audio_fixture(audio_dir / "bundle-match.flac", sample_rate=48_000, duration_s=1.0)

        audio_setting = AudioSetting(sampling_rate_hz=48_000, bit_depth=16, channel_num=1, duration_s=1.0)
        db.add(audio_setting)
        db.flush()
        media = Media(
            name="M_BUNDLE_MATCH",
            creator_id=user.user_id,
            uploader_id=user.user_id,
            media_type="audio",
            filename="bundle-match.flac",
            directory=26,
            audio_setting_id=audio_setting.audio_setting_id,
        )
        db.add(media)
        db.flush()
        db.add(MediaCollection(media_id=media.media_id, collection_id=col.collection_id, added_by=user.user_id))
        db.commit()

        bundle = media_service.get_or_create_detail_asset_bundle(
            db,
            media.media_id,
            start_time=0.0,
            end_time=0.5,
            min_freq=1000,
            max_freq=20_000,
            channel=1,
            filter_enabled=True,
            fft_size=512,
        )
        spectrogram_filename = media_service.get_spectrogram_download_filename(
            db,
            media.media_id,
            start_time=0.0,
            end_time=0.5,
            min_freq=1000,
            max_freq=20_000,
            fft_size=512,
            channel=1,
            apply_frequency_filter=True,
        )

        assert spectrogram_filename == f"{bundle.download_basename}.png"

    def test_get_media_list(self, db: Session, setup_data):
        user = setup_data["user"]
        admin = setup_data["admin"]
        proj = Project(name="ProjectListZ", creator_id=user.user_id, url="h")
        col = setup_data["collection"]
        db.add(proj)
        db.flush()
        from app.models import ProjectCollection
        db.add(ProjectCollection(project_id=proj.project_id, collection_id=col.collection_id))

        res = media_service.get_media_list(db, admin, project_id=proj.project_id)
        assert res.page_info.total >= 0

    def test_get_media_list_collection_scoped_to_requested_project(
        self, db: Session, setup_data
    ):
        """List items must pick collection/project fields within the requested project scope."""
        user = setup_data["user"]
        admin = setup_data["admin"]
        # other_col gets a smaller collection_id than scoped_col, so a
        # global-min selection would wrongly pick the foreign collection.
        other_col = Collection(name="ScopeZ Other Col", creator_id=user.user_id)
        db.add(other_col)
        db.flush()
        scoped_col = Collection(name="ScopeZ Col", creator_id=user.user_id)
        db.add(scoped_col)
        db.flush()
        other_proj = Project(name="ScopeZ Other Proj", creator_id=user.user_id, url="h")
        scoped_proj = Project(name="ScopeZ Proj", creator_id=user.user_id, url="h")
        db.add_all([other_proj, scoped_proj])
        db.flush()
        db.add_all([
            ProjectCollection(project_id=other_proj.project_id, collection_id=other_col.collection_id),
            ProjectCollection(project_id=scoped_proj.project_id, collection_id=scoped_col.collection_id),
        ])
        media_setting = AudioSetting(duration_s=1.0, sampling_rate_hz=44100, bit_depth=16, channel_num=1)
        db.add(media_setting)
        db.flush()
        media = Media(
            filename="scopez.flac",
            media_type="audio",
            creator_id=user.user_id,
            audio_setting_id=media_setting.audio_setting_id,
        )
        db.add(media)
        db.flush()
        db.add_all([
            MediaCollection(media_id=media.media_id, collection_id=other_col.collection_id, added_by=user.user_id),
            MediaCollection(media_id=media.media_id, collection_id=scoped_col.collection_id, added_by=user.user_id),
        ])
        db.flush()

        res = media_service.get_media_list(db, admin, project_id=scoped_proj.project_id)
        items = [m for m in res.data if m.media_id == media.media_id]
        assert len(items) == 1
        assert items[0].collection_id == scoped_col.collection_id
        assert items[0].project_id == scoped_proj.project_id
        assert items[0].project_name == "ScopeZ Proj"

    def test_get_media_list_query_count_constant_per_page(self, db: Session, setup_data):
        """Eager loading keeps the SQL count per page constant regardless of page size."""
        from sqlalchemy import event

        user = setup_data["user"]
        admin = setup_data["admin"]
        proj = setup_data["project"]
        col = setup_data["collection"]
        for i in range(8):
            setting = AudioSetting(duration_s=1.0, sampling_rate_hz=44100, bit_depth=16, channel_num=1)
            db.add(setting)
            db.flush()
            m = Media(
                filename=f"qc-{i}.flac",
                media_type="audio",
                creator_id=user.user_id,
                audio_setting_id=setting.audio_setting_id,
            )
            db.add(m)
            db.flush()
            db.add(MediaCollection(media_id=m.media_id, collection_id=col.collection_id, added_by=user.user_id))
        db.flush()

        statements: list[str] = []
        bind = db.get_bind()

        def _record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(bind, "before_cursor_execute", _record)
        try:
            res = media_service.get_media_list(
                db, admin, project_id=proj.project_id, page_size=8
            )
        finally:
            event.remove(bind, "before_cursor_execute", _record)

        assert res.page_info.total >= 8
        # Previously each row triggered several lazy loads (~5 statements/row).
        assert len(statements) <= 25, f"expected constant query count, got {len(statements)}"

    def test_get_media_list_does_not_read_photo_dimensions(
        self, db: Session, setup_data, monkeypatch: pytest.MonkeyPatch
    ):
        user = setup_data["user"]
        project = Project(name="PhotoListNoRead", creator_id=user.user_id, url="h")
        photo_setting = PhotoSetting(exposure_ms=8.5, aperture=2.8, iso=400)
        db.add_all([project, photo_setting])
        db.flush()
        photo = Media(
            name="Photo list item",
            creator_id=user.user_id,
            media_type="photo",
            photo_setting_id=photo_setting.photo_setting_id,
        )
        db.add(photo)
        db.flush()
        db.add_all([
            ProjectCollection(
                project_id=project.project_id,
                collection_id=setup_data["collection"].collection_id,
            ),
            MediaCollection(
                media_id=photo.media_id,
                collection_id=setup_data["collection"].collection_id,
                added_by=user.user_id,
            ),
        ])
        db.commit()

        def fail_if_dimension_is_read(*_args, **_kwargs):
            raise AssertionError("Photo dimensions must not be read for media lists")

        monkeypatch.setattr(media_service, "get_media_content_path", fail_if_dimension_is_read)
        result = media_service.get_media_list(
            db,
            setup_data["admin"],
            project_id=project.project_id,
            media_type="photo",
        )

        assert [item.media_id for item in result.data] == [photo.media_id]
        assert not hasattr(result.data[0], "image_width")
        assert not hasattr(result.data[0], "image_height")

    def test_get_media_list_anonymous_public_only_and_empty_labels(self, db: Session, setup_data):
        user = setup_data["user"]
        project = Project(name="ProjectListAnonZ", creator_id=user.user_id, url="h")
        public_col = Collection(name="PublicListAnonZ", creator_id=user.user_id, public_access=True)
        private_col = Collection(name="PrivateListAnonZ", creator_id=user.user_id, public_access=False)
        db.add_all([project, public_col, private_col])
        db.flush()
        db.add(ProjectCollection(project_id=project.project_id, collection_id=public_col.collection_id))
        db.add(ProjectCollection(project_id=project.project_id, collection_id=private_col.collection_id))

        media_public = Media(name="PublicListMediaZ", creator_id=user.user_id, media_type="audio", is_metadata=True)
        media_private = Media(name="PrivateListMediaZ", creator_id=user.user_id, media_type="audio", is_metadata=True)
        db.add_all([media_public, media_private])
        db.flush()
        db.add(MediaCollection(media_id=media_public.media_id, collection_id=public_col.collection_id, added_by=user.user_id))
        db.add(MediaCollection(media_id=media_private.media_id, collection_id=private_col.collection_id, added_by=user.user_id))

        label = Label(name="anon_visible_label", creator_id=user.user_id)
        db.add(label)
        db.flush()
        db.add(LabelMedia(media_id=media_public.media_id, user_id=user.user_id, label_id=label.label_id))
        db.commit()

        res = media_service.get_media_list(db, None, project_id=project.project_id)
        ids = {item.media_id for item in res.data}
        assert media_public.media_id in ids
        assert media_private.media_id not in ids
        assert all(item.labels == [] for item in res.data)




    def test_get_media_list_label_filter_only_matches_current_user_labels(self, db: Session, setup_data):
        user = setup_data["user"]
        admin = setup_data["admin"]
        project = setup_data["project"]
        collection = setup_data["collection"]

        media = Media(name="ScopedLabelMedia", creator_id=user.user_id, media_type="audio", is_metadata=True)
        db.add(media)
        db.flush()
        db.add(
            MediaCollection(
                media_id=media.media_id,
                collection_id=collection.collection_id,
                added_by=user.user_id,
            )
        )

        user_label = Label(name="user-only-label", creator_id=user.user_id)
        requester_label = Label(name="requester-only-label", creator_id=admin.user_id)
        db.add_all([user_label, requester_label])
        db.flush()
        db.add_all(
            [
                LabelMedia(media_id=media.media_id, user_id=user.user_id, label_id=user_label.label_id),
                LabelMedia(media_id=media.media_id, user_id=admin.user_id, label_id=requester_label.label_id),
            ]
        )
        db.commit()

        admin_res = media_service.get_media_list(
            db,
            admin,
            project_id=project.project_id,
            label_id=requester_label.label_id,
        )
        user_res = media_service.get_media_list(
            db,
            user,
            project_id=project.project_id,
            label_id=requester_label.label_id,
        )

        assert [item.media_id for item in admin_res.data] == [media.media_id]
        assert user_res.data == []

    def test_export_media_csv_branches(self, db: Session, setup_data):
        user = setup_data["user"]
        proj = Project(name="ExpProjZ", creator_id=user.user_id, url="h")
        db.add(proj)
        db.flush()
        csv_str = media_service.export_media_csv(
            db,
            setup_data["admin"],
            project_id=proj.project_id,
            media_type="audio",
        )
        assert isinstance(csv_str, str)
        assert "type" in csv_str.splitlines()[0]

    def test_export_photos_csv_includes_type_column(self, db: Session, setup_data):
        """Photo export exposes the metadata flag like audio export does."""
        user = setup_data["user"]
        col = setup_data["collection"]
        proj = Project(name="ExpPhotoProjZ", creator_id=user.user_id, url="h")
        db.add(proj)
        db.flush()
        db.add(ProjectCollection(project_id=proj.project_id, collection_id=col.collection_id))

        photo_setting = PhotoSetting(exposure_ms=8.5, aperture=2.8, iso=400)
        db.add(photo_setting)
        db.flush()
        media = Media(
            name="PhotoMetaExport",
            creator_id=user.user_id,
            media_type="photo",
            is_metadata=True,
            photo_setting_id=photo_setting.photo_setting_id,
        )
        file_media = Media(
            name="PhotoFileExport",
            creator_id=user.user_id,
            media_type="photo",
            is_metadata=False,
            photo_setting_id=photo_setting.photo_setting_id,
        )
        db.add(media)
        db.add(file_media)
        db.flush()
        db.add(MediaCollection(media_id=media.media_id, collection_id=col.collection_id, added_by=user.user_id))
        db.add(MediaCollection(media_id=file_media.media_id, collection_id=col.collection_id, added_by=user.user_id))
        db.commit()

        csv_str = media_service.export_media_csv(
            db,
            setup_data["admin"],
            project_id=proj.project_id,
            media_type="photo",
        )
        rows = list(csv.reader(csv_str.splitlines()))
        header = rows[0]
        assert "type" in header
        metadata_row = next(row for row in rows[1:] if row[header.index("name")] == "PhotoMetaExport")
        file_row = next(row for row in rows[1:] if row[header.index("name")] == "PhotoFileExport")
        assert metadata_row[header.index("type")] == "metadata"
        assert file_row[header.index("type")] == "file"

    def test_update_media_audio_setting_fields_are_persisted(self, db: Session, setup_data):
        """Audio setting fields (gain, sr, bit_depth, channels, duration) must be written
        to AudioSetting after PATCH — regression guard for the sanitize-before-extract bug."""
        user = setup_data["user"]
        audio_setting = AudioSetting(sampling_rate_hz=44100, duration_s=10.0)
        db.add(audio_setting)
        db.flush()
        media = Media(
            name="UpdateTest",
            creator_id=user.user_id,
            media_type="audio",
            is_metadata=False,
            audio_setting_id=audio_setting.audio_setting_id,
        )
        db.add(media)
        db.commit()
        db.refresh(media)

        media_in = MediaUpdate(
            recording_gain_db=12,
            sampling_rate_hz=48000,
            bit_depth=24,
            channel_num=2,
            duration_s=30.5,
        )
        media_service.update_media(db, media.media_id, media_in)
        db.refresh(audio_setting)

        assert audio_setting.recording_gain_db == 12
        assert audio_setting.sampling_rate_hz == 48000
        assert audio_setting.bit_depth == 24
        assert audio_setting.channel_num == 2
        assert audio_setting.duration_s == 30.5

    def test_update_media_audio_metadata_creates_audio_setting(self, db: Session, setup_data):
        """Audio metadata without technical settings gets an AudioSetting created on PATCH."""
        user = setup_data["user"]
        media = Media(
            name="NoSettingMedia",
            creator_id=user.user_id,
            media_type="audio",
            is_metadata=True,
        )
        db.add(media)
        db.commit()
        db.refresh(media)
        assert media.audio_setting_id is None

        media_in = MediaUpdate(
            recording_gain_db=6,
            sampling_rate_hz=22050,
            bit_depth=24,
            channel_num=2,
            duration_s=5.0,
        )
        media_service.update_media(db, media.media_id, media_in)
        db.refresh(media)

        assert media.audio_setting_id is not None
        assert media.audio_setting.recording_gain_db == 6
        assert media.audio_setting.sampling_rate_hz == 22050
        assert media.audio_setting.bit_depth == 24
        assert media.audio_setting.channel_num == 2
        assert media.audio_setting.duration_s == 5.0

    def test_update_media_audio_metadata_updates_existing_audio_setting(self, db: Session, setup_data):
        """Audio metadata with an existing AudioSetting overwrites its values on PATCH."""
        user = setup_data["user"]
        audio_setting = AudioSetting(sampling_rate_hz=44100, duration_s=10.0)
        db.add(audio_setting)
        db.flush()
        media = Media(
            name="MetadataWithSetting",
            creator_id=user.user_id,
            media_type="audio",
            is_metadata=True,
            audio_setting_id=audio_setting.audio_setting_id,
        )
        db.add(media)
        db.commit()
        db.refresh(media)

        media_in = MediaUpdate(sampling_rate_hz=96000, duration_s=2240.0)
        media_service.update_media(db, media.media_id, media_in)
        db.refresh(audio_setting)

        assert audio_setting.sampling_rate_hz == 96000
        assert audio_setting.duration_s == 2240.0

    def test_update_media_audio_metadata_persists_duty_cycle_fields(self, db: Session, setup_data):
        media = Media(
            name="Metadata",
            creator_id=setup_data["user"].user_id,
            media_type="audio",
            is_metadata=True,
        )
        db.add(media)
        db.commit()
        db.refresh(media)

        media_service.update_media(
            db,
            media.media_id,
            MediaUpdate(duty_cycle_recording=60, duty_cycle_period=3600),
        )
        db.refresh(media)

        assert media.duty_cycle_recording == 60
        assert media.duty_cycle_period == 3600

    def test_update_media_photo_metadata_rejects_audio_setting_fields(self, db: Session, setup_data):
        photo_setting = PhotoSetting()
        db.add(photo_setting)
        db.flush()
        media = Media(
            name="PhotoMetadata",
            creator_id=setup_data["user"].user_id,
            media_type="photo",
            is_metadata=True,
            photo_setting_id=photo_setting.photo_setting_id,
        )
        db.add(media)
        db.commit()
        db.refresh(media)

        with pytest.raises(HTTPException) as exc_info:
            media_service.update_media(
                db,
                media.media_id,
                MediaUpdate(sampling_rate_hz=22050, duration_s=5.0),
            )

        assert exc_info.value.status_code == 422
        assert "Photo media must not include audio-only fields" in str(exc_info.value.detail)
        assert media.audio_setting_id is None

    def test_update_photo_rejects_null_audio_fields_without_orphan(self, db: Session, setup_data):
        user = setup_data["user"]
        photo_setting = PhotoSetting()
        db.add(photo_setting)
        db.flush()
        media = Media(
            name="Photo",
            creator_id=user.user_id,
            media_type="photo",
            photo_setting_id=photo_setting.photo_setting_id,
        )
        db.add(media)
        db.commit()
        audio_setting_count = len(db.exec(select(AudioSetting)).all())

        media_in = MediaUpdate(
            name="Rejected Photo",
            recording_gain_db=None,
            sampling_rate_hz=None,
            bit_depth=None,
            channel_num=None,
            duration_s=None,
            duty_cycle_recording=None,
            duty_cycle_period=None,
        )
        with pytest.raises(HTTPException) as exc_info:
            media_service.update_media(db, media.media_id, media_in)

        assert exc_info.value.status_code == 422
        db.refresh(media)
        assert media.name == "Photo"
        assert len(db.exec(select(AudioSetting)).all()) == audio_setting_count

    def test_update_photo_common_fields_succeed(self, db: Session, setup_data):
        user = setup_data["user"]
        photo_setting = PhotoSetting()
        db.add(photo_setting)
        db.flush()
        media = Media(
            name="Photo",
            creator_id=user.user_id,
            media_type="photo",
            photo_setting_id=photo_setting.photo_setting_id,
        )
        db.add(media)
        db.commit()

        media_service.update_media(
            db,
            media.media_id,
            MediaUpdate(name="Renamed Photo", note="photo note", site_id=None),
        )

        db.refresh(media)
        assert media.name == "Renamed Photo"
        assert media.note == "photo note"
        assert media.audio_setting_id is None

    def test_update_media_rejects_sensor_type_mismatch(self, db: Session, setup_data):
        user = setup_data["user"]
        audio_setting = AudioSetting(sampling_rate_hz=44100, duration_s=1)
        photo_sensor = _create_photo_sensor(db, "Photo Sensor")
        db.add(audio_setting)
        db.flush()
        media = Media(
            name="Audio",
            creator_id=user.user_id,
            media_type="audio",
            audio_setting_id=audio_setting.audio_setting_id,
        )
        db.add(media)
        db.commit()

        with pytest.raises(HTTPException) as exc_info:
            media_service.update_media(
                db,
                media.media_id,
                MediaUpdate(sensor_id=photo_sensor.sensor_id),
            )

        assert exc_info.value.status_code == 422
        assert "cannot be used for audio media" in str(exc_info.value.detail)

    def test_update_media_rolls_back_when_commit_fails(
        self, db: Session, setup_data, monkeypatch: pytest.MonkeyPatch
    ):
        user = setup_data["user"]
        audio_setting = AudioSetting(
            recording_gain_db=1,
            sampling_rate_hz=44100,
            duration_s=1,
        )
        db.add(audio_setting)
        db.flush()
        media = Media(
            name="Atomic Audio",
            creator_id=user.user_id,
            media_type="audio",
            audio_setting_id=audio_setting.audio_setting_id,
        )
        db.add(media)
        db.commit()
        media_id = media.media_id

        def fail_commit() -> None:
            raise RuntimeError("forced commit failure")

        rollback = MagicMock(wraps=db.rollback)
        monkeypatch.setattr(db, "commit", fail_commit)
        monkeypatch.setattr(db, "rollback", rollback)
        # A commit failure must propagate and trigger exactly one rollback so the
        # PATCH stays atomic (Media row and AudioSetting update roll back together).
        with pytest.raises(RuntimeError, match="forced commit failure"):
            media_service.update_media(
                db,
                media_id,
                MediaUpdate(name="Partially Updated", recording_gain_db=9),
            )
        rollback.assert_called_once_with()

    def test_update_media_base_fields_persisted(self, db: Session, setup_data):
        """Media table fields (name, note, license_id, etc.) are still updated correctly."""
        user = setup_data["user"]
        lic = setup_data["license"]
        # Use is_metadata=True to avoid the audio_setting_id NOT NULL constraint
        media = Media(
            name="BaseFieldTest",
            creator_id=user.user_id,
            media_type="audio",
            is_metadata=True,
        )
        db.add(media)
        db.commit()
        db.refresh(media)

        media_in = MediaUpdate(
            name="Renamed",
            note="updated note",
            doi="10.1234/test",
            date_time="2025-06-01 10:00:00",
            license_id=lic.license_id,
        )
        media_service.update_media(db, media.media_id, media_in)
        db.refresh(media)

        assert media.name == "Renamed"
        assert media.note == "updated note"
        assert media.doi == "10.1234/test"
        assert media.license_id == lic.license_id

    def test_update_media_date_time_optional(self, db: Session, setup_data):
        """date_time is optional in MediaUpdate — omitting it must not raise an error."""
        user = setup_data["user"]
        media = Media(
            name="OptionalDateTest",
            creator_id=user.user_id,
            media_type="audio",
            is_metadata=True,
            date_time=datetime(2025, 1, 1),
        )
        db.add(media)
        db.commit()
        db.refresh(media)
        original_dt = media.date_time

        # Only update name, do not send date_time
        media_in = MediaUpdate(name="DateOptional")
        media_service.update_media(db, media.media_id, media_in)
        db.refresh(media)

        assert media.name == "DateOptional"
        assert media.date_time == original_dt

    def test_update_media_not_found(self, db: Session, setup_data):
        """update_media raises 404 for a non-existent media_id."""
        user = setup_data["user"]
        media_in = MediaUpdate(name="Ghost")
        with pytest.raises(HTTPException) as exc_info:
            media_service.update_media(db, 999999999, media_in)
        assert exc_info.value.status_code == 404

"""Unit tests for MediaService (final coverage push)."""
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlmodel import Session

from app.models import (
    User, Role, FileUpload
)
from app.schemas.media import MediaCreate
from app.services import media_service


@pytest.mark.anyio
class TestMediaServiceEdgeCases:
    """Final tests to cross 80%."""

    async def test_create_media_date_manual(self, db: Session):
        # setup role
        role = Role(name="FinalRole")
        db.add(role)
        db.flush()

        u = User(username="mu_m", role_id=role.role_id, email="mxm@e.com", password="p", name="M")
        db.add(u)
        db.flush()
        fu = FileUpload(filename="x", name="x", directory=1, path="x", size=0, status=1, uploader_id=u.user_id)
        db.add(fu)
        db.flush()

        req = MediaCreate(
            collection_id=1,
            file_upload_ids=[fu.file_upload_id],
            date_time="2024-01-01 12:00:00",
            media_type="audio",
        )
        res = await media_service.create_media(db, req, u, AsyncMock())
        assert len(res.queued) == 1

    def test_get_media_by_id_not_found(self, db: Session):
        role = Role(name="FinalRole2")
        db.add(role)
        db.flush()
        u = User(username="mu_n", role_id=role.role_id, email="mun@e.com", password="p", name="M")
        db.add(u)
        db.flush()
        with pytest.raises(HTTPException) as exc:
            media_service.get_media(db, 1, 99999, u)
        assert exc.value.status_code == 404

    def test_delete_media_not_found(self, db: Session):
        role = Role(name="FinalRole3")
        db.add(role)
        db.flush()
        u = User(username="mu_d", role_id=role.role_id, email="mud@e.com", password="p", name="M")
        db.add(u)
        db.flush()
        with pytest.raises(HTTPException) as exc:
            media_service.delete_media(db, 99999, u)
        assert exc.value.status_code == 404

"""Unit tests for MediaService (comprehensive)."""
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import (
    User, Role, Project, ProjectCollection, Collection, Media, FileUpload, MediaCollection, UserPermission, Permission, AudioSetting
)
from app.schemas.media import MediaCreate
from app.services import media_service
from app.services.upload_validation_service import validate_csv_content


@pytest.fixture
def setup_media_scenarios(db: Session):
    admin_role = db.exec(select(Role).where(Role.name == "Administrator")).first()
    if not admin_role:
        admin_role = Role(name="Administrator")
        db.add(admin_role)

    user_role_name = "Media_Service_Role_Comp_" + str(datetime.now().timestamp())
    user_role = Role(name=user_role_name)
    db.add_all([user_role])
    db.flush()

    user = User(username="ms_user_c", role_id=user_role.role_id, email="msc@e.com", password="p", name="M")
    admin = User(username="ms_admin_c", role_id=admin_role.role_id, email="msac@e.com", password="p", name="MA")
    db.add_all([user, admin])
    db.flush()

    col = Collection(name="Comp Col", creator_id=user.user_id)
    db.add(col)
    db.flush()
    project = Project(name="Comp Project", creator_id=user.user_id, url="https://media-service.example")
    db.add(project)
    db.flush()
    db.add(ProjectCollection(project_id=project.project_id, collection_id=col.collection_id))
    db.flush()

    return {"user": user, "admin": admin, "collection": col, "project": project}


@pytest.mark.anyio
class TestMediaServiceScenarios:
    """Tests for MediaService high coverage."""

    async def test_create_media_errors(self, db: Session, setup_media_scenarios):
        user = setup_media_scenarios["user"]
        col = setup_media_scenarios["collection"]

        # 1. FileUpload not found
        req = MediaCreate(
            collection_id=col.collection_id,
            file_upload_ids=[9999],
            media_type="audio",
            date_from_filename=True,
        )
        res = await media_service.create_media(db, req, user, MagicMock())
        assert len(res.failed) == 1
        assert "not found" in res.failed[0].reason

        # 2. FileUpload not pending
        fu = FileUpload(filename="x", name="x", directory=1, path="x", size=0, status=3, uploader_id=user.user_id)
        db.add(fu)
        db.flush()
        req = MediaCreate(
            collection_id=col.collection_id,
            file_upload_ids=[fu.file_upload_id],
            media_type="audio",
            date_from_filename=True,
        )
        res = await media_service.create_media(db, req, user, MagicMock())
        assert len(res.failed) == 1
        assert "not pending" in res.failed[0].reason

    async def test_import_metadata_csv_encodings_extended(self, db: Session, setup_media_scenarios):
        user = setup_media_scenarios["user"]
        col = setup_media_scenarios["collection"]
        content = "date_time,duration_s,sampling_rate_hz,name\n2024-01-01 12:00:00,1,1,X\n"

        # UTF-8 BOM is stripped during upload validation before the service runs.
        text = validate_csv_content(b'\xef\xbb\xbf' + content.encode("utf-8"))
        res = media_service.import_metadata_csv(db, text, col.collection_id, user)
        assert res.succeeded == 1

    async def test_import_metadata_csv_recording_start_formats(self, db: Session, setup_media_scenarios):
        user = setup_media_scenarios["user"]
        col = setup_media_scenarios["collection"]
        csv = (
            "date_time,duration_s,sampling_rate_hz,name\n"
            "2022/1/1 12:12,10,48000,FmtSlash\n"
            "2022-01-01T12:12:00,10,48000,FmtT\n"
            "2022-01-01 12:12,10,48000,FmtNoSec\n"
        )
        res = media_service.import_metadata_csv(db, csv, col.collection_id, user)
        assert res.total == 3
        assert res.succeeded == 3

    async def test_import_metadata_csv_validation_errors(self, db: Session, setup_media_scenarios):
        user = setup_media_scenarios["user"]
        col = setup_media_scenarios["collection"]

        # Insufficient columns
        csv = "col1,col2\nval1,val2\n"
        result = media_service.import_metadata_csv(db, csv, col.collection_id, user)
        assert result.committed is False
        assert result.global_errors

        # Invalid duration
        csv = "date_time,duration_s,sampling_rate_hz,name\n2024-01-01 12:00:00,invalid,48000,X\n"
        assert media_service.import_metadata_csv(db, csv, col.collection_id, user).global_errors

        # Invalid sampling rate
        csv = "date_time,duration_s,sampling_rate_hz,name\n2024-01-01 12:00:00,10,invalid,X\n"
        assert media_service.import_metadata_csv(db, csv, col.collection_id, user).global_errors

        # Unsupported recording_start format
        csv = "date_time,duration_s,sampling_rate_hz,name\n01-01-2022 12:12,10,48000,X\n"
        result = media_service.import_metadata_csv(db, csv, col.collection_id, user)
        assert result.global_errors and "supported formats" in result.global_errors[0]

    async def test_import_metadata_csv_photo_encodings_extended(self, db: Session, setup_media_scenarios):
        user = setup_media_scenarios["user"]
        col = setup_media_scenarios["collection"]
        content = "date_time,name\n2024-01-01 12:00:00,PhotoX\n"

        # UTF-8 BOM is stripped during upload validation before the service runs.
        text = validate_csv_content(b'\xef\xbb\xbf' + content.encode("utf-8"))
        res = media_service.import_metadata_csv(
            db, text, col.collection_id, user, media_type="photo"
        )
        assert res.succeeded == 1

    async def test_import_metadata_csv_photo_recording_start_formats(self, db: Session, setup_media_scenarios):
        user = setup_media_scenarios["user"]
        col = setup_media_scenarios["collection"]
        csv = (
            "date_time,name\n"
            "2022/1/1 12:12,FmtSlash\n"
            "2022-01-01T12:12:00,FmtT\n"
            "2022-01-01 12:12,FmtNoSec\n"
        )
        res = media_service.import_metadata_csv(
            db, csv, col.collection_id, user, media_type="photo"
        )
        assert res.total == 3
        assert res.succeeded == 3

    async def test_import_metadata_csv_photo_validation_errors(self, db: Session, setup_media_scenarios):
        user = setup_media_scenarios["user"]
        col = setup_media_scenarios["collection"]

        # Missing/blank capture_time value
        csv = "date_time,name\n,X\n"
        result = media_service.import_metadata_csv(db, csv, col.collection_id, user, media_type="photo")
        assert result.global_errors

        # Invalid exposure_ms
        csv = "date_time,name,exposure_ms\n2024-01-01 12:00:00,X,invalid\n"
        assert media_service.import_metadata_csv(db, csv, col.collection_id, user, media_type="photo").global_errors

        # Invalid aperture
        csv = "date_time,name,exposure_ms,aperture\n2024-01-01 12:00:00,X,10,invalid\n"
        assert media_service.import_metadata_csv(db, csv, col.collection_id, user, media_type="photo").global_errors

        # Invalid iso
        csv = "date_time,name,exposure_ms,aperture,iso\n2024-01-01 12:00:00,X,10,2.8,invalid\n"
        assert media_service.import_metadata_csv(db, csv, col.collection_id, user, media_type="photo").global_errors

        # Unsupported capture_time format
        csv = "date_time,name\n01-01-2022 12:12,X\n"
        result = media_service.import_metadata_csv(db, csv, col.collection_id, user, media_type="photo")
        assert result.global_errors and "supported formats" in result.global_errors[0]

    async def test_get_media_list_user(self, db: Session, setup_media_scenarios):
        user = setup_media_scenarios["user"]
        proj = Project(name="UP", creator_id=user.user_id, url="h")
        db.add(proj)
        db.flush()
        res = media_service.get_media_list(db, user, project_id=proj.project_id)
        assert res.page_info.total >= 0

    async def test_get_media_by_id_permission_audio_read(self, db: Session, setup_media_scenarios):
        user = setup_media_scenarios["user"]
        col = setup_media_scenarios["collection"]
        project = setup_media_scenarios["project"]
        media = Media(name="M_Perm", creator_id=user.user_id, media_type="audio", is_metadata=True)
        db.add(media)
        db.flush()
        db.add(MediaCollection(media_id=media.media_id, collection_id=col.collection_id, added_by=user.user_id))
        db.flush()

        # Grant audio:read
        perm = db.exec(select(Permission).where(Permission.name == "audio:read")).first()
        if not perm:
            perm = Permission(name="audio:read", resource_type="audio", action="read")
            db.add(perm)
            db.flush()
        db.add(UserPermission(user_id=user.user_id, project_id=project.project_id, collection_id=col.collection_id, permission_id=perm.permission_id))
        db.flush()

        res = media_service.get_media(db, project.project_id, media.media_id, user)
        assert res.name == "M_Perm"

    async def test_update_media_proxy(self, db: Session, setup_media_scenarios):
        user = setup_media_scenarios["user"]
        media = Media(name="Old", creator_id=user.user_id, media_type="audio", is_metadata=True)
        db.add(media)
        db.flush()

        class MockIn:
            def model_dump(self, **kwargs): return {"name": "New"}

        media_service.update_media(db, media.media_id, MockIn())
        db.refresh(media)
        assert media.name == "New"

    async def test_update_media_metadata_ignores_setting_fields(self, db: Session, setup_media_scenarios):
        user = setup_media_scenarios["user"]
        media = Media(
            name="Imported Metadata",
            creator_id=user.user_id,
            uploader_id=user.user_id,
            media_type="audio", is_metadata=True,
        )
        db.add(media)
        db.flush()

        class MockIn:
            def model_dump(self, **kwargs):
                return {
                    "name": "Updated Metadata",
                    "audio_setting_id": 999,
                    "photo_setting_id": 888,
                }

        media_service.update_media(db, media.media_id, MockIn())
        db.refresh(media)
        assert media.name == "Updated Metadata"
        assert media.audio_setting_id is None
        assert media.photo_setting_id is None

    async def test_update_media_audio_preserves_existing_audio_setting(self, db: Session, setup_media_scenarios):
        user = setup_media_scenarios["user"]
        audio_setting = AudioSetting(
            sampling_rate_hz=44100,
            bit_depth=16,
            channel_num=1,
            duration_s=5.0,
        )
        db.add(audio_setting)
        db.flush()
        media = Media(
            name="Audio Media",
            creator_id=user.user_id,
            uploader_id=user.user_id,
            media_type="audio",
            audio_setting_id=audio_setting.audio_setting_id,
            filename="audio.wav",
            directory=1,
        )
        db.add(media)
        db.flush()

        class MockIn:
            def model_dump(self, **kwargs):
                return {"name": "Audio Renamed", "audio_setting_id": 123456}

        media_service.update_media(db, media.media_id, MockIn())
        db.refresh(media)
        assert media.name == "Audio Renamed"
        assert media.audio_setting_id == audio_setting.audio_setting_id
