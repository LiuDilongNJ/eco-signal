from typing import Optional

from sqlmodel import SQLModel


class ProjectOption(SQLModel):
    """Project option for dropdown menus."""
    project_id: int
    name: str
    can_manage: bool = False  # Whether the current user has admin/write permission on this project


class CollectionOption(SQLModel):
    """Collection option for dropdown menus."""
    collection_id: int
    name: str
    sphere: Optional[str] = None
    can_manage: bool = False  # Whether the current user has admin/write permission on this collection

