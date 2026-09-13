from sqlmodel import Session, select

from app.models.system import MLModel
from app.repositories.base import BaseRepository


class ModelRepository(BaseRepository[MLModel, MLModel, MLModel]):
    """Repository for machine learning model operations."""

    def __init__(self):
        super().__init__(MLModel)

    def get_by_id(self, session: Session, model_id: int) -> MLModel | None:
        """Get model by its primary key."""
        statement = select(MLModel).where(MLModel.model_id == model_id)
        return session.exec(statement).first()

    def get_by_name(self, session: Session, name: str) -> MLModel | None:
        """Get model by its name."""
        statement = select(MLModel).where(MLModel.name == name)
        return session.exec(statement).first()

    def list_all(self, session: Session) -> list[MLModel]:
        """List all machine learning models ordered by model_id."""
        statement = select(MLModel).order_by(MLModel.model_id.asc())
        return list(session.exec(statement).all())


model_repository = ModelRepository()
