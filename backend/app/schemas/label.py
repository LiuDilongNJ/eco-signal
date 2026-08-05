from datetime import datetime
from typing import Literal, Optional

from pydantic import ConfigDict, Field, field_serializer, field_validator
from sqlmodel import SQLModel

LabelType = Literal["private", "public"]


class LabelBase(SQLModel):
    """Base schema for Label."""
    name: str


class LabelPublic(LabelBase):
    """Schema for Label public response."""
    label_id: int
    creator_id: Optional[int] = None
    type: str
    creation_date: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("creation_date")
    def serialize_datetime(self, dt: datetime, _info):
        return dt.strftime("%Y-%m-%d %H:%M:%S")


class LabelAdminPublic(LabelPublic):
    """Schema for admin label settings responses."""

    creator_name: Optional[str] = None


class MediaSetLabelsRequest(SQLModel):
    """Request schema for setting one label across multiple media records."""

    media_ids: list[int] = Field(..., min_length=1, description="Media IDs to label. / 要设置标签的媒体 ID。")
    label_id: int | None = Field(
        default=None,
        description="Exactly one label id, or null to clear. / 单个标签 ID；传 null 表示清除。",
    )

    model_config = ConfigDict(extra="forbid")


class LabelCreateRequest(SQLModel):
    """Request schema for creating a label."""
    name: str

    model_config = ConfigDict(extra="forbid")


class LabelAdminCreateRequest(SQLModel):
    """Request schema for admin label creation."""

    name: str = Field(max_length=20)
    type: LabelType = "private"

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("Label name cannot be empty")
        return name


class LabelAdminUpdateRequest(SQLModel):
    """Request schema for admin label updates."""

    name: Optional[str] = Field(default=None, max_length=20)
    type: Optional[LabelType] = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        name = value.strip()
        if not name:
            raise ValueError("Label name cannot be empty")
        return name
