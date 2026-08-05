"""Unit tests for initial_data.py."""
from unittest.mock import MagicMock, patch

from app.initial_data import init, main


def test_init_calls_init_db():
    """init() opens a session and calls init_db."""
    mock_session = MagicMock()

    with (
        patch("app.initial_data.Session") as mock_session_cls,
        patch("app.initial_data.init_db") as mock_init_db,
    ):
        mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

        init()

        mock_init_db.assert_called_once_with(mock_session)


def test_main_calls_init():
    """main() logs and delegates to init()."""
    with (
        patch("app.initial_data.init") as mock_init,
        patch.object(__import__("app.initial_data", fromlist=["logger"]).logger, "info"),
    ):
        main()

        mock_init.assert_called_once()
