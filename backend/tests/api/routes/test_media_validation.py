from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings


def test_create_media_invalid_date_time_format(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    data = {
        "collection_id": 1,
        "file_upload_ids": [1],
        "date_time": "2024-03-10T19:45:53",  # ISO format, should fail
    }
    response = client.post(
        f"{settings.API_V1_STR}/media",
        headers=superuser_token_headers,
        json=data,
    )
    assert response.status_code == 422
    assert "date_time must be in format YYYY-MM-DD HH:mm:ss" in str(response.json())


def test_create_media_valid_date_time_format(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    # This just tests the Pydantic validation layer. 
    # Actual processing might fail later if fid 999999 doesn't exist, 
    # but it should pass the 422 schema validation stage.
    data = {
        "collection_id": 1,
        "file_upload_ids": [999999],
        "date_time": "2024-03-10 19:45:53",  # Correct format
    }
    response = client.post(
        f"{settings.API_V1_STR}/media",
        headers=superuser_token_headers,
        json=data,
    )
    # fid 999999 not found passes schema validation but fails batch validation.
    assert response.status_code == 409
    assert "FileUpload not found" in response.json()["message"]
