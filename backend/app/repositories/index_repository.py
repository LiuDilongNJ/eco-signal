from sqlmodel import Session, select

from app.models.index import IndexType
from app.repositories.base import BaseRepository


class IndexTypeRepository(BaseRepository[IndexType, IndexType, IndexType]):
    """Repository for IndexType operations."""

    def __init__(self):
        super().__init__(IndexType)

    def get_by_name(self, session: Session, name: str) -> IndexType | None:
        """Get index type by name."""
        statement = select(IndexType).where(IndexType.name == name)
        return session.exec(statement).first()

    def get_by_id(self, session: Session, index_id: int) -> IndexType | None:
        """Get index type by its primary key."""
        statement = select(IndexType).where(IndexType.index_id == index_id)
        return session.exec(statement).first()

    def list_all(self, session: Session) -> list[IndexType]:
        """List all acoustic index types ordered by name."""
        statement = select(IndexType).order_by(IndexType.name.asc())
        return list(session.exec(statement).all())

    def get_or_create(
        self, session: Session, name: str, description: str | None = None
    ) -> IndexType:
        """Get existing index type or create new one."""
        existing = self.get_by_name(session, name)
        if existing:
            return existing

        new_type = IndexType(name=name, description=description)
        session.add(new_type)
        session.commit()
        session.refresh(new_type)
        return new_type


index_type_repository = IndexTypeRepository()
