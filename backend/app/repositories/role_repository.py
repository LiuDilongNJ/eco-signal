from app.models import Role
from app.repositories import BaseRepository
from app.schemas.role import RoleCreate, RoleUpdate
from sqlmodel import Session, select


class RoleRepository(BaseRepository[Role, RoleCreate, RoleUpdate]):

    def __init__(self):
        super().__init__(Role)

    def get_by_name(self, session: Session, name: str) -> Role | None:
        return session.exec(select(Role).where(Role.name == name)).first()

role_repository = RoleRepository()
