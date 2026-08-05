import hashlib
import json
import stat
import uuid
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from PIL import Image
from sqlmodel import Session, select

from app.core.config import settings
from app.enums import QueueStatus
from app.models import (
    Annotation,
    AnnotationReview,
    AnnotationReviewStatus,
    AudioSetting,
    Collection,
    FileUpload,
    Label,
    LabelMedia,
    Media,
    MediaCollection,
    PhotoSetting,
    Project,
    ProjectCollection,
    Queue,
    Site,
    SiteCollection,
    SoundClassification,
    User,
)
from app.schemas.data_import import DataImportSummary
from app.services import offline_bundle_service


def _write_media_file(collection_id: int, directory: int, filename: str, content: bytes) -> None:
    target = Path(settings.MEDIA_ROOT) / "sounds" / str(collection_id) / str(directory)
    target.mkdir(parents=True, exist_ok=True)
    (target / filename).write_bytes(content)


def _seed_exportable_collection(db: Session) -> Collection:
    sound = SoundClassification(soundscape_component="Biophony", sound_type="Bird")
    review_status = AnnotationReviewStatus(name="approved")
    collection = Collection(name=f"Offline {uuid.uuid4().hex[:6]}", creator_id=1)
    site = Site(name=f"Site {uuid.uuid4().hex[:6]}", creator_id=1, longitude=1.2, latitude=3.4)
    db.add(sound)
    db.add(review_status)
    db.add(collection)
    db.add(site)
    db.flush()
    db.add(SiteCollection(site_id=site.site_id, collection_id=collection.collection_id))

    content = b"offline-bundle-audio"
    _write_media_file(collection.collection_id, 7, "clip.wav", content)
    audio_setting = AudioSetting(sampling_rate_hz=48000, duration_s=2.5, channel_num=1)
    db.add(audio_setting)
    db.flush()
    media = Media(
        media_type="audio",
        directory=7,
        filename="clip.wav",
        name="clip.wav",
        size_b=len(content),
        md5_hash=hashlib.md5(content).hexdigest(),
        uploader_id=1,
        creator_id=1,
        site_id=site.site_id,
        audio_setting_id=audio_setting.audio_setting_id,
    )
    db.add(media)
    db.flush()
    db.add(MediaCollection(media_id=media.media_id, collection_id=collection.collection_id, added_by=1))

    annotation = Annotation(
        media_id=media.media_id,
        creator_id=1,
        sound_id=sound.sound_id,
        min_x=0.0,
        max_x=1.0,
        min_y=0.0,
        max_y=1000.0,
        reference=False,
    )
    db.add(annotation)
    db.flush()
    db.add(
        AnnotationReview(
            annotation_id=annotation.annotation_id,
            reviewer_id=1,
            annotation_review_status_id=review_status.annotation_review_status_id,
            note="looks good",
        )
    )
    label = Label(name="checked", creator_id=1)
    db.add(label)
    db.flush()
    db.add(LabelMedia(media_id=media.media_id, user_id=1, label_id=label.label_id))
    db.commit()
    db.refresh(collection)
    return collection


def _build_bundle_bytes(
    *,
    sound_id: int,
    review_status_name: str,
    collection_uuid: str | None = None,
    sensor_id: int | None = None,
    license_id: int | None = None,
    label_assignments: list[tuple[int, str]] | None = None,
) -> bytes:
    collection_uuid = collection_uuid or str(uuid.uuid4())
    site_uuid = str(uuid.uuid4())
    media_uuid = str(uuid.uuid4())
    annotation_uuid = str(uuid.uuid4())
    media_bytes = b"field-audio"
    media_md5 = hashlib.md5(media_bytes).hexdigest()
    media_sha256 = hashlib.sha256(media_bytes).hexdigest()
    media_bundle_path = f"media/sounds/{media_uuid}/clip.wav"
    labels = [
        {"media_uuid": media_uuid, "user_id": user_id, "label_name": label_name}
        for user_id, label_name in (label_assignments or [(1, "checked")])
    ]

    files = {
        "data/collection.json": json.dumps(
            {
                "uuid": collection_uuid,
                "name": "Imported Collection",
                "public_access": False,
                "public_tags": False,
            },
            separators=(",", ":"),
        ).encode("utf-8"),
        "data/sites.json": json.dumps(
            [{"uuid": site_uuid, "name": "Imported Site", "longitude": 12.3, "latitude": 45.6}],
            separators=(",", ":"),
        ).encode("utf-8"),
        "data/media.json": json.dumps(
            [
                {
                    "uuid": media_uuid,
                    "media_type": "audio",
                    "is_metadata": False,
                    "directory": 7,
                    "filename": "clip.wav",
                    "name": "clip.wav",
                    "size_b": len(media_bytes),
                    "md5_hash": media_md5,
                    "uploader_id": 1,
                    "creator_id": 1,
                    "site_uuid": site_uuid,
                    "sensor_id": sensor_id,
                    "license_id": license_id,
                    "audio_setting": {
                        "sampling_rate_hz": 44100,
                        "duration_s": 1.5,
                        "channel_num": 1,
                    },
                    "bundle_path": media_bundle_path,
                    "bundle_sha256": media_sha256,
                }
            ],
            separators=(",", ":"),
        ).encode("utf-8"),
        "data/annotations.json": json.dumps(
            [
                {
                    "uuid": annotation_uuid,
                    "media_uuid": media_uuid,
                    "sound_id": sound_id,
                    "creator_id": 1,
                    "min_x": 0.0,
                    "max_x": 1.0,
                    "min_y": 0.0,
                    "max_y": 1000.0,
                }
            ],
            separators=(",", ":"),
        ).encode("utf-8"),
        "data/reviews.json": json.dumps(
            [{"annotation_uuid": annotation_uuid, "reviewer_id": 1, "status_name": review_status_name, "note": "approved"}],
            separators=(",", ":"),
        ).encode("utf-8"),
        "data/labels.json": json.dumps(
            labels,
            separators=(",", ":"),
        ).encode("utf-8"),
        media_bundle_path: media_bytes,
    }
    checksums = {path: hashlib.sha256(content).hexdigest() for path, content in files.items()}
    manifest = {
        "schema": offline_bundle_service.BUNDLE_SCHEMA,
        "exported_at": "2026-05-17 12:00:00",
        "collection_id": 999,
        "collection_uuid": collection_uuid,
        "includes_media": True,
        "hash_algorithm": "sha256",
        "signature_algorithm": offline_bundle_service.SIGNATURE_ALGORITHM,
        "counts": {
            "sites": 1,
            "media": 1,
            "audio": 1,
            "photos": 0,
            "media_files": 1,
            "annotations": 1,
            "reviews": 1,
            "labels": len(labels),
        },
        "warnings": [],
    }
    signature = offline_bundle_service._compute_signature(manifest, checksums)

    stream = BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
        archive.writestr("checksums.json", json.dumps(checksums, separators=(",", ":")).encode("utf-8"))
        archive.writestr("manifest.json", json.dumps(manifest, separators=(",", ":")).encode("utf-8"))
        archive.writestr("manifest.sig", signature.encode("utf-8"))
    return stream.getvalue()


