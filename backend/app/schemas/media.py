import uuid
from datetime import datetime
from typing import Optional

from pydantic import (
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)
from sqlmodel import SQLModel

from app.enums import MediaType


class PreviewPublic(SQLModel):
    """Schema for Preview public response."""
    preview_id: int
    media_id: int
    type: str
    url: str

    model_config = ConfigDict(from_attributes=True)


class AudioSettingPublic(SQLModel):
    """Schema for AudioSetting public response."""
    recording_gain_db: Optional[int] = None
    sampling_rate_hz: int
    bit_depth: Optional[int] = None
    channel_num: Optional[int] = None
    duration_s: float

    model_config = ConfigDict(from_attributes=True)


class PhotoSettingPublic(SQLModel):
    """Schema for photo technical metadata."""
    exposure_ms: Optional[float] = None
    aperture: Optional[float] = None
    iso: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class ChunkUploadRequest(SQLModel):
    """Request for chunk upload."""
    filename: str = Field(..., description="Original filename")
    chunk_index: int = Field(..., ge=0, description="Chunk index (0-based)")
    total_chunks: int = Field(..., ge=1, description="Total number of chunks")


class ChunkUploadResponse(SQLModel):
    """Response for chunk upload."""
    filename: str
    uploaded_chunks: int
    total_chunks: int
    is_complete: bool
    file_upload_id: Optional[int] = Field(None, description="Created FileUpload ID, returned when is_complete=True")


