"""
Annotation database models.

This module contains Annotation, AnnotationReview, AnnotationReviewStatus models.
"""
import uuid as uuid_lib
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.media import Media
    from app.models.taxon import Taxon, SoundClassification


class AnnotationReviewStatus(SQLModel, table=True):
    """Annotation validation statuses: approved, rejected, needs_review, etc."""
    __tablename__ = "annotation_review_status"
    
    annotation_review_status_id: int = Field(default=None, primary_key=True)
    name: str = Field(max_length=128)
    
    # Relationships
    reviews: list["AnnotationReview"] = Relationship(back_populates="status")


class AnnotationBase(SQLModel):
    """Base properties for Annotation."""
    creator_type: Optional[str] = Field(default="user", max_length=128)
    confidence: Optional[float] = Field(default=None)
    min_x: float
    max_x: float
    min_y: float
    max_y: float
    uncertain: Optional[bool] = Field(default=None)
    sound_distance_m: Optional[int] = Field(default=None)
    distance_not_estimable: Optional[bool] = Field(default=None)
    individual_num: Optional[int] = Field(default=1)
    animal_sound_type: Optional[str] = Field(default=None, max_length=128)
    reference: bool = Field(default=False)
    comments: Optional[str] = Field(default=None, max_length=500)


class Annotation(AnnotationBase, table=True):
    """Annotations on media: bounding boxes with taxonomic identification."""
    __tablename__ = "annotation"
    
    annotation_id: int = Field(default=None, primary_key=True)
    uuid: uuid_lib.UUID = Field(
        default_factory=uuid_lib.uuid4,
        unique=True,
        index=True
    )
    sound_id: Optional[int] = Field(
        foreign_key="sound_classification.sound_id",
        ondelete="RESTRICT",
        index=True
    )
    object_type: Optional[str] = Field(default=None, max_length=16, index=True)
    media_id: int = Field(
        foreign_key="media.media_id",
        ondelete="CASCADE",
        index=True
    )
    creator_id: int = Field(
        foreign_key="user.user_id",
        ondelete="CASCADE",
        index=True
    )
    taxon_id: Optional[int] = Field(
        default=None,
        foreign_key="taxon.taxon_id",
        ondelete="CASCADE",
        index=True
    )
    creation_date: datetime = Field(default_factory=datetime.utcnow, index=True)
    
    # Relationships
    sound: Optional["SoundClassification"] = Relationship(back_populates="annotations")
    media: Optional["Media"] = Relationship(back_populates="annotations")
    creator: Optional["User"] = Relationship(back_populates="annotations")
    taxon: Optional["Taxon"] = Relationship(back_populates="annotations")
    reviews: list["AnnotationReview"] = Relationship(
        back_populates="annotation",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class AnnotationReview(SQLModel, table=True):
    """Peer reviews of annotations by other users."""
    __tablename__ = "annotation_review"
    
    annotation_id: int = Field(
        foreign_key="annotation.annotation_id",
        primary_key=True,
        ondelete="CASCADE"
    )
    reviewer_id: int = Field(
        foreign_key="user.user_id",
        primary_key=True,
        ondelete="CASCADE",
        index=True
    )
    annotation_review_status_id: int = Field(
        foreign_key="annotation_review_status.annotation_review_status_id",
        ondelete="CASCADE",
        index=True
    )
    taxon_id: Optional[int] = Field(
        default=None,
        foreign_key="taxon.taxon_id",
        ondelete="CASCADE",
        index=True
    )
    note: Optional[str] = Field(default=None, max_length=200)
    creation_date: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    annotation: Optional[Annotation] = Relationship(back_populates="reviews")
    reviewer: Optional["User"] = Relationship(back_populates="annotation_reviews")
    status: Optional[AnnotationReviewStatus] = Relationship(back_populates="reviews")
    taxon: Optional["Taxon"] = Relationship(back_populates="annotation_reviews")
