"""
Media database models.

This module contains Media, MediaCollection, AudioSetting, PhotoSetting, Preview, License models.
"""
import uuid as uuid_lib
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.site import Site
    from app.models.device import Sensor
    from app.models.collection import Collection
    from app.models.annotation import Annotation
    from app.models.index import IndexLog
    from app.models.label import LabelMedia


class License(SQLModel, table=True):
    """Content licenses (CC-BY, CC0, etc.)."""
    __tablename__ = "license"
    
    license_id: int = Field(default=None, primary_key=True)
    name: str = Field(max_length=100)
    link: str = Field(max_length=255)
    
    # Relationships
    media: list["Media"] = Relationship(back_populates="license")


class AudioSetting(SQLModel, table=True):
    """Audio-specific technical settings for media recordings."""
    __tablename__ = "audio_setting"

    audio_setting_id: int = Field(default=None, primary_key=True)
    recording_gain_db: Optional[int] = Field(default=None)
    sampling_rate_hz: int = Field(default=44100, index=True)
    bit_depth: Optional[int] = Field(default=16, index=True)
    channel_num: Optional[int] = Field(default=1)
    duration_s: float
    creation_date: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    media: list["Media"] = Relationship(back_populates="audio_setting")


class PhotoSetting(SQLModel, table=True):
    """Photo/video-specific technical settings for media."""
    __tablename__ = "photo_setting"
    
    photo_setting_id: int = Field(default=None, primary_key=True)
    exposure_ms: Optional[float] = Field(default=None)
    aperture: Optional[float] = Field(default=None)
    iso: Optional[int] = Field(default=None)
    creation_date: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    media: list["Media"] = Relationship(back_populates="photo_setting")


class MediaBase(SQLModel):
    """Base properties for Media."""
    media_type: str = Field(max_length=20, index=True)  # 'audio', 'photo', 'video'
    is_metadata: bool = Field(default=False, index=True)
    directory: Optional[int] = Field(default=None)
    filename: Optional[str] = Field(default=None, max_length=250)
    name: Optional[str] = Field(default=None, max_length=250)
    medium: Optional[str] = Field(default=None, max_length=50)
    duty_cycle_recording: Optional[int] = Field(default=None)
    duty_cycle_period: Optional[int] = Field(default=None)
    note: Optional[str] = Field(default=None, max_length=250)
    date_time: Optional[datetime] = Field(default=None, index=True)
    size_b: Optional[int] = Field(default=None)
    md5_hash: Optional[str] = Field(default=None, max_length=32, index=True)
    doi: Optional[str] = Field(default=None, max_length=255)


class Media(MediaBase, table=True):
    """Media files (audio recordings, photos, videos) with core metadata."""
    __tablename__ = "media"
    
    media_id: int = Field(default=None, primary_key=True)
    uuid: uuid_lib.UUID = Field(
        default_factory=uuid_lib.uuid4,
        unique=True,
        index=True
    )
    uploader_id: Optional[int] = Field(
        default=None,
        foreign_key="user.user_id",
        ondelete="SET NULL",
        index=True
    )
    creator_id: Optional[int] = Field(
        default=None,
        foreign_key="user.user_id",
        ondelete="RESTRICT",
        index=True
    )
    site_id: Optional[int] = Field(
        default=None,
        foreign_key="site.site_id",
        ondelete="SET NULL",
        index=True
    )
    sensor_id: Optional[int] = Field(
        default=None,
        foreign_key="sensor.sensor_id",
        ondelete="RESTRICT",
        index=True
    )
    license_id: Optional[int] = Field(
        default=None,
        foreign_key="license.license_id",
        ondelete="RESTRICT"
    )
    audio_setting_id: Optional[int] = Field(
        default=None,
        foreign_key="audio_setting.audio_setting_id",
        ondelete="SET NULL",
        index=True
    )
    photo_setting_id: Optional[int] = Field(
        default=None,
        foreign_key="photo_setting.photo_setting_id",
        ondelete="SET NULL",
        index=True
    )
    creation_date: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    uploader: Optional["User"] = Relationship(
        back_populates="uploaded_media",
        sa_relationship_kwargs={"foreign_keys": "[Media.uploader_id]"}
    )
    creator: Optional["User"] = Relationship(
        back_populates="created_media",
        sa_relationship_kwargs={"foreign_keys": "[Media.creator_id]"}
    )
    site: Optional["Site"] = Relationship(back_populates="media")
    sensor: Optional["Sensor"] = Relationship(back_populates="media")
    license: Optional[License] = Relationship(back_populates="media")
    audio_setting: Optional[AudioSetting] = Relationship(back_populates="media")
    photo_setting: Optional[PhotoSetting] = Relationship(back_populates="media")
    media_collections: list["MediaCollection"] = Relationship(
        back_populates="media",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    previews: list["Preview"] = Relationship(
        back_populates="media",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    annotations: list["Annotation"] = Relationship(
        back_populates="media",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    index_logs: list["IndexLog"] = Relationship(
        back_populates="media",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    label_media: list["LabelMedia"] = Relationship(
        back_populates="media",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

    @property
    def uploader_name(self) -> Optional[str]:
        return self.uploader.name if self.uploader else None

    @property
    def creator_name(self) -> Optional[str]:
        return self.creator.name if self.creator else None


class MediaCollection(SQLModel, table=True):
    """Many-to-many: Media can belong to multiple collections."""
    __tablename__ = "media_collection"
    
    media_id: int = Field(
        foreign_key="media.media_id",
        primary_key=True,
        ondelete="CASCADE"
    )
    collection_id: int = Field(
        foreign_key="collection.collection_id",
        primary_key=True,
        ondelete="CASCADE"
    )
    added_by: int = Field(
        foreign_key="user.user_id",
        ondelete="RESTRICT",
        index=True
    )
    added_date: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    media: Optional[Media] = Relationship(back_populates="media_collections")
    collection: Optional["Collection"] = Relationship(back_populates="media_collections")


class Preview(SQLModel, table=True):
    """Preview representations for media: spectrograms/waveforms for audio, thumbnails for photos/videos."""
    __tablename__ = "preview"
    
    preview_id: int = Field(default=None, primary_key=True)
    media_id: int = Field(
        foreign_key="media.media_id",
        ondelete="CASCADE",
        index=True
    )
    filename: str = Field(max_length=250)
    type: str = Field(max_length=30, index=True)  # 'spectrogram', 'waveform', 'thumbnail'
    created_date: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    media: Optional[Media] = Relationship(back_populates="previews")