class MediaCreate(SQLModel):
    """Request body for creating media records from uploaded files (batch)."""
    collection_id: int = Field(..., description="Collection ID")
    file_upload_ids: list[int] = Field(..., min_length=1, description="List of FileUpload IDs to process")
    filename_prefix: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Optional prefix to prepend to stored filename",
    )
    date_time: Optional[str] = Field(None, description="Recording datetime in format YYYY-MM-DD HH:mm:ss")
    date_from_filename: bool = Field(False, description="Parse date from filename")
    site_id: Optional[int] = Field(None, description="Site ID")
    sensor_id: Optional[int] = Field(None, description="Sensor ID (recorder+mic combo)")
    license_id: Optional[int] = Field(None, description="License ID")
    medium: Optional[str] = Field(None, description="Medium: Air or Water")
    media_type: Optional[MediaType] = Field(None, description="Media type: audio, photo, video")
    recording_gain_db: Optional[int] = Field(None, description="Recording gain in dB")
    duty_cycle_recording: Optional[int] = Field(None, description="Duty cycle recording duration (seconds)")
    duty_cycle_period: Optional[int] = Field(None, description="Duty cycle period (seconds)")
    note: Optional[str] = Field(None, max_length=250, description="Optional note")
    doi: Optional[str] = Field(None, max_length=255, description="DOI")

    @field_validator("date_time")
    @classmethod
    def validate_date_time_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        try:
            datetime.strptime(v, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            raise ValueError("date_time must be in format YYYY-MM-DD HH:mm:ss")
        return v

    @field_validator("filename_prefix")
    @classmethod
    def validate_filename_prefix(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if ".." in v or "/" in v or "\\" in v:
            raise ValueError("filename_prefix contains invalid path characters")
        return v

    @model_validator(mode="after")
    def require_date_source(self) -> "MediaCreate":
        if self.media_type != MediaType.PHOTO and not self.date_from_filename and not self.date_time:
            raise ValueError("Either date_time or date_from_filename=true must be provided")
        if self.media_type == MediaType.PHOTO:
            audio_only_fields = {
                "recording_gain_db",
                "duty_cycle_recording",
                "duty_cycle_period",
            }
            supplied = sorted(audio_only_fields & self.model_fields_set)
            if supplied:
                raise ValueError(
                    "Photo media must not include audio-only fields: " + ", ".join(supplied)
                )
        return self


class MediaCreateFailedItem(SQLModel):
    """A failed item in batch media creation."""
    file_upload_id: int
    reason: str


class MediaCreateResponse(SQLModel):
    """Response for submitted media batch processing."""
    queue_id: int | None = Field(default=None, description="Background queue ID")
    queued: list[int] = Field(default_factory=list, description="Successfully queued file_upload_ids")
    failed: list[MediaCreateFailedItem] = Field(default_factory=list, description="Failed items with reasons")


class MediaBase(SQLModel):
    """Base schema for Media with common fields."""
    filename: Optional[str] = None
    name: Optional[str] = None
    medium: Optional[str] = None
    note: Optional[str] = None
    doi: Optional[str] = None
    date_time: Optional[datetime] = None


class MediaUpdate(SQLModel):
    """Schema for updating base Media fields; technical settings are managed elsewhere."""
    name: Optional[str] = None
    medium: Optional[str] = None
    note: Optional[str] = None
    doi: Optional[str] = None
    date_time: Optional[str] = Field(None, description="Recording datetime in format YYYY-MM-DD HH:mm:ss")
    site_id: Optional[int] = None
    sensor_id: Optional[int] = None
    license_id: Optional[int] = None
    recording_gain_db: Optional[int] = None
    sampling_rate_hz: Optional[int] = None
    bit_depth: Optional[int] = None
    channel_num: Optional[int] = None
    duration_s: Optional[float] = None
    duty_cycle_recording: Optional[int] = None
    duty_cycle_period: Optional[int] = None

    @field_validator("date_time")
    @classmethod
    def validate_date_time_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        try:
            datetime.strptime(v, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            raise ValueError("date_time must be in format YYYY-MM-DD HH:mm:ss")
        return v


class MediaListPublic(MediaBase):
    """Schema for media list responses without content-derived dimensions."""
    media_id: int
    uuid: uuid.UUID
    media_type: str
    is_metadata: bool = False
    size_b: Optional[int] = None  # Python attribute name from model (maps to size_B in DB)
    md5_hash: Optional[str] = None
    uploader_id: Optional[int] = None
    uploader_name: Optional[str] = None
    creator_id: Optional[int] = None
    creator_name: Optional[str] = None
    site_id: Optional[int] = None
    site_name: Optional[str] = None
    theme_value: Optional[str] = None
    theme_source: Optional[str] = None
    sensor_id: Optional[int] = None
    sensor_name: Optional[str] = None
    license_id: Optional[int] = None
    license_name: Optional[str] = None
    duty_cycle_recording: Optional[int] = None
    duty_cycle_period: Optional[int] = None
    creation_date: datetime

    # Related collection / project (populated in detail view)
    collection_id: Optional[int] = None
    collection_name: Optional[str] = None
    project_id: Optional[int] = None
    project_name: Optional[str] = None

    # Audio URL for player (populated in detail view)
    audio_url: Optional[str] = None
    # Original file URL for non-audio media (populated in detail view)
    media_url: Optional[str] = None
    # Previews list (populated in detail view)
    previews: list[PreviewPublic] = Field(default_factory=list)

    audio_setting: Optional[AudioSettingPublic] = None
    photo_setting: Optional[PhotoSettingPublic] = None
    labels: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("date_time", "creation_date")
    def serialize_datetime(self, dt: Optional[datetime], _info):
        if dt is None:
            return None
            
        return dt.strftime("%Y-%m-%d %H:%M:%S")


class MediaPublic(MediaListPublic):
    """Schema for a media detail response including image dimensions."""
    image_width: Optional[int] = None
    image_height: Optional[int] = None


from app.csv_import import CsvImportResult

MetadataImportResponse = CsvImportResult


class MediaOption(SQLModel):
    """下拉选项 Schema：仅包含 media_id 与显示名称。 / Dropdown option schema: only media_id and display name."""
    media_id: int
    name: Optional[str] = None  # 优先使用 name，为空时前端可降级显示 filename
    media_type: str

    model_config = ConfigDict(from_attributes=True)


class MediaBrowseGalleryItem(SQLModel):
    """Gallery view item for media browsing."""
    media_id: int
    name: Optional[str] = None
    filename: Optional[str] = None
    media_type: str
    is_metadata: bool = False
    date_time: Optional[datetime] = None
    size_b: Optional[int] = None
    duration_s: Optional[float] = None
    sampling_rate_hz: Optional[int] = None
    bit_depth: Optional[int] = None
    channel_num: Optional[int] = None
    duty_cycle_period: Optional[int] = None
    duty_cycle_recording: Optional[int] = None
    label: Optional[str] = None
    preview_url: Optional[str] = None
    sphere: Optional[str] = None
    realm_name: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("date_time")
    def serialize_gallery_datetime(self, dt: Optional[datetime], _info):
        if dt is None:
            return None
        return dt.strftime("%Y-%m-%d %H:%M:%S")


class MediaBrowseListItem(SQLModel):
    """List view item for media browsing."""
    media_id: int
    name: Optional[str] = None
    filename: Optional[str] = None
    media_type: str
    is_metadata: bool = False
    site_id: Optional[int] = None
    site_name: Optional[str] = None
    sensor_id: Optional[int] = None
    sensor_name: Optional[str] = None
    license_id: Optional[int] = None
    license_name: Optional[str] = None
    medium: Optional[str] = None
    date_time: Optional[datetime] = None
    duration_s: Optional[float] = None
    sampling_rate_hz: Optional[int] = None
    bit_depth: Optional[int] = None
    channel_num: Optional[int] = None
    duty_cycle_period: Optional[int] = None
    duty_cycle_recording: Optional[int] = None
    label: Optional[str] = None
    preview_url: Optional[str] = None
    size_b: Optional[int] = None
    uploader_name: Optional[str] = None
    creator_name: Optional[str] = None
    note: Optional[str] = None
    doi: Optional[str] = None
    sphere: Optional[str] = None
    topography_m: Optional[float] = None
    freshwater_depth_m: Optional[float] = None
    realm_name: Optional[str] = None
    biome_name: Optional[str] = None
    functional_type_name: Optional[str] = None
    hierarchy: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("date_time")
    def serialize_list_datetime(self, dt: Optional[datetime], _info):
        if dt is None:
            return None
        return dt.strftime("%Y-%m-%d %H:%M:%S")


class MediaTimelineItem(SQLModel):
    """Schema for a single timeline item in media timeline view."""
    media_id: int
    media_type: str
    name: str = ""
    start_date: datetime
    end_date: datetime
    duration_s: Optional[float] = None
    site_id: Optional[int] = None
    site_key: str = "nogeo"
    site_name: str = "not geo-referenced"
    duty_cycle_period: Optional[int] = None
    duty_cycle_recording: Optional[int] = None
    is_metadata: bool = False
    creator_name: str = ""
    realm: Optional[str] = None
    item_count: int = 1

    @field_serializer("start_date", "end_date")
    @classmethod
    def serialize_datetime(cls, dt: datetime) -> str:
        return dt.strftime("%Y-%m-%d %H:%M:%S")


class MediaTimelineRange(SQLModel):
    """Schema for media timeline window range."""
    min: Optional[datetime] = None
    max: Optional[datetime] = None

    @field_serializer("min", "max")
    @classmethod
    def serialize_datetime(cls, dt: Optional[datetime]) -> Optional[str]:
        if dt is None:
            return None
        return dt.strftime("%Y-%m-%d %H:%M:%S")


class MediaTimelineResponse(SQLModel):
    """Schema for media timeline payload."""
    project_id: int
    collection_id: Optional[int] = None
    items: list[MediaTimelineItem] = Field(default_factory=list)
    time_range: MediaTimelineRange
    has_more: bool = False


class MediaCollectionLinksSyncRequest(SQLModel):
    """Request schema for syncing collection links across multiple media records."""

    media_ids: list[int] = Field(..., min_length=1, description="Media IDs to update")
    collection_ids: list[int] = Field(default_factory=list, description="Collection IDs to set on every media")

    model_config = ConfigDict(extra="forbid")


class MediaBatchFailedItem(SQLModel):
    """Failed item returned by batch media operations."""

    media_id: int
    status_code: int
    message: str


class MediaBatchOperationResponse(SQLModel):
    """Common response for batch media relation operations."""

    succeeded: list[int] = Field(default_factory=list)
    failed: list[MediaBatchFailedItem] = Field(default_factory=list)


class MediaLinkCollectionItem(SQLModel):
    """Collection item used by media-collection link dialog."""
    collection_id: int
    name: str
    selected: bool = False
    duplicate_project_ids: list[int] = Field(default_factory=list)


class MediaLinkCurrentProject(SQLModel):
    """Current project block for media-collection link dialog."""
    project_id: int
    project_name: str
    collections: list[MediaLinkCollectionItem] = Field(default_factory=list)


class MediaLinkOtherProject(SQLModel):
    """Other project block for media-collection link dialog."""
    project_id: int
    project_name: str
    collections: list[MediaLinkCollectionItem] = Field(default_factory=list)


class MediaCollectionLinkOptionsResponse(SQLModel):
    """Response schema for media-collection link dialog options."""
    current_project: MediaLinkCurrentProject
    other_projects: list[MediaLinkOtherProject] = Field(default_factory=list)
    unassigned_collections: list[MediaLinkCollectionItem] = Field(default_factory=list)
    selected_collection_ids: list[int] = Field(default_factory=list)


class MediaNavigationItem(SQLModel):
    """A single media item used in navigation response."""
    media_id: int
    name: Optional[str] = None


class MediaNavigation(SQLModel):
    """Navigation response for prev/next media within the same collection."""
    prev: Optional[MediaNavigationItem] = None
    next: Optional[MediaNavigationItem] = None
