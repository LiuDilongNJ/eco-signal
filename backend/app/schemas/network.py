from datetime import datetime

from pydantic import field_serializer, field_validator
from sqlmodel import SQLModel

from app.utils import validate_optional_http_url, validate_required_http_url

from app.schemas.coordinates import Latitude, Longitude


class NodeStats(SQLModel):
    users: int = 0
    projects: int = 0
    collections: int = 0
    audios: int = 0
    photos: int = 0
    videos: int = 0
    annotations: int = 0
    sites: int = 0


class NetworkNodePublic(SQLModel):
    id: int
    name: str
    app_url: str
    latitude: float | None
    longitude: float | None
    is_local: bool
    shared: bool
    stats: NodeStats
    last_synced_at: datetime | None

    @field_serializer("last_synced_at")
    def serialize_last_synced_at(self, dt: datetime | None) -> str | None:
        if dt is None:
            return None
        return dt.strftime("%Y-%m-%d %H:%M:%S")


class NetworkSettings(SQLModel):
    server_name: str = ""
    app_url: str = ""
    host_url: str = ""
    latitude: float | None = None
    longitude: float | None = None
    shared: bool = False
    federation_secret: str = ""


class NetworkSettingsUpdate(SQLModel):
    server_name: str | None = None
    app_url: str | None = None
    host_url: str | None = None
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    shared: bool | None = None
    federation_secret: str | None = None

    @field_validator("app_url", "host_url")
    @classmethod
    def validate_urls(cls, value: str | None) -> str | None:
        return validate_optional_http_url(value)


class NodeRegistration(SQLModel):
    app_url: str
    name: str
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    stats: NodeStats | None = None
    shared: bool = True

    @field_validator("app_url")
    @classmethod
    def validate_app_url(cls, value: str) -> str:
        return validate_required_http_url(value)


class SyncResult(SQLModel):
    synced: int
    message: str = "ok"
