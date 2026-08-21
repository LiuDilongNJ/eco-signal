import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import ConfigDict, Field, field_serializer, model_validator
from sqlmodel import SQLModel

from app.schemas.review import ReviewRead


class AnnotationTaskSummary(SQLModel):
    """Minimal task info shown on annotation — only when assigned to the current user."""
    task_id: int
    type: str
    status: str
    comment: Optional[str] = None


class AnnotationCreate(SQLModel):
    """Schema for creating a new annotation."""
    project_id: int = Field(gt=0)
    media_id: int
    min_x: float
    max_x: float
    min_y: float
    max_y: float
    sound_id: Optional[int] = Field(None, gt=0)
    object_type: Literal["organism", "other"] | None = None
    reference: bool = False
    comments: Optional[str] = Field(None, max_length=500)
    
    taxon_id: Optional[int] = None
    uncertain: Optional[bool] = None
    sound_distance_m: Optional[int] = None
    distance_not_estimable: Optional[bool] = None
    individual_num: Optional[int] = Field(default=None, ge=1)
    
    creator_type: str = "user"
    confidence: Optional[float] = None
    animal_sound_type: Optional[str] = Field(None, max_length=128)

    @model_validator(mode="after")
    def validate_conditional_fields(self) -> "AnnotationCreate":
        if self.creator_type == "user" and self.confidence is not None:
            self.confidence = None
            
        if self.distance_not_estimable:
            self.sound_distance_m = None
            
        return self


class AnnotationUpdate(SQLModel):
    """Schema for updating an existing annotation."""
    min_x: Optional[float] = None
    max_x: Optional[float] = None
    min_y: Optional[float] = None
    max_y: Optional[float] = None
    sound_id: Optional[int] = None
    object_type: Literal["organism", "other"] | None = None
    reference: Optional[bool] = None
    comments: Optional[str] = Field(None, max_length=500)
    
    # Conditional fields
    taxon_id: Optional[int] = None
    uncertain: Optional[bool] = None
    sound_distance_m: Optional[int] = None
    distance_not_estimable: Optional[bool] = None
    individual_num: Optional[int] = Field(default=None, ge=1)
    confidence: Optional[float] = None
    animal_sound_type: Optional[str] = Field(None, max_length=128)

    @model_validator(mode="after")
    def validate_conditional_fields(self) -> "AnnotationUpdate":
        if self.distance_not_estimable is True:
            self.sound_distance_m = None
        return self


class AnnotationPublic(SQLModel):
    """Schema for returning annotation records."""
    annotation_id: int
    uuid: uuid.UUID
    media_id: int
    media_name: Optional[str] = None
    media_type: str
    
    # Bounding box
    min_x: float
    max_x: float
    min_y: float
    max_y: float
    
    # Sound type
    sound_id: Optional[int] = None
    object_type: Literal["organism", "other"] | None = None
    soundscape_component: Optional[str] = None
    sound_type: Optional[str] = None
    
    # Additional flags
    reference: bool = False
    comments: Optional[str] = None
    
    # Biophony-specific
    taxon_id: Optional[int] = None
    taxon_scientific_name: Optional[str] = None
    taxon_common_name: Optional[str] = None
    uncertain: Optional[bool] = None
    task: Optional[AnnotationTaskSummary] = None
    sound_distance_m: Optional[int] = None
    distance_not_estimable: Optional[bool] = None
    individual_num: Optional[int] = None
    animal_sound_type: Optional[str] = None
    
    # Creator info
    creator_id: int
    creator_name: Optional[str] = None
    creator_color: str = "#FFFFFF"
    creator_type: Optional[str] = "user"
    confidence: Optional[float] = None
    
    creation_date: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("creation_date")
    def serialize_datetime(self, dt: Optional[datetime], _info) -> Optional[str]:
        if dt is None:
            return None
        return dt.strftime("%Y-%m-%d %H:%M:%S")


class AnnotationsPublic(SQLModel):
    """Schema for multiple annotations response."""
    data: list["AnnotationWithReviews"]
    count: int


class AnnotationWithReviews(AnnotationPublic):
    """Annotation detail schema including embedded reviews list."""
    reviews: list[ReviewRead] = Field(default_factory=list)


class AnnotationNavigation(SQLModel):
    """Navigation response for prev/next annotation within the same media."""
    prev_annotation_id: Optional[int] = None
    next_annotation_id: Optional[int] = None
