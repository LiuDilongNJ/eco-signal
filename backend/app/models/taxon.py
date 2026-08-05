"""
Taxon database models.

This module contains Taxon, TaxonSoundType, SoundClassification models.
"""
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.annotation import Annotation, AnnotationReview


class TaxonBase(SQLModel):
    """Base properties for Taxon."""
    col_species_id: Optional[str] = Field(default=None, max_length=64, index=True)
    col_genus_id: Optional[str] = Field(default=None, max_length=64, index=True)
    col_family_id: Optional[str] = Field(default=None, max_length=64, index=True)
    col_order_id: Optional[str] = Field(default=None, max_length=64)
    col_class_id: Optional[str] = Field(default=None, max_length=64)
    cached_scientific_name: Optional[str] = Field(default=None, max_length=200)
    cached_common_name: Optional[str] = Field(default=None, max_length=200)
    taxonomy_source: Optional[str] = Field(default="CatalogueOfLife", max_length=50)


class Taxon(TaxonBase, table=True):
    """Minimal taxon table storing Catalogue-of-Life IDs for taxonomic ranks."""
    __tablename__ = "taxon"
    
    taxon_id: int = Field(default=None, primary_key=True)
    last_synced: Optional[datetime] = Field(default=None)
    creation_date: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    annotations: list["Annotation"] = Relationship(back_populates="taxon")
    annotation_reviews: list["AnnotationReview"] = Relationship(back_populates="taxon")


class TaxonSoundType(SQLModel, table=True):
    """Animal vocalization types associated with taxonomic class/order."""
    __tablename__ = "taxon_sound_type"
    
    taxon_sound_type_id: int = Field(default=None, primary_key=True)
    name: str = Field(max_length=100)
    taxon_class: str = Field(max_length=20)
    taxon_order: str = Field(max_length=20)


class SoundClassification(SQLModel, table=True):
    """Soundscape composition components (biophony, geophony, anthrophony)."""
    __tablename__ = "sound_classification"
    
    sound_id: int = Field(default=None, primary_key=True)
    soundscape_component: Optional[str] = Field(default=None, max_length=200)
    sound_type: Optional[str] = Field(default=None, max_length=30)
    
    # Relationships
    annotations: list["Annotation"] = Relationship(back_populates="sound")
