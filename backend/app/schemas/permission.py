from typing import Optional

from sqlmodel import SQLModel


class UserPermissionInfo(SQLModel):
    """Schema for a user with their assigned permissions (used in lists)."""
    user_id: int
    username: str
    permissions: list[str]  # e.g. ['audio:read', 'collection:manage']


class CollectionPermissionConfig(SQLModel):
    """Collection row data for the permission config page."""
    project_id: int
    collection_id: int
    collection_name: str
    stored_permissions: list[str]
    effective_permissions: list[str]


class ProjectPermissionConfig(SQLModel):
    """Project row data (with its collections) for the permission config page."""
    project_id: int
    project_name: str
    can_manage_project: bool
    stored_permissions: list[str]
    effective_permissions: list[str]
    collections: list[CollectionPermissionConfig]


class UserPermissionConfig(SQLModel):
    """Full permission config snapshot for one user, used to render the config page."""
    is_admin: bool
    can_manage_admin_role: bool
    projects: list[ProjectPermissionConfig]


class CollectionPermissionAssignment(SQLModel):
    """Editable stored permissions for one collection under a project."""
    project_id: int
    collection_id: int
    stored_permissions: list[str] = []


class ProjectPermissionAssignment(SQLModel):
    """Editable stored permissions for one project and its collections."""
    project_id: int
    stored_permissions: list[str] = []
    collections: list[CollectionPermissionAssignment] = []


class UserPermissionSyncRequest(SQLModel):
    """
    Full user permission sync request body using the same tree shape as the config response.

    is_admin: Optional admin toggle (only Admin can set this).
    projects: List of project nodes with stored permissions.
    """
    is_admin: Optional[bool] = None
    projects: list[ProjectPermissionAssignment] = []
