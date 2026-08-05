"""
Tests for anonymous access to collection options.
"""
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.models import Project, Collection, ProjectCollection


def test_get_collection_options_anonymous_no_project(client: TestClient) -> None:
    """Anonymous request without project_id should return 400."""
    r = client.get(f"{settings.API_V1_STR}/collection-options")
    assert r.status_code == 400
    assert r.json()["message"] == "project_id is required for unauthenticated requests"

def test_get_collection_options_anonymous_private_project(
    client: TestClient, db: Session
) -> None:
    """Anonymous request with private project should return empty list."""
    project = Project(name="Private Project", url="private", public=False, creator_id=1)
    db.add(project)
    db.commit()
    db.refresh(project)
    
    # Private project must have private collection or the database trigger will fail
    collection = Collection(name="Private Collection", public_access=False, creator_id=1)
    db.add(collection)
    db.commit()
    db.refresh(collection)
    
    pc = ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id)
    db.add(pc)
    db.commit()
    
    r = client.get(f"{settings.API_V1_STR}/collection-options?project_id={project.project_id}")
    assert r.status_code == 200
    assert r.json()["data"] == []

def test_get_collection_options_anonymous_public_project(
    client: TestClient, db: Session
) -> None:
    """Anonymous request with public project should return public collections."""
    project = Project(name="Public Project", url="public", public=True, creator_id=1)
    db.add(project)
    db.commit()
    db.refresh(project)
    
    c1 = Collection(name="Public Collection", public_access=True, creator_id=1)
    c2 = Collection(name="Private Collection", public_access=False, creator_id=1)
    db.add(c1)
    db.add(c2)
    db.commit()
    db.refresh(c1)
    db.refresh(c2)
    
    db.add(ProjectCollection(project_id=project.project_id, collection_id=c1.collection_id))
    db.add(ProjectCollection(project_id=project.project_id, collection_id=c2.collection_id))
    db.commit()
    
    r = client.get(f"{settings.API_V1_STR}/collection-options?project_id={project.project_id}")
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 1
    assert data[0]["name"] == "Public Collection"
    assert data[0]["collection_id"] == c1.collection_id

def test_get_collection_options_authenticated_no_project(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    """Authenticated user should still be able to get options without project_id."""
    # Ensure there's at least one collection
    Collection(name="Any Collection", creator_id=1)
    
    r = client.get(
        f"{settings.API_V1_STR}/collection-options",
        headers=superuser_token_headers
    )
    assert r.status_code == 200
    assert len(r.json()["data"]) >= 1
