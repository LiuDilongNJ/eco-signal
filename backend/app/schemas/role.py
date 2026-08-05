from sqlmodel import SQLModel, Field


class RoleBase(SQLModel):
    """Base properties for Role."""
    name: str = Field(min_length=2, max_length=128)


class RoleCreate(RoleBase):
    """Schema for creating a role."""
    pass


class RoleUpdate(RoleBase):
    """Schema for updating a role."""
    pass


class UserRoleUpdate(SQLModel):
    """Schema for updating a user's role (admin toggle)."""
    is_admin: bool = Field(description="Whether the user should be granted admin role")


class UserRoleResponse(SQLModel):
    """Schema for returning user's role status."""
    is_admin: bool = Field(description="Whether the user has the admin role")

