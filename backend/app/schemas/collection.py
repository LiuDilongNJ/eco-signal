from datetime import datetime
from typing import Optional, Any
from uuid import UUID

from pydantic import Field, ConfigDict, field_serializer, field_validator
from sqlmodel import SQLModel

from app.enums.collection import CollectionSphere
from app.schemas.capability import RowCapabilities
from app.utils import validate_optional_http_url


class CollectionSimple(SQLModel):
    """Schema for a simplified collection response (id and name only)."""
    collection_id: int
    name: str

class CollectionCreate(SQLModel):
    """Schema for creating a new collection."""
    name: str = Field(..., max_length=100, description="Collection name")
    doi: Optional[str] = Field(None, max_length=255, description="DOI")
    description: Optional[str] = Field(None, description="Full description")
    sphere: Optional[str] = Field(None, max_length=100, description="Sphere")
    external_media_url: Optional[str] = Field(None, max_length=255, description="External media URL")
    project_url: Optional[str] = Field(None, max_length=255, description="Project URL")
    public_access: bool = Field(False, description="Whether collection is publicly accessible")
    public_tags: bool = Field(False, description="Whether tags are public")
    
    @field_validator('sphere')
    @classmethod
    def validate_sphere(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        if v not in [e.value for e in CollectionSphere]:
            raise ValueError(f"sphere must be one of: {[e.value for e in CollectionSphere]}")
        return v

    @field_validator("external_media_url", "project_url")
    @classmethod
    def validate_urls(cls, value: Optional[str]) -> Optional[str]:
        return validate_optional_http_url(value)
    



class CollectionUpdate(SQLModel):
    """Schema for updating a collection (all fields optional)."""
    name: Optional[str] = Field(None, max_length=100)
    doi: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    sphere: Optional[str] = Field(None, max_length=100)
    external_media_url: Optional[str] = Field(None, max_length=255)
    project_url: Optional[str] = Field(None, max_length=255)
    public_access: Optional[bool] = None
    public_tags: Optional[bool] = None
    
    @field_validator('sphere')
    @classmethod
    def validate_sphere(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        if v not in [e.value for e in CollectionSphere]:
            raise ValueError(f"sphere must be one of: {[e.value for e in CollectionSphere]}")
        return v

    @field_validator("external_media_url", "project_url")
    @classmethod
    def validate_urls(cls, value: Optional[str]) -> Optional[str]:
        return validate_optional_http_url(value)
    



class CollectionPublic(SQLModel):
    """Schema for collection response data."""
    collection_id: int
    uuid: UUID
    name: str
    doi: Optional[str] = None
    description: Optional[str] = None
    sphere: Optional[str] = None
    external_media_url: Optional[str] = None
    project_url: Optional[str] = None
    public_access: bool
    public_tags: bool
    creator_id: int
    creator_name: Optional[str] = None
    creation_date: datetime
    project_ids: list[int] = Field(default_factory=list)
    capabilities: RowCapabilities = Field(default_factory=RowCapabilities)
    
    taxons: list[Any] = []
    
    @field_serializer('taxons')
    @classmethod
    def serialize_taxons(cls, taxons: list[Any]) -> list[dict[str, Any]]:
        if not taxons:
            return []
        return [{"id": getattr(t, "id", None), "cached_name": getattr(t, "cached_name", None)} for t in taxons]
    
    @field_serializer('creation_date')
    @classmethod
    def serialize_datetime(cls, dt: datetime) -> str:
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    
    @field_serializer('doi', 'description', 'sphere', 'external_media_url', 'project_url')
    @classmethod
    def convert_none_to_empty_string(cls, v: Optional[str]) -> str:
        return v if v is not None else ""
    
    model_config = ConfigDict(from_attributes=True)


class CollectionDetail(CollectionPublic):
    """Schema for collection detail response, includes flat creator name."""
    creator_name: str = Field(default="", description="Display name of the collection creator")


class CollectionViewResponse(SQLModel):
    """Schema for collection view panel data."""
    project_id: int
    project_name: str = ""
    project_picture_url: str = ""
    sphere: str = ""
    external_media_url: str = ""
    project_url: str = ""
    collection_id: int
    collection_name: str = ""
    collection_code: str = ""
    researcher_name: str = ""
    collection_creation_date: datetime
    taxon_tags: list[str] = Field(default_factory=list)
    description: str = ""

    @field_serializer("collection_creation_date")
    @classmethod
    def serialize_datetime(cls, dt: datetime) -> str:
        return dt.strftime("%Y-%m-%d %H:%M:%S")


class CollectionTaxonItem(SQLModel):
    """Dialogue box single Taxon item for setting taxons."""
    col_taxon_id: str = Field(description="Catalogue of Life ID")
    cached_name: str = Field(description="UI display name")
    col_rank: str = Field(default="species", description="Taxonomic rank")
    notes: Optional[str] = Field(default=None, description="Additional notes")


class CollectionTaxonsSet(SQLModel):
    """Payload for setting collection taxons."""
    taxons: list[CollectionTaxonItem] = Field(default_factory=list)


class CollectionTaxonResponse(SQLModel):
    """Response model for a collection's taxon."""
    id: int
    collection_id: int
    col_taxon_id: str
    col_rank: str
    cached_name: Optional[str] = None
    asserted_by: Optional[int] = None
    asserted_by_name: Optional[str] = None
    asserted_at: datetime
    notes: Optional[str] = None

    @field_serializer('asserted_at')
    @classmethod
    def serialize_datetime(cls, dt: datetime) -> str:
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    model_config = ConfigDict(from_attributes=True)
