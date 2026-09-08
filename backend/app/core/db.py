"""
Database connection and initialization module.
"""
from sqlmodel import Session, create_engine, select, text

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


def sync_db_sequences(session: Session) -> None:
    """Synchronize all PostgreSQL sequence values with the current maximum column values."""
    bind = session.get_bind()
    if bind is None or getattr(getattr(bind, "dialect", None), "name", None) != "postgresql":
        return

    sync_sql = text(
        """
        DO $$
        DECLARE
            r RECORD;
            v_max BIGINT;
        BEGIN
            FOR r IN (
                SELECT 
                    t.relname AS tbl,
                    a.attname AS col,
                    s.relname AS seq
                FROM pg_class s
                JOIN pg_depend d ON d.objid = s.oid
                JOIN pg_class t ON d.refobjid = t.oid
                JOIN pg_attribute a ON (d.refobjid = a.attrelid AND d.refobjsubid = a.attnum)
                JOIN pg_namespace n ON n.oid = t.relnamespace
                WHERE s.relkind = 'S'
                  AND n.nspname = 'public'
                  AND t.relkind = 'r'
                ORDER BY t.relname
            ) LOOP
                EXECUTE format('SELECT COALESCE(MAX(%I), 0) FROM %I', r.col, r.tbl) INTO v_max;
                IF v_max > 0 THEN
                    EXECUTE format('SELECT setval(%L, %s, true)', r.seq, v_max);
                END IF;
            END LOOP;
        END $$;
        """
    )
    session.exec(sync_sql)
    session.commit()


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

    sync_db_sequences(session)
