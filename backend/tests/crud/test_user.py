"""
Tests for user repository operations.
"""
from fastapi.encoders import jsonable_encoder
from sqlmodel import Session

from app.core.security import verify_password
from app.models import User
from app.repositories import user_repository
from app.schemas import UserCreate, UserUpdate
from tests.utils.utils import random_email, random_lower_string


def create_test_user(db: Session, **kwargs) -> User:
    # Repository always assigns the normal role; promote afterwards when a test needs another role
    role_id = kwargs.pop("role_id", None)
    defaults = {
        "username": random_lower_string()[:20],
        "name": "Test User",
        "email": random_email(),
        "password": random_lower_string(),
    }
    defaults.update(kwargs)
    user_in = UserCreate(**defaults)
    user = user_repository.create(session=db, obj_in=user_in)
    if role_id is not None and user.role_id != role_id:
        user.role_id = role_id
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def test_create_user(db: Session) -> None:
    user = create_test_user(db)
    assert user.email
    assert hasattr(user, "password")
    # New users are always created with the normal "User" role
    assert user.role.name == "User"


def test_create_user_with_color(db: Session) -> None:
    user = create_test_user(db, color="#11aa33")
    assert user.color == "#11AA33"


def test_authenticate_user(db: Session) -> None:
    password = random_lower_string()
    user = create_test_user(db, password=password)
    authenticated_user = user_repository.authenticate_by_username(
        session=db, username=user.username, password=password
    )
    assert authenticated_user
    assert user.username == authenticated_user.username


def test_not_authenticate_user(db: Session) -> None:
    password = random_lower_string()
    user = user_repository.authenticate_by_username(
        session=db, username="nonexistent_user_xyz", password=password
    )
    assert user is None


def test_verify_password_returns_false_for_unknown_hash() -> None:
    unknown_hash = "803df8c6f34f1c51770c8bc872788845"
    assert verify_password("any-password", unknown_hash) is False


def test_check_if_user_is_active(db: Session) -> None:
    user = create_test_user(db)
    assert user.active is True


def test_check_if_user_is_active_inactive(db: Session) -> None:
    user = create_test_user(db, active=False)
    assert user.active is False


def test_check_if_user_is_superuser(db: Session) -> None:
    user = create_test_user(db, role_id=1)  # Superuser role
    assert user.role_id == 1


def test_check_if_user_is_superuser_normal_user(db: Session) -> None:
    user = create_test_user(db, role_id=2)  # Normal user role
    assert user.role_id == 2


def test_get_user(db: Session) -> None:
    user = create_test_user(db)
    user_2 = db.get(User, user.user_id)
    assert user_2
    assert user.email == user_2.email
    assert jsonable_encoder(user) == jsonable_encoder(user_2)


def test_update_user(db: Session) -> None:
    user = create_test_user(db)
    new_name = "Updated Name"
    user_in_update = UserUpdate(name=new_name)
    if user.user_id is not None:
        user_repository.update(session=db, db_obj=user, obj_in=user_in_update)
    user_2 = db.get(User, user.user_id)
    assert user_2
    assert user.email == user_2.email
    assert user_2.name == new_name


def test_update_user_color(db: Session) -> None:
    user = create_test_user(db)
    user_in_update = UserUpdate(color="#11aa33")
    if user.user_id is not None:
        user_repository.update(session=db, db_obj=user, obj_in=user_in_update)
    user_2 = db.get(User, user.user_id)
    assert user_2
    assert user_2.color == "#11AA33"
