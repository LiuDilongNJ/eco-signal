"""
Database connection and initialization module.
"""
from sqlmodel import Session, create_engine, select

from app.core.config import settings
from app.core.security import get_password_hash
from app.models import Role, User
from app.repositories import role_repository
from app.schemas.role import RoleCreate

engine = create_engine(
    str(settings.sqlalchemy_database_uri),
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_pre_ping=True,
)


def init_db(session: Session) -> None:
    """Initialize database with the configured superuser account."""
    admin_role: Role = session.exec(
        select(Role).where(Role.name == settings.ADMIN_ROLE_NAME)
    ).first()
    if not admin_role:
        role_in = RoleCreate(name=settings.ADMIN_ROLE_NAME)
        admin_role: Role = role_repository.create(session=session, obj_in=role_in)

    user: User | None = session.exec(
        select(User).where(User.username == settings.FIRST_SUPERUSER)
    ).first()
    if not user:
        user = session.get(User, 1)

    if user:
        user.username = settings.FIRST_SUPERUSER
        user.password = get_password_hash(settings.FIRST_SUPERUSER_PASSWORD)
        user.role_id = admin_role.role_id
        session.add(user)
        session.commit()
