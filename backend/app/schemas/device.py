import uuid as uuid_lib
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import ConfigDict, field_serializer, field_validator, model_validator
from sqlmodel import Field, SQLModel

from app.utils import validate_required_http_url
from app.csv_import import ImportResult


def _normalize_required_device_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Name is required")
    return value.strip()


def _normalize_optional_serial_number(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("serial_number must be a string")
    stripped = value.strip()
    return stripped or None


class RecorderOption(SQLModel):
    """Recorder option for dropdown menus."""
    recorder_id: int
    name: str


class MicrophoneOption(SQLModel):
    """Microphone option for dropdown menus."""
    microphone_id: int
    name: str


class SiteOption(SQLModel):
    """Site option for dropdown menus."""
    site_id: int
    name: str


class LicenseOption(SQLModel):
    """License option for dropdown menus."""
    license_id: int
    name: str


class SensorOption(SQLModel):
    """Sensor option for dropdown menus."""
    sensor_id: int
    name: str
    sensor_type: str
    serial_number: Optional[str] = None


class CameraOption(SQLModel):
    """Camera option for dropdown menus."""
    camera_id: int
    name: str


class LensOption(SQLModel):
    """Lens option for dropdown menus."""
    lens_id: int
    name: str


DeviceImportResponse = ImportResult



class LicenseCreate(SQLModel):
    """Schema for creating a license."""
    name: str
    link: str

    @field_validator("link")
    @classmethod
    def validate_link(cls, value: str) -> str:
        return validate_required_http_url(value)


class LicenseUpdate(SQLModel):
    """Schema for updating a license."""
    name: Optional[str] = None
    link: Optional[str] = None

    @field_validator("link")
    @classmethod
    def validate_link(cls, value: Optional[str]) -> str:
        return validate_required_http_url(value)


class LicensePublic(SQLModel):
    """Public license response schema."""
    license_id: int
    name: str
    link: str



class RecorderMicrophoneInfo(SQLModel):
    """Microphone info embedded in recorder detail."""
    microphone_id: int
    name: Optional[str] = None
    notes: Optional[str] = None


class RecorderCreate(SQLModel):
    """Schema for creating a recorder."""
    name: Optional[str] = None
    version: Optional[str] = None
    brand: Optional[str] = None


class RecorderUpdate(SQLModel):
    """Schema for updating a recorder."""
    name: Optional[str] = None
    version: Optional[str] = None
    brand: Optional[str] = None


class RecorderPublic(SQLModel):
    """Public recorder response schema."""
    recorder_id: int
    uuid: uuid_lib.UUID
    name: Optional[str] = None
    version: Optional[str] = None
    brand: Optional[str] = None
    microphones: list[RecorderMicrophoneInfo] = []


class RecorderListItem(SQLModel):
    """Recorder list item schema (without microphone detail)."""
    recorder_id: int
    uuid: uuid_lib.UUID
    name: Optional[str] = None
    version: Optional[str] = None
    brand: Optional[str] = None
    microphone_count: int = 0


class RecorderMicrophoneCreate(SQLModel):
    """Schema for associating a microphone with a recorder."""
    model_config = ConfigDict(extra="forbid")

    microphone_id: int
    notes: Optional[str] = None



class MicrophoneCreate(SQLModel):
    """Schema for creating a microphone."""
    name: Optional[str] = None
    microphone_element: Optional[str] = None
    sensitivity: Optional[int] = None
    signal_to_noise_ratio: Optional[int] = None


class MicrophoneUpdate(SQLModel):
    """Schema for updating a microphone."""
    name: Optional[str] = None
    microphone_element: Optional[str] = None
    sensitivity: Optional[int] = None
    signal_to_noise_ratio: Optional[int] = None


class MicrophoneRecorderInfo(SQLModel):
    """Recorder info embedded in microphone detail."""
    recorder_id: int
    name: Optional[str] = None
    notes: Optional[str] = None


class MicrophonePublic(SQLModel):
    """Public microphone response schema."""
    microphone_id: int
    uuid: uuid_lib.UUID
    name: Optional[str] = None
    microphone_element: Optional[str] = None
    sensitivity: Optional[int] = None
    signal_to_noise_ratio: Optional[int] = None
    recorders: list[MicrophoneRecorderInfo] = []


class MicrophoneListItem(SQLModel):
    """Microphone list item schema with associated recorder count."""
    microphone_id: int
    uuid: uuid_lib.UUID
    name: Optional[str] = None
    microphone_element: Optional[str] = None
    sensitivity: Optional[int] = None
    signal_to_noise_ratio: Optional[int] = None
    recorder_count: int = 0



class CameraLensInfo(SQLModel):
    """Lens info embedded in camera detail."""
    lens_id: int
    name: Optional[str] = None
    notes: Optional[str] = None


class CameraCreate(SQLModel):
    """Schema for creating a camera."""
    name: str = Field(max_length=100)
    version: Optional[str] = None
    brand: Optional[str] = None

    _normalize_name = field_validator("name")(_normalize_required_device_name)


class CameraUpdate(SQLModel):
    """Schema for updating a camera."""
    name: Optional[str] = None
    version: Optional[str] = None
    brand: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def validate_name_when_provided(cls, data: Any) -> Any:
        if isinstance(data, dict) and "name" in data:
            return {**data, "name": _normalize_required_device_name(data["name"])}
        return data


class CameraPublic(SQLModel):
    """Public camera response schema."""
    camera_id: int
    uuid: uuid_lib.UUID
    name: Optional[str] = None
    version: Optional[str] = None
    brand: Optional[str] = None
    lenses: list[CameraLensInfo] = []


class CameraListItem(SQLModel):
    """Camera list item schema (without lens detail)."""
    camera_id: int
    uuid: uuid_lib.UUID
    name: Optional[str] = None
    version: Optional[str] = None
    brand: Optional[str] = None
    lens_count: int = 0


class CameraLensCreate(SQLModel):
    """Schema for associating a lens with a camera."""
    model_config = ConfigDict(extra="forbid")

    lens_id: int
    notes: Optional[str] = None



class LensCreate(SQLModel):
    """Schema for creating a lens."""
    name: str = Field(max_length=100)
    focal_length: Optional[str] = None
    max_aperture: Optional[str] = None
    brand: Optional[str] = None

    _normalize_name = field_validator("name")(_normalize_required_device_name)


class LensUpdate(SQLModel):
    """Schema for updating a lens."""
    name: Optional[str] = None
    focal_length: Optional[str] = None
    max_aperture: Optional[str] = None
    brand: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def validate_name_when_provided(cls, data: Any) -> Any:
        if isinstance(data, dict) and "name" in data:
            return {**data, "name": _normalize_required_device_name(data["name"])}
        return data


class LensCameraInfo(SQLModel):
    """Camera info embedded in lens detail."""
    camera_id: int
    name: Optional[str] = None
    notes: Optional[str] = None


class LensPublic(SQLModel):
    """Public lens response schema."""
    lens_id: int
    uuid: uuid_lib.UUID
    name: Optional[str] = None
    focal_length: Optional[str] = None
    max_aperture: Optional[str] = None
    brand: Optional[str] = None
    cameras: list[LensCameraInfo] = []


class LensListItem(SQLModel):
    """Lens list item schema with associated camera count."""
    lens_id: int
    uuid: uuid_lib.UUID
    name: Optional[str] = None
    focal_length: Optional[str] = None
    max_aperture: Optional[str] = None
    brand: Optional[str] = None
    camera_count: int = 0



class SensorCreate(SQLModel):
    """Schema for creating a sensor."""
    model_config = ConfigDict(extra="forbid")

    name: str
    sensor_type: Literal["audio", "photo"]
    recorder_id: Optional[int] = None
    microphone_id: Optional[int] = None
    camera_id: Optional[int] = None
    lens_id: Optional[int] = None
    description: Optional[str] = None
    serial_number: Optional[str] = Field(default=None, max_length=100)

    _normalize_serial_number = field_validator("serial_number")(_normalize_optional_serial_number)


class SensorUpdate(SQLModel):
    """Schema for updating a sensor."""
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    sensor_type: Optional[Literal["audio", "photo"]] = None
    recorder_id: Optional[int] = None
    microphone_id: Optional[int] = None
    camera_id: Optional[int] = None
    lens_id: Optional[int] = None
    description: Optional[str] = None
    serial_number: Optional[str] = Field(default=None, max_length=100)

    _normalize_serial_number = field_validator("serial_number")(_normalize_optional_serial_number)


class SensorPublic(SQLModel):
    """Public sensor response schema with device names."""
    sensor_id: int
    uuid: uuid_lib.UUID
    name: str
    sensor_type: str
    recorder_id: Optional[int] = None
    recorder_name: Optional[str] = None
    microphone_id: Optional[int] = None
    microphone_name: Optional[str] = None
    camera_id: Optional[int] = None
    camera_name: Optional[str] = None
    lens_id: Optional[int] = None
    lens_name: Optional[str] = None
    description: Optional[str] = None
    serial_number: Optional[str] = None
    creation_date: datetime

    @field_serializer("creation_date")
    @classmethod
    def serialize_creation_date(cls, value: datetime) -> str:
        return value.strftime("%Y-%m-%d %H:%M:%S")
