from typing import Any, Literal

from pydantic import ConfigDict, field_validator, model_validator
from sqlmodel import Field, SQLModel

from app.schemas.index_log import IndexLogCreateRequest
from app.schemas.queue import QueueDetail

BirdNETLocale = Literal[
    "af", "ar", "cs", "da", "de", "en_uk", "en_us", "es", "fi", "fr",
    "hu", "it", "ja", "ko", "nl", "no", "pl", "pt", "ro", "ru", "sk",
    "sl", "sv", "th", "tr", "uk", "zh",
]


class BirdNETParams(SQLModel):
    """BirdNET model parameters."""

    model_config = ConfigDict(extra="forbid")

    sensitivity: float = Field(default=1.0, ge=0.5, le=1.5, description="Detection sensitivity; higher values result in more detections. Values in [0.5, 1.5]. Defaults to 1.0.")
    min_conf: float = Field(default=0.1, ge=0.01, le=0.99, description="Minimum confidence threshold. Values in [0.01, 0.99]. Defaults to 0.1.")
    overlap: float = Field(default=0.0, ge=0.0, le=2.9, description="Overlap between segments in seconds (0-2.9)")
    sf_thresh: float = Field(default=0.03, ge=0.0001, le=0.99, description="Minimum species occurrence frequency threshold for location filter. Values in [0.0001, 0.99]. Defaults to 0.03.")
    min_freq: int = Field(default=1, ge=0, description="Annotation minimum frequency in Hz. Defaults to 1.")
    max_freq: int | None = Field(default=None, ge=0, description="Annotation maximum frequency in Hz. Defaults to the audio Nyquist frequency when omitted.")
    locale: BirdNETLocale = Field(default="en_us", description="Locale for translated BirdNET common names.")
    top_n: int | None = Field(default=None, ge=1, le=10000, description="Keep the top N predictions per segment; BirdNET ignores min_conf when set.")

    @model_validator(mode="after")
    def validate_frequency_bounds(self) -> "BirdNETParams":
        if self.max_freq is not None and self.min_freq >= self.max_freq:
            raise ValueError("min_freq must be less than max_freq")
        return self


class BatDetectParams(SQLModel):
    """BatDetect2 model parameters."""

    model_config = ConfigDict(extra="forbid")

    detection_threshold: float = Field(default=0.3, ge=0.0, le=1.0, description="Detection threshold (0-1)")
    chunk_size: float = Field(default=2.0, gt=0, description="Audio chunk size in seconds. Defaults to 2.")


class MergeParams(SQLModel):
    """Tag merging parameters for conspecific tags."""

    model_config = ConfigDict(extra="forbid")

    is_merged: bool = Field(default=False, description="Enable merging of conspecific tags")
    max_gap: float = Field(default=0.0, ge=0.0, description="Maximum gap between tags to merge (seconds)")
    keep_merged: bool = Field(default=True, description="Keep only merged tags and discard isolated ones. False keeps the original ordered tags and appends merged tags.")


class InsectParams(SQLModel):
    """insects-base-cnn10-96k-t model parameters."""

    model_config = ConfigDict(extra="forbid")

    window_size: float = Field(default=4.0, ge=0.5, le=30.0, description="Analysis window size in seconds (0.5-30)")
    stride_length: float = Field(default=4.0, ge=0.5, le=30.0, description="Analysis stride length in seconds (0.5-30)")
    max_freq: int | None = Field(default=None, ge=1, le=96000, description="Maximum frequency in Hz for the annotation bounding box. Defaults to the audio Nyquist frequency when omitted.")


