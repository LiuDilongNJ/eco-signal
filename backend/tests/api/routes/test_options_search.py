from fastapi.testclient import TestClient
from sqlmodel import Session

from app.main import app
from app.models import Project, Collection, ProjectCollection

client = TestClient(app)

# Use creator_id=1 which usually exists in test environment (admin user)
TEST_CREATOR_ID = 1

def test_project_options_search(db: Session, superuser_token_headers):
    # Create test projects
    p1 = Project(name="Searchable Project A", url="http://a.com", public=True, creator_id=TEST_CREATOR_ID)
    p2 = Project(name="Other Project B", url="http://b.com", public=True, creator_id=TEST_CREATOR_ID)
    db.add(p1)
    db.add(p2)
    db.commit()

    # Search by name
    response = client.get("/api/v1/project-options?name=Searchable", headers=superuser_token_headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert any(p["name"] == "Searchable Project A" for p in data)
    assert not any(p["name"] == "Other Project B" for p in data)

def test_collection_options_search(db: Session, superuser_token_headers):
    # Create test project and collections
    p = Project(name="Test Project For Search", url="http://testsearch.com", public=True, creator_id=TEST_CREATOR_ID)
    db.add(p)
    db.commit()
    db.refresh(p)

    c1 = Collection(name="Searchable Collection X", public_access=True, creator_id=TEST_CREATOR_ID)
    c2 = Collection(name="Other Collection Y", public_access=True, creator_id=TEST_CREATOR_ID)
    db.add(c1)
    db.add(c2)
    db.commit()
    db.refresh(c1)
    db.refresh(c2)

    pc1 = ProjectCollection(project_id=p.project_id, collection_id=c1.collection_id)
    pc2 = ProjectCollection(project_id=p.project_id, collection_id=c2.collection_id)
    db.add(pc1)
    db.add(pc2)
    db.commit()

    # Search by name
    response = client.get(f"/api/v1/collection-options?project_id={p.project_id}&name=Searchable", headers=superuser_token_headers)
    assert response.status_code == 200
    data = response.json()["data"]
    # Should only return c1
    assert len(data) == 1
    assert data[0]["name"] == "Searchable Collection X"
