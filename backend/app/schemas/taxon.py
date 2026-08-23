from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import ConfigDict, field_serializer, field_validator, model_validator
from sqlmodel import Field, SQLModel

TaxonRank = Literal["class", "order", "family", "genus", "species"]


def _inject_lowest_col_id(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        payload = dict(value)
    else:
        payload = {
            "taxon_id": getattr(value, "taxon_id", None),
            "cached_scientific_name": getattr(value, "cached_scientific_name", None),
            "cached_common_name": getattr(value, "cached_common_name", None),
            "col_species_id": getattr(value, "col_species_id", None),
            "col_genus_id": getattr(value, "col_genus_id", None),
            "col_family_id": getattr(value, "col_family_id", None),
            "col_order_id": getattr(value, "col_order_id", None),
            "col_class_id": getattr(value, "col_class_id", None),
            "taxonomy_source": getattr(value, "taxonomy_source", None),
            "creation_date": getattr(value, "creation_date", None),
            "last_synced": getattr(value, "last_synced", None),
        }

    lowest_col_id = None
    if payload.get("col_species_id"):
        lowest_col_id = payload["col_species_id"]
    elif payload.get("col_genus_id"):
        lowest_col_id = payload["col_genus_id"]
    elif payload.get("col_family_id"):
        lowest_col_id = payload["col_family_id"]
    elif payload.get("col_order_id"):
        lowest_col_id = payload["col_order_id"]
    elif payload.get("col_class_id"):
        lowest_col_id = payload["col_class_id"]

    payload["lowest_col_id"] = lowest_col_id
    return payload


class TaxonPublic(SQLModel):
    """Schema for public taxon information."""
    taxon_id: int
    col_species_id: Optional[str] = None
    col_genus_id: Optional[str] = None
    col_family_id: Optional[str] = None
    col_order_id: Optional[str] = None
    col_class_id: Optional[str] = None
    cached_scientific_name: Optional[str] = None
    cached_common_name: Optional[str] = None
    taxonomy_source: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class TaxonListItem(SQLModel):
    """Schema for taxon list items (admin view)."""
    taxon_id: int
    cached_scientific_name: Optional[str] = None
    cached_common_name: Optional[str] = None
    col_species_id: Optional[str] = None
    col_genus_id: Optional[str] = None
    col_family_id: Optional[str] = None
    col_order_id: Optional[str] = None
    col_class_id: Optional[str] = None
    col_species_name: Optional[str] = None
    col_genus_name: Optional[str] = None
    col_family_name: Optional[str] = None
    col_order_name: Optional[str] = None
    col_class_name: Optional[str] = None
    lowest_col_id: Optional[str] = None
    taxonomy_source: Optional[str] = None
    creation_date: datetime
    last_synced: Optional[datetime] = None

    @model_validator(mode="before")
    @classmethod
    def populate_lowest_fields(cls, value: Any) -> Any:
        return _inject_lowest_col_id(value)

    @field_serializer('creation_date')
    @classmethod
    def serialize_creation_date(cls, dt: datetime) -> str:
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    @field_serializer('last_synced')
    @classmethod
    def serialize_last_synced(cls, dt: Optional[datetime]) -> Optional[str]:
        return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None

    model_config = ConfigDict(from_attributes=True)


class TaxonCreate(SQLModel):
    """Schema for creating a new taxon."""
    cached_common_name: Optional[str] = None
    col_species_id: Optional[str] = None
    col_genus_id: Optional[str] = None
    col_family_id: Optional[str] = None
    col_order_id: Optional[str] = None
    col_class_id: Optional[str] = None
    taxonomy_source: Optional[str] = "CatalogueOfLife-XR"


class TaxonUpdate(SQLModel):
    """Schema for updating an existing taxon; all fields optional."""
    cached_common_name: Optional[str] = None
    col_species_id: Optional[str] = None
    col_genus_id: Optional[str] = None
    col_family_id: Optional[str] = None
    col_order_id: Optional[str] = None
    col_class_id: Optional[str] = None
    taxonomy_source: Optional[str] = None


class TaxonImportRow(SQLModel):
    """Validated CSV row used to resolve a taxon against the COL dictionary."""

    binomial: str = Field(min_length=1, max_length=100)
    common_name: str = Field(min_length=1, max_length=200)
    genus: Optional[str] = Field(default=None, max_length=100)
    family: Optional[str] = Field(default=None, max_length=100)
    taxon_order: Optional[str] = Field(default=None, max_length=100)
    taxon_class: Optional[str] = Field(default=None, alias="class", max_length=100)
    source: str = Field(min_length=1, max_length=50)

    @model_validator(mode="before")
    @classmethod
    def normalize_values(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        return {key: (value.strip() if isinstance(value, str) else value) for key, value in data.items()}

    @field_validator("genus", "family", "taxon_order", "taxon_class", mode="after")
    @classmethod
    def empty_optional_text_to_none(cls, value: str | None) -> str | None:
        return value or None


from app.csv_import import ImportResult

TaxonImportResponse = ImportResult


class TaxonOption(SQLModel):
    """Schema for taxon hierarchy dropdown options."""
    id: str
    name: str


class SoundClassificationPublic(SQLModel):
    """Schema for sound classification dropdown options."""
    sound_id: int
    soundscape_component: Optional[str] = None
    sound_type: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class TaxonSoundTypePublic(SQLModel):
    """Schema for taxon sound type dropdown options."""
    taxon_sound_type_id: int
    name: str

    model_config = ConfigDict(from_attributes=True)
