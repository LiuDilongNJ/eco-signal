from datetime import UTC, datetime

from sqlmodel import Session, delete, select

from app.models.network import NetworkNode
from app.schemas.network import NodeStats


class NetworkRepository:
    """Data access layer for network_node table."""

    # Reads

    def get_all(self, session: Session) -> list[NetworkNode]:
        """Return all known nodes ordered by is_local (local first) then name."""
        stmt = select(NetworkNode).order_by(
            NetworkNode.is_local.desc(), NetworkNode.name
        )
        return list(session.exec(stmt).all())

    def get_public_nodes(self, session: Session) -> list[NetworkNode]:
        """Return nodes that are currently discoverable to the public."""
        stmt = (
            select(NetworkNode)
            .where(NetworkNode.shared == True)  # noqa: E712
            .order_by(NetworkNode.is_local.desc(), NetworkNode.name)
        )
        return list(session.exec(stmt).all())

    def get_local_node(self, session: Session) -> NetworkNode | None:
        """Return the local instance row when it exists."""
        return session.exec(
            select(NetworkNode).where(NetworkNode.is_local == True)  # noqa: E712
        ).first()

    def get_by_url(self, session: Session, app_url: str) -> NetworkNode | None:
        """Look up a node by its canonical app_url."""
        return session.exec(
            select(NetworkNode).where(NetworkNode.app_url == app_url)
        ).first()

    def get_by_id(self, session: Session, node_id: int) -> NetworkNode | None:
        return session.get(NetworkNode, node_id)

    # Writes

    def upsert(
        self,
        session: Session,
        app_url: str,
        name: str,
        latitude: float | None,
        longitude: float | None,
        is_local: bool,
        shared: bool,
        stats: NodeStats,
    ) -> NetworkNode:
        """
        Insert a new node or update an existing one identified by app_url.
        Returns the persisted node.
        """
        node = self.get_by_url(session, app_url)
        now = datetime.now(UTC)

        if node is None:
            node = NetworkNode(
                app_url=app_url,
                name=name,
                latitude=latitude,
                longitude=longitude,
                is_local=is_local,
                shared=shared,
                stat_users=stats.users,
                stat_projects=stats.projects,
                stat_collections=stats.collections,
                stat_audios=stats.audios,
                stat_photos=stats.photos,
                stat_videos=stats.videos,
                stat_annotations=stats.annotations,
                stat_sites=stats.sites,
                last_synced_at=now,
                created_at=now,
            )
        else:
            node.name = name
            node.latitude = latitude
            node.longitude = longitude
            node.is_local = is_local
            node.shared = shared
            node.stat_users = stats.users
            node.stat_projects = stats.projects
            node.stat_collections = stats.collections
            node.stat_audios = stats.audios
            node.stat_photos = stats.photos
            node.stat_videos = stats.videos
            node.stat_annotations = stats.annotations
            node.stat_sites = stats.sites
            node.last_synced_at = now

        session.add(node)
        session.commit()
        session.refresh(node)
        return node

    def delete_remote_nodes(self, session: Session) -> int:
        """
        Delete all non-local nodes (used before a full HOST sync).
        Returns the number of deleted rows.
        """
        result = session.exec(
            delete(NetworkNode).where(NetworkNode.is_local == False)  # noqa: E712
        )
        session.commit()
        return result.rowcount  # type: ignore[attr-defined]

    def delete_by_id(self, session: Session, node_id: int) -> NetworkNode | None:
        node = session.get(NetworkNode, node_id)
        if node:
            session.delete(node)
            session.commit()
        return node


network_repository = NetworkRepository()
