"""
Device database models.

This module contains Recorder, Microphone, Camera, Lens, Sensor and related models.
"""
import uuid as uuid_lib
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.media import Media


class Recorder(SQLModel, table=True):
    """Audio/video recording device models."""
    __tablename__ = "recorder"
    
    recorder_id: int = Field(default=None, primary_key=True)
    uuid: uuid_lib.UUID = Field(
        default_factory=uuid_lib.uuid4,
        unique=True,
        index=True
    )
    name: Optional[str] = Field(default=None, max_length=100)
    version: Optional[str] = Field(default=None, max_length=100)
    brand: Optional[str] = Field(default=None, max_length=100)
    
    # Relationships
    recorder_microphones: list["RecorderMicrophone"] = Relationship(back_populates="recorder")
    sensors: list["Sensor"] = Relationship(back_populates="recorder")


class Microphone(SQLModel, table=True):
    """Microphone specifications."""
    __tablename__ = "microphone"
    
    microphone_id: int = Field(default=None, primary_key=True)
    uuid: uuid_lib.UUID = Field(
        default_factory=uuid_lib.uuid4,
        unique=True,
        index=True
    )
    name: Optional[str] = Field(default=None, max_length=100)
    microphone_element: Optional[str] = Field(default=None, max_length=100)
    sensitivity: Optional[int] = Field(default=None)
    signal_to_noise_ratio: Optional[int] = Field(default=None)
    
    # Relationships
    sensors: list["Sensor"] = Relationship(back_populates="microphone")


class RecorderMicrophone(SQLModel, table=True):
    """Many-to-many: Compatible microphones for recorders."""
    __tablename__ = "recorder_microphone"
    
    recorder_id: int = Field(
        foreign_key="recorder.recorder_id",
        primary_key=True,
        ondelete="CASCADE"
    )
    microphone_id: int = Field(
        foreign_key="microphone.microphone_id",
        primary_key=True,
        ondelete="CASCADE"
    )
    notes: Optional[str] = Field(default=None)
    
    # Relationships
    recorder: Optional[Recorder] = Relationship(back_populates="recorder_microphones")
    microphone: Optional[Microphone] = Relationship()


class Camera(SQLModel, table=True):
    """Camera device models for photo/video capture."""
    __tablename__ = "camera"
    
    camera_id: int = Field(default=None, primary_key=True)
    uuid: uuid_lib.UUID = Field(
        default_factory=uuid_lib.uuid4,
        unique=True,
        index=True
    )
    name: Optional[str] = Field(default=None, max_length=100)
    version: Optional[str] = Field(default=None, max_length=100)
    brand: Optional[str] = Field(default=None, max_length=100)
    
    # Relationships
    camera_lenses: list["CameraLens"] = Relationship(back_populates="camera")
    sensors: list["Sensor"] = Relationship(back_populates="camera")


class Lens(SQLModel, table=True):
    """Camera lens specifications."""
    __tablename__ = "lens"
    
    lens_id: int = Field(default=None, primary_key=True)
    uuid: uuid_lib.UUID = Field(
        default_factory=uuid_lib.uuid4,
        unique=True,
        index=True
    )
    name: Optional[str] = Field(default=None, max_length=100)
    focal_length: Optional[str] = Field(default=None, max_length=50)
    max_aperture: Optional[str] = Field(default=None, max_length=20)
    brand: Optional[str] = Field(default=None, max_length=100)
    
    # Relationships
    sensors: list["Sensor"] = Relationship(back_populates="lens")


class CameraLens(SQLModel, table=True):
    """Many-to-many: Compatible lenses for cameras."""
    __tablename__ = "camera_lens"
    
    camera_id: int = Field(
        foreign_key="camera.camera_id",
        primary_key=True,
        ondelete="CASCADE"
    )
    lens_id: int = Field(
        foreign_key="lens.lens_id",
        primary_key=True,
        ondelete="CASCADE"
    )
    notes: Optional[str] = Field(default=None)
    
    # Relationships
    camera: Optional[Camera] = Relationship(back_populates="camera_lenses")
    lens: Optional[Lens] = Relationship()


class Sensor(SQLModel, table=True):
    """Specific sensor configurations combining devices."""
    __tablename__ = "sensor"
    
    sensor_id: int = Field(default=None, primary_key=True)
    uuid: uuid_lib.UUID = Field(
        default_factory=uuid_lib.uuid4,
        unique=True,
        index=True
    )
    name: str = Field(max_length=255)
    sensor_type: str = Field(max_length=20, index=True)  # 'audio' or 'photo'
    recorder_id: Optional[int] = Field(
        default=None,
        foreign_key="recorder.recorder_id",
        ondelete="CASCADE",
        index=True
    )
    microphone_id: Optional[int] = Field(
        default=None,
        foreign_key="microphone.microphone_id",
        ondelete="CASCADE",
        index=True
    )
    camera_id: Optional[int] = Field(
        default=None,
        foreign_key="camera.camera_id",
        ondelete="CASCADE",
        index=True
    )
    lens_id: Optional[int] = Field(
        default=None,
        foreign_key="lens.lens_id",
        ondelete="CASCADE",
        index=True
    )
    description: Optional[str] = Field(default=None)
    serial_number: Optional[str] = Field(default=None, max_length=100)
    creation_date: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    recorder: Optional[Recorder] = Relationship(back_populates="sensors")
    microphone: Optional[Microphone] = Relationship(back_populates="sensors")
    camera: Optional[Camera] = Relationship(back_populates="sensors")
    lens: Optional[Lens] = Relationship(back_populates="sensors")
    media: list["Media"] = Relationship(back_populates="sensor")