def _seed_import_context(db: Session) -> tuple[SoundClassification, AnnotationReviewStatus, Project, User]:
    sound = SoundClassification(soundscape_component="Biophony", sound_type="Bird")
    status = AnnotationReviewStatus(name=f"approved-{uuid.uuid4().hex[:6]}")
    project = Project(
        name=f"Project {uuid.uuid4().hex[:6]}",
        url=f"https://{uuid.uuid4().hex[:6]}.example",
        creator_id=1,
    )
    db.add(sound)
    db.add(status)
    db.add(project)
    db.commit()
    db.refresh(project)
    uploader = db.get(User, 1)
    assert uploader is not None
    return sound, status, project, uploader


def _import_bundle_bytes(
    db: Session,
    *,
    project: Project,
    uploader: User,
    bundle_bytes: bytes,
) -> DataImportSummary:
    batch_id = uuid.uuid4()
    relative_bundle_path = Path("tmp") / "pending" / str(uploader.user_id) / f"{batch_id}.zip"
    bundle_path = Path(settings.MEDIA_ROOT) / relative_bundle_path
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_bytes(bundle_bytes)
    file_upload = FileUpload(
        batch_id=batch_id,
        path=relative_bundle_path.as_posix(),
        filename="bundle.zip",
        name="bundle.zip",
        directory=1,
        uploader_id=uploader.user_id,
        status=1,
    )
    db.add(file_upload)
    db.commit()
    db.refresh(file_upload)
    return offline_bundle_service.import_collection_bundle_from_file_upload(
        db,
        project_id=project.project_id,
        file_upload=file_upload,
        uploader=uploader,
        batch_id=str(batch_id),
    )


def _create_user(db: Session, *, role_id: int) -> User:
    user = User(
        username=f"bundle-{uuid.uuid4().hex[:8]}",
        name="Bundle User",
        email=f"bundle-{uuid.uuid4().hex[:8]}@example.com",
        password="test-password",
        role_id=role_id,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _photo_bytes() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (8, 6), color=(20, 80, 140)).save(stream, format="PNG")
    return stream.getvalue()


def _build_media_only_bundle(
    media_specs: list[dict],
    *,
    collection_uuid: str | None = None,
) -> bytes:
    collection_uuid = collection_uuid or str(uuid.uuid4())
    files: dict[str, bytes] = {
        "data/collection.json": json.dumps(
            {
                "uuid": collection_uuid,
                "name": "Media Bundle",
                "public_access": False,
                "public_tags": False,
            },
            separators=(",", ":"),
        ).encode(),
        "data/sites.json": b"[]",
        "data/annotations.json": b"[]",
        "data/reviews.json": b"[]",
        "data/labels.json": b"[]",
    }
    media_payload = []
    for spec in media_specs:
        media_uuid = str(spec.get("uuid") or uuid.uuid4())
        media_type = spec["media_type"]
        is_metadata = spec.get("is_metadata", False)
        filename = spec.get("filename")
        content = spec.get("content")
        if not is_metadata:
            assert filename is not None
            assert content is not None
            media_root_name = "sounds" if media_type == "audio" else "images"
            bundle_path = f"media/{media_root_name}/{media_uuid}/{filename}"
        else:
            bundle_path = None
        item = {
            "uuid": media_uuid,
            "media_type": media_type,
            "is_metadata": is_metadata,
            "directory": None if is_metadata else spec.get("directory", 5),
            "filename": filename,
            "name": spec.get("name", filename or f"metadata-{media_uuid}"),
            "size_b": None if is_metadata else len(content),
            "md5_hash": None if is_metadata else hashlib.md5(content).hexdigest(),
            "uploader_id": 1,
            "creator_id": 1,
            "audio_setting": (
                {"sampling_rate_hz": 44100, "duration_s": 1.0, "channel_num": 1}
                if media_type == "audio"
                else None
            ),
            "photo_setting": (
                {"exposure_ms": 5.0, "aperture": 2.8, "iso": 100}
                if media_type == "photo"
                else None
            ),
            "bundle_path": bundle_path,
            "bundle_sha256": None if is_metadata else hashlib.sha256(content).hexdigest(),
        }
        media_payload.append(item)
        if bundle_path is not None:
            files[bundle_path] = content
    files["data/media.json"] = json.dumps(media_payload, separators=(",", ":")).encode()

    checksums = {path: hashlib.sha256(content).hexdigest() for path, content in files.items()}
    audio_count = sum(spec["media_type"] == "audio" for spec in media_specs)
    photo_count = sum(spec["media_type"] == "photo" for spec in media_specs)
    manifest = {
        "schema": offline_bundle_service.BUNDLE_SCHEMA,
        "exported_at": "2026-07-23 12:00:00",
        "collection_id": 999,
        "collection_uuid": collection_uuid,
        "includes_media": True,
        "hash_algorithm": "sha256",
        "signature_algorithm": offline_bundle_service.SIGNATURE_ALGORITHM,
        "counts": {
            "sites": 0,
            "media": len(media_specs),
            "audio": audio_count,
            "photos": photo_count,
            "media_files": sum(not spec.get("is_metadata", False) for spec in media_specs),
            "annotations": 0,
            "reviews": 0,
            "labels": 0,
        },
        "warnings": [],
    }
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
        archive.writestr("checksums.json", json.dumps(checksums, separators=(",", ":")))
        archive.writestr("manifest.json", json.dumps(manifest, separators=(",", ":")))
        archive.writestr(
            "manifest.sig",
            offline_bundle_service._compute_signature(manifest, checksums),
        )
    return stream.getvalue()


def _create_import_upload(
    db: Session,
    *,
    uploader: User,
    filename: str,
    content: bytes,
) -> FileUpload:
    relative_path = Path("tmp") / "pending" / str(uploader.user_id) / filename
    bundle_path = Path(settings.MEDIA_ROOT) / relative_path
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_bytes(content)
    upload = FileUpload(
        batch_id=uuid.uuid4(),
        path=relative_path.as_posix(),
        filename=filename,
        name=filename,
        directory=1,
        uploader_id=uploader.user_id,
        status=1,
    )
    db.add(upload)
    db.commit()
    db.refresh(upload)
    return upload


