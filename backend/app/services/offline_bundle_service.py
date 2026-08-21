from __future__ import annotations

import hashlib
import hmac
import json
import os
import shutil
import stat
import tempfile
import zipfile
from datetime import UTC, datetime
from io import TextIOWrapper
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from app.core.config import settings
from app.core.task_cancellation import (
    TASK_CANCELLED_MESSAGE,
    CancellationToken,
    TaskCancelledError,
)
from app.enums import QueueStatus
from app.media_paths import (
    audio_filename_candidates,
    logical_audio_media_path,
    logical_photo_media_path,
    media_root,
    resolve_existing_media_path,
)
from app.models import (
    Annotation,
    AnnotationReview,
    AnnotationReviewStatus,
    AudioSetting,
    Collection,
    FileUpload,
    Label,
    LabelMedia,
    License,
    Media,
    MediaCollection,
    PhotoSetting,
    Project,
    ProjectCollection,
    Queue,
    Sensor,
    Site,
    SiteCollection,
    SiteProject,
    SoundClassification,
    Taxon,
    User,
)
from app.schemas.data_import import (
    DataImportSummary,
    DataImportWarning,
)
from app.schemas.offline_bundle import (
    OfflineBundleManifest,
    OfflineBundlePayloads,
    OfflineMediaPayload,
)
from app.services.annotation_service import _normalize_annotation_fields
from app.repositories.label_repository import label_repository
from app.services import permission_service
from app.services.media_preview_service import generate_media_previews
from app.services.upload_validation_service import validate_filename

BUNDLE_SCHEMA = "offline-bundle"
SIGNATURE_ALGORITHM = "hmac-sha256"
_ARCHIVE_COPY_CHUNK_SIZE = 1024 * 1024
_MAX_ARCHIVE_MEMBERS = 100_000
_MAX_COMPRESSION_RATIO = 200
_MIN_FREE_SPACE_AFTER_EXTRACT = 2 * 1024 * 1024 * 1024


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=UTC)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"Object of type {type(value)!r} is not JSON serializable")


def _canonical_json_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=_json_default,
    ).encode("utf-8")


def _bundle_secret() -> str:
    return settings.SECRET_KEY


def _compute_signature(manifest: dict[str, Any], checksums: dict[str, str]) -> str:
    message = _canonical_json_bytes({"checksums": checksums, "manifest": manifest})
    return hmac.new(_bundle_secret().encode("utf-8"), message, hashlib.sha256).hexdigest()


def _safe_bundle_member(path: str) -> PurePosixPath:
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts:
        raise HTTPException(status_code=400, detail=f"Unsafe bundle path: {path}")
    return pure


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_archive_member(archive: zipfile.ZipFile, member: str) -> str:
    digest = hashlib.sha256()
    try:
        with archive.open(member) as source:
            for chunk in iter(lambda: source.read(_ARCHIVE_COPY_CHUNK_SIZE), b""):
                digest.update(chunk)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"Missing bundle payload file: {member}") from exc
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_json_bytes(payload))


