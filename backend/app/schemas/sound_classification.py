from pydantic import ConfigDict, field_validator
from sqlmodel import Field, SQLModel


class SoundClassificationWrite(SQLModel):
    """Validated fields shared by sound classification create and update requests."""

    soundscape_component: str = Field(min_length=1, max_length=200)
    sound_type: str | None = Field(default=None, max_length=30)

    @field_validator("soundscape_component", mode="before")
    @classmethod
    def normalize_soundscape_component(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("soundscape_component is required")
        return value

    @field_validator("sound_type", mode="before")
    @classmethod
    def normalize_sound_type(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


class SoundClassificationCreate(SoundClassificationWrite):
    """Schema for creating a sound classification."""


class SoundClassificationUpdate(SoundClassificationWrite):
    """Schema for replacing a sound classification."""


class SoundClassificationPublic(SQLModel):
    """Public sound classification representation."""

    sound_id: int
    soundscape_component: str | None = None
    sound_type: str | None = None

    model_config = ConfigDict(from_attributes=True)


from app.csv_import import ImportResult

SoundClassificationImportResponse = ImportResult