def _rewrite_bundle(
    content: bytes,
    *,
    manifest_update=None,
    checksums_update=None,
) -> bytes:
    with zipfile.ZipFile(BytesIO(content)) as source:
        files = {
            name: source.read(name)
            for name in source.namelist()
            if name not in {"manifest.json", "checksums.json", "manifest.sig"}
        }
        manifest = json.loads(source.read("manifest.json"))
        checksums = json.loads(source.read("checksums.json"))
    if manifest_update:
        manifest_update(manifest)
    if checksums_update:
        checksums_update(checksums)
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
        archive.writestr("manifest.json", json.dumps(manifest, separators=(",", ":")))
        archive.writestr("checksums.json", json.dumps(checksums, separators=(",", ":")))
        archive.writestr(
            "manifest.sig",
            offline_bundle_service._compute_signature(manifest, checksums),
        )
    return stream.getvalue()


def test_export_collection_bundle_missing_collection(db: Session) -> None:
    with pytest.raises(HTTPException) as exc_info:
        offline_bundle_service.export_collection_bundle(
            db,
            999999,
            output_path=Path("/tmp/missing-collection.zip"),
        )
    assert exc_info.value.status_code == 404


def test_verify_bundle_rejects_suspicious_compression_ratio(tmp_path: Path) -> None:
    path = tmp_path / "ratio.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("large.txt", b"0" * 1024 * 1024)

    with zipfile.ZipFile(path) as archive, pytest.raises(HTTPException, match="compression ratio"):
        offline_bundle_service._verify_bundle(archive)


def test_verify_bundle_rejects_symbolic_link(tmp_path: Path) -> None:
    path = tmp_path / "symlink.zip"
    info = zipfile.ZipInfo("link")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(info, "target")

    with zipfile.ZipFile(path) as archive, pytest.raises(HTTPException, match="Symbolic link"):
        offline_bundle_service._verify_bundle(archive)


