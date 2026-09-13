"""Machine learning model schemas."""
from typing import Any

from sqlmodel import SQLModel


class MLModelRead(SQLModel):
    """Machine learning model information exposed to API consumers."""

    model_id: int
    name: str | None = None
    version: str | None = None
    description: str | None = None
    source_url: str | None = None
    parameter: Any = None