def _write_json_array(path: Path, payloads) -> int:
    """Write a JSON array incrementally and return its item count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("wb") as output:
        output.write(b"[")
        for payload in payloads:
            if count:
                output.write(b",")
            output.write(_canonical_json_bytes(payload))
            count += 1
        output.write(b"]")
    return count


def _iter_query(session: Session, statement):
    result = session.exec(statement.execution_options(yield_per=1000))
    for partition in result.partitions(1000):
        yield from partition


def _collection_payload(collection: Collection) -> dict[str, Any]:
    return {
        "collection_id": collection.collection_id,
        "uuid": str(collection.uuid),
        "name": collection.name,
        "doi": collection.doi,
        "description": collection.description,
        "sphere": collection.sphere,
        "external_media_url": collection.external_media_url,
        "project_url": collection.project_url,
        "public_access": collection.public_access,
        "public_tags": collection.public_tags,
        "creator_id": collection.creator_id,
        "creation_date": collection.creation_date,
    }


def _site_payload(site: Site) -> dict[str, Any]:
    return {
        "site_id": site.site_id,
        "uuid": str(site.uuid),
        "name": site.name,
        "longitude": site.longitude,
        "latitude": site.latitude,
        "topography_m": site.topography_m,
        "freshwater_depth_m": site.freshwater_depth_m,
        "realm_id": site.realm_id,
        "biome_id": site.biome_id,
        "functional_type_id": site.functional_type_id,
        "iho": site.iho,
        "gadm0": site.gadm0,
        "gadm1": site.gadm1,
        "gadm2": site.gadm2,
        "gadm0_gid": site.gadm0_gid,
        "gadm1_gid": site.gadm1_gid,
        "gadm2_gid": site.gadm2_gid,
        "creator_id": site.creator_id,
        "creation_date": site.creation_date,
    }


def _annotation_payload(annotation: Annotation) -> dict[str, Any]:
    return {
        "annotation_id": annotation.annotation_id,
        "uuid": str(annotation.uuid),
        "media_uuid": str(annotation.media.uuid) if annotation.media else None,
        "sound_id": annotation.sound_id,
        "object_type": annotation.object_type,
        "creator_id": annotation.creator_id,
        "taxon_id": annotation.taxon_id,
        "creator_type": annotation.creator_type,
        "confidence": annotation.confidence,
        "min_x": annotation.min_x,
        "max_x": annotation.max_x,
        "min_y": annotation.min_y,
        "max_y": annotation.max_y,
        "uncertain": annotation.uncertain,
        "sound_distance_m": annotation.sound_distance_m,
        "distance_not_estimable": annotation.distance_not_estimable,
        "individual_num": annotation.individual_num,
        "animal_sound_type": annotation.animal_sound_type,
        "reference": annotation.reference,
        "comments": annotation.comments,
        "creation_date": annotation.creation_date,
    }


def _review_payload(review: AnnotationReview) -> dict[str, Any]:
    status_name = review.status.name if review.status else None
    annotation_uuid = str(review.annotation.uuid) if review.annotation else None
    return {
        "annotation_uuid": annotation_uuid,
        "reviewer_id": review.reviewer_id,
        "status_id": review.annotation_review_status_id,
        "status_name": status_name,
        "taxon_id": review.taxon_id,
        "note": review.note,
        "creation_date": review.creation_date,
    }


def _label_assignment_payload(label_media: LabelMedia) -> dict[str, Any]:
    return {
        "media_uuid": str(label_media.media.uuid) if label_media.media else None,
        "user_id": label_media.user_id,
        "label_name": label_media.label.name if label_media.label else None,
    }


def _resolve_media_source(session: Session, media: Media) -> Path:
    if media.media_type not in {"audio", "photo"}:
        raise HTTPException(
            status_code=409,
            detail=f"Media {media.uuid} has unsupported type {media.media_type!r}",
        )
    if not media.filename or media.directory is None:
        raise HTTPException(status_code=409, detail=f"Media {media.uuid} has no storage path")

    collection_ids = session.exec(
        select(MediaCollection.collection_id).where(MediaCollection.media_id == media.media_id)
    ).all()
    candidates: list[Path] = []
    for linked_collection_id in collection_ids:
        if media.media_type == "audio":
            for candidate in audio_filename_candidates(media.filename):
                resolved = resolve_existing_media_path(
                    logical_audio_media_path(
                        linked_collection_id,
                        media.directory,
                        candidate,
                    )
                )
                if resolved is not None and resolved not in candidates:
                    candidates.append(resolved)
            continue
        else:
            resolved = resolve_existing_media_path(
                logical_photo_media_path(
                    linked_collection_id,
                    media.directory,
                    media.filename,
                )
            )
        if resolved is not None and resolved not in candidates:
            candidates.append(resolved)
    if not candidates:
        raise HTTPException(
            status_code=409,
            detail=f"Media {media.uuid} binary file is missing",
        )
    if len(candidates) > 1:
        raise HTTPException(
            status_code=409,
            detail=f"Media {media.uuid} resolves to multiple binary files",
        )
    return candidates[0]


def _media_bundle_relative_path(media: Media, source: Path) -> str:
    media_root_name = "sounds" if media.media_type == "audio" else "images"
    return (Path("media") / media_root_name / str(media.uuid) / source.name).as_posix()


def _media_payload(media: Media, source: Path | None = None) -> dict[str, Any]:
    audio_setting = None
    if media.audio_setting:
        audio_setting = {
            "recording_gain_db": media.audio_setting.recording_gain_db,
            "sampling_rate_hz": media.audio_setting.sampling_rate_hz,
            "bit_depth": media.audio_setting.bit_depth,
            "channel_num": media.audio_setting.channel_num,
            "duration_s": media.audio_setting.duration_s,
        }

    photo_setting = None
    if media.photo_setting:
        photo_setting = {
            "exposure_ms": media.photo_setting.exposure_ms,
            "aperture": media.photo_setting.aperture,
            "iso": media.photo_setting.iso,
        }

    payload = {
        "media_id": media.media_id,
        "uuid": str(media.uuid),
        "media_type": media.media_type,
        "is_metadata": media.is_metadata,
        "directory": media.directory,
        "filename": source.name if source is not None else None,
        "name": media.name,
        "medium": media.medium,
        "duty_cycle_recording": media.duty_cycle_recording,
        "duty_cycle_period": media.duty_cycle_period,
        "note": media.note,
        "date_time": media.date_time,
        "creation_date": media.creation_date,
        "size_b": source.stat().st_size if source is not None else None,
        "md5_hash": media.md5_hash,
        "doi": media.doi,
        "uploader_id": media.uploader_id,
        "creator_id": media.creator_id,
        "site_uuid": str(media.site.uuid) if media.site else None,
        "license_id": media.license_id,
        "sensor_id": media.sensor_id,
        "audio_setting": audio_setting,
        "photo_setting": photo_setting,
        "bundle_path": _media_bundle_relative_path(media, source) if source is not None else None,
        "bundle_sha256": _hash_file(source) if source is not None else None,
    }
    return payload


def _copy_media_file(bundle_root: Path, media: Media, source: Path) -> None:
    dest = bundle_root / _media_bundle_relative_path(media, source)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)


def export_collection_bundle(
    session: Session,
    collection_id: int,
    *,
    output_path: Path,
    cancellation_token: CancellationToken | None = None,
) -> dict[str, Any]:
    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()
    collection = session.get(Collection, collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    media_statement = (
        select(Media)
        .join(MediaCollection, MediaCollection.media_id == Media.media_id)
        .where(MediaCollection.collection_id == collection_id)
        .options(
            selectinload(Media.audio_setting),
            selectinload(Media.photo_setting),
            selectinload(Media.site),
        )
    )
    site_statement = (
        select(Site)
        .join(SiteCollection, SiteCollection.site_id == Site.site_id)
        .where(SiteCollection.collection_id == collection_id)
    )
    annotation_statement = (
        select(Annotation)
        .join(MediaCollection, MediaCollection.media_id == Annotation.media_id)
        .where(MediaCollection.collection_id == collection_id)
        .options(selectinload(Annotation.media))
    )
    review_statement = (
        select(AnnotationReview)
        .join(Annotation, Annotation.annotation_id == AnnotationReview.annotation_id)
        .join(MediaCollection, MediaCollection.media_id == Annotation.media_id)
        .where(MediaCollection.collection_id == collection_id)
        .options(
            selectinload(AnnotationReview.annotation),
            selectinload(AnnotationReview.status),
        )
    )
    label_statement = (
        select(LabelMedia)
        .join(MediaCollection, MediaCollection.media_id == LabelMedia.media_id)
        .where(MediaCollection.collection_id == collection_id)
        .options(selectinload(LabelMedia.media), selectinload(LabelMedia.label))
    )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []

    with tempfile.TemporaryDirectory(prefix="offline-bundle-") as temp_dir:
        bundle_root = Path(temp_dir)
        data_dir = bundle_root / "data"

        _write_json(data_dir / "collection.json", _collection_payload(collection))
        site_count = _write_json_array(
            data_dir / "sites.json",
            (_site_payload(site) for site in _iter_query(session, site_statement)),
        )

        media_type_counts = {"audio": 0, "photo": 0}
        media_file_count = 0

        def media_payloads():
            nonlocal media_file_count
            for media in _iter_query(session, media_statement):
                if cancellation_token is not None:
                    cancellation_token.raise_if_cancelled()
                source = None if media.is_metadata else _resolve_media_source(session, media)
                payload = _media_payload(media, source)
                try:
                    OfflineMediaPayload.model_validate(payload)
                except ValidationError as exc:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Media {media.uuid} cannot be exported: {exc.errors(include_url=False)}",
                    ) from exc
                if source is not None:
                    _copy_media_file(bundle_root, media, source)
                    media_file_count += 1
                media_type_counts[media.media_type] += 1
                yield payload

        media_count = _write_json_array(data_dir / "media.json", media_payloads())
        annotation_count = _write_json_array(
            data_dir / "annotations.json",
            (_annotation_payload(item) for item in _iter_query(session, annotation_statement)),
        )
        review_count = _write_json_array(
            data_dir / "reviews.json",
            (_review_payload(item) for item in _iter_query(session, review_statement)),
        )
        label_count = _write_json_array(
            data_dir / "labels.json",
            (_label_assignment_payload(item) for item in _iter_query(session, label_statement)),
        )

        checksum_entries: dict[str, str] = {}
        for path in sorted(bundle_root.rglob("*")):
            if cancellation_token is not None:
                cancellation_token.raise_if_cancelled()
            if not path.is_file():
                continue
            rel = path.relative_to(bundle_root).as_posix()
            checksum_entries[rel] = _hash_file(path)

        manifest = {
            "schema": BUNDLE_SCHEMA,
            "exported_at": datetime.now(UTC),
            "collection_id": collection.collection_id,
            "collection_uuid": str(collection.uuid),
            "includes_media": True,
            "hash_algorithm": "sha256",
            "signature_algorithm": SIGNATURE_ALGORITHM,
            "counts": {
                "sites": site_count,
                "media": media_count,
                "audio": media_type_counts["audio"],
                "photos": media_type_counts["photo"],
                "media_files": media_file_count,
                "annotations": annotation_count,
                "reviews": review_count,
                "labels": label_count,
            },
            "warnings": warnings,
        }
        _write_json(bundle_root / "checksums.json", checksum_entries)
        _write_json(bundle_root / "manifest.json", manifest)
        signature = _compute_signature(manifest, checksum_entries)
        (bundle_root / "manifest.sig").write_text(signature, encoding="utf-8")

        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(bundle_root.rglob("*")):
                if cancellation_token is not None:
                    cancellation_token.raise_if_cancelled()
                if path.is_file():
                    archive.write(path, arcname=path.relative_to(bundle_root).as_posix())

    return {
        "output_path": str(output),
        "collection_id": collection.collection_id,
        "collection_uuid": str(collection.uuid),
        "counts": manifest["counts"],
        "warnings": warnings,
    }


def _load_json(archive: zipfile.ZipFile, member: str) -> Any:
    try:
        with archive.open(member) as source, TextIOWrapper(source, encoding="utf-8") as text:
            return json.load(text)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"Missing required bundle file: {member}") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON in bundle file: {member}") from exc


def _verify_bundle(archive: zipfile.ZipFile) -> tuple[dict[str, Any], dict[str, str]]:
    members = archive.infolist()
    if len(members) > _MAX_ARCHIVE_MEMBERS:
        raise HTTPException(status_code=400, detail="Offline bundle contains too many files")
    member_names = [member.filename for member in members]
    if len(member_names) != len(set(member_names)):
        raise HTTPException(status_code=400, detail="Offline bundle contains duplicate file names")
    for member in members:
        relative = _safe_bundle_member(member.filename)
        mode = member.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise HTTPException(status_code=400, detail=f"Symbolic link is not allowed: {member.filename}")
        if (
            not member.is_dir()
            and member.file_size > 0
            and member.file_size / max(member.compress_size, 1) > _MAX_COMPRESSION_RATIO
        ):
            raise HTTPException(status_code=400, detail=f"Suspicious compression ratio: {member.filename}")
        # Bundles have a deliberately closed layout.  This prevents a signed
        # archive from carrying arbitrary executable or web-served payloads.
        parts = relative.parts
        allowed_root_file = relative.as_posix() in {"manifest.json", "checksums.json", "manifest.sig"}
        allowed_data_file = len(parts) == 2 and parts[0] == "data" and parts[1] in {
            "collection.json", "sites.json", "media.json", "annotations.json", "reviews.json", "labels.json",
        }
        allowed_media_file = (
            len(parts) == 4
            and parts[0] == "media"
            and parts[1] in {"sounds", "images"}
            and _is_uuid(parts[2])
        )
        if not member.is_dir() and not (allowed_root_file or allowed_data_file or allowed_media_file):
            raise HTTPException(status_code=400, detail="unsafe_archive")
        if allowed_media_file:
            validate_filename(parts[-1])

    manifest = _load_json(archive, "manifest.json")
    checksums = _load_json(archive, "checksums.json")
    try:
        with archive.open("manifest.sig") as source, TextIOWrapper(source, encoding="utf-8") as text:
            signature = text.read().strip()
    except KeyError as exc:
        raise HTTPException(status_code=400, detail="Missing required bundle file: manifest.sig") from exc

    try:
        OfflineBundleManifest.model_validate(manifest)
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid offline bundle manifest: {exc.errors(include_url=False)}",
        ) from exc
    if not isinstance(checksums, dict) or any(
        not isinstance(key, str)
        or not isinstance(value, str)
        or len(value) != 64
        for key, value in checksums.items()
    ):
        raise HTTPException(status_code=400, detail="Invalid offline bundle checksums")

    payload_members = {
        member.filename
        for member in members
        if not member.is_dir()
        and member.filename not in {"manifest.json", "checksums.json", "manifest.sig"}
    }
    if set(checksums) != payload_members:
        raise HTTPException(
            status_code=400,
            detail="Offline bundle checksum list does not match archive payload files",
        )

    expected_signature = _compute_signature(manifest, checksums)
    if not hmac.compare_digest(expected_signature, signature):
        raise HTTPException(status_code=400, detail="Offline bundle signature verification failed")

    for member, expected in checksums.items():
        actual = _hash_archive_member(archive, member)
        if actual != expected:
            raise HTTPException(status_code=400, detail=f"Checksum mismatch for bundle file: {member}")

    return manifest, checksums


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _load_json_file(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as source:
            return json.load(source)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=f"Missing required bundle file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON in bundle file: {path.name}") from exc


def _validate_bundle_payloads(
    *,
    manifest: dict[str, Any],
    checksums: dict[str, str],
    collection_payload: Any,
    sites_payload: Any,
    media_payload: Any,
    annotations_payload: Any,
    reviews_payload: Any,
    labels_payload: Any,
) -> dict[str, Any]:
    try:
        payloads = OfflineBundlePayloads.model_validate(
            {
                "collection": collection_payload,
                "sites": sites_payload,
                "media": media_payload,
                "annotations": annotations_payload,
                "reviews": reviews_payload,
                "labels": labels_payload,
            }
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid offline bundle data: {exc.errors(include_url=False)}",
        ) from exc

    if str(payloads.collection.uuid) != str(manifest["collection_uuid"]):
        raise HTTPException(status_code=400, detail="Collection UUID does not match manifest")

    actual_counts = {
        "sites": len(payloads.sites),
        "media": len(payloads.media),
        "audio": sum(item.media_type == "audio" for item in payloads.media),
        "photos": sum(item.media_type == "photo" for item in payloads.media),
        "media_files": sum(not item.is_metadata for item in payloads.media),
        "annotations": len(payloads.annotations),
        "reviews": len(payloads.reviews),
        "labels": len(payloads.labels),
    }
    if actual_counts != manifest["counts"]:
        raise HTTPException(status_code=400, detail="Bundle item counts do not match manifest")

    file_media = [item for item in payloads.media if not item.is_metadata]
    referenced_media_paths = {item.bundle_path for item in file_media}
    if len(referenced_media_paths) != len(file_media):
        raise HTTPException(status_code=400, detail="Multiple media records reference the same bundle file")
    archive_media_paths = {path for path in checksums if path.startswith("media/")}
    if referenced_media_paths != archive_media_paths:
        raise HTTPException(status_code=400, detail="Bundle media records do not match media files")
    for item in file_media:
        if checksums[item.bundle_path] != item.bundle_sha256:
            raise HTTPException(
                status_code=400,
                detail=f"Media checksum does not match media record: {item.uuid}",
            )

    return payloads.model_dump(mode="python")


def _extract_archive(archive: zipfile.ZipFile, destination: Path) -> None:
    members = archive.infolist()
    required_space = sum(member.file_size for member in members if not member.is_dir())
    if shutil.disk_usage(destination).free - required_space < _MIN_FREE_SPACE_AFTER_EXTRACT:
        raise HTTPException(status_code=507, detail="Insufficient disk space for offline bundle")
    for member in members:
        relative = _safe_bundle_member(member.filename)
        target = destination / relative
        if member.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(member) as source, target.open("wb") as output:
            shutil.copyfileobj(source, output, length=_ARCHIVE_COPY_CHUNK_SIZE)


def _offline_import_temp_dir(batch_id: str) -> Path:
    return media_root() / "tmp" / "offline-imports" / batch_id


def _resolve_or_create_collection(
    session: Session,
    payload: dict[str, Any],
    current_user: User,
) -> tuple[Collection, bool]:
    collection = session.exec(
        select(Collection).where(Collection.uuid == payload["uuid"])
    ).first()
    created = False
    if collection is None:
        collection = Collection(
            uuid=payload["uuid"],
            name=payload["name"],
            doi=payload.get("doi"),
            description=payload.get("description"),
            sphere=payload.get("sphere"),
            external_media_url=payload.get("external_media_url"),
            project_url=payload.get("project_url"),
            public_access=bool(payload.get("public_access", False)),
            public_tags=bool(payload.get("public_tags", False)),
            creator_id=current_user.user_id,
        )
        session.add(collection)
        session.flush()
        created = True
    return collection, created


def _link_collection_to_project(session: Session, project_id: int, collection_id: int) -> bool:
    existing = session.exec(
        select(ProjectCollection).where(
            ProjectCollection.project_id == project_id,
            ProjectCollection.collection_id == collection_id,
        )
    ).first()
    if existing is not None:
        return False
    session.add(ProjectCollection(project_id=project_id, collection_id=collection_id))
    session.flush()
    return True


def _resolve_or_create_site(
    session: Session,
    payload: dict[str, Any],
    current_user: User,
    project_id: int,
    collection_id: int,
) -> tuple[Site, bool, bool]:
    site = session.exec(select(Site).where(Site.uuid == payload["uuid"])).first()
    created = False
    if site is None:
        site = Site(
            uuid=payload["uuid"],
            name=payload["name"],
            creator_id=current_user.user_id,
            longitude=payload.get("longitude"),
            latitude=payload.get("latitude"),
            topography_m=payload.get("topography_m"),
            freshwater_depth_m=payload.get("freshwater_depth_m"),
            realm_id=payload.get("realm_id"),
            biome_id=payload.get("biome_id"),
            functional_type_id=payload.get("functional_type_id"),
            iho=payload.get("iho"),
            gadm0=payload.get("gadm0"),
            gadm1=payload.get("gadm1"),
            gadm2=payload.get("gadm2"),
            gadm0_gid=payload.get("gadm0_gid"),
            gadm1_gid=payload.get("gadm1_gid"),
            gadm2_gid=payload.get("gadm2_gid"),
        )
        session.add(site)
        session.flush()
        created = True

    collection_linked = session.exec(
        select(SiteCollection).where(
            SiteCollection.site_id == site.site_id,
            SiteCollection.collection_id == collection_id,
        )
    ).first()
    if collection_linked is None:
        session.add(SiteCollection(site_id=site.site_id, collection_id=collection_id))
        collection_linked = True
    else:
        collection_linked = False

    project_linked = session.exec(
        select(SiteProject).where(
            SiteProject.site_id == site.site_id,
            SiteProject.project_id == project_id,
        )
    ).first()
    if project_linked is None:
        session.add(SiteProject(site_id=site.site_id, project_id=project_id))
    session.flush()
    return site, created, collection_linked


def _resolve_user_id(session: Session, preferred_user_id: int | None, current_user: User) -> int:
    if preferred_user_id is None:
        return current_user.user_id
    existing = session.get(User, preferred_user_id)
    return existing.user_id if existing else current_user.user_id


def _resolve_optional_foreign_key(
    session: Session,
    *,
    model: type[Sensor] | type[License],
    identifier: int | None,
    resource_type: str,
    media_uuid: str,
    warnings: list[DataImportWarning],
) -> int | None:
    if identifier is None:
        return None
    if session.get(model, identifier) is not None:
        return identifier
    warnings.append(
        DataImportWarning(
            resource_type="media",
            identifier=media_uuid,
            message=f"Referenced {resource_type}_id={identifier} does not exist in target instance; field imported as null.",
        )
    )
    return None


def _copy_bundle_media_file(
    extracted_root: Path,
    bundle_path: str,
    target_collection_id: int,
    payload: dict[str, Any],
    created_files: list[Path],
) -> tuple[Path, str]:
    source = extracted_root / _safe_bundle_member(bundle_path)
    if not source.is_file():
        raise HTTPException(status_code=400, detail=f"Bundle file is missing: {bundle_path}")

    filename = str(payload["filename"])
    directory = payload["directory"]

    if payload.get("media_type") == "audio":
        relative = logical_audio_media_path(target_collection_id, directory, filename)
    else:
        relative = logical_photo_media_path(target_collection_id, directory, filename)
    target = media_root() / relative
    if target.exists():
        path = Path(filename)
        filename = f"{path.stem}__{payload['uuid']}{path.suffix}"
        if payload.get("media_type") == "audio":
            relative = logical_audio_media_path(target_collection_id, directory, filename)
        else:
            relative = logical_photo_media_path(target_collection_id, directory, filename)
        target = media_root() / relative
    if target.exists():
        raise HTTPException(
            status_code=409,
            detail=f"Deterministic media target already exists for {payload['uuid']}",
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(f".{target.name}.{uuid4().hex}.part")
    try:
        shutil.copy2(source, part)
        os.link(part, target)
        created_files.append(target)
    finally:
        part.unlink(missing_ok=True)
    return target, filename


def _ensure_media_collection_link(
    session: Session,
    *,
    media_id: int,
    collection_id: int,
    added_by: int,
) -> bool:
    existing = session.exec(
        select(MediaCollection).where(
            MediaCollection.media_id == media_id,
            MediaCollection.collection_id == collection_id,
        )
    ).first()
    if existing is not None:
        return False
    session.add(
        MediaCollection(
            media_id=media_id,
            collection_id=collection_id,
            added_by=added_by,
        )
    )
    session.flush()
    return True


def _as_datetime(value: datetime | str | None) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


def _import_bundle_payloads(
    session: Session,
    *,
    project_id: int,
    current_user: User,
    manifest: dict[str, Any],
    collection_payload: dict[str, Any],
    sites_payload: list[dict[str, Any]],
    media_payload: list[dict[str, Any]],
    annotations_payload: list[dict[str, Any]],
    reviews_payload: list[dict[str, Any]],
    labels_payload: list[dict[str, Any]],
    extracted_root: Path,
    cancellation_token: CancellationToken | None = None,
    created_files: list[Path] | None = None,
    commit: bool = True,
) -> DataImportSummary:
    result = DataImportSummary(
        project_id=project_id,
        collection_id=0,
        collection_uuid=str(collection_payload["uuid"]),
        bundle_manifest=manifest,
    )

    collection, collection_created = _resolve_or_create_collection(session, collection_payload, current_user)
    result.collection_id = collection.collection_id
    if collection_created:
        result.created_counts.collections += 1
    else:
        result.skipped_counts.collections += 1
    if _link_collection_to_project(session, project_id, collection.collection_id):
        result.created_counts.project_links += 1
    else:
        result.skipped_counts.project_links += 1

    site_map: dict[str, int] = {}
    for site_item in sites_payload:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        site, created, linked = _resolve_or_create_site(
            session,
            site_item,
            current_user,
            project_id,
            collection.collection_id,
        )
        site_map[str(site.uuid)] = site.site_id
        if created:
            result.created_counts.sites += 1
        else:
            result.skipped_counts.sites += 1
        if linked:
            result.created_counts.site_links += 1
        else:
            result.skipped_counts.site_links += 1

    media_map: dict[str, int | None] = {}
    for media_item in media_payload:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        media_uuid = str(media_item["uuid"])
        existing_by_uuid = session.exec(
            select(Media).where(Media.uuid == media_item["uuid"])
        ).first()
        if existing_by_uuid is not None:
            if existing_by_uuid.is_metadata != media_item["is_metadata"]:
                raise HTTPException(
                    status_code=409,
                    detail=f"Media UUID {media_uuid} already exists with different metadata mode",
                )
            if not media_item["is_metadata"]:
                existing_source = _resolve_media_source(session, existing_by_uuid)
                if _hash_file(existing_source) != media_item["bundle_sha256"]:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Media UUID {media_uuid} already exists with different binary content",
                    )
            result.skipped_counts.media += 1
            if not media_item["is_metadata"]:
                result.skipped_counts.media_files += 1
            if existing_by_uuid.media_type == "audio":
                result.skipped_counts.audio += 1
            else:
                result.skipped_counts.photos += 1
            if _ensure_media_collection_link(
                session,
                media_id=existing_by_uuid.media_id,
                collection_id=collection.collection_id,
                added_by=current_user.user_id,
            ):
                result.created_counts.media_links += 1
            else:
                result.skipped_counts.media_links += 1
            media_map[media_uuid] = existing_by_uuid.media_id
            continue

        audio_setting_id = None
        if media_item.get("audio_setting"):
            audio = media_item["audio_setting"]
            audio_setting = AudioSetting(
                recording_gain_db=audio.get("recording_gain_db"),
                sampling_rate_hz=audio["sampling_rate_hz"],
                bit_depth=audio.get("bit_depth"),
                channel_num=audio.get("channel_num"),
                duration_s=audio["duration_s"],
            )
            session.add(audio_setting)
            session.flush()
            audio_setting_id = audio_setting.audio_setting_id

        photo_setting_id = None
        if media_item.get("photo_setting"):
            photo = media_item["photo_setting"]
            photo_setting = PhotoSetting(
                exposure_ms=photo.get("exposure_ms"),
                aperture=photo.get("aperture"),
                iso=photo.get("iso"),
            )
            session.add(photo_setting)
            session.flush()
            photo_setting_id = photo_setting.photo_setting_id

        site_id = None
        if media_item.get("site_uuid"):
            site_id = site_map.get(str(media_item["site_uuid"]))
        sensor_id = _resolve_optional_foreign_key(
            session,
            model=Sensor,
            identifier=media_item.get("sensor_id"),
            resource_type="sensor",
            media_uuid=media_uuid,
            warnings=result.warnings,
        )
        license_id = _resolve_optional_foreign_key(
            session,
            model=License,
            identifier=media_item.get("license_id"),
            resource_type="license",
            media_uuid=media_uuid,
            warnings=result.warnings,
        )

        target_path = None
        final_filename = None
        if not media_item["is_metadata"]:
            if created_files is None:
                created_files = []
            target_path, final_filename = _copy_bundle_media_file(
                extracted_root,
                media_item["bundle_path"],
                collection.collection_id,
                media_item,
                created_files,
            )

        media = Media(
            uuid=media_item["uuid"],
            media_type=media_item["media_type"],
            is_metadata=media_item.get("is_metadata", False),
            directory=media_item.get("directory"),
            filename=final_filename,
            name=media_item.get("name"),
            medium=media_item.get("medium"),
            duty_cycle_recording=media_item.get("duty_cycle_recording"),
            duty_cycle_period=media_item.get("duty_cycle_period"),
            note=media_item.get("note"),
            date_time=_as_datetime(media_item.get("date_time")),
            size_b=media_item.get("size_b"),
            md5_hash=media_item.get("md5_hash"),
            doi=media_item.get("doi"),
            uploader_id=_resolve_user_id(session, media_item.get("uploader_id"), current_user),
            creator_id=_resolve_user_id(session, media_item.get("creator_id"), current_user),
            site_id=site_id,
            sensor_id=sensor_id,
            license_id=license_id,
            audio_setting_id=audio_setting_id,
            photo_setting_id=photo_setting_id,
            creation_date=_as_datetime(media_item.get("creation_date")) or datetime.now(UTC).replace(tzinfo=None),
        )
        session.add(media)
        session.flush()
        _ensure_media_collection_link(
            session,
            media_id=media.media_id,
            collection_id=collection.collection_id,
            added_by=current_user.user_id,
        )
        if target_path is not None:
            preview_result = generate_media_previews(
                session,
                media=media,
                collection_id=collection.collection_id,
                source_path=target_path,
            )
            created_files.extend(preview_result.created_paths)
            result.created_counts.previews += preview_result.created_count
            for warning in preview_result.warnings:
                result.warnings.append(
                    DataImportWarning(
                        resource_type="preview",
                        identifier=media_uuid,
                        message=warning,
                    )
                )
        media_map[media_uuid] = media.media_id
        result.created_counts.media += 1
        result.created_counts.media_links += 1
        if not media.is_metadata:
            result.created_counts.media_files += 1
        if media.media_type == "audio":
            result.created_counts.audio += 1
        else:
            result.created_counts.photos += 1

    annotation_map: dict[str, int] = {}
    valid_sound_ids = set(session.exec(select(SoundClassification.sound_id)).all())
    valid_taxon_ids = set(session.exec(select(Taxon.taxon_id)).all())
    for annotation_item in annotations_payload:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        media_id = media_map.get(str(annotation_item.get("media_uuid")))
        if media_id is None:
            result.skipped_counts.annotations += 1
            result.warnings.append(
                DataImportWarning(
                    resource_type="annotation",
                    identifier=str(annotation_item.get("uuid")),
                    message="Target media was skipped; annotation not imported.",
                )
            )
            continue
        media = session.get(Media, media_id)
        if media is None:
            continue
        if media.media_type == "audio" and annotation_item["sound_id"] not in valid_sound_ids:
            result.skipped_counts.annotations += 1
            result.warnings.append(
                DataImportWarning(
                    resource_type="annotation",
                    identifier=str(annotation_item.get("uuid")),
                    message="Referenced sound classification does not exist; annotation skipped.",
                )
            )
            continue
        existing_annotation = session.exec(
            select(Annotation).where(Annotation.uuid == annotation_item["uuid"])
        ).first()
        if existing_annotation is not None:
            result.skipped_counts.annotations += 1
            annotation_map[str(annotation_item["uuid"])] = existing_annotation.annotation_id
            continue
        annotation = Annotation(
            uuid=annotation_item["uuid"],
            sound_id=annotation_item["sound_id"],
            object_type=annotation_item.get("object_type"),
            media_id=media_id,
            creator_id=_resolve_user_id(session, annotation_item.get("creator_id"), current_user),
            taxon_id=annotation_item.get("taxon_id") if annotation_item.get("taxon_id") in valid_taxon_ids else None,
            creator_type=annotation_item.get("creator_type"),
            confidence=annotation_item.get("confidence"),
            min_x=annotation_item["min_x"],
            max_x=annotation_item["max_x"],
            min_y=annotation_item["min_y"],
            max_y=annotation_item["max_y"],
            uncertain=annotation_item.get("uncertain"),
            sound_distance_m=annotation_item.get("sound_distance_m"),
            distance_not_estimable=annotation_item.get("distance_not_estimable"),
            individual_num=annotation_item.get("individual_num", 1),
            animal_sound_type=annotation_item.get("animal_sound_type"),
            reference=bool(annotation_item.get("reference", False)),
            comments=annotation_item.get("comments"),
        )
        normalized = _normalize_annotation_fields(media.media_type, annotation.model_dump())
        annotation.sqlmodel_update(normalized)
        session.add(annotation)
        session.flush()
        annotation_map[str(annotation.uuid)] = annotation.annotation_id
        result.created_counts.annotations += 1

    status_by_name = {
        status.name: status.annotation_review_status_id
        for status in session.exec(select(AnnotationReviewStatus)).all()
    }
    for review_item in reviews_payload:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        annotation_id = annotation_map.get(str(review_item.get("annotation_uuid")))
        if annotation_id is None:
            result.skipped_counts.reviews += 1
            continue
        status_id = status_by_name.get(review_item.get("status_name"))
        if status_id is None:
            result.skipped_counts.reviews += 1
            result.warnings.append(
                DataImportWarning(
                    resource_type="review",
                    identifier=str(review_item.get("annotation_uuid")),
                    message="Referenced review status does not exist; review skipped.",
                )
            )
            continue
        reviewer_id = _resolve_user_id(session, review_item.get("reviewer_id"), current_user)
        existing_review = session.exec(
            select(AnnotationReview).where(
                AnnotationReview.annotation_id == annotation_id,
                AnnotationReview.reviewer_id == reviewer_id,
            )
        ).first()
        if existing_review is not None:
            result.skipped_counts.reviews += 1
            continue
        review = AnnotationReview(
            annotation_id=annotation_id,
            reviewer_id=reviewer_id,
            annotation_review_status_id=status_id,
            taxon_id=review_item.get("taxon_id") if review_item.get("taxon_id") in valid_taxon_ids else None,
            note=review_item.get("note"),
        )
        session.add(review)
        session.flush()
        result.created_counts.reviews += 1

    for label_item in labels_payload:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        media_id = media_map.get(str(label_item.get("media_uuid")))
        label_name = (label_item.get("label_name") or "").strip()
        if media_id is None or not label_name:
            result.skipped_counts.label_links += 1
            continue
        label_user_id = _resolve_user_id(session, label_item.get("user_id"), current_user)
        label = label_repository.get_public_by_name(session, label_name)
        if label is None:
            label = label_repository.get_by_creator_and_name(
                session,
                label_user_id,
                label_name,
            )
        if label is None:
            label = Label(name=label_name, creator_id=label_user_id)
            session.add(label)
            session.flush()
            result.created_counts.labels += 1
        else:
            result.skipped_counts.labels += 1
        existing_link = session.exec(
            select(LabelMedia).where(
                LabelMedia.media_id == media_id,
                LabelMedia.user_id == label_user_id,
                LabelMedia.label_id == label.label_id,
            )
        ).first()
        if existing_link is not None:
            result.skipped_counts.label_links += 1
            continue
        session.add(
            LabelMedia(
                media_id=media_id,
                user_id=label_user_id,
                label_id=label.label_id,
            )
        )
        session.flush()
        result.created_counts.label_links += 1

    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()
    if commit:
        session.commit()
    else:
        session.flush()
    return result


def import_collection_bundle_from_file_upload(
    session: Session,
    *,
    project_id: int,
    file_upload: FileUpload,
    uploader: User,
    batch_id: str,
    cancellation_token: CancellationToken | None = None,
    queue_id: int | None = None,
) -> DataImportSummary:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if not permission_service.has_resource_permission(
        session,
        uploader,
        "project",
        "write",
        project_id=project_id,
    ):
        raise HTTPException(status_code=403, detail="Uploader no longer has project:write permission")

    if not file_upload.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Offline import file must be a .zip bundle")

    zip_path = media_root() / file_upload.path
    if not zip_path.is_file():
        raise HTTPException(status_code=400, detail="Uploaded bundle file is missing")

    created_files: list[Path] = []
    try:
        if cancellation_token is not None:
            cancellation_token.raise_if_cancelled()
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Invalid offline bundle zip file") from exc

    extract_root = _offline_import_temp_dir(batch_id)
    if extract_root.exists():
        shutil.rmtree(extract_root)
    extract_root.mkdir(parents=True, exist_ok=True)

    try:
        with archive:
            manifest, checksums = _verify_bundle(archive)
            _extract_archive(archive, extract_root)

        collection_payload = _load_json_file(extract_root / "data" / "collection.json")
        sites_payload = _load_json_file(extract_root / "data" / "sites.json")
        media_payload = _load_json_file(extract_root / "data" / "media.json")
        annotations_payload = _load_json_file(extract_root / "data" / "annotations.json")
        reviews_payload = _load_json_file(extract_root / "data" / "reviews.json")
        labels_payload = _load_json_file(extract_root / "data" / "labels.json")
        payloads = _validate_bundle_payloads(
            manifest=manifest,
            checksums=checksums,
            collection_payload=collection_payload,
            sites_payload=sites_payload,
            media_payload=media_payload,
            annotations_payload=annotations_payload,
            reviews_payload=reviews_payload,
            labels_payload=labels_payload,
        )

        result = _import_bundle_payloads(
            session,
            project_id=project_id,
            current_user=uploader,
            manifest=manifest,
            collection_payload=payloads["collection"],
            sites_payload=payloads["sites"],
            media_payload=payloads["media"],
            annotations_payload=payloads["annotations"],
            reviews_payload=payloads["reviews"],
            labels_payload=payloads["labels"],
            extracted_root=extract_root,
            cancellation_token=cancellation_token,
            created_files=created_files,
            commit=queue_id is None,
        )
        if queue_id is not None:
            queue = session.exec(
                select(Queue).where(Queue.queue_id == queue_id).with_for_update()
            ).first()
            if queue is None:
                raise RuntimeError("Queue not found")
            if queue.status == QueueStatus.ERROR and queue.error == TASK_CANCELLED_MESSAGE:
                if cancellation_token is not None:
                    cancellation_token.cancel()
                raise TaskCancelledError("Task cancellation requested")
            file_upload.status = 3
            file_upload.error = None
            file_upload.path = ""
            queue.status = QueueStatus.COMPLETED
            queue.completed = 1
            queue.total = 1
            queue.error = None
            queue.stop_time = datetime.now(UTC).replace(tzinfo=None)
            session.add(file_upload)
            session.add(queue)
            session.commit()
        if zip_path.exists():
            zip_path.unlink()
        return result
    except Exception:
        session.rollback()
        for target in reversed(created_files):
            target.unlink(missing_ok=True)
        raise
    finally:
        if extract_root.exists():
            shutil.rmtree(extract_root)
