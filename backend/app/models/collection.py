"""
Collection database models.

This module contains Collection, CollectionContributor, and CollectionTaxon models.
"""
import uuid as uuid_lib
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.permission import UserPermission
    from app.models.project import ProjectCollection
    from app.models.site import SiteCollection
    from app.models.media import MediaCollection


class CollectionBase(SQLModel):
    """Base properties for Collection."""
    name: str = Field(max_length=100)
    doi: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = Field(default=None)
    sphere: Optional[str] = Field(default=None, max_length=100)
    external_media_url: Optional[str] = Field(default=None, max_length=255)
    project_url: Optional[str] = Field(default=None, max_length=255)
    public_access: bool = Field(default=False)
    public_tags: bool = Field(default=False)


class Collection(CollectionBase, table=True):
    """Groups of related media (audio/photos) with shared metadata."""
    __tablename__ = "collection"
    
    collection_id: int = Field(default=None, primary_key=True)
    uuid: uuid_lib.UUID = Field(
        default_factory=uuid_lib.uuid4,
        unique=True,
        index=True
    )
    creator_id: int = Field(
        foreign_key="user.user_id",
        ondelete="RESTRICT",
        index=True
    )
    creation_date: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    creator: Optional["User"] = Relationship(
        back_populates="created_collections",
        sa_relationship_kwargs={"foreign_keys": "[Collection.creator_id]"}
    )
    contributors: list["CollectionContributor"] = Relationship(back_populates="collection")
    project_collections: list["ProjectCollection"] = Relationship(
        back_populates="collection",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    site_collections: list["SiteCollection"] = Relationship(
        back_populates="collection",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    media_collections: list["MediaCollection"] = Relationship(
        back_populates="collection",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    user_permissions: list["UserPermission"] = Relationship(
        back_populates="collection",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    taxons: list["CollectionTaxon"] = Relationship(back_populates="collection")


class CollectionContributor(SQLModel, table=True):
    """Collection contributors for proper attribution."""
    __tablename__ = "collection_contributor"
    
    collection_id: int = Field(
        foreign_key="collection.collection_id",
        primary_key=True,
        ondelete="CASCADE"
    )
    user_id: int = Field(
        foreign_key="user.user_id",
        primary_key=True,
        ondelete="CASCADE"
    )
    contribution_role: Optional[str] = Field(default=None, max_length=100)
    added_date: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    collection: Optional[Collection] = Relationship(back_populates="contributors")
    user: Optional["User"] = Relationship(back_populates="collection_contributions")


class CollectionTaxon(SQLModel, table=True):
    """Assigns Catalogue-of-Life taxa to collections."""
    __tablename__ = "collection_taxon"
    
    id: int = Field(default=None, primary_key=True)
    collection_id: int = Field(
        foreign_key="collection.collection_id",
        ondelete="CASCADE",
        index=True
    )
    col_taxon_id: str = Field(max_length=128, index=True)
    col_rank: str = Field(default="species", max_length=32, index=True)
    cached_name: Optional[str] = Field(default=None, max_length=255)
    asserted_by: Optional[int] = Field(
        default=None,
        foreign_key="user.user_id",
        ondelete="SET NULL"
    )
    asserted_at: datetime = Field(default_factory=datetime.utcnow)
    notes: Optional[str] = Field(default=None)
    
    # Relationships
    collection: Optional[Collection] = Relationship(back_populates="taxons")
