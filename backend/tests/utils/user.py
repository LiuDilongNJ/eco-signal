"""
Test utilities for user operations.
"""
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import User
from app.repositories import user_repository
from app.schemas import UserCreate, UserUpdate
from tests.utils.utils import random_email, random_lower_string


def user_authentication_headers(
    *, client: TestClient, username: str, password: str
) -> dict[str, str]:
    """Get authentication headers for a user by username and password."""
    data = {"username": username, "password": password}

    r = client.post(f"{settings.API_V1_STR}/auth-tokens", data=data)
    response = r.json()
    token_data = response.get("data", response)
    auth_token = token_data["access_token"]
    headers = {"Authorization": f"Bearer {auth_token}"}
    return headers


def create_random_user(db: Session) -> User:
    email = random_email()
    password = random_lower_string()
    username = random_lower_string()[:20]
    user_in = UserCreate(
        username=username,
        name="Test User",
        email=email,
        password=password,
    )
    user = user_repository.create(session=db, obj_in=user_in)
    return user


def authentication_token_from_email(
    *, client: TestClient, email: str, db: Session
) -> dict[str, str]:
    """
    Return a valid token for the user with given email.

    If the user doesn't exist it is created first.
    Uses username for login authentication.
    """
    # Use a fixed password for test user to ensure consistency across tests
    password = "testpassword123"
    username = email.split("@")[0]  # Use email prefix as username
    
    # Check if user exists by email or username
    user = user_repository.get_by_email(session=db, email=email)
    if not user:
        user = user_repository.get_by_username(session=db, username=username)
    
    if not user:
        user_in_create = UserCreate(
            username=username,
            name="Test User",
            email=email,
            password=password,
        )
        user = user_repository.create(session=db, obj_in=user_in_create)
    else:
        # Update password and email to ensure they match expected values
        user_in_update = UserUpdate(password=password, email=email)
        user = user_repository.update(session=db, db_obj=user, obj_in=user_in_update)

    # Use username for login authentication
    return user_authentication_headers(client=client, username=user.username, password=password)

