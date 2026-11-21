"""Unit tests for media and collection physical storage cleanup."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    AudioSetting,
    Collection,
    Media,
    MediaCollection,
    PhotoSetting,
    Preview,
    User,
)
from app.services import detail_cache_service, media_storage_cleanup_service


def _admin_user(db: Session) -> User:
    user = db.exec(select(User).where(User.role_id == 1)).first()
    assert user is not None
    return user


def _create_collection(db: Session, creator_id: int, prefix: str = "cleanup") -> Collection:
    collection = Collection(
        name=f"{prefix}_{uuid.uuid4().hex[:8]}",
        creator_id=creator_id,
        public_access=False,
    )
    db.add(collection)
    db.commit()
    db.refresh(collection)
    return collection


def _write_bytes(path: Path, data: bytes = b"payload") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


class TestMediaStorageCleanupService:
    def test_cleanup_audio_files_previews_detail_cache_and_empty_dirs(
        self,
        db: Session,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        admin = _admin_user(db)
        col = _create_collection(db, admin.user_id, "audio_clean")

        setting = AudioSetting(sampling_rate_hz=44100, bit_depth=16, channel_num=1, duration_s=5.0)
        db.add(setting)
        db.flush()

        media = Media(
            media_type="audio",
            directory=42,
            filename="bird.flac",
            name="bird.flac",
            storage_collection_id=col.collection_id,
            uploader_id=admin.user_id,
            creator_id=admin.user_id,
            audio_setting_id=setting.audio_setting_id,
        )
        db.add(media)
        db.flush()
        db.add(MediaCollection(media_id=media.media_id, collection_id=col.collection_id, added_by=admin.user_id))
        thumb_preview = Preview(media_id=media.media_id, filename="bird_thumbnail.png", type="thumbnail")
        player_preview = Preview(media_id=media.media_id, filename="bird_player_s.png", type="spectrogram")
        db.add(thumb_preview)
        db.add(player_preview)
        db.commit()

        flac_file = _write_bytes(tmp_path / "sounds" / str(col.collection_id) / "42" / "bird.flac")
        wav_file = _write_bytes(tmp_path / "sounds" / str(col.collection_id) / "42" / "bird.wav")
        thumb_file = _write_bytes(tmp_path / "sounds" / str(col.collection_id) / "42" / "bird_thumbnail.png")
        player_file = _write_bytes(tmp_path / "images" / str(col.collection_id) / "42" / "bird_player_s.png")
        cache_bundle = _write_bytes(
            tmp_path / "tmp" / "detail" / str(media.media_id) / "bundle_a" / "zoomed.flac"
        )

        snapshot = media_storage_cleanup_service.build_media_cleanup_snapshot(
            media,
            collection_ids=(col.collection_id,),
            previews=(thumb_preview, player_preview),
        )
        setting_id = setting.audio_setting_id
        db.delete(media)
        db.flush()
        media_storage_cleanup_service.delete_unreferenced_media_settings(
            db, audio_setting_ids=(setting_id,)
        )
        db.commit()

        removed = media_storage_cleanup_service.cleanup_deleted_media_files(db, snapshot)

        assert removed == 4
        assert not flac_file.exists()
        assert not wav_file.exists()
        assert not thumb_file.exists()
        assert not player_file.exists()
        assert not cache_bundle.parent.parent.exists()
        # Empty collection subdirectories are pruned while top-level roots remain.
        assert not (tmp_path / "sounds" / str(col.collection_id)).exists()
        assert not (tmp_path / "images" / str(col.collection_id)).exists()
        assert (tmp_path / "sounds").is_dir()
        assert (tmp_path / "images").is_dir()
        assert db.get(AudioSetting, setting_id) is None

    def test_cleanup_photo_files_thumbnail_and_unreferenced_setting(
        self,
        db: Session,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        admin = _admin_user(db)
        col = _create_collection(db, admin.user_id, "photo_clean")

        photo_setting = PhotoSetting(exposure_ms=10.0, aperture=2.8, iso=200)
        db.add(photo_setting)
        db.flush()

        media = Media(
            media_type="photo",
            directory=7,
            filename="owl.jpg",
            name="owl.jpg",
            storage_collection_id=col.collection_id,
            uploader_id=admin.user_id,
            creator_id=admin.user_id,
            photo_setting_id=photo_setting.photo_setting_id,
        )
        db.add(media)
        db.flush()
        db.add(MediaCollection(media_id=media.media_id, collection_id=col.collection_id, added_by=admin.user_id))
        thumb_preview = Preview(media_id=media.media_id, filename="owl_thumbnail.png", type="thumbnail")
        db.add(thumb_preview)
        db.commit()

        photo_file = _write_bytes(tmp_path / "images" / str(col.collection_id) / "7" / "owl.jpg")
        thumb_file = _write_bytes(tmp_path / "images" / str(col.collection_id) / "7" / "owl_thumbnail.png")

        snapshot = media_storage_cleanup_service.build_media_cleanup_snapshot(
            media,
            collection_ids=(col.collection_id,),
            previews=(thumb_preview,),
        )
        setting_id = photo_setting.photo_setting_id
        db.delete(media)
        db.flush()
        media_storage_cleanup_service.delete_unreferenced_media_settings(
            db, photo_setting_ids=(setting_id,)
        )
        db.commit()

        removed = media_storage_cleanup_service.cleanup_deleted_media_files(db, snapshot)

        assert removed == 2
        assert not photo_file.exists()
        assert not thumb_file.exists()
        assert not (tmp_path / "images" / str(col.collection_id)).exists()
        assert db.get(PhotoSetting, setting_id) is None

    def test_cleanup_fallback_derived_previews_when_preview_rows_absent(
        self,
        db: Session,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        admin = _admin_user(db)
        col = _create_collection(db, admin.user_id, "fallback_prev")

        setting = AudioSetting(sampling_rate_hz=44100, duration_s=2.0)
        db.add(setting)
        db.flush()
        media = Media(
            media_type="audio",
            directory=3,
            filename="frog.flac",
            storage_collection_id=col.collection_id,
            uploader_id=admin.user_id,
            creator_id=admin.user_id,
            audio_setting_id=setting.audio_setting_id,
        )
        db.add(media)
        db.commit()

        audio_file = _write_bytes(tmp_path / "sounds" / str(col.collection_id) / "3" / "frog.flac")
        thumb_file = _write_bytes(tmp_path / "sounds" / str(col.collection_id) / "3" / "frog_thumbnail.png")
        player_file = _write_bytes(tmp_path / "images" / str(col.collection_id) / "3" / "frog_player_s.png")

        snapshot = media_storage_cleanup_service.build_media_cleanup_snapshot(
            media, collection_ids=(col.collection_id,), previews=()
        )
        db.delete(media)
        db.commit()

        removed = media_storage_cleanup_service.cleanup_deleted_media_files(db, snapshot)

        assert removed == 3
        assert not audio_file.exists()
        assert not thumb_file.exists()
        assert not player_file.exists()

    def test_cleanup_preserves_files_and_settings_referenced_by_other_media(
        self,
        db: Session,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        admin = _admin_user(db)
        col = _create_collection(db, admin.user_id, "shared_ref")

        shared_setting = AudioSetting(sampling_rate_hz=48000, duration_s=3.0)
        db.add(shared_setting)
        db.flush()

        m1 = Media(
            media_type="audio",
            directory=11,
            filename="dup.flac",
            storage_collection_id=col.collection_id,
            uploader_id=admin.user_id,
            creator_id=admin.user_id,
            audio_setting_id=shared_setting.audio_setting_id,
        )
        m2 = Media(
            media_type="audio",
            directory=11,
            filename="dup.flac",
            storage_collection_id=col.collection_id,
            uploader_id=admin.user_id,
            creator_id=admin.user_id,
            audio_setting_id=shared_setting.audio_setting_id,
        )
        db.add(m1)
        db.add(m2)
        db.flush()
        db.add(MediaCollection(media_id=m1.media_id, collection_id=col.collection_id, added_by=admin.user_id))
        db.add(MediaCollection(media_id=m2.media_id, collection_id=col.collection_id, added_by=admin.user_id))
        p1 = Preview(media_id=m1.media_id, filename="dup_thumbnail.png", type="thumbnail")
        p2 = Preview(media_id=m2.media_id, filename="dup_thumbnail.png", type="thumbnail")
        db.add(p1)
        db.add(p2)
        db.commit()

        audio_file = _write_bytes(tmp_path / "sounds" / str(col.collection_id) / "11" / "dup.flac")
        thumb_file = _write_bytes(tmp_path / "sounds" / str(col.collection_id) / "11" / "dup_thumbnail.png")

        snapshot = media_storage_cleanup_service.build_media_cleanup_snapshot(
            m1, collection_ids=(col.collection_id,), previews=(p1,)
        )
        db.delete(m1)
        db.flush()
        media_storage_cleanup_service.delete_unreferenced_media_settings(
            db, audio_setting_ids=(shared_setting.audio_setting_id,)
        )
        db.commit()

        removed = media_storage_cleanup_service.cleanup_deleted_media_files(db, snapshot)

        assert removed == 0
        assert audio_file.exists()
        assert thumb_file.exists()
        assert db.get(AudioSetting, shared_setting.audio_setting_id) is not None

    def test_cleanup_ignores_path_traversal_and_symlinks(
        self,
        db: Session,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        media_dir = tmp_path / "media_root"
        media_dir.mkdir()
        outside_file = _write_bytes(tmp_path / "outside.flac", b"keep-me")
        monkeypatch.setattr(settings, "MEDIA_ROOT", str(media_dir))

        admin = _admin_user(db)
        col = _create_collection(db, admin.user_id, "symlink_guard")

        symlink_path = media_dir / "sounds" / str(col.collection_id) / "1" / "link.flac"
        symlink_path.parent.mkdir(parents=True, exist_ok=True)
        symlink_path.symlink_to(outside_file)

        snapshot_traversal = media_storage_cleanup_service.MediaCleanupSnapshot(
            media_id=999001,
            media_type="audio",
            directory=1,
            filename="../../outside.flac",
            storage_collection_id=col.collection_id,
            collection_ids=(col.collection_id,),
            previews=(("thumbnail", "../outside.flac"),),
            audio_setting_id=None,
            photo_setting_id=None,
        )
        snapshot_symlink = media_storage_cleanup_service.MediaCleanupSnapshot(
            media_id=999002,
            media_type="audio",
            directory=1,
            filename="link.flac",
            storage_collection_id=col.collection_id,
            collection_ids=(col.collection_id,),
            previews=(),
            audio_setting_id=None,
            photo_setting_id=None,
        )

        assert media_storage_cleanup_service.cleanup_deleted_media_files(db, snapshot_traversal) == 0
        assert media_storage_cleanup_service.cleanup_deleted_media_files(db, snapshot_symlink) == 0
        assert outside_file.exists()
        assert symlink_path.is_symlink()

    def test_remove_media_cache_skips_locked_bundle_and_cleans_unlocked(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        media_id = 88421
        unlocked_file = _write_bytes(
            tmp_path / "tmp" / "detail" / str(media_id) / "unlocked_bundle" / "zoomed.flac"
        )
        locked_file = _write_bytes(
            tmp_path / "tmp" / "detail" / str(media_id) / "locked_bundle" / "zoomed.flac"
        )

        with detail_cache_service.bundle_lock("locked_bundle", shared=True):
            result = detail_cache_service.remove_media_cache(media_id)

        assert result.deleted == 1
        assert result.skipped_locked == 1
        assert not unlocked_file.parent.exists()
        assert locked_file.exists()

    def test_cleanup_deleted_collection_removes_cross_bucket_exclusive_media(
        self,
        db: Session,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        admin = _admin_user(db)
        origin_col = _create_collection(db, admin.user_id, "origin_bucket")
        target_col = _create_collection(db, admin.user_id, "target_bucket")

        # Media originally stored in origin_col, later linked solely to target_col.
        photo_setting = PhotoSetting(exposure_ms=4.0, aperture=2.8, iso=100)
        db.add(photo_setting)
        db.flush()
        media = Media(
            media_type="photo",
            directory=5,
            filename="cross.png",
            storage_collection_id=origin_col.collection_id,
            uploader_id=admin.user_id,
            creator_id=admin.user_id,
            photo_setting_id=photo_setting.photo_setting_id,
        )
        db.add(media)
        db.commit()

        cross_file = _write_bytes(tmp_path / "images" / str(origin_col.collection_id) / "5" / "cross.png")
        orphan_in_target = _write_bytes(tmp_path / "sounds" / str(target_col.collection_id) / "9" / "stale.flac")
        export_zip = _write_bytes(tmp_path / "offline_exports" / "exp1" / "bundle.zip")

        snapshot = media_storage_cleanup_service.build_media_cleanup_snapshot(
            media, collection_ids=(target_col.collection_id,), previews=()
        )
        db.delete(media)
        db.commit()

        media_storage_cleanup_service.cleanup_deleted_collection_storage(
            db,
            target_col.collection_id,
            [snapshot],
            export_paths=["offline_exports/exp1/bundle.zip"],
        )

        assert not cross_file.exists()
        assert not orphan_in_target.exists()
        assert not (tmp_path / "sounds" / str(target_col.collection_id)).exists()
        assert not export_zip.exists()

    def test_cleanup_photo_fallback_thumbnail_without_directory_or_storage_bucket(
        self,
        db: Session,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        admin = _admin_user(db)
        col = _create_collection(db, admin.user_id, "nodir_photo")

        photo_file = _write_bytes(tmp_path / "images" / str(col.collection_id) / "root_snap.jpg")
        thumb_file = _write_bytes(tmp_path / "images" / str(col.collection_id) / "root_snap_thumbnail.png")

        snapshot = media_storage_cleanup_service.MediaCleanupSnapshot(
            media_id=777001,
            media_type="photo",
            directory=None,
            filename="root_snap.jpg",
            storage_collection_id=None,
            collection_ids=(col.collection_id,),
            previews=(),
            audio_setting_id=None,
            photo_setting_id=None,
        )
        removed = media_storage_cleanup_service.cleanup_deleted_media_files(db, snapshot)
        assert removed == 2
        assert not photo_file.exists()
        assert not thumb_file.exists()
        assert not (tmp_path / "images" / str(col.collection_id)).exists()

        # Metadata-only snapshot with empty filename and bad preview name is a safe no-op.
        meta_snapshot = media_storage_cleanup_service.MediaCleanupSnapshot(
            media_id=777002,
            media_type="audio",
            directory=None,
            filename="..",
            storage_collection_id=col.collection_id,
            collection_ids=(col.collection_id,),
            previews=(("thumbnail", "."),),
            audio_setting_id=None,
            photo_setting_id=None,
        )
        assert media_storage_cleanup_service.cleanup_deleted_media_files(db, meta_snapshot) == 0

    def test_cleanup_oserror_resilience(
        self,
        db: Session,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "MEDIA_ROOT", str(tmp_path))
        admin = _admin_user(db)
        col = _create_collection(db, admin.user_id, "oserror_resilience")
        target = _write_bytes(tmp_path / "sounds" / str(col.collection_id) / "1" / "err.flac")

        orig_unlink = Path.unlink

        def _failing_unlink(self: Path, *args, **kwargs):
            if self == target:
                raise OSError("simulated permission denied")
            return orig_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", _failing_unlink)
        snapshot = media_storage_cleanup_service.MediaCleanupSnapshot(
            media_id=777003,
            media_type="audio",
            directory=1,
            filename="err.flac",
            storage_collection_id=col.collection_id,
            collection_ids=(col.collection_id,),
            previews=(),
            audio_setting_id=None,
            photo_setting_id=None,
        )
        assert media_storage_cleanup_service.cleanup_deleted_media_files(db, snapshot) == 0
        assert target.exists()

        monkeypatch.setattr(
            "app.services.media_storage_cleanup_service.collection_bundle_export_service.remove_artifact_path",
            lambda _path: (_ for _ in ()).throw(OSError("simulated export unlink error")),
        )
        monkeypatch.setattr(
            "app.services.media_storage_cleanup_service.shutil.rmtree",
            lambda _path: (_ for _ in ()).throw(OSError("simulated rmtree error")),
        )
        media_storage_cleanup_service.cleanup_deleted_collection_storage(
            db,
            col.collection_id,
            [],
            export_paths=["offline_exports/fake/bundle.zip"],
        )
