"""项目/集合概览响应。 / Project/collection overview."""
from typing import Optional

from sqlmodel import SQLModel


class OverviewStats(SQLModel):
    """Statistics for the current scope."""
    users: int = 0
    # project scope → collections count; collection scope → projects count
    collections_or_projects: int = 0
    audios: int = 0
    photos: int = 0
    annotations: int = 0
    sites: int = 0


class OverviewContributor(SQLModel):
    """A single contributor entry."""
    user_id: int
    name: str
    email: str
    orcid: Optional[str] = None
    contribution_role: Optional[str] = None


class ProjectOverviewResponse(SQLModel):
    """
    Aggregated overview response for a project or collection.

    stats: Left-panel statistics.
    contributors: Right-panel contributor list.
    """
    stats: OverviewStats
    contributors: list[OverviewContributor] = []
