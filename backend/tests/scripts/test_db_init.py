"""Unit tests for core/db.py init_db branches (lines 21-22, 28-34)."""
from unittest.mock import MagicMock, patch

from app.core.db import init_db


def test_init_db_creates_admin_role_when_missing():
    """init_db creates the admin role when it does not exist."""
    mock_session = MagicMock()

    # First exec: admin_role not found; second exec: user not found
    mock_session.exec.return_value.first.side_effect = [None, MagicMock()]

    with patch("app.core.db.role_repository") as mock_role_repo:
        mock_admin_role = MagicMock()
        mock_admin_role.role_id = 99
        mock_role_repo.create.return_value = mock_admin_role

        init_db(mock_session)

    mock_role_repo.create.assert_called_once()


def test_init_db_reuses_existing_admin_role():
    """init_db skips role creation when admin role already exists."""
    mock_session = MagicMock()
    existing_role = MagicMock()
    existing_role.role_id = 1

    # First exec: role found; second exec: user found
    mock_session.exec.return_value.first.side_effect = [existing_role, MagicMock()]

    with patch("app.core.db.role_repository") as mock_role_repo:
        init_db(mock_session)

    mock_role_repo.create.assert_not_called()


def test_init_db_updates_existing_user1_when_superuser_missing():
    """When superuser login not found but user id=1 exists, updates that user."""
    mock_session = MagicMock()
    existing_role = MagicMock()
    existing_role.role_id = 1

    # First exec: role exists; second exec: no user with superuser username
    mock_session.exec.return_value.first.side_effect = [existing_role, None]

    # session.get(User, 1) returns a user
    existing_user = MagicMock()
    mock_session.get.return_value = existing_user

    with patch("app.core.db.role_repository"):
        with patch("app.core.db.get_password_hash", return_value="hashed_pw"):
            init_db(mock_session)

    mock_session.add.assert_called_with(existing_user)
    mock_session.commit.assert_called()


def test_init_db_updates_existing_superuser_to_configured_password():
    """When the seeded admin user already exists, init_db should update it with the configured superuser credentials."""
    mock_session = MagicMock()
    existing_role = MagicMock()
    existing_role.role_id = 1
    existing_user = MagicMock()

    mock_session.exec.return_value.first.side_effect = [existing_role, existing_user]

    with patch("app.core.db.role_repository"):
        with patch("app.core.db.settings.FIRST_SUPERUSER", "admin"):
            with patch("app.core.db.settings.FIRST_SUPERUSER_PASSWORD", "new-secret"):
                with patch("app.core.db.get_password_hash", return_value="hashed_pw") as mock_hash:
                    init_db(mock_session)

    mock_hash.assert_called_once_with("new-secret")
    assert existing_user.username == "admin"
    assert existing_user.password == "hashed_pw"
    assert existing_user.role_id == 1
    mock_session.add.assert_called_with(existing_user)
    mock_session.commit.assert_called_once()


def test_init_db_does_nothing_when_both_missing():
    """When superuser not found and no user id=1, no updates are made."""
    mock_session = MagicMock()
    existing_role = MagicMock()
    existing_role.role_id = 1

    mock_session.exec.return_value.first.side_effect = [existing_role, None]
    mock_session.get.return_value = None  # no user with id=1

    with patch("app.core.db.role_repository"):
        init_db(mock_session)

    mock_session.add.assert_not_called()
