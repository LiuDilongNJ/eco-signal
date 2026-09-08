from typing import Literal

from sqlmodel import Field, SQLModel


class RoleBase(SQLModel):
    """Base properties for Role."""
    name: str = Field(min_length=2, max_length=128)


class RoleCreate(RoleBase):
    """Schema for creating a role."""
    pass


class RoleUpdate(RoleBase):
    """Schema for updating a role."""
    pass


class AccessRolePublic(SQLModel):
    code: Literal["viewer", "annotator", "reviewer", "manager", "custom"]
    name: str
    kind: str
    display_order: int
    project_permissions: list[str]
    collection_permissions: list[str]