class RunAnalysisRequest(SQLModel):
    """Request body for the unified AI analysis endpoint."""

    project_id: int = Field(..., description="Project ID that provides the media context")
    media_ids: list[int] = Field(..., min_length=1, description="IDs of the uploaded media files to analyze")
    birdnet: BirdNETParams | None = Field(default=None, description="BirdNET parameters; omit to skip this model")
    batdetect: BatDetectParams | None = Field(default=None, description="BatDetect2 parameters; omit to skip this model")
    insects: InsectParams | None = Field(default=None, description="insects-base-cnn10-96k-t parameters; omit to skip this model")
    merge: MergeParams = Field(default_factory=MergeParams, description="Tag merging parameters (applied after analysis)")


class RunAnalysisResponse(SQLModel):
    """Response for the unified AI analysis endpoint."""

    queued: list[QueueDetail] = Field(default_factory=list, description="Successfully enqueued tasks")
    failed: list[dict] = Field(default_factory=list, description="Models that failed to enqueue")


class AcousticIndexJob(SQLModel):
    """Single acoustic calculation request."""

    index_id: int | None = Field(default=None, description="Acoustic index type ID")
    analysis_type: Literal["template_matching", "max_frequency"] | None = Field(
        default=None,
        description="Acoustic analysis type for calculations that do not use index_log",
    )
    params: dict[str, Any] = Field(default_factory=dict, description="Calculation parameter values")

    @model_validator(mode="after")
    def validate_calculation_target(self) -> "AcousticIndexJob":
        if (self.index_id is None) == (self.analysis_type is None):
            raise ValueError("Exactly one of index_id or analysis_type must be provided")
        return self


AcousticChannel = Literal["mono", "left", "right"]


class AcousticIndexSelection(SQLModel):
    """Selected time and frequency range for acoustic index analysis."""

    min_time: float = Field(..., ge=0, description="Selection start time in seconds")
    max_time: float = Field(..., description="Selection end time in seconds")
    min_frequency: float = Field(..., ge=0, description="Selection minimum frequency in Hz")
    max_frequency: float = Field(..., description="Selection maximum frequency in Hz")
    filter_enabled: bool = Field(default=False, description="Apply the selected frequency band to the analysis audio")

    @model_validator(mode="after")
    def validate_bounds(self) -> "AcousticIndexSelection":
        if self.max_time <= self.min_time:
            raise ValueError("max_time must be greater than min_time")
        if self.max_frequency <= self.min_frequency:
            raise ValueError("max_frequency must be greater than min_frequency")
        return self


class RunAcousticIndicesRequest(SQLModel):
    """Request body for acoustic calculations."""

    project_id: int = Field(..., description="Project ID that provides the media context")
    media_ids: list[int] = Field(..., min_length=1, description="IDs of the media files to analyze")
    selection: AcousticIndexSelection | None = Field(default=None, description="Optional selected time/frequency range")
    channel: AcousticChannel | None = Field(default=None, description="Audio channel to analyze")
    indices: list[AcousticIndexJob] = Field(..., min_length=1, description="Acoustic calculations to enqueue")

    @field_validator("indices")
    @classmethod
    def validate_indices(cls, value: list[AcousticIndexJob]) -> list[AcousticIndexJob]:
        if not value:
            raise ValueError("At least one index must be selected")
        return value

class AcousticIndexPreviewRequest(SQLModel):
    """Request body for one acoustic index preview calculation."""

    project_id: int
    media_id: int
    selection: AcousticIndexSelection
    channel: AcousticChannel | None = None
    index_id: int
    params: dict[str, Any] = Field(default_factory=dict)


class AcousticIndexPreviewResponse(SQLModel):
    """Preview calculation result that can be saved after user confirmation."""

    media_id: int
    index_id: int
    index_name: str
    version: str
    params: dict[str, Any] = Field(default_factory=dict)
    results: dict[str, Any] = Field(default_factory=dict)
    save_payload: IndexLogCreateRequest


class AcousticIndicesResponse(SQLModel):
    """Response for acoustic calculation jobs."""

    queued: list[QueueDetail] = Field(default_factory=list, description="Successfully enqueued tasks")
    failed: list[dict] = Field(default_factory=list, description="Calculations that failed to enqueue")
