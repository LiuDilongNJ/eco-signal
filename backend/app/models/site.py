"""
Site database models.

This module contains Site, SiteCollection, IucnGet, and IhoSeaArea models.
"""
import uuid as uuid_lib
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from geoalchemy2 import Geometry
from sqlalchemy import Column
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.collection import Collection
    from app.models.project import Project
    from app.models.media import Media


class IucnGet(SQLModel, table=True):
    """IUCN Global Ecosystem Typology - hierarchical classification of ecosystem types."""
    __tablename__ = "iucn_get"
    
    iucn_get_id: int = Field(default=None, primary_key=True)
    pid: int = Field(description="Parent ID for ecosystem hierarchy")
    name: str = Field(max_length=100)
    level: int = Field(description="Level: 1=Realm, 2=Biome, 3=Functional Group, 4=Ecosystem Type")
    
    # Relationships
    sites_realm: list["Site"] = Relationship(
        back_populates="realm",
        sa_relationship_kwargs={"foreign_keys": "[Site.realm_id]"}
    )
    sites_biome: list["Site"] = Relationship(
        back_populates="biome",
        sa_relationship_kwargs={"foreign_keys": "[Site.biome_id]"}
    )
    sites_functional_type: list["Site"] = Relationship(
        back_populates="functional_type",
        sa_relationship_kwargs={"foreign_keys": "[Site.functional_type_id]"}
    )


class IhoSeaArea(SQLModel, table=True):
    """IHO Sea Areas - foreign table mapped from geo_db via postgres_fdw.

    This table is not managed by alembic (it is a foreign table).
    Data comes from the IHO Sea Areas v3 (2018) Shapefile loaded into geo_db.
    All source columns are preserved as-is (lowercased).
    """
    __tablename__ = "iho_sea_area"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: Optional[str] = Field(default=None, max_length=100)
    iho_id: Optional[str] = Field(default=None, max_length=16)
    longitude: Optional[float] = Field(default=None)
    latitude: Optional[float] = Field(default=None)
    min_x: Optional[float] = Field(default=None)
    min_y: Optional[float] = Field(default=None)
    max_x: Optional[float] = Field(default=None)
    max_y: Optional[float] = Field(default=None)
    area: Optional[int] = Field(default=None)
    mrgid: Optional[int] = Field(default=None)
    geometry: Any = Field(
        default=None,
        sa_column=Column("geometry", Geometry(geometry_type="MULTIPOLYGON", srid=4326))
    )


class SiteBase(SQLModel):
    """Base properties for Site."""
    name: str = Field(max_length=100, index=True)
    topography_m: Optional[float] = Field(default=None)
    freshwater_depth_m: Optional[float] = Field(default=None)


class Site(SiteBase, table=True):
    """Recording locations with geographic and ecological metadata."""
    __tablename__ = "site"
    
    site_id: int = Field(default=None, primary_key=True)
    uuid: uuid_lib.UUID = Field(
        default_factory=uuid_lib.uuid4,
        unique=True,
        index=True
    )
    creator_id: int = Field(
        foreign_key="user.user_id",
        ondelete="CASCADE",
        index=True
    )
    realm_id: Optional[int] = Field(
        default=None,
        foreign_key="iucn_get.iucn_get_id",
        ondelete="RESTRICT",
        index=True
    )
    biome_id: Optional[int] = Field(
        default=None,
        foreign_key="iucn_get.iucn_get_id",
        ondelete="RESTRICT",
        index=True
    )
    functional_type_id: Optional[int] = Field(
        default=None,
        foreign_key="iucn_get.iucn_get_id",
        ondelete="RESTRICT",
        index=True
    )
    creation_date: datetime = Field(default_factory=datetime.utcnow)
    
    # PostGIS geometry column - handled via SQLAlchemy Column
    location: Any = Field(
        default=None,
        sa_column=Column(Geometry(geometry_type="GEOMETRY", srid=4326))
    )
    location_iho: Any = Field(
        default=None,
        sa_column=Column("location_iho", Geometry(geometry_type="GEOMETRY", srid=4326))
    )
    longitude: Optional[float] = Field(default=None, index=True)
    latitude: Optional[float] = Field(default=None, index=True)

    # Geographic reference fields chosen by user from geo options
    iho: Optional[str] = Field(default=None, max_length=200)    # Cached IHO sea area name
    gadm0: Optional[str] = Field(default=None, max_length=100)  # Cached Country
    gadm1: Optional[str] = Field(default=None, max_length=100)  # Cached Province/state
    gadm2: Optional[str] = Field(default=None, max_length=100)  # Cached City/district
    gadm0_gid: Optional[str] = Field(default=None, max_length=100)
    gadm1_gid: Optional[str] = Field(default=None, max_length=100)
    gadm2_gid: Optional[str] = Field(default=None, max_length=100)
    
    # Relationships
    creator: Optional["User"] = Relationship(back_populates="created_sites")
    realm: Optional[IucnGet] = Relationship(
        back_populates="sites_realm",
        sa_relationship_kwargs={"foreign_keys": "[Site.realm_id]"}
    )
    biome: Optional[IucnGet] = Relationship(
        back_populates="sites_biome",
        sa_relationship_kwargs={"foreign_keys": "[Site.biome_id]"}
    )
    functional_type: Optional[IucnGet] = Relationship(
        back_populates="sites_functional_type",
        sa_relationship_kwargs={"foreign_keys": "[Site.functional_type_id]"}
    )
    site_collections: list["SiteCollection"] = Relationship(back_populates="site")
    site_projects: list["SiteProject"] = Relationship(
        back_populates="site",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    media: list["Media"] = Relationship(back_populates="site")


class SiteCollection(SQLModel, table=True):
    """Many-to-many relationship between sites and collections."""
    __tablename__ = "site_collection"
    
    site_id: int = Field(
        foreign_key="site.site_id",
        primary_key=True,
        ondelete="CASCADE"
    )
    collection_id: int = Field(
        foreign_key="collection.collection_id",
        primary_key=True,
        ondelete="CASCADE"
    )
    
    # Relationships
    site: Optional[Site] = Relationship(back_populates="site_collections")
    collection: Optional["Collection"] = Relationship(back_populates="site_collections")


class SiteProject(SQLModel, table=True):
    """Many-to-many relationship between sites and projects."""
    __tablename__ = "site_project"

    site_id: int = Field(
        foreign_key="site.site_id",
        primary_key=True,
        ondelete="CASCADE",
    )
    project_id: int = Field(
        foreign_key="project.project_id",
        primary_key=True,
        ondelete="CASCADE",
    )

    # Relationships
    site: Optional[Site] = Relationship(back_populates="site_projects")
    project: Optional["Project"] = Relationship(back_populates="site_projects")
