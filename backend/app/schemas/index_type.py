from typing import Any, Literal

from sqlmodel import Field, SQLModel


class IndexTypeParameterRead(SQLModel):
    """Normalized acoustic index parameter metadata for the frontend."""

    key: str
    default: Any = None
    value_type: Literal["string", "number", "boolean"] = "string"


class IndexTypeRead(SQLModel):
    """Acoustic index type exposed to API consumers."""

    index_id: int
    name: str | None = None
    description: str | None = None
    param: Any = None
    url: str | None = None
    parameters: list[IndexTypeParameterRead] = Field(default_factory=list)
