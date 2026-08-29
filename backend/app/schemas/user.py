from datetime import datetime
from typing import Literal, Optional

from pydantic import EmailStr, field_serializer, field_validator
from sqlmodel import Field, SQLModel

from app.models import UserPreference


def _normalize_hex_color(v: Optional[str]) -> Optional[str]:
    if v is None:
        return v
    if len(v) != 7 or not v.startswith("#") or any(ch not in "0123456789ABCDEFabcdef" for ch in v[1:]):
        raise ValueError("color must be a hex value like #RRGGBB")
    return v.upper()


class UserCreate(SQLModel):
    """Schema for creating a new user."""
    username: str = Field(min_length=3, max_length=20)
    name: str = Field(max_length=100)
    email: EmailStr = Field(max_length=100)
    password: str = Field(min_length=8, max_length=128)
    orcid: Optional[str] = Field(default=None, max_length=100)
    color: str = Field(default="#FFFFFF", min_length=7, max_length=7)
    active: bool = Field(default=True)

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: str) -> str:
        return _normalize_hex_color(v) or "#FFFFFF"


class UserRegister(SQLModel):
    """Schema for user self-registration."""
    username: str = Field(min_length=3, max_length=20)
    name: str = Field(max_length=100)
    email: EmailStr = Field(max_length=100)
    password: str = Field(min_length=8, max_length=128)


# Properties to receive via API on update, all are optional
class UserUpdate(SQLModel):
    """Schema for updating a user (admin). Password cannot be updated here."""
    username: Optional[str] = Field(default=None, min_length=3, max_length=20)
    name: Optional[str] = Field(default=None, max_length=100)
    email: Optional[EmailStr] = Field(default=None, max_length=100)
    orcid: Optional[str] = Field(default=None, max_length=100)
    color: Optional[str] = Field(default=None, min_length=7, max_length=7)
    active: Optional[bool] = Field(default=None)

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: Optional[str]) -> Optional[str]:
        return _normalize_hex_color(v)


class UserUpdateMe(SQLModel):
    """Schema for user updating their own profile."""
    name: Optional[str] = Field(default=None, max_length=100)
    email: Optional[EmailStr] = Field(default=None, max_length=100)
    orcid: Optional[str] = Field(default=None, max_length=100)
    color: Optional[str] = Field(default=None, min_length=7, max_length=7)

    @field_validator("name", "email", mode="before")
    @classmethod
    def validate_required_profile_text(cls, v: object) -> object:
        if v is None or (isinstance(v, str) and not v.strip()):
            raise ValueError("field cannot be empty")
        return v

    @field_validator("color")
    @classmethod
    def validate_color(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            raise ValueError("color cannot be empty")
        return _normalize_hex_color(v)


_FFT_VALID_VALUES = {128, 256, 512, 1024, 2048, 4096}


class UserPreferenceUpdate(SQLModel):
    """Schema for updating user preferences (FFT size, theme, language, etc.)."""
    fft: Optional[int] = Field(default=None, description="FFT 窗口大小偏好 / Default FFT window size")
    theme: Optional[Literal["light", "dark", "auto"]] = Field(
        default=None,
        description="主题（light/dark/auto）/ Theme",
    )
    language: Optional[str] = Field(default=None, max_length=10, description="界面语言 / Interface language")
    timezone: Optional[str] = Field(default=None, max_length=50, description="时区 / Timezone")
    notifications_enabled: Optional[bool] = Field(default=None, description="是否启用通知 / Enable notifications")

    @field_validator("fft")
    @classmethod
    def validate_fft(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v not in _FFT_VALID_VALUES:
            raise ValueError(f"fft must be one of {sorted(_FFT_VALID_VALUES)}")
        return v


class UpdatePassword(SQLModel):
    """Schema for user updating their own password."""
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class AdminUpdatePassword(SQLModel):
    """Schema for admin updating a user's password."""
    new_password: str = Field(min_length=8, max_length=128)


class ContributorPublic(SQLModel):
    """Schema for contributor details (project or collection)."""
    contribution_role: Optional[str] = None
    added_date: datetime

    @field_serializer("added_date")
    @classmethod
    def serialize_added_date(cls, value: datetime) -> str:
        return value.strftime("%Y-%m-%d %H:%M:%S")


# Properties to return via API
class UserPublic(SQLModel):
    """Schema for public user response."""
    user_id: int
    username: str
    name: str
    email: str
    orcid: Optional[str] = None
    color: str = "#FFFFFF"
    active: bool
    role_id: int
    preference: Optional[UserPreference] = None
    contrib: Optional[str] = None
    is_project_admin: bool = False
    is_admin: bool

    # Convert None to empty string for nullable string fields
    @field_serializer('orcid')
    @classmethod
    def convert_none_to_empty_string(cls, v: Optional[str]) -> str:
        return v if v is not None else ""


class CurrentUserPublic(UserPublic):
    """Current-user response with capabilities evaluated for the requested scope."""
    can_write_audio: bool = False

class UserListPublic(SQLModel):
    """Schema for user list/export response (without preferences)."""
    user_id: int
    username: str
    name: str
    email: str
    orcid: Optional[str] = None
    color: str = "#FFFFFF"
    active: bool
    role_id: int
    contrib: Optional[str] = None
    is_admin: bool

    @field_serializer('orcid')
    @classmethod
    def convert_none_to_empty_string(cls, v: Optional[str]) -> str:
        return v if v is not None else ""

class UserOption(SQLModel):
    """Schema for user dropdown options."""
    user_id: int
    name: str


class CreatorOption(SQLModel):
    """Compact user representation for media Creator selectors."""
    user_id: int
    name: str
    username: str
    is_admin: bool

class SetContributorRequest(SQLModel):
    """Schema for setting a user as a contributor."""
    project_id: int = Field(description="The project ID")
    collection_id: Optional[int] = Field(default=None, description="The collection ID. If provided, sets collection contributor instead of project contributor.")
    contribution_role: Optional[str] = Field(default=None, description="Role of the contributor (e.g., PI, Field Recorder)")

# Constants for predefined contributor roles
PROJECT_CONTRIBUTOR_ROLES = [
    "PI",
    "Researcher",
    "Field Technician",
    "Data Analyst",
]

COLLECTION_CONTRIBUTOR_ROLES = [
    "Field Recorder", 
    "Annotator", 
    "Reviewer", 
    "Data Curator",
]
