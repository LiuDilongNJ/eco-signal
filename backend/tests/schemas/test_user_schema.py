import pytest
from pydantic import ValidationError

from app.schemas.user import UserUpdate


def test_user_update_accepts_null_color() -> None:
    schema = UserUpdate(color=None)

    assert schema.color is None


def test_user_update_rejects_invalid_color() -> None:
    with pytest.raises(ValidationError, match="color must be a hex value"):
        UserUpdate(color="#GGGGGG")
