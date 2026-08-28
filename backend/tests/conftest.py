import os
from collections.abc import Generator

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from psycopg import connect
from sqlalchemy import create_engine
from sqlmodel import SQLModel
from sqlmodel import Session

from app.api.deps import get_db
from app.core.config import settings
from app.core.db import init_db
from app.main import app
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import get_superuser_token_headers


@pytest.fixture(scope="session", autouse=True)
def _isolate_auth_environment() -> Generator[None, None, None]:
    """Keep idle-timeout auth off unless a test explicitly opts into staging/production.

    Host `.env` may set ENVIRONMENT=staging for the running app. Tests mint tokens
    without a Redis session family and stub Redis without activity keys, so the
    suite must not inherit that host setting.
    """
    original = settings.ENVIRONMENT
    settings.ENVIRONMENT = "local"
    yield
    settings.ENVIRONMENT = original


@pytest.fixture(scope="session")
def db_engine():
    """
    Session-scoped fixture to setup the test database.
    1. Creates 'ecosignal_test' database if it doesn't exist.
    2. Runs Alembic migrations to bring it to the latest schema.
    3. Initializes default data (admin user, etc.).
    4. Yields the SQLAlchemy engine for the test database.
    """
    # Database connection details
    user = settings.POSTGRES_USER
    password = settings.POSTGRES_PASSWORD
    server = settings.POSTGRES_SERVER
    port = settings.POSTGRES_PORT
    
    # We use a distinct name for the test database
    test_db_name = "ecosignal_test"
    
    # Connect to the default 'postgres' database to create the test database
    # We must use autocommit=True to execute CREATE DATABASE
    default_db_url = f"postgresql://{user}:{password}@{server}:{port}/postgres"
    
    try:
        with connect(default_db_url, autocommit=True) as conn:
            with conn.cursor() as cur:
                # Check if test database exists
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (test_db_name,))
                if not cur.fetchone():
                    print(f"Creating test database: {test_db_name}")
                    # template1 may carry a stale collation version in local dev
                    # containers; template0 avoids inheriting that mismatch.
                    cur.execute(f'CREATE DATABASE "{test_db_name}" TEMPLATE template0')
                else:
                    print(f"Test database {test_db_name} already exists")
    except Exception as e:
        raise RuntimeError(f"Could not ensure test database exists: {e}") from e

    # Patch settings to point to the test database
    # This affects how create_engine works and how Alembic finds the URL
    original_db_name = settings.POSTGRES_DB
    settings.POSTGRES_DB = test_db_name
    
    # Run Alembic Migrations
    # We need to point to the alembic.ini file in the project root
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    alembic_cfg_path = os.path.join(base_dir, "alembic.ini")
    
    if os.path.exists(alembic_cfg_path):
        alembic_cfg = Config(alembic_cfg_path)
        # Verify that Alembic will use the correct URL (from patched settings)
        # app/alembic/env.py reads settings.sqlalchemy_database_uri, so we are good.
        command.upgrade(alembic_cfg, "head")
    else:
        print(f"Warning: alembic.ini not found at {alembic_cfg_path}. Skipping migrations.")

    # Create Engine for the test database
    engine = create_engine(str(settings.sqlalchemy_database_uri))
    
    # Initialize DB (create admin user etc)
    # creates any tables models define that Alembic didn't create (e.g. foreign table IhoSeaArea)
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        init_db(session)
        
    yield engine
    
    # Cleanup/Teardown
    engine.dispose()
    # Restore original settings
    settings.POSTGRES_DB = original_db_name


@pytest.fixture(scope="function")
def db(db_engine) -> Generator[Session, None, None]:
    """
    Function-scoped fixture for test isolation.
    Opens a transaction for each test and rolls it back at the end.
    """
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    
    yield session
    
    session.close()
    # Only rollback if transaction is still active
    if transaction.is_active:
        transaction.rollback()
    connection.close()


@pytest.fixture(scope="function")
def client(db: Session) -> Generator[TestClient, None, None]:
    """
    Test client fixture using the transaction-isolated db session.
    """
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)


@pytest.fixture(scope="function")
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    # Ensure client fixture is used so dependency override is active
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
