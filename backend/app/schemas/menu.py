"""Menu response schemas."""
from sqlmodel import SQLModel


class MenuItemPublic(SQLModel):
    """Current-user menu visibility item."""
    name: str
    visible: bool