def test_verify_bundle_rejects_duplicate_members(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", b"{}")
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr("manifest.json", b"{}")

    with zipfile.ZipFile(path) as archive, pytest.raises(HTTPException, match="duplicate"):
        offline_bundle_service._verify_bundle(archive)


def test_verify_bundle_rejects_unsupported_schema(tmp_path: Path) -> None:
    content = _rewrite_bundle(
        _build_media_only_bundle(
            [{"media_type": "photo", "filename": "image.png", "content": _photo_bytes()}]
        ),
        manifest_update=lambda manifest: manifest.update(schema="unsupported-bundle"),
    )
    path = tmp_path / "old-schema.zip"
    path.write_bytes(content)

    with zipfile.ZipFile(path) as archive, pytest.raises(HTTPException, match="manifest"):
        offline_bundle_service._verify_bundle(archive)


def test_verify_bundle_rejects_incomplete_checksum_coverage(tmp_path: Path) -> None:
    content = _rewrite_bundle(
        _build_media_only_bundle(
            [{"media_type": "photo", "filename": "image.png", "content": _photo_bytes()}]
        ),
        checksums_update=lambda checksums: checksums.pop("data/media.json"),
    )
    path = tmp_path / "checksums.zip"
    path.write_bytes(content)

    with zipfile.ZipFile(path) as archive, pytest.raises(HTTPException, match="checksum list"):
        offline_bundle_service._verify_bundle(archive)


def test_bundle_json_helpers_reject_invalid_inputs(tmp_path: Path) -> None:
    assert offline_bundle_service._json_default(uuid.uuid4())
    with pytest.raises(TypeError):
        offline_bundle_service._json_default(object())
    with pytest.raises(HTTPException, match="Unsafe bundle path"):
        offline_bundle_service._safe_bundle_member("../outside")
    assert offline_bundle_service._is_uuid("not-a-uuid") is False

    with pytest.raises(HTTPException, match="unsupported type"):
        offline_bundle_service._resolve_media_source(
            MagicMock(),
            Media(media_type="video", uploader_id=1, creator_id=1),
        )
    with pytest.raises(HTTPException, match="no storage path"):
        offline_bundle_service._resolve_media_source(
            MagicMock(),
            Media(media_type="audio", uploader_id=1, creator_id=1),
        )

    missing = tmp_path / "missing.json"
    with pytest.raises(HTTPException, match="Missing required"):
        offline_bundle_service._load_json_file(missing)
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{")
    with pytest.raises(HTTPException, match="Invalid JSON"):
        offline_bundle_service._load_json_file(invalid)

    archive_path = tmp_path / "json.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("invalid.json", b"{")
    with zipfile.ZipFile(archive_path) as archive:
        with pytest.raises(HTTPException, match="Missing required"):
            offline_bundle_service._load_json(archive, "missing.json")
        with pytest.raises(HTTPException, match="Invalid JSON"):
            offline_bundle_service._load_json(archive, "invalid.json")
        with pytest.raises(HTTPException, match="Missing bundle payload"):
            offline_bundle_service._hash_archive_member(archive, "missing.bin")


def test_verify_bundle_rejects_missing_signature_and_bad_integrity(tmp_path: Path) -> None:
    content = _build_media_only_bundle(
        [{"media_type": "photo", "filename": "image.png", "content": _photo_bytes()}]
    )
    with zipfile.ZipFile(BytesIO(content)) as source:
        members = {
            name: source.read(name)
            for name in source.namelist()
            if name != "manifest.sig"
        }
    missing_signature = tmp_path / "missing-signature.zip"
    with zipfile.ZipFile(missing_signature, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    with zipfile.ZipFile(missing_signature) as archive, pytest.raises(
        HTTPException, match="manifest.sig"
    ):
        offline_bundle_service._verify_bundle(archive)

    bad_signature = tmp_path / "bad-signature.zip"
    with zipfile.ZipFile(BytesIO(content)) as source, zipfile.ZipFile(bad_signature, "w") as archive:
        for name in source.namelist():
            archive.writestr(name, b"0" * 64 if name == "manifest.sig" else source.read(name))
    with zipfile.ZipFile(bad_signature) as archive, pytest.raises(
        HTTPException, match="signature verification"
    ):
        offline_bundle_service._verify_bundle(archive)

    bad_checksum = tmp_path / "bad-checksum.zip"
    with zipfile.ZipFile(BytesIO(content)) as source, zipfile.ZipFile(bad_checksum, "w") as archive:
        for name in source.namelist():
            payload = source.read(name)
            if name.startswith("media/"):
                payload += b"changed"
            archive.writestr(name, payload)
    with zipfile.ZipFile(bad_checksum) as archive, pytest.raises(
        HTTPException, match="Checksum mismatch"
    ):
        offline_bundle_service._verify_bundle(archive)


def test_verify_bundle_rejects_unsafe_member_and_invalid_checksums(
    tmp_path: Path,
) -> None:
    unsafe = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("scripts/run.sh", b"echo")
    with zipfile.ZipFile(unsafe) as archive, pytest.raises(HTTPException, match="unsafe_archive"):
        offline_bundle_service._verify_bundle(archive)

    content = _rewrite_bundle(
        _build_media_only_bundle(
            [{"media_type": "photo", "filename": "image.png", "content": _photo_bytes()}]
        ),
        checksums_update=lambda checksums: checksums.update({"data/media.json": "bad"}),
    )
    invalid = tmp_path / "invalid-checksums.zip"
    invalid.write_bytes(content)
    with zipfile.ZipFile(invalid) as archive, pytest.raises(
        HTTPException, match="Invalid offline bundle checksums"
    ):
        offline_bundle_service._verify_bundle(archive)


def test_validate_bundle_payloads_rejects_manifest_and_media_mismatches() -> None:
    content = _build_media_only_bundle(
        [{"media_type": "photo", "filename": "image.png", "content": _photo_bytes()}]
    )
    with zipfile.ZipFile(BytesIO(content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        checksums = json.loads(archive.read("checksums.json"))
        collection = json.loads(archive.read("data/collection.json"))
        media = json.loads(archive.read("data/media.json"))

    arguments = {
        "manifest": manifest,
        "checksums": checksums,
        "collection_payload": collection,
        "sites_payload": [],
        "media_payload": media,
        "annotations_payload": [],
        "reviews_payload": [],
        "labels_payload": [],
    }
    with pytest.raises(HTTPException, match="Collection UUID"):
        offline_bundle_service._validate_bundle_payloads(
            **{**arguments, "collection_payload": {**collection, "uuid": str(uuid.uuid4())}}
        )
    with pytest.raises(HTTPException, match="item counts"):
        offline_bundle_service._validate_bundle_payloads(
            **{**arguments, "manifest": {**manifest, "counts": {**manifest["counts"], "photos": 2}}}
        )
    with pytest.raises(HTTPException, match="media files"):
        offline_bundle_service._validate_bundle_payloads(
            **{
                **arguments,
                "checksums": {
                    **checksums,
                    f"media/images/{uuid.uuid4()}/extra.png": "0" * 64,
                },
            }
        )
    with pytest.raises(HTTPException, match="Media checksum"):
        offline_bundle_service._validate_bundle_payloads(
            **{
                **arguments,
                "media_payload": [{**media[0], "bundle_sha256": "0" * 64}],
            }
        )
    with pytest.raises(HTTPException, match="Invalid offline bundle data"):
        offline_bundle_service._validate_bundle_payloads(
            **{
                **arguments,
                "media_payload": [{**media[0], "media_type": "video"}],
            }
        )


def test_extract_archive_requires_reserved_disk_space(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "bundle.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("file.txt", b"content")
    disk_usage = type("DiskUsage", (), {"free": offline_bundle_service._MIN_FREE_SPACE_AFTER_EXTRACT})
    monkeypatch.setattr(offline_bundle_service.shutil, "disk_usage", lambda _path: disk_usage)

    with zipfile.ZipFile(path) as archive, pytest.raises(HTTPException) as exc_info:
        offline_bundle_service._extract_archive(archive, tmp_path)

    assert exc_info.value.status_code == 507


def test_export_collection_bundle_includes_media(tmp_path: Path, db: Session) -> None:
    collection = _seed_exportable_collection(db)
    output_path = tmp_path / f"collection-{collection.collection_id}-export.zip"

    result = offline_bundle_service.export_collection_bundle(
        db,
        collection.collection_id,
        output_path=output_path,
    )

    assert Path(result["output_path"]) == output_path
    assert output_path.exists()

    with zipfile.ZipFile(output_path) as archive:
        names = set(archive.namelist())
        assert "manifest.json" in names
        assert "checksums.json" in names
        assert "manifest.sig" in names
        assert "data/collection.json" in names
        assert "data/sites.json" in names
        assert "data/media.json" in names
        assert "data/annotations.json" in names
        assert "data/reviews.json" in names
        assert "data/labels.json" in names
        assert any(name.startswith("media/") for name in names)
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["includes_media"] is True


def test_export_collection_bundle_includes_public_and_private_label_assignments(tmp_path: Path, db: Session) -> None:
    collection = _seed_exportable_collection(db)
    media = db.exec(
        select(Media)
        .join(MediaCollection, MediaCollection.media_id == Media.media_id)
        .where(MediaCollection.collection_id == collection.collection_id)
    ).one()
    public_label = Label(name=f"Public {uuid.uuid4().hex[:6]}", creator_id=1, type="public")
    db.add(public_label)
    db.flush()
    db.add(LabelMedia(media_id=media.media_id, user_id=1, label_id=public_label.label_id))
    db.commit()

    output_path = tmp_path / f"collection-{collection.collection_id}-export.zip"
    offline_bundle_service.export_collection_bundle(
        db,
        collection.collection_id,
        output_path=output_path,
    )

    with zipfile.ZipFile(output_path) as archive:
        labels = json.loads(archive.read("data/labels.json"))

    assert labels == [
        {"media_uuid": str(media.uuid), "user_id": 1, "label_name": "checked"},
        {"media_uuid": str(media.uuid), "user_id": 1, "label_name": public_label.name},
    ]


def test_import_collection_bundle_reuses_public_label_for_existing_association_user(db: Session) -> None:
    sound, status, project, uploader = _seed_import_context(db)
    original_user = _create_user(db, role_id=uploader.role_id)
    public_label = Label(name=f"Shared {uuid.uuid4().hex[:6]}", creator_id=uploader.user_id, type="public")
    db.add(public_label)
    db.commit()

    result = _import_bundle_bytes(
        db,
        project=project,
        uploader=uploader,
        bundle_bytes=_build_bundle_bytes(
            sound_id=sound.sound_id,
            review_status_name=status.name,
            label_assignments=[(original_user.user_id, public_label.name.lower())],
        ),
    )

    link = db.exec(select(LabelMedia).where(LabelMedia.label_id == public_label.label_id)).one()
    assert result.created_counts.labels == 0
    assert link.user_id == original_user.user_id


def test_import_collection_bundle_reuses_private_label_for_existing_association_user(db: Session) -> None:
    sound, status, project, uploader = _seed_import_context(db)
    original_user = _create_user(db, role_id=uploader.role_id)
    private_label = Label(name=f"Private {uuid.uuid4().hex[:6]}", creator_id=original_user.user_id)
    db.add(private_label)
    db.commit()

    result = _import_bundle_bytes(
        db,
        project=project,
        uploader=uploader,
        bundle_bytes=_build_bundle_bytes(
            sound_id=sound.sound_id,
            review_status_name=status.name,
            label_assignments=[(original_user.user_id, private_label.name.upper())],
        ),
    )

    link = db.exec(select(LabelMedia).where(LabelMedia.label_id == private_label.label_id)).one()
    assert result.created_counts.labels == 0
    assert link.user_id == original_user.user_id


def test_import_collection_bundle_creates_private_label_for_existing_association_user(db: Session) -> None:
    sound, status, project, uploader = _seed_import_context(db)
    original_user = _create_user(db, role_id=uploader.role_id)
    label_name = f"Created {uuid.uuid4().hex[:6]}"

    _import_bundle_bytes(
        db,
        project=project,
        uploader=uploader,
        bundle_bytes=_build_bundle_bytes(
            sound_id=sound.sound_id,
            review_status_name=status.name,
            label_assignments=[(original_user.user_id, label_name)],
        ),
    )

    label = db.exec(select(Label).where(Label.name == label_name)).one()
    link = db.exec(select(LabelMedia).where(LabelMedia.label_id == label.label_id)).one()
    assert label.creator_id == original_user.user_id
    assert label.type == "private"
    assert link.user_id == original_user.user_id


def test_import_collection_bundle_falls_back_to_current_user_and_is_idempotent(db: Session) -> None:
    sound, status, project, uploader = _seed_import_context(db)
    label_name = f"Fallback {uuid.uuid4().hex[:6]}"
    bundle_bytes = _build_bundle_bytes(
        sound_id=sound.sound_id,
        review_status_name=status.name,
        label_assignments=[(999_999_999, label_name)],
    )

    first_result = _import_bundle_bytes(
        db,
        project=project,
        uploader=uploader,
        bundle_bytes=bundle_bytes,
    )
    second_result = _import_bundle_bytes(
        db,
        project=project,
        uploader=uploader,
        bundle_bytes=bundle_bytes,
    )

    label = db.exec(select(Label).where(Label.name == label_name)).one()
    links = db.exec(select(LabelMedia).where(LabelMedia.label_id == label.label_id)).all()
    assert first_result.created_counts.labels == 1
    assert label.creator_id == uploader.user_id
    assert len(links) == 1
    assert links[0].user_id == uploader.user_id
    assert second_result.created_counts.labels == 0
    assert second_result.created_counts.label_links == 0
    assert second_result.skipped_counts.label_links == 1


def test_import_collection_bundle_from_file_upload_creates_records_and_deletes_zip(db: Session) -> None:
    sound = SoundClassification(soundscape_component="Biophony", sound_type="Bird")
    status = AnnotationReviewStatus(name="approved")
    project = Project(name=f"Project {uuid.uuid4().hex[:6]}", url=f"https://{uuid.uuid4().hex[:6]}.example", creator_id=1)
    db.add(sound)
    db.add(status)
    db.add(project)
    db.commit()
    db.refresh(project)

    uploader = db.get(User, 1)
    assert uploader is not None

    relative_bundle_path = Path("tmp") / "pending" / str(uploader.user_id) / "bundle.zip"
    bundle_path = Path(settings.MEDIA_ROOT) / relative_bundle_path
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_bytes(_build_bundle_bytes(sound_id=sound.sound_id, review_status_name=status.name))

    file_upload = FileUpload(
        batch_id=uuid.uuid4(),
        path=relative_bundle_path.as_posix(),
        filename="bundle.zip",
        name="bundle.zip",
        directory=1,
        uploader_id=uploader.user_id,
        status=1,
    )
    db.add(file_upload)
    db.commit()
    db.refresh(file_upload)

    result = offline_bundle_service.import_collection_bundle_from_file_upload(
        db,
        project_id=project.project_id,
        file_upload=file_upload,
        uploader=uploader,
        batch_id=str(file_upload.batch_id),
    )

    assert result.project_id == project.project_id
    assert result.created_counts.collections == 1
    assert result.created_counts.project_links == 1
    assert result.created_counts.media == 1
    assert result.created_counts.annotations == 1
    assert result.created_counts.reviews == 1
    assert result.created_counts.label_links == 1
    assert not bundle_path.exists()
    collection = db.get(Collection, result.collection_id)
    assert collection is not None
    assert db.exec(
        select(ProjectCollection).where(
            ProjectCollection.project_id == project.project_id,
            ProjectCollection.collection_id == collection.collection_id,
        )
    ).first() is not None


def test_import_collection_bundle_completes_queue_atomically(db: Session) -> None:
    sound = SoundClassification(soundscape_component="Biophony", sound_type="Bird")
    status = AnnotationReviewStatus(name="approved")
    project = Project(
        name=f"Queued {uuid.uuid4().hex[:6]}",
        url=f"https://{uuid.uuid4().hex[:6]}.example",
        creator_id=1,
    )
    queue = Queue(
        type="offline_import",
        user_id=1,
        total=1,
        status=QueueStatus.RUNNING,
    )
    db.add(sound)
    db.add(status)
    db.add(project)
    db.add(queue)
    db.commit()
    uploader = db.get(User, 1)
    assert uploader is not None
    upload = _create_import_upload(
        db,
        uploader=uploader,
        filename="queued-import.zip",
        content=_build_bundle_bytes(
            sound_id=sound.sound_id,
            review_status_name=status.name,
        ),
    )

    result = offline_bundle_service.import_collection_bundle_from_file_upload(
        db,
        project_id=project.project_id,
        file_upload=upload,
        uploader=uploader,
        batch_id=str(upload.batch_id),
        queue_id=queue.queue_id,
    )

    db.refresh(queue)
    db.refresh(upload)
    assert result.created_counts.media == 1
    assert queue.status == QueueStatus.COMPLETED
    assert queue.completed == 1
    assert upload.status == 3
    assert upload.path == ""


def test_import_collection_bundle_reuses_existing_collection_and_links_project(db: Session) -> None:
    sound = SoundClassification(soundscape_component="Biophony", sound_type="Bird")
    status = AnnotationReviewStatus(name="approved")
    project = Project(name=f"Project {uuid.uuid4().hex[:6]}", url=f"https://{uuid.uuid4().hex[:6]}.example", creator_id=1)
    existing_collection = Collection(name=f"Existing {uuid.uuid4().hex[:6]}", creator_id=1)
    db.add(sound)
    db.add(status)
    db.add(project)
    db.add(existing_collection)
    db.commit()
    db.refresh(project)
    db.refresh(existing_collection)

    uploader = db.get(User, 1)
    assert uploader is not None

    relative_bundle_path = Path("tmp") / "pending" / str(uploader.user_id) / "bundle-reuse.zip"
    bundle_path = Path(settings.MEDIA_ROOT) / relative_bundle_path
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_bytes(
        _build_bundle_bytes(
            sound_id=sound.sound_id,
            review_status_name=status.name,
            collection_uuid=str(existing_collection.uuid),
        )
    )

    file_upload = FileUpload(
        batch_id=uuid.uuid4(),
        path=relative_bundle_path.as_posix(),
        filename="bundle-reuse.zip",
        name="bundle-reuse.zip",
        directory=1,
        uploader_id=uploader.user_id,
        status=1,
    )
    db.add(file_upload)
    db.commit()
    db.refresh(file_upload)

    result = offline_bundle_service.import_collection_bundle_from_file_upload(
        db,
        project_id=project.project_id,
        file_upload=file_upload,
        uploader=uploader,
        batch_id=str(file_upload.batch_id),
    )

    assert result.collection_id == existing_collection.collection_id
    assert result.created_counts.collections == 0
    assert result.skipped_counts.collections == 1
    assert result.created_counts.project_links == 1
    assert db.exec(
        select(ProjectCollection).where(
            ProjectCollection.project_id == project.project_id,
            ProjectCollection.collection_id == existing_collection.collection_id,
        )
    ).first() is not None


def test_import_collection_bundle_nulls_missing_sensor_and_license_with_warnings(db: Session) -> None:
    sound = SoundClassification(soundscape_component="Biophony", sound_type="Bird")
    status = AnnotationReviewStatus(name="approved")
    project = Project(name=f"Project {uuid.uuid4().hex[:6]}", url=f"https://{uuid.uuid4().hex[:6]}.example", creator_id=1)
    db.add(sound)
    db.add(status)
    db.add(project)
    db.commit()
    db.refresh(project)

    uploader = db.get(User, 1)
    assert uploader is not None

    relative_bundle_path = Path("tmp") / "pending" / str(uploader.user_id) / "bundle-missing-fks.zip"
    bundle_path = Path(settings.MEDIA_ROOT) / relative_bundle_path
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_bytes(
        _build_bundle_bytes(
            sound_id=sound.sound_id,
            review_status_name=status.name,
            sensor_id=999999,
            license_id=999998,
        )
    )

    file_upload = FileUpload(
        batch_id=uuid.uuid4(),
        path=relative_bundle_path.as_posix(),
        filename="bundle-missing-fks.zip",
        name="bundle-missing-fks.zip",
        directory=1,
        uploader_id=uploader.user_id,
        status=1,
    )
    db.add(file_upload)
    db.commit()
    db.refresh(file_upload)

    result = offline_bundle_service.import_collection_bundle_from_file_upload(
        db,
        project_id=project.project_id,
        file_upload=file_upload,
        uploader=uploader,
        batch_id=str(file_upload.batch_id),
    )

    media = db.exec(
        select(Media)
        .join(MediaCollection, MediaCollection.media_id == Media.media_id)
        .where(MediaCollection.collection_id == result.collection_id)
    ).first()
    assert media is not None
    assert media.sensor_id is None
    assert media.license_id is None
    assert result.created_counts.media == 1
    media_warnings = [warning for warning in result.warnings if warning.resource_type == "media"]
    assert len(media_warnings) == 2
    assert any("sensor_id=999999" in warning.message for warning in result.warnings)
    assert any("license_id=999998" in warning.message for warning in result.warnings)


def test_import_collection_bundle_supports_mixed_audio_and_photos(db: Session) -> None:
    project = Project(
        name=f"Mixed {uuid.uuid4().hex[:6]}",
        url=f"https://{uuid.uuid4().hex[:6]}.example",
        creator_id=1,
    )
    db.add(project)
    db.commit()
    uploader = db.get(User, 1)
    assert uploader is not None
    upload = _create_import_upload(
        db,
        uploader=uploader,
        filename="mixed.zip",
        content=_build_media_only_bundle(
            [
                {"media_type": "audio", "filename": "same.wav", "content": b"audio"},
                {"media_type": "photo", "filename": "same.png", "content": _photo_bytes()},
            ]
        ),
    )

    result = offline_bundle_service.import_collection_bundle_from_file_upload(
        db,
        project_id=project.project_id,
        file_upload=upload,
        uploader=uploader,
        batch_id=str(upload.batch_id),
    )

    assert result.created_counts.media == 2
    assert result.created_counts.audio == 1
    assert result.created_counts.photos == 1
    assert result.created_counts.media_files == 2
    imported = db.exec(
        select(Media)
        .join(MediaCollection, MediaCollection.media_id == Media.media_id)
        .where(MediaCollection.collection_id == result.collection_id)
    ).all()
    assert {item.media_type for item in imported} == {"audio", "photo"}
    assert next(item for item in imported if item.media_type == "photo").photo_setting_id is not None


def test_import_collection_bundle_preserves_metadata_media_without_files(db: Session) -> None:
    project = Project(
        name=f"Metadata {uuid.uuid4().hex[:6]}",
        url=f"https://{uuid.uuid4().hex[:6]}.example",
        creator_id=1,
    )
    db.add(project)
    db.commit()
    uploader = db.get(User, 1)
    assert uploader is not None
    upload = _create_import_upload(
        db,
        uploader=uploader,
        filename="metadata.zip",
        content=_build_media_only_bundle(
            [
                {"media_type": "audio", "filename": "recording.wav", "content": b"audio"},
                {"media_type": "photo", "filename": "camera.png", "content": _photo_bytes()},
                {"media_type": "audio", "is_metadata": True, "name": "audio metadata"},
                {"media_type": "photo", "is_metadata": True, "name": "photo metadata"},
            ]
        ),
    )

    result = offline_bundle_service.import_collection_bundle_from_file_upload(
        db,
        project_id=project.project_id,
        file_upload=upload,
        uploader=uploader,
        batch_id=str(upload.batch_id),
    )

    assert result.created_counts.media == 4
    assert result.created_counts.media_files == 2
    metadata_media = db.exec(
        select(Media)
        .join(MediaCollection, MediaCollection.media_id == Media.media_id)
        .where(MediaCollection.collection_id == result.collection_id, Media.is_metadata.is_(True))
    ).all()
    assert {item.media_type for item in metadata_media} == {"audio", "photo"}
    assert all(item.directory is None and item.filename is None and item.size_b is None for item in metadata_media)


def test_import_collection_bundle_never_overwrites_existing_target(db: Session) -> None:
    project = Project(
        name=f"Collision {uuid.uuid4().hex[:6]}",
        url=f"https://{uuid.uuid4().hex[:6]}.example",
        creator_id=1,
    )
    collection = Collection(name="Collision target", creator_id=1)
    db.add(project)
    db.add(collection)
    db.commit()
    original = Path(settings.MEDIA_ROOT) / "images" / str(collection.collection_id) / "5" / "camera.png"
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_bytes(b"existing")
    media_uuid = uuid.uuid4()
    uploader = db.get(User, 1)
    assert uploader is not None
    upload = _create_import_upload(
        db,
        uploader=uploader,
        filename="collision.zip",
        content=_build_media_only_bundle(
            [
                {
                    "uuid": media_uuid,
                    "media_type": "photo",
                    "filename": "camera.png",
                    "content": _photo_bytes(),
                }
            ],
            collection_uuid=str(collection.uuid),
        ),
    )

    result = offline_bundle_service.import_collection_bundle_from_file_upload(
        db,
        project_id=project.project_id,
        file_upload=upload,
        uploader=uploader,
        batch_id=str(upload.batch_id),
    )

    media = db.exec(select(Media).where(Media.uuid == media_uuid)).one()
    assert original.read_bytes() == b"existing"
    assert media.filename == f"camera__{media_uuid}.png"
    assert (
        Path(settings.MEDIA_ROOT)
        / "images"
        / str(collection.collection_id)
        / "5"
        / media.filename
    ).is_file()
    assert result.created_counts.project_links == 1


def test_import_collection_bundle_same_hash_different_uuids_creates_distinct_media(
    db: Session,
) -> None:
    project = Project(
        name=f"Identity {uuid.uuid4().hex[:6]}",
        url=f"https://{uuid.uuid4().hex[:6]}.example",
        creator_id=1,
    )
    db.add(project)
    db.commit()
    uploader = db.get(User, 1)
    assert uploader is not None
    content = _photo_bytes()
    upload = _create_import_upload(
        db,
        uploader=uploader,
        filename="identity.zip",
        content=_build_media_only_bundle(
            [
                {"media_type": "photo", "filename": "camera.png", "content": content},
                {"media_type": "photo", "filename": "camera.png", "content": content},
            ]
        ),
    )

    result = offline_bundle_service.import_collection_bundle_from_file_upload(
        db,
        project_id=project.project_id,
        file_upload=upload,
        uploader=uploader,
        batch_id=str(upload.batch_id),
    )

    media = db.exec(
        select(Media)
        .join(MediaCollection, MediaCollection.media_id == Media.media_id)
        .where(MediaCollection.collection_id == result.collection_id)
    ).all()
    assert len(media) == 2
    assert len({item.uuid for item in media}) == 2
    assert len({item.md5_hash for item in media}) == 1
    assert len({item.filename for item in media}) == 2


def test_import_collection_bundle_reuses_matching_uuid_and_links_target_collection(
    db: Session,
) -> None:
    project = Project(
        name=f"Reuse {uuid.uuid4().hex[:6]}",
        url=f"https://{uuid.uuid4().hex[:6]}.example",
        creator_id=1,
    )
    source_collection = Collection(name="Reuse source", creator_id=1)
    target_collection = Collection(name="Reuse target", creator_id=1)
    db.add(project)
    db.add(source_collection)
    db.add(target_collection)
    db.flush()
    setting = PhotoSetting()
    db.add(setting)
    db.flush()
    content = _photo_bytes()
    media = Media(
        media_type="photo",
        directory=5,
        filename="reuse.png",
        name="reuse.png",
        size_b=len(content),
        md5_hash=hashlib.md5(content).hexdigest(),
        uploader_id=1,
        creator_id=1,
        photo_setting_id=setting.photo_setting_id,
    )
    db.add(media)
    db.flush()
    db.add(
        MediaCollection(
            media_id=media.media_id,
            collection_id=source_collection.collection_id,
            added_by=1,
        )
    )
    source = (
        Path(settings.MEDIA_ROOT)
        / "images"
        / str(source_collection.collection_id)
        / "5"
        / "reuse.png"
    )
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(content)
    db.commit()
    uploader = db.get(User, 1)
    assert uploader is not None
    upload = _create_import_upload(
        db,
        uploader=uploader,
        filename="reuse-media.zip",
        content=_build_media_only_bundle(
            [
                {
                    "uuid": media.uuid,
                    "media_type": "photo",
                    "filename": "reuse.png",
                    "content": content,
                }
            ],
            collection_uuid=str(target_collection.uuid),
        ),
    )

    result = offline_bundle_service.import_collection_bundle_from_file_upload(
        db,
        project_id=project.project_id,
        file_upload=upload,
        uploader=uploader,
        batch_id=str(upload.batch_id),
    )

    assert result.skipped_counts.media == 1
    assert result.created_counts.media_links == 1
    assert db.exec(
        select(MediaCollection).where(
            MediaCollection.media_id == media.media_id,
            MediaCollection.collection_id == target_collection.collection_id,
        )
    ).first() is not None


def test_import_collection_bundle_rejects_matching_uuid_with_different_content(
    db: Session,
) -> None:
    project = Project(
        name=f"UUID conflict {uuid.uuid4().hex[:6]}",
        url=f"https://{uuid.uuid4().hex[:6]}.example",
        creator_id=1,
    )
    source_collection = Collection(name="UUID source", creator_id=1)
    target_collection = Collection(name="UUID target", creator_id=1)
    db.add(project)
    db.add(source_collection)
    db.add(target_collection)
    db.flush()
    setting = PhotoSetting()
    db.add(setting)
    db.flush()
    media = Media(
        media_type="photo",
        directory=5,
        filename="uuid.png",
        name="uuid.png",
        size_b=3,
        md5_hash=hashlib.md5(b"old").hexdigest(),
        uploader_id=1,
        creator_id=1,
        photo_setting_id=setting.photo_setting_id,
    )
    db.add(media)
    db.flush()
    db.add(
        MediaCollection(
            media_id=media.media_id,
            collection_id=source_collection.collection_id,
            added_by=1,
        )
    )
    source = (
        Path(settings.MEDIA_ROOT)
        / "images"
        / str(source_collection.collection_id)
        / "5"
        / "uuid.png"
    )
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"old")
    db.commit()
    media_id = media.media_id
    target_collection_id = target_collection.collection_id
    uploader = db.get(User, 1)
    assert uploader is not None
    upload = _create_import_upload(
        db,
        uploader=uploader,
        filename="uuid-conflict.zip",
        content=_build_media_only_bundle(
            [
                {
                    "uuid": media.uuid,
                    "media_type": "photo",
                    "filename": "uuid.png",
                    "content": _photo_bytes(),
                }
            ],
            collection_uuid=str(target_collection.uuid),
        ),
    )

    with pytest.raises(HTTPException, match="different binary content"):
        offline_bundle_service.import_collection_bundle_from_file_upload(
            db,
            project_id=project.project_id,
            file_upload=upload,
            uploader=uploader,
            batch_id=str(upload.batch_id),
        )

    assert db.exec(
        select(MediaCollection).where(
            MediaCollection.media_id == media_id,
            MediaCollection.collection_id == target_collection_id,
        )
    ).first() is None


def test_import_collection_bundle_rolls_back_created_files_on_error(db: Session) -> None:
    project = Project(
        name=f"Rollback {uuid.uuid4().hex[:6]}",
        url=f"https://{uuid.uuid4().hex[:6]}.example",
        creator_id=1,
    )
    collection = Collection(name="Rollback target", creator_id=1)
    db.add(project)
    db.add(collection)
    db.commit()
    media_uuid = uuid.uuid4()
    uploader = db.get(User, 1)
    assert uploader is not None
    upload = _create_import_upload(
        db,
        uploader=uploader,
        filename="rollback.zip",
        content=_build_media_only_bundle(
            [
                {
                    "uuid": media_uuid,
                    "media_type": "photo",
                    "filename": "rollback.png",
                    "content": _photo_bytes(),
                }
            ],
            collection_uuid=str(collection.uuid),
        ),
    )
    target = (
        Path(settings.MEDIA_ROOT)
        / "images"
        / str(collection.collection_id)
        / "5"
        / "rollback.png"
    )

    with (
        patch(
            "app.services.offline_bundle_service.generate_media_previews",
            side_effect=RuntimeError("preview service unavailable"),
        ),
        pytest.raises(RuntimeError, match="preview service unavailable"),
    ):
        offline_bundle_service.import_collection_bundle_from_file_upload(
            db,
            project_id=project.project_id,
            file_upload=upload,
            uploader=uploader,
            batch_id=str(upload.batch_id),
        )

    assert not target.exists()
    assert db.exec(select(Media).where(Media.uuid == media_uuid)).first() is None


def test_export_collection_bundle_resolves_linked_flac_and_uses_actual_filename(
    tmp_path: Path,
    db: Session,
) -> None:
    source_collection = Collection(name="Source", creator_id=1)
    selected_collection = Collection(name="Selected", creator_id=1)
    db.add(source_collection)
    db.add(selected_collection)
    db.flush()
    audio_setting = AudioSetting(sampling_rate_hz=48000, duration_s=1)
    db.add(audio_setting)
    db.flush()
    media = Media(
        media_type="audio",
        directory=8,
        filename="field.wav",
        name="field.wav",
        size_b=4,
        md5_hash=hashlib.md5(b"flac").hexdigest(),
        uploader_id=1,
        creator_id=1,
        audio_setting_id=audio_setting.audio_setting_id,
    )
    db.add(media)
    db.flush()
    db.add(MediaCollection(media_id=media.media_id, collection_id=source_collection.collection_id, added_by=1))
    db.add(MediaCollection(media_id=media.media_id, collection_id=selected_collection.collection_id, added_by=1))
    _write_media_file(source_collection.collection_id, 8, "field.flac", b"flac")
    db.commit()
    output = tmp_path / "linked.zip"

    result = offline_bundle_service.export_collection_bundle(
        db,
        selected_collection.collection_id,
        output_path=output,
    )

    assert result["counts"]["audio"] == 1
    with zipfile.ZipFile(output) as archive:
        payload = json.loads(archive.read("data/media.json"))
        assert payload[0]["filename"] == "field.flac"
        assert payload[0]["bundle_path"] == f"media/sounds/{media.uuid}/field.flac"
        assert payload[0]["bundle_path"] in archive.namelist()


def test_export_collection_bundle_fails_when_media_binary_is_missing(
    tmp_path: Path,
    db: Session,
) -> None:
    collection = Collection(name="Missing binary", creator_id=1)
    setting = PhotoSetting()
    db.add(collection)
    db.add(setting)
    db.flush()
    media = Media(
        media_type="photo",
        directory=9,
        filename="missing.png",
        name="missing.png",
        size_b=10,
        uploader_id=1,
        creator_id=1,
        photo_setting_id=setting.photo_setting_id,
    )
    db.add(media)
    db.flush()
    db.add(MediaCollection(media_id=media.media_id, collection_id=collection.collection_id, added_by=1))
    db.commit()

    with pytest.raises(HTTPException, match="binary file is missing"):
        offline_bundle_service.export_collection_bundle(
            db,
            collection.collection_id,
            output_path=tmp_path / "missing.zip",
        )


def test_export_collection_bundle_preserves_metadata_media_without_files(
    tmp_path: Path,
    db: Session,
) -> None:
    collection = _seed_exportable_collection(db)
    audio_metadata = Media(
        media_type="audio",
        is_metadata=True,
        name="audio metadata",
        uploader_id=1,
        creator_id=1,
        audio_setting=AudioSetting(sampling_rate_hz=44100, duration_s=0),
    )
    photo_metadata = Media(
        media_type="photo",
        is_metadata=True,
        name="photo metadata",
        uploader_id=1,
        creator_id=1,
        photo_setting=PhotoSetting(),
    )
    db.add_all([audio_metadata, photo_metadata])
    db.flush()
    db.add_all(
        [
            MediaCollection(
                media_id=audio_metadata.media_id,
                collection_id=collection.collection_id,
                added_by=1,
            ),
            MediaCollection(
                media_id=photo_metadata.media_id,
                collection_id=collection.collection_id,
                added_by=1,
            ),
        ]
    )
    db.commit()
    output = tmp_path / "metadata.zip"

    result = offline_bundle_service.export_collection_bundle(
        db,
        collection.collection_id,
        output_path=output,
    )

    assert result["counts"]["media"] == 3
    assert result["counts"]["media_files"] == 1
    with zipfile.ZipFile(output) as archive:
        media_payload = json.loads(archive.read("data/media.json"))
        metadata_payloads = [item for item in media_payload if item["is_metadata"]]
        assert len(metadata_payloads) == 2
        assert all(item["bundle_path"] is None and item["bundle_sha256"] is None for item in metadata_payloads)
        assert len([name for name in archive.namelist() if name.startswith("media/")]) == 1


def test_export_collection_bundle_fails_when_audio_source_is_ambiguous(
    tmp_path: Path,
    db: Session,
) -> None:
    collection = Collection(name="Ambiguous audio", creator_id=1)
    setting = AudioSetting(sampling_rate_hz=48000, duration_s=1)
    db.add(collection)
    db.add(setting)
    db.flush()
    media = Media(
        media_type="audio",
        directory=10,
        filename="ambiguous.wav",
        name="ambiguous.wav",
        size_b=4,
        uploader_id=1,
        creator_id=1,
        audio_setting_id=setting.audio_setting_id,
    )
    db.add(media)
    db.flush()
    db.add(MediaCollection(media_id=media.media_id, collection_id=collection.collection_id, added_by=1))
    _write_media_file(collection.collection_id, 10, "ambiguous.wav", b"wave")
    _write_media_file(collection.collection_id, 10, "ambiguous.flac", b"flac")
    db.commit()

    with pytest.raises(HTTPException, match="multiple binary files"):
        offline_bundle_service.export_collection_bundle(
            db,
            collection.collection_id,
            output_path=tmp_path / "ambiguous.zip",
        )
