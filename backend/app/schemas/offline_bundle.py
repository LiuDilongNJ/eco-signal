from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BundleModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OfflineBundleCounts(BundleModel):
    sites: int = Field(ge=0)
    media: int = Field(ge=0)
    audio: int = Field(ge=0)
    photos: int = Field(ge=0)
    media_files: int = Field(ge=0)
    annotations: int = Field(ge=0)
    reviews: int = Field(ge=0)
    labels: int = Field(ge=0)


class OfflineBundleManifest(BundleModel):
    bundle_schema: Literal["offline-bundle"] = Field(alias="schema")
    exported_at: datetime
    collection_id: int
    collection_uuid: UUID
    includes_media: Literal[True]
    hash_algorithm: Literal["sha256"]
    signature_algorithm: Literal["hmac-sha256"]
    counts: OfflineBundleCounts
    warnings: list[str] = Field(default_factory=list)


class OfflineCollectionPayload(BundleModel):
    collection_id: int | None = None
    uuid: UUID
    name: str = Field(min_length=1, max_length=250)
    doi: str | None = None
    description: str | None = None
    sphere: str | None = None
    external_media_url: str | None = None
    project_url: str | None = None
    public_access: bool = False
    public_tags: bool = False
    creator_id: int | None = None
    creation_date: datetime | None = None


class OfflineSitePayload(BundleModel):
    site_id: int | None = None
    uuid: UUID
    name: str = Field(min_length=1, max_length=250)
    longitude: float | None = None
    latitude: float | None = None
    topography_m: float | None = None
    freshwater_depth_m: float | None = None
    realm_id: int | None = None
    biome_id: int | None = None
    functional_type_id: int | None = None
    iho: str | None = None
    gadm0: str | None = None
    gadm1: str | None = None
    gadm2: str | None = None
    gadm0_gid: str | None = None
    gadm1_gid: str | None = None
    gadm2_gid: str | None = None
    creator_id: int | None = None
    creation_date: datetime | None = None


class OfflineAudioSettingPayload(BundleModel):
    recording_gain_db: int | None = None
    sampling_rate_hz: int = Field(gt=0)
    bit_depth: int | None = Field(default=None, gt=0)
    channel_num: int | None = Field(default=None, gt=0)
    duration_s: float = Field(ge=0)


class OfflinePhotoSettingPayload(BundleModel):
    exposure_ms: float | None = Field(default=None, ge=0)
    aperture: float | None = Field(default=None, ge=0)
    iso: int | None = Field(default=None, ge=0)


class OfflineMediaPayload(BundleModel):
    media_id: int | None = None
    uuid: UUID
    media_type: Literal["audio", "photo"]
    is_metadata: bool = False
    directory: int | None = Field(default=None, ge=0)
    filename: str | None = Field(default=None, min_length=1, max_length=250)
    name: str | None = Field(default=None, max_length=250)
    medium: str | None = None
    duty_cycle_recording: int | None = None
    duty_cycle_period: int | None = None
    note: str | None = None
    date_time: datetime | None = None
    creation_date: datetime | None = None
    size_b: int | None = Field(default=None, ge=0)
    md5_hash: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{32}$")
    doi: str | None = None
    uploader_id: int | None = None
    creator_id: int | None = None
    site_uuid: UUID | None = None
    license_id: int | None = None
    sensor_id: int | None = None
    audio_setting: OfflineAudioSettingPayload | None = None
    photo_setting: OfflinePhotoSettingPayload | None = None
    bundle_path: str | None = None
    bundle_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_media_settings(self) -> OfflineMediaPayload:
        if self.media_type == "audio":
            if not self.is_metadata and self.audio_setting is None:
                raise ValueError("Audio media requires audio_setting")
            if self.photo_setting is not None:
                raise ValueError("Audio media cannot contain photo_setting")
        else:
            if self.photo_setting is None:
                raise ValueError("Photo media requires photo_setting")
            if self.audio_setting is not None:
                raise ValueError("Photo media cannot contain audio settings")

        storage_fields = (self.directory, self.filename, self.size_b, self.bundle_path, self.bundle_sha256)
        if self.is_metadata:
            if any(value is not None for value in storage_fields):
                raise ValueError("Metadata media cannot reference a bundle file")
            return self

        if any(value is None for value in storage_fields):
            raise ValueError("File media requires storage and bundle file fields")
        expected_root = "sounds" if self.media_type == "audio" else "images"
        expected = f"media/{expected_root}/{self.uuid}/{self.filename}"
        if self.bundle_path != expected:
            raise ValueError("Media bundle_path does not match its type, UUID, and filename")
        return self


class OfflineAnnotationPayload(BundleModel):
    annotation_id: int | None = None
    uuid: UUID
    media_uuid: UUID
    sound_id: int
    creator_id: int | None = None
    taxon_id: int | None = None
    creator_type: str | None = None
    confidence: float | None = None
    min_x: float
    max_x: float
    min_y: float
    max_y: float
    uncertain: bool | None = None
    sound_distance_m: float | None = None
    distance_not_estimable: bool | None = None
    individual_num: int = 1
    animal_sound_type: str | None = None
    reference: bool = False
    comments: str | None = None
    creation_date: datetime | None = None


class OfflineReviewPayload(BundleModel):
    annotation_uuid: UUID
    reviewer_id: int | None = None
    status_id: int | None = None
    status_name: str
    taxon_id: int | None = None
    note: str | None = None
    creation_date: datetime | None = None


class OfflineLabelPayload(BundleModel):
    media_uuid: UUID
    user_id: int | None = None
    label_name: str


class OfflineBundlePayloads(BundleModel):
    collection: OfflineCollectionPayload
    sites: list[OfflineSitePayload]
    media: list[OfflineMediaPayload]
    annotations: list[OfflineAnnotationPayload]
    reviews: list[OfflineReviewPayload]
    labels: list[OfflineLabelPayload]
