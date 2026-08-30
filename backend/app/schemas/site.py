import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import ConfigDict, field_serializer, model_validator
from sqlmodel import SQLModel, Field

from app.schemas.coordinates import Latitude, Longitude


class SiteCreate(SQLModel):
    """Schema for creating a new site."""
    name: str
    longitude: Optional[Longitude] = None
    latitude: Optional[Latitude] = None
    topography_m: Optional[float] = None
    freshwater_depth_m: Optional[float] = None
    realm_id: Optional[int] = None
    biome_id: Optional[int] = None
    functional_type_id: Optional[int] = None
    iho_id: Optional[int] = None
    gadm0_gid: Optional[str] = None
    gadm1_gid: Optional[str] = None
    gadm2_gid: Optional[str] = None
    collection_id: Optional[int] = None   # Bind to single collection (takes priority)
    project_id: Optional[int] = None      # Bind to all collections under this project

    @model_validator(mode="after")
    def check_collection_or_project(self) -> "SiteCreate":
        """Ensure at least one of collection_id or project_id is provided."""
        if self.collection_id is None and self.project_id is None:
            raise ValueError("At least one of collection_id or project_id must be provided")
        has_manual = self.longitude is not None and self.latitude is not None
        has_iho = self.iho_id is not None
        has_gadm = self.gadm0_gid is not None and self.gadm0_gid.strip() != ""
        if not any([has_manual, has_iho, has_gadm]):
            raise ValueError("At least one of coordinates, gadm0_gid, or iho_id must be provided")
        if (self.longitude is None) != (self.latitude is None):
            raise ValueError("longitude and latitude must be provided together")
        if (self.gadm1_gid or self.gadm2_gid) and (self.gadm0_gid is None or not self.gadm0_gid.strip()):
            raise ValueError("gadm0_gid is required when gadm1_gid or gadm2_gid is provided")
        return self


class SiteUpdate(SQLModel):
    """Schema for updating an existing site. All fields are optional."""
    name: Optional[str] = None
    longitude: Optional[Longitude] = None
    latitude: Optional[Latitude] = None
    topography_m: Optional[float] = None
    freshwater_depth_m: Optional[float] = None
    realm_id: Optional[int] = None
    biome_id: Optional[int] = None
    functional_type_id: Optional[int] = None
    iho_id: Optional[int] = None
    gadm0_gid: Optional[str] = None
    gadm1_gid: Optional[str] = None
    gadm2_gid: Optional[str] = None

    @model_validator(mode="after")
    def check_geo_selection_rules(self) -> "SiteUpdate":
        """Validate optional geo selection combinations for update."""
        has_gadm0 = self.gadm0_gid is not None and self.gadm0_gid.strip() != ""
        if (self.gadm1_gid or self.gadm2_gid) and not has_gadm0:
            raise ValueError("gadm0_gid is required when gadm1_gid or gadm2_gid is provided")
        return self


class SitePublic(SQLModel):
    """Schema for site public response."""
    site_id: int
    uuid: uuid.UUID
    name: str
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    iho_longitude: Optional[float] = None
    iho_latitude: Optional[float] = None
    topography_m: Optional[float] = None
    freshwater_depth_m: Optional[float] = None
    realm_id: Optional[int] = None
    realm_name: Optional[str] = None
    biome_id: Optional[int] = None
    biome_name: Optional[str] = None
    functional_type_id: Optional[int] = None
    functional_type_name: Optional[str] = None
    iho: Optional[str] = None      # IHO sea area name (queried via ID before save)
    gadm0: Optional[str] = None    # Country (queried via ID before save)
    gadm1: Optional[str] = None    # Province/state (queried via ID before save)
    gadm2: Optional[str] = None    # City/district (queried via ID before save)
    gadm0_gid: Optional[str] = None
    gadm1_gid: Optional[str] = None
    gadm2_gid: Optional[str] = None
    creator_id: int
    creator_name: Optional[str] = None
    creation_date: datetime
    collection_ids: list[int] = []

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("creation_date")
    def serialize_datetime(self, dt: Optional[datetime], _info) -> Optional[str]:
        if dt is None:
            return None
        return dt.strftime("%Y-%m-%d %H:%M:%S")


class SiteMapLightPoint(SQLModel):
    latitude: float
    longitude: float


class SiteMapLightGeometry(SQLModel):
    point: Optional[SiteMapLightPoint] = None
    point_source: Optional[str] = None


class SiteMapLightMarker(SQLModel):
    site_id: int
    name: str
    geometry: SiteMapLightGeometry
    media_count: int = 0
    realm_id: Optional[int] = None
    realm_name: Optional[str] = None
    biome_id: Optional[int] = None
    functional_type_id: Optional[int] = None


class SiteMapLightResponse(SQLModel):
    markers: list[SiteMapLightMarker]
    center: Optional["SiteMapCenter"] = None
    count: int


class SiteMapCenter(SQLModel):
    """Schema for map center point."""
    latitude: float
    longitude: float


class SiteMapGeometryItem(SQLModel):
    """Schema for on-demand map geometry payload."""
    site_id: int
    geometry: dict[str, Any]


class SiteMapGeometryResponse(SQLModel):
    """Schema for map geometry-on-demand response."""
    items: list[SiteMapGeometryItem]
    count: int


class SiteCollectionSyncRequest(SQLModel):
    """Schema for syncing site collections."""
    site_ids: list[int] = Field(min_length=1)
    project_ids: list[int] = Field(default_factory=list)
    collection_ids: list[int] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class SiteLinkCollectionItem(SQLModel):
    """Collection item used by site-link dialog."""
    collection_id: int
    name: str
    selected: bool = False
    duplicate_project_ids: list[int] = Field(default_factory=list)


class SiteLinkCurrentProject(SQLModel):
    """Current project block for site-link dialog."""
    project_id: int
    project_name: str
    collections: list[SiteLinkCollectionItem] = Field(default_factory=list)


class SiteLinkOtherProject(SQLModel):
    """Other project block for site-link dialog."""
    project_id: int
    project_name: str
    collections: list[SiteLinkCollectionItem] = Field(default_factory=list)


class SiteLinkOptionsResponse(SQLModel):
    """Response schema for site-link dialog options."""
    current_project: SiteLinkCurrentProject
    other_projects: list[SiteLinkOtherProject] = Field(default_factory=list)
    unassigned_collections: list[SiteLinkCollectionItem] = Field(default_factory=list)
    selected_collection_ids: list[int] = Field(default_factory=list)
    selected_project_ids: list[int] = Field(default_factory=list)


class IucnGetOption(SQLModel):
    """Schema for a single IUCN GET option node."""
    id: int
    name: str
    children: list["IucnGetOption"] = []


IucnGetOption.model_rebuild()


class IucnGetOptionsResponse(SQLModel):
    """Schema for IUCN GET three-level typology options."""
    realms: list[IucnGetOption]
