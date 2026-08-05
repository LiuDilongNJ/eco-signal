"""
Network node database model.

Stores federated ecoSignal instance information.
Each record represents either the local instance (is_local=True)
or a remote peer discovered via HOST synchronization.
"""
from datetime import datetime

from sqlmodel import Field, SQLModel


class NetworkNode(SQLModel, table=True):
    """
    Federated network node (ecoSignal instance).

    Coordinates are manually entered by the administrator.
    Stats are cached: local node stats are refreshed on demand,
    remote node stats are synced from the HOST.
    """
    __tablename__ = "network_node"

    node_id: int = Field(default=None, primary_key=True)

    # Unique URL used as the business key for upsert
    app_url: str = Field(max_length=255, unique=True, index=True)

    name: str = Field(max_length=255)
    latitude: float | None = Field(default=None)
    longitude: float | None = Field(default=None)

    # True for the current instance; only one row should have is_local=True
    is_local: bool = Field(default=False, index=True)
    shared: bool = Field(default=False, index=True)

    # Cached aggregate statistics
    stat_users: int = Field(default=0)
    stat_projects: int = Field(default=0)
    stat_collections: int = Field(default=0)
    stat_audios: int = Field(default=0)
    stat_photos: int = Field(default=0)
    stat_videos: int = Field(default=0)
    stat_annotations: int = Field(default=0)
    stat_sites: int = Field(default=0)

    last_synced_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
