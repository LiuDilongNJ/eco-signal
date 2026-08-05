"""
Test cases for collection API routes.
"""
import csv
from datetime import datetime, timedelta, UTC

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import (
    Collection,
    Project,
    Permission,
    UserPermission,
    ProjectCollection,
    CollectionTaxon,
    CollectionContributor,
)
from app.repositories import user_repository
from app.schemas import UserCreate
from tests.utils.csv import read_csv_header
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_lower_string, random_email


def create_test_collection(db: Session, creator_id: int = 1, **kwargs) -> Collection:
    """Helper function to create a test collection."""
    
    defaults = {
        "name": f"Test Collection {random_lower_string()[:10]}",
        "description": "Test description",
        "public_access": True,
        "public_tags": False,
        "creator_id": creator_id,
    }
    defaults.update(kwargs)
    collection = Collection(**defaults)
    db.add(collection)
    db.commit()
    db.refresh(collection)
    
    return collection


def create_test_project(db: Session, creator_id: int = 1, **kwargs) -> Project:
    """Helper function to create a test project."""
    defaults = {
        "name": f"Test Project {random_lower_string()[:10]}",
        "url": f"https://example.com/{random_lower_string()[:10]}",
        "description": "Test description",
        "public": True,
        "active": True,
        "creator_id": creator_id,
    }
    defaults.update(kwargs)
    project = Project(**defaults)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def link_collection_to_project(db: Session, collection: Collection, project: Project | None = None) -> Project:
    """Attach a collection to a project and return that project."""
    if project is None:
        project = create_test_project(db, creator_id=collection.creator_id, public=collection.public_access)
    existing = db.exec(
        select(ProjectCollection).where(
            ProjectCollection.project_id == project.project_id,
            ProjectCollection.collection_id == collection.collection_id,
        )
    ).first()
    if existing is None:
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()
    return project


def create_user_with_headers(db: Session, client: TestClient, *, name: str = "Test User"):
    """Create a user and return (user, auth_headers)."""
    email = random_email()
    password = "testpassword123"
    user_in = UserCreate(
        username=random_lower_string()[:20],
        name=name,
        email=email,
        password=password,
    )
    user = user_repository.create(session=db, obj_in=user_in)
    headers = user_authentication_headers(client=client, username=user.username, password=password)
    return user, headers


class TestCollectionList:
    """Tests for GET /collections endpoint."""
    
    def test_list_collections_anonymous_restricted(
        self, client: TestClient, db: Session
    ) -> None:
        """Anonymous user cannot list collections via main endpoint."""
        create_test_collection(db, public_access=True)
        
        r = client.get(f"{settings.API_V1_STR}/collections")
        assert r.status_code == 401

    def test_list_collections_authenticated(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Authenticated user (Admin) can list collections."""
        create_test_collection(db)
        
        r = client.get(
            f"{settings.API_V1_STR}/collections",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        json_resp = r.json()
        assert json_resp["code"] == 0
        data = json_resp
        assert "data" in data
        assert len(data["data"]) >= 1
    
    def test_list_collections_manager_limited(
        self, client: TestClient, db: Session
    ) -> None:
        """Manager only sees collections they have write permission for."""
        
        # 1. Create a manager user manually to know the password
        email = random_email()
        password = "testpassword123"
        user_in = UserCreate(
            username=random_lower_string()[:20],
            name="Test Manager",
            email=email,
            password=password,
        )
        manager = user_repository.create(session=db, obj_in=user_in)
        
        # 2. Create two collections
        managed_coll = create_test_collection(db, name="Managed Collection", public_access=False)
        create_test_collection(db, name="Other Collection", public_access=True)
        project = link_collection_to_project(db, managed_coll)
        
        # 3. Grant write permission on managed_coll to manager
        write_perm = db.exec(select(Permission).where(Permission.resource_type == "collection", Permission.action == "write")).first()
        up = UserPermission(user_id=manager.user_id, permission_id=write_perm.permission_id, project_id=project.project_id, collection_id=managed_coll.collection_id)
        db.add(up)
        db.add_all(
            [
                CollectionTaxon(
                    collection_id=managed_coll.collection_id,
                    col_taxon_id="manager-taxon-1",
                    cached_name="Manager Taxon One",
                ),
                CollectionTaxon(
                    collection_id=managed_coll.collection_id,
                    col_taxon_id="manager-taxon-2",
                    cached_name="Manager Taxon Two",
                ),
            ]
        )
        db.commit()
        
        # 4. Get authentication headers for manager
        headers = user_authentication_headers(client=client, username=manager.username, password=password)
        
        # 5. List collections
        r = client.get(
            f"{settings.API_V1_STR}/collections",
            params={"taxon_name": "manager", "page_size": 1},
            headers=headers
        )
        assert r.status_code == 200
        data = r.json()["data"]
        
        # Should only see the managed one, NOT the other_coll (even if it is public)
        # Because we passed managed_only=True in the route
        assert len(data) == 1
        assert data[0]["name"] == "Managed Collection"
        assert not any(c["name"] == "Other Collection" for c in data)
        assert r.json()["page_info"]["total"] == 1
    
    def test_list_collections_with_filters(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Test collection filtering functionality with multiple fields."""
        
        # Create test collections with specific attributes
        c1 = create_test_collection(
            db, 
            name="Unique Amazon Collection", 
            doi="10.1234/amazon", 
            sphere="biosphere",
            public_access=True
        )
        c2 = create_test_collection(
            db, 
            name="Ocean Monitoring", 
            doi="10.1234/ocean", 
            sphere="hydrosphere",
            public_access=False
        )
        
        # Manually adjust creation dates for testing date filters
        c1.creation_date = datetime.now(UTC) - timedelta(days=10)
        c2.creation_date = datetime.now(UTC) - timedelta(days=2)
        db.add_all([c1, c2])
        db.commit()
        
        # 1. Test fuzzy matching on name
        r = client.get(
            f"{settings.API_V1_STR}/collections?name=Amazon",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) >= 1
        assert any(c["name"] == "Unique Amazon Collection" for c in data)
        assert not any(c["name"] == "Ocean Monitoring" for c in data)
        
        # 2. Test fuzzy matching on DOI
        r = client.get(
            f"{settings.API_V1_STR}/collections?doi=ocean",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["doi"] == "10.1234/ocean"
        
        # 3. Test exact matching on sphere and public_access
        r = client.get(
            f"{settings.API_V1_STR}/collections?sphere=hydrosphere&public_access=false",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["sphere"] == "hydrosphere"

        r = client.get(
            f"{settings.API_V1_STR}/collections?sphere=hydro",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["sphere"] == "hydrosphere"
        
        # 4. Test date range filtering
        from_dt = (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=5)).isoformat()
        r = client.get(
            f"{settings.API_V1_STR}/collections?creation_date_from={from_dt}",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) >= 1
        assert any(c["name"] == "Ocean Monitoring" for c in data)
        
        # Test creation_date_to
        to_dt = (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=5)).isoformat()
        r = client.get(
            f"{settings.API_V1_STR}/collections?creation_date_to={to_dt}",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) >= 1
        assert any(c["name"] == "Unique Amazon Collection" for c in data)
        assert not any(c["name"] == "Ocean Monitoring" for c in data)
        # 5. Test public_tags and taxon filtering
        
        c3 = create_test_collection(
            db, 
            name="Forest Monitoring", 
            public_access=True,
            public_tags=True
        )
        t1 = CollectionTaxon(collection_id=c3.collection_id, col_taxon_id="123", cached_name="Ursidae")
        db.add(t1)
        db.commit()
        
        r = client.get(
            f"{settings.API_V1_STR}/collections?public_tags=true&taxon_name=Ursidae",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) >= 1
        
        # Verify response structure including newly added eager loaded relations
        c3_response = next((c for c in data if c["name"] == "Forest Monitoring"), None)
        assert c3_response is not None
        assert "creator_id" in c3_response
        assert "taxons" in c3_response
        assert isinstance(c3_response["taxons"], list)
        assert len(c3_response["taxons"]) > 0
        assert c3_response["taxons"][0]["cached_name"] == "Ursidae"
        
        # 6. Test other exact and fuzzy filters (project_id, collection_id, uuid, project_url, external_media_url, creator_id)
        c4 = create_test_collection(
            db, 
            name="Filter Collection", 
            project_url="https://external.test/project",
            external_media_url="https://external.test/media",
            creator_id=c1.creator_id,
            public_access=True
        )
        proj = create_test_project(db)
        db.add(ProjectCollection(project_id=proj.project_id, collection_id=c4.collection_id))
        db.commit()
        
        r = client.get(
            f"{settings.API_V1_STR}/collections?project_id={proj.project_id}",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        assert len(r.json()["data"]) == 1
        assert r.json()["data"][0]["collection_id"] == c4.collection_id
        
        r = client.get(
            f"{settings.API_V1_STR}/collections?collection_id={c4.collection_id}",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        assert len(r.json()["data"]) == 1
        assert r.json()["data"][0]["collection_id"] == c4.collection_id
        
        r = client.get(
            f"{settings.API_V1_STR}/collections?uuid={c4.uuid}",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        assert len(r.json()["data"]) == 1
        assert r.json()["data"][0]["uuid"] == str(c4.uuid)

        r = client.get(
            f"{settings.API_V1_STR}/collections?project_url=external.test/proj",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        assert len(r.json()["data"]) == 1
        assert r.json()["data"][0]["project_url"] == "https://external.test/project"
        
        r = client.get(
            f"{settings.API_V1_STR}/collections?external_media_url=external.test/medi",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        assert len(r.json()["data"]) == 1
        assert r.json()["data"][0]["external_media_url"] == "https://external.test/media"
        
        r = client.get(
            f"{settings.API_V1_STR}/collections?creator_id={c1.creator_id}",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) >= 1
        assert all(c["creator_id"] == c1.creator_id for c in data)

    def test_list_collections_filters_taxon_once_and_counts_once(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Taxon filtering is case-insensitive and counts each collection once."""
        matching = create_test_collection(db, name="Taxon Match")
        non_matching = create_test_collection(db, name="Taxon Miss")
        db.add_all(
            [
                CollectionTaxon(
                    collection_id=matching.collection_id,
                    col_taxon_id="taxon-match-1",
                    cached_name="Silver Falcon",
                ),
                CollectionTaxon(
                    collection_id=matching.collection_id,
                    col_taxon_id="taxon-match-2",
                    cached_name="Mountain Falcon",
                ),
                CollectionTaxon(
                    collection_id=non_matching.collection_id,
                    col_taxon_id="taxon-miss",
                    cached_name="River Otter",
                ),
            ]
        )
        db.commit()

        response = client.get(
            f"{settings.API_V1_STR}/collections",
            params={"taxon_name": "FALCON", "page_size": 1},
            headers=superuser_token_headers,
        )

        assert response.status_code == 200
        payload = response.json()
        assert [item["collection_id"] for item in payload["data"]] == [matching.collection_id]
        assert payload["page_info"]["total"] == 1

    def test_list_collections_with_new_order(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Test collection ordering by creator_name, public_tags and taxon."""
        
        c1 = create_test_collection(db, name="C1", public_access=True, public_tags=False)
        c2 = create_test_collection(db, name="C2", public_access=True, public_tags=True)
        
        # Add taxons
        db.add(CollectionTaxon(collection_id=c1.collection_id, col_taxon_id="1", cached_name="Apple"))
        db.add(CollectionTaxon(collection_id=c2.collection_id, col_taxon_id="2", cached_name="Banana"))
        db.commit()
        
        # Order by public_tags desc
        r = client.get(
            f"{settings.API_V1_STR}/collections?order_by=public_tags&order_dir=desc",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        data = r.json()["data"]
        # In python True > False
        tags = [c["public_tags"] for c in data if c["name"] in ["C1", "C2"]]
        assert tags == [True, False]
        
        # Order by taxon asc
        r = client.get(
            f"{settings.API_V1_STR}/collections?order_by=taxon_name&order_dir=asc",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        data = r.json()["data"]
        # Should be Apple (c1) then Banana (c2)
        c_names = [c["name"] for c in data if c["name"] in ["C1", "C2"]]
        assert c_names == ["C1", "C2"]
        
        # Order by creator_name asc
        r = client.get(
            f"{settings.API_V1_STR}/collections?order_by=creator_name&order_dir=asc",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
    def test_list_collections_with_order(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Test collection ordering by different fields."""
        create_test_collection(db, name="AAA Collection", public_access=True)
        create_test_collection(db, name="ZZZ Collection", public_access=True)
        
        # Order by name ascending
        r = client.get(
            f"{settings.API_V1_STR}/collections?order_by=name&order_dir=asc",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        json_resp = r.json()
        assert json_resp["code"] == 0
        data = json_resp
        names = [c["name"] for c in data["data"]]
        assert names == sorted(names)
        
        # Order by name descending
        r = client.get(
            f"{settings.API_V1_STR}/collections?order_by=name&order_dir=desc",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        json_resp = r.json()
        assert json_resp["code"] == 0
        data = json_resp
        names = [c["name"] for c in data["data"]]
        assert names == sorted(names, reverse=True)


class TestCollectionView:
    """Tests for GET /collection-overviews endpoint."""

    def test_collection_view_anonymous_public_success(self, client: TestClient, db: Session) -> None:
        """Anonymous user can access when both project and collection are public."""
        creator, _ = create_user_with_headers(db, client, name="Researcher D")
        project = create_test_project(
            db,
            creator_id=creator.user_id,
            name="Canopy Audio - Phase D",
            public=True,
            picture_id="phase-d.jpg",
        )
        collection = create_test_collection(
            db,
            creator_id=creator.user_id,
            name="Phase D Collection",
            description="Spectrogram reveals distinct banding patterns.",
            sphere="biosphere",
            external_media_url="https://external.example/media/phase-d",
            project_url="https://external.example/project/phase-d",
            public_access=True,
        )
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.add(CollectionTaxon(collection_id=collection.collection_id, col_taxon_id="tx-1", cached_name="Ursus arctos"))
        db.add(CollectionTaxon(collection_id=collection.collection_id, col_taxon_id="tx-2", cached_name="Aquila"))
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/collection-overviews",
            params={"project_id": project.project_id, "collection_id": collection.collection_id},
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload["code"] == 0
        data = payload["data"]
        assert data["project_id"] == project.project_id
        assert data["project_name"] == "Canopy Audio - Phase D"
        assert data["project_picture_url"] == f"{settings.media_base_url}/projects/phase-d.jpg"
        assert data["collection_id"] == collection.collection_id
        assert data["collection_name"] == "Phase D Collection"
        assert data["collection_code"] == f"col.{collection.collection_id}"
        assert data["researcher_name"] == "Researcher D"
        assert data["sphere"] == "biosphere"
        assert data["external_media_url"] == "https://external.example/media/phase-d"
        assert data["project_url"] == "https://external.example/project/phase-d"
        assert data["description"] == "Spectrogram reveals distinct banding patterns."
        assert sorted(data["taxon_tags"]) == ["Aquila", "Ursus arctos"]

    def test_collection_view_anonymous_private_denied(self, client: TestClient, db: Session) -> None:
        """Anonymous user is denied when collection is private."""
        project = create_test_project(db, public=True)
        collection = create_test_collection(db, public_access=False)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/collection-overviews",
            params={"project_id": project.project_id, "collection_id": collection.collection_id},
        )
        assert r.status_code == 403


    def test_collection_view_private_with_collection_read_permission(
        self, client: TestClient, db: Session
    ) -> None:
        """Authenticated user with collection:read can access private data."""
        project = create_test_project(db, public=False, picture_id="private-phase.jpg")
        collection = create_test_collection(
            db,
            public_access=False,
            description="Private description from collection field.",
            sphere="hydrosphere",
            external_media_url="https://private.example/media",
            project_url="https://private.example/project",
        )
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))

        viewer, headers = create_user_with_headers(db, client, name="Collection Reader")
        read_perm = db.exec(
            select(Permission).where(
                (Permission.resource_type == "collection") & (Permission.action == "read")
            )
        ).one()
        db.add(
            UserPermission(
                user_id=viewer.user_id,
                project_id=project.project_id,
                collection_id=collection.collection_id,
                permission_id=read_perm.permission_id,
            )
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/collection-overviews",
            params={"project_id": project.project_id, "collection_id": collection.collection_id},
            headers=headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["description"] == "Private description from collection field."
        assert data["project_picture_url"] == f"{settings.media_base_url}/projects/private-phase.jpg"
        assert data["sphere"] == "hydrosphere"
        assert data["external_media_url"] == "https://private.example/media"
        assert data["project_url"] == "https://private.example/project"

    def test_collection_view_returns_empty_strings_for_nullable_links(
        self, client: TestClient, db: Session
    ) -> None:
        """Nullable collection fields should be normalized to empty strings."""
        project = create_test_project(db, public=True, picture_id="nullable.jpg")
        collection = create_test_collection(
            db,
            public_access=True,
            sphere=None,
            external_media_url=None,
            project_url=None,
        )
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/collection-overviews",
            params={"project_id": project.project_id, "collection_id": collection.collection_id},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["sphere"] == ""
        assert data["external_media_url"] == ""
        assert data["project_url"] == ""

    def test_collection_view_mismatched_project_collection_returns_400(
        self, client: TestClient, db: Session
    ) -> None:
        """collection_id not belonging to project_id should not leak public data."""
        project = create_test_project(db, public=True)
        collection = create_test_collection(db, public_access=True)

        r = client.get(
            f"{settings.API_V1_STR}/collection-overviews",
            params={"project_id": project.project_id, "collection_id": collection.collection_id},
        )
        assert r.status_code == 403

    def test_collection_view_project_not_found_returns_404(self, client: TestClient, db: Session) -> None:
        """Non-existent project should return 404."""
        collection = create_test_collection(db, public_access=True)
        r = client.get(
            f"{settings.API_V1_STR}/collection-overviews",
            params={"project_id": 999999, "collection_id": collection.collection_id},
        )
        assert r.status_code == 404


class TestCollectionGet:
    """Tests for GET /collections/{id} endpoint."""
    
    def test_get_collection_admin(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Admin can get any collection details."""
        collection = create_test_collection(db)
        project = link_collection_to_project(db, collection)
        
        r = client.get(
            f"{settings.API_V1_STR}/collections/{collection.collection_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        json_resp = r.json()
        assert json_resp["code"] == 0
        assert json_resp["data"]["collection_id"] == collection.collection_id

    def test_get_collection_returns_project_ids_and_taxons(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Detail endpoint should include project_ids and non-null taxon fields."""
        project = create_test_project(db)
        collection = create_test_collection(db, public_access=True)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.add(
            CollectionTaxon(
                collection_id=collection.collection_id,
                col_taxon_id="tx-1001",
                cached_name="Canis lupus",
            )
        )
        db.add(
            CollectionTaxon(
                collection_id=collection.collection_id,
                col_taxon_id="tx-1002",
                cached_name="Vulpes vulpes",
            )
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/collections/{collection.collection_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload["code"] == 0

        detail = payload["data"]
        assert project.project_id in detail["project_ids"]
        assert len(detail["taxons"]) == 2
        assert all(t["id"] is not None for t in detail["taxons"])
        assert {t["cached_name"] for t in detail["taxons"]} == {"Canis lupus", "Vulpes vulpes"}
    
    def test_get_collection_with_write_permission(
        self, client: TestClient, db: Session
    ) -> None:
        """User with collection:write permission can get details."""

        # 1. Create a user
        email = "manager2@example.com"
        password = "testpassword123"
        user_in = UserCreate(
            username="testmanager2",
            name="Test Manager 2",
            email=email,
            password=password,
        )
        manager = user_repository.create(session=db, obj_in=user_in)
        
        # 2. Create a collection
        collection = create_test_collection(db)
        project = link_collection_to_project(db, collection)
        
        # 3. Grant collection:write
        write_perm = db.exec(select(Permission).where(
            (Permission.resource_type == "collection") & (Permission.action == "write")
        )).one()
        db.add(UserPermission(user_id=manager.user_id, project_id=project.project_id, collection_id=collection.collection_id, permission_id=write_perm.permission_id))
        db.commit()

        # 4. Auth
        headers = user_authentication_headers(client=client, username="testmanager2", password=password)

        # 5. Get
        r = client.get(
            f"{settings.API_V1_STR}/collections/{collection.collection_id}",
            headers=headers,
        )
        assert r.status_code == 200

    def test_get_collection_with_write_permission_on_any_project_path(
        self, client: TestClient, db: Session
    ) -> None:
        """User with collection:write on any linked path can get details."""
        email = "manager2b@example.com"
        password = "testpassword123"
        user_in = UserCreate(
            username="testmanager2b",
            name="Test Manager 2B",
            email=email,
            password=password,
        )
        manager = user_repository.create(session=db, obj_in=user_in)

        collection = create_test_collection(db)
        project_a = create_test_project(db)
        project_b = create_test_project(db)
        db.add(ProjectCollection(project_id=project_a.project_id, collection_id=collection.collection_id))
        db.add(ProjectCollection(project_id=project_b.project_id, collection_id=collection.collection_id))

        write_perm = db.exec(
            select(Permission).where(
                (Permission.resource_type == "collection") & (Permission.action == "write")
            )
        ).one()
        db.add(
            UserPermission(
                user_id=manager.user_id,
                project_id=project_b.project_id,
                collection_id=collection.collection_id,
                permission_id=write_perm.permission_id,
            )
        )
        db.commit()

        headers = user_authentication_headers(client=client, username="testmanager2b", password=password)
        r = client.get(
            f"{settings.API_V1_STR}/collections/{collection.collection_id}",
            headers=headers,
        )
        assert r.status_code == 200

    def test_get_collection_no_permission_fails(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """User without write permission gets 403."""
        collection = create_test_collection(db)
        project = link_collection_to_project(db, collection)
        
        r = client.get(
            f"{settings.API_V1_STR}/collections/{collection.collection_id}",
            headers=normal_user_token_headers,
        )
        assert r.status_code == 403

    def test_get_collection_anonymous_forbidden(
        self, client: TestClient, db: Session
    ) -> None:
        """Anonymous user cannot get collection details."""
        collection = create_test_collection(db, public_access=True)
        project = link_collection_to_project(db, collection)
        r = client.get(
            f"{settings.API_V1_STR}/collections/{collection.collection_id}",
        )
        assert r.status_code == 401

    def test_get_collection_not_found(
        self, client: TestClient, superuser_token_headers: dict[str, str]
    ) -> None:
        """Returns 404 for non-existent collection."""
        r = client.get(
            f"{settings.API_V1_STR}/collections/99999",
            headers=superuser_token_headers,
        )
        assert r.status_code == 404


class TestCollectionCreate:
    """Tests for POST /collections endpoint."""
    
    def test_create_collection_admin(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Admin can create a collection for any project."""
        project = create_test_project(db)
        data = {
            "name": f"New Collection {random_lower_string()[:10]}",
            "description": "New collection description",
            "public_access": True,
        }
        r = client.post(
            f"{settings.API_V1_STR}/collections",
            params={"project_id": project.project_id},
            headers=superuser_token_headers,
            json=data
        )
        assert r.status_code == 201
        json_resp = r.json()
        assert json_resp["code"] == 0
        assert json_resp["data"] is None
        col = db.exec(select(Collection).where(Collection.name == data["name"])).first()
        assert col is not None

        # Verify ProjectCollection association
        pc = db.exec(select(ProjectCollection).where(
            (ProjectCollection.project_id == project.project_id) &
            (ProjectCollection.collection_id == col.collection_id)
        )).first()
        assert pc is not None

    def test_create_collection_with_project_write_permission(
        self, client: TestClient, db: Session
    ) -> None:
        """User with project:write permission can create collection in that project."""

        # 1. Create a user
        email = "manager3@example.com"
        password = "testpassword123"
        user_in = UserCreate(
            username="testmanager3",
            name="Test Manager 3",
            email=email,
            password=password,
        )
        manager = user_repository.create(session=db, obj_in=user_in)
        
        # 2. Create a project
        project = create_test_project(db)
        
        # 3. Grant project:write
        write_perm = db.exec(select(Permission).where(
            (Permission.resource_type == "project") & (Permission.action == "write")
        )).one()
        db.add(UserPermission(user_id=manager.user_id, project_id=project.project_id, permission_id=write_perm.permission_id))
        db.commit()

        # 4. Auth
        headers = user_authentication_headers(client=client, username="testmanager3", password=password)

        # 5. Create
        data = {"name": "Manager's Collection"}
        r = client.post(
            f"{settings.API_V1_STR}/collections",
            params={"project_id": project.project_id},
            headers=headers,
            json=data
        )
        assert r.status_code == 201
        row = db.exec(select(Collection).where(Collection.name == "Manager's Collection")).first()
        assert row is not None

    def test_create_public_collection_in_private_project_fails(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Creating public collection in private project should return 400."""
        private_project = create_test_project(db, public=False)
        data = {
            "name": f"Public In Private {random_lower_string()[:8]}",
            "public_access": True,
        }
        r = client.post(
            f"{settings.API_V1_STR}/collections",
            params={"project_id": private_project.project_id},
            headers=superuser_token_headers,
            json=data,
        )
        assert r.status_code == 400
        assert r.json()["message"] == "Cannot set public_access=true when associated project is private"

    def test_create_collection_no_project_id_fails(
        self, client: TestClient, superuser_token_headers: dict[str, str]
    ) -> None:
        """Missing project_id query param results in 400."""
        r = client.post(
            f"{settings.API_V1_STR}/collections",
            headers=superuser_token_headers,
            json={"name": "No Project Collection"}
        )
        assert r.status_code == 400

    def test_create_collection_no_permission_fails(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """User without write permission on project gets 403."""
        project = create_test_project(db)
        
        r = client.post(
            f"{settings.API_V1_STR}/collections",
            params={"project_id": project.project_id},
            headers=normal_user_token_headers,
            json={"name": "No Permission Collection"}
        )
        assert r.status_code == 403

    def test_create_collection_anonymous_forbidden(
        self, client: TestClient, db: Session
    ) -> None:
        """Anonymous user cannot create a collection."""
        project = create_test_project(db)
        r = client.post(
            f"{settings.API_V1_STR}/collections", 
            params={"project_id": project.project_id},
            json={"name": "Anonymous Collection"}
        )
        assert r.status_code == 401


class TestCollectionUpdate:
    """Tests for PATCH /collections/{id} endpoint."""
    
    def test_update_collection_admin(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Admin can update any collection."""
        collection = create_test_collection(db)
        project = link_collection_to_project(db, collection)
        data = {"name": "Updated Name"}
        
        r = client.patch(
            f"{settings.API_V1_STR}/collections/{collection.collection_id}",
            headers=superuser_token_headers,
            json=data
        )
        assert r.status_code == 200
        assert r.json()["data"] is None
        db.refresh(collection)
        assert collection.name == "Updated Name"

    def test_update_collection_with_write_permission(
        self, client: TestClient, db: Session
    ) -> None:
        """User with collection:write permission can update details."""

        # 1. Create a user
        email = "manager4@example.com"
        password = "testpassword123"
        user_in = UserCreate(
            username="testmanager4",
            name="Test Manager 4",
            email=email,
            password=password,
        )
        manager = user_repository.create(session=db, obj_in=user_in)
        
        # 2. Create a collection
        collection = create_test_collection(db)
        project = link_collection_to_project(db, collection)
        
        # 3. Grant collection:write
        write_perm = db.exec(select(Permission).where(
            (Permission.resource_type == "collection") & (Permission.action == "write")
        )).one()
        db.add(UserPermission(user_id=manager.user_id, project_id=project.project_id, collection_id=collection.collection_id, permission_id=write_perm.permission_id))
        db.commit()

        # 4. Auth
        headers = user_authentication_headers(client=client, username="testmanager4", password=password)

        # 5. Update
        data = {"name": "New Manager Name"}
        r = client.patch(
            f"{settings.API_V1_STR}/collections/{collection.collection_id}",
            headers=headers,
            json=data
        )
        assert r.status_code == 200

    def test_update_collection_with_write_permission_on_any_project_path(
        self, client: TestClient, db: Session
    ) -> None:
        """User with collection:write on any linked path can update details."""
        email = "manager4b@example.com"
        password = "testpassword123"
        user_in = UserCreate(
            username="testmanager4b",
            name="Test Manager 4B",
            email=email,
            password=password,
        )
        manager = user_repository.create(session=db, obj_in=user_in)

        collection = create_test_collection(db)
        project_a = create_test_project(db)
        project_b = create_test_project(db)
        db.add(ProjectCollection(project_id=project_a.project_id, collection_id=collection.collection_id))
        db.add(ProjectCollection(project_id=project_b.project_id, collection_id=collection.collection_id))

        write_perm = db.exec(
            select(Permission).where(
                (Permission.resource_type == "collection") & (Permission.action == "write")
            )
        ).one()
        db.add(
            UserPermission(
                user_id=manager.user_id,
                project_id=project_b.project_id,
                collection_id=collection.collection_id,
                permission_id=write_perm.permission_id,
            )
        )
        db.commit()

        headers = user_authentication_headers(client=client, username="testmanager4b", password=password)
        r = client.patch(
            f"{settings.API_V1_STR}/collections/{collection.collection_id}",
            headers=headers,
            json={"name": "Updated via Any Path"},
        )
        assert r.status_code == 200

    def test_update_collection_to_public_with_private_project_fails(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Updating to public_access=true should fail when linked project is private."""
        private_project = create_test_project(db, public=False)
        collection = create_test_collection(db, public_access=False)
        db.add(
            ProjectCollection(
                project_id=private_project.project_id,
                collection_id=collection.collection_id,
            )
        )
        db.commit()

        r = client.patch(
            f"{settings.API_V1_STR}/collections/{collection.collection_id}",
            headers=superuser_token_headers,
            json={"public_access": True},
        )
        assert r.status_code == 400
        assert r.json()["message"] == "Cannot set public_access=true when associated project is private"

    def test_update_collection_no_permission_fails(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """User without write permission gets 403."""
        collection = create_test_collection(db)
        project = link_collection_to_project(db, collection)
        
        r = client.patch(
            f"{settings.API_V1_STR}/collections/{collection.collection_id}",
            headers=normal_user_token_headers,
            json={"name": "Attemp Update"}
        )
        assert r.status_code == 403

    def test_update_collection_not_found(
        self, client: TestClient, superuser_token_headers: dict[str, str]
    ) -> None:
        """Returns 404 for non-existent collection."""
        r = client.patch(
            f"{settings.API_V1_STR}/collections/99999",
            headers=superuser_token_headers,
            json={"name": "Updated"}
        )
        assert r.status_code == 404


class TestCollectionDelete:
    """Tests for DELETE /collections/{id} endpoint."""
    
    def test_delete_collection_admin(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Admin can delete a collection."""
        project = create_test_project(db)
        collection = create_test_collection(db)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()
        
        collection_id = collection.collection_id
        
        r = client.delete(
            f"{settings.API_V1_STR}/collections/{collection_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        
        # Verify collection is deleted
        deleted = db.exec(select(Collection).where(Collection.collection_id == collection_id)).first()
        assert deleted is None

    def test_delete_collection_with_project_write_permission(
        self, client: TestClient, db: Session
    ) -> None:
        """User with project:write permission can delete collections in that project."""

        # 1. Create a user
        email = "manager6@example.com"
        password = "testpassword123"
        user_in = UserCreate(
            username="testmanager6",
            name="Test Manager 6",
            email=email,
            password=password,
        )
        manager = user_repository.create(session=db, obj_in=user_in)
        
        # 2. Create a project
        project = create_test_project(db)
        
        # 3. Create a collection and associate it
        collection = create_test_collection(db)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        
        # 4. Grant project:write
        write_perm = db.exec(select(Permission).where(
            (Permission.resource_type == "project") & (Permission.action == "write")
        )).one()
        db.add(UserPermission(user_id=manager.user_id, project_id=project.project_id, permission_id=write_perm.permission_id))
        db.commit()

        # 5. Auth
        headers = user_authentication_headers(client=client, username="testmanager6", password=password)

        # 6. Delete
        collection_id = collection.collection_id
        r = client.delete(
            f"{settings.API_V1_STR}/collections/{collection_id}",
            headers=headers,
        )
        assert r.status_code == 200
        
        # Verify collection is deleted
        deleted = db.exec(select(Collection).where(Collection.collection_id == collection_id)).first()
        assert deleted is None

    def test_delete_collection_cleans_relationships(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Deleting a collection clears dependent relationship rows first."""
        project = create_test_project(db)
        collection = create_test_collection(db)
        contributor, _ = create_user_with_headers(db, client, name="Collection Contributor")
        read_perm = db.exec(select(Permission).where(Permission.name == "collection:read")).one()

        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()
        db.add(CollectionContributor(collection_id=collection.collection_id, user_id=contributor.user_id))
        db.add(CollectionTaxon(collection_id=collection.collection_id, col_taxon_id="delete-test", cached_name="Delete Test"))
        db.add(
            UserPermission(
                user_id=contributor.user_id,
                project_id=project.project_id,
                collection_id=collection.collection_id,
                permission_id=read_perm.permission_id,
            )
        )
        db.commit()

        collection_id = collection.collection_id
        r = client.delete(
            f"{settings.API_V1_STR}/collections/{collection_id}",
            headers=superuser_token_headers,
        )

        assert r.status_code == 200
        assert db.exec(select(Collection).where(Collection.collection_id == collection_id)).first() is None
        assert db.exec(select(ProjectCollection).where(ProjectCollection.collection_id == collection_id)).first() is None
        assert db.exec(select(CollectionContributor).where(CollectionContributor.collection_id == collection_id)).first() is None
        assert db.exec(select(CollectionTaxon).where(CollectionTaxon.collection_id == collection_id)).first() is None
        assert db.exec(select(UserPermission).where(UserPermission.collection_id == collection_id)).first() is None

    def test_delete_collection_with_any_linked_project_write_permission(
        self, client: TestClient, db: Session
    ) -> None:
        """User can delete when having project:write on any linked project."""
        email = "manager6b@example.com"
        password = "testpassword123"
        user_in = UserCreate(
            username="testmanager6b",
            name="Test Manager 6B",
            email=email,
            password=password,
        )
        manager = user_repository.create(session=db, obj_in=user_in)

        project_a = create_test_project(db)
        project_b = create_test_project(db)
        collection = create_test_collection(db)
        db.add(ProjectCollection(project_id=project_a.project_id, collection_id=collection.collection_id))
        db.add(ProjectCollection(project_id=project_b.project_id, collection_id=collection.collection_id))

        write_perm = db.exec(
            select(Permission).where(
                (Permission.resource_type == "project") & (Permission.action == "write")
            )
        ).one()
        db.add(UserPermission(user_id=manager.user_id, project_id=project_b.project_id, permission_id=write_perm.permission_id))
        db.commit()

        headers = user_authentication_headers(client=client, username="testmanager6b", password=password)
        r = client.delete(
            f"{settings.API_V1_STR}/collections/{collection.collection_id}",
            headers=headers,
        )
        assert r.status_code == 200
        assert db.exec(select(Collection).where(Collection.collection_id == collection.collection_id)).first() is None

    def test_delete_collection_with_collection_write_only_fails(
        self, client: TestClient, db: Session
    ) -> None:
        """collection:write without project:write cannot delete."""
        email = "manager6c@example.com"
        password = "testpassword123"
        user_in = UserCreate(
            username="testmanager6c",
            name="Test Manager 6C",
            email=email,
            password=password,
        )
        manager = user_repository.create(session=db, obj_in=user_in)

        project = create_test_project(db)
        collection = create_test_collection(db, public_access=False)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))

        collection_write_perm = db.exec(
            select(Permission).where(
                (Permission.resource_type == "collection") & (Permission.action == "write")
            )
        ).one()
        db.add(
            UserPermission(
                user_id=manager.user_id,
                project_id=project.project_id,
                collection_id=collection.collection_id,
                permission_id=collection_write_perm.permission_id,
            )
        )
        db.commit()

        headers = user_authentication_headers(client=client, username="testmanager6c", password=password)
        r = client.delete(
            f"{settings.API_V1_STR}/collections/{collection.collection_id}",
            headers=headers,
        )
        assert r.status_code == 403
        assert db.exec(select(Collection).where(Collection.collection_id == collection.collection_id)).first() is not None
    
    def test_delete_collection_no_permission(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """Normal user without write permission cannot delete a private collection."""
        # Create a private collection the normal user doesn't own or have write access to
        collection = create_test_collection(
            db, creator_id=1, public_access=False, name="Private No Delete"
        )
        project = link_collection_to_project(db, collection)

        r = client.delete(
            f"{settings.API_V1_STR}/collections/{collection.collection_id}",
            headers=normal_user_token_headers,
        )
        assert r.status_code == 403

    def test_delete_collection_not_found(
        self, client: TestClient, superuser_token_headers: dict[str, str]
    ) -> None:
        """Returns 404 for non-existent collection."""
        r = client.delete(
            f"{settings.API_V1_STR}/collections/99999",
            headers=superuser_token_headers,
        )
        assert r.status_code == 404


class TestCollectionExport:
    """Tests for GET /collections/exports endpoint."""
    
    def test_export_collections_admin(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Admin can export collections for a specific project."""
        project = create_test_project(db)
        create_test_collection(db)
        
        r = client.get(
            f"{settings.API_V1_STR}/collections/exports",
            params={"project_id": project.project_id},
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")
        assert r.headers.get("content-disposition") == (
            'attachment; filename="collections.csv"; '
            "filename*=UTF-8''collections.csv"
        )
        header = read_csv_header(r.text)
        assert header == [
            "collection_id", "uuid", "name", "sphere", "project_url", "external_media_url",
            "doi", "creator_name", "creator_id", "creation_date", "public_access",
            "public_tags", "taxon_names",
        ]

    def test_export_collections_includes_taxon_names(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Export renders sorted taxon display names in one CSV column."""
        project = create_test_project(db)
        tagged = create_test_collection(db, name="Tagged Collection")
        untagged = create_test_collection(db, name="Untagged Collection")
        link_collection_to_project(db, tagged, project)
        link_collection_to_project(db, untagged, project)
        db.add_all(
            [
                CollectionTaxon(
                    collection_id=tagged.collection_id,
                    col_taxon_id="taxon-b",
                    cached_name="Zebra",
                ),
                CollectionTaxon(
                    collection_id=tagged.collection_id,
                    col_taxon_id="taxon-a",
                    cached_name="Antelope",
                ),
            ]
        )
        db.commit()

        response = client.get(
            f"{settings.API_V1_STR}/collections/exports",
            params={"project_id": project.project_id},
            headers=superuser_token_headers,
        )

        assert response.status_code == 200
        rows = list(csv.DictReader(response.text.splitlines()))
        taxons_by_name = {row["name"]: row["taxon_names"] for row in rows}
        assert taxons_by_name["Tagged Collection"] == "Antelope; Zebra"
        assert taxons_by_name["Untagged Collection"] == ""

    def test_export_collections_with_write_permission(
        self, client: TestClient, db: Session
    ) -> None:
        """User with project:write permission can export collections."""

        # 1. Create a user
        email = "manager@example.com"
        password = "testpassword123"
        user_in = UserCreate(
            username="testmanager",
            name="Test Manager",
            email=email,
            password=password,
        )
        manager = user_repository.create(session=db, obj_in=user_in)
        
        # 2. Create a project
        project = create_test_project(db)
        
        # 3. Grant project:write
        write_perm = db.exec(select(Permission).where(Permission.name == "project:write")).one()
        db.add(UserPermission(user_id=manager.user_id, project_id=project.project_id, permission_id=write_perm.permission_id))
        db.commit()

        # 4. Auth
        headers = user_authentication_headers(client=client, username="testmanager", password=password)

        # 5. Export
        r = client.get(
            f"{settings.API_V1_STR}/collections/exports",
            params={"project_id": project.project_id},
            headers=headers
        )
        assert r.status_code == 200

    def test_export_collections_no_project_id_fails(
        self, client: TestClient, superuser_token_headers: dict[str, str]
    ) -> None:
        """Missing project_id query param results in 400 (from PermissionChecker)."""
        r = client.get(
            f"{settings.API_V1_STR}/collections/exports",
            headers=superuser_token_headers
        )
        assert r.status_code == 400

    def test_export_collections_no_permission_fails(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """User without write permission on project gets 403."""
        project = create_test_project(db)
        
        r = client.get(
            f"{settings.API_V1_STR}/collections/exports",
            params={"project_id": project.project_id},
            headers=normal_user_token_headers
        )
        assert r.status_code == 403

    def test_export_collections_anonymous_forbidden(
        self, client: TestClient, db: Session
    ) -> None:
        """Anonymous user cannot export collections."""
        project = create_test_project(db)
        r = client.get(f"{settings.API_V1_STR}/collections/exports", params={"project_id": project.project_id})
        assert r.status_code == 401


class TestCollectionOptions:
    """Tests for GET /collection-options endpoint."""
    
    def test_get_options_as_admin(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Admin can get collection options."""
        create_test_collection(db, name="Option Collection A")
        create_test_collection(db, name="Option Collection B")
        
        r = client.get(
            f"{settings.API_V1_STR}/collection-options",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        json_resp = r.json()
        assert json_resp["code"] == 0
        options = json_resp["data"]
        
        assert isinstance(options, list)
        assert len(options) >= 2
        
        # Verify structure
        for opt in options:
            assert "collection_id" in opt
            assert "name" in opt
            assert "can_manage" in opt
            assert opt["can_manage"] is True
    
    def test_get_options_as_normal_user(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """Normal user can get collection options (public collections)."""
        create_test_collection(db, name="Public Option Collection", public_access=True)
        
        r = client.get(
            f"{settings.API_V1_STR}/collection-options",
            headers=normal_user_token_headers
        )
        assert r.status_code == 200
        json_resp = r.json()
        assert json_resp["code"] == 0
        options = json_resp["data"]
        assert isinstance(options, list)
        assert len(options) >= 1
        for opt in options:
            if opt["name"] == "Public Option Collection":
                assert opt["can_manage"] is False
    
    def test_get_options_with_write_permission(
        self, client: TestClient, db: Session
    ) -> None:
        """User with collection:write permission gets can_manage=True for that collection."""

        # 1. Create a user
        email = "option_writer@example.com"
        password = "testpassword123"
        user_in = UserCreate(
            username="optionwriter1",
            name="Option Writer",
            email=email,
            password=password,
        )
        writer = user_repository.create(session=db, obj_in=user_in)
        
        # 2. Create collections
        c_manageable = create_test_collection(db, name="Manageable Collection")
        c_read_only = create_test_collection(db, name="Read Only Collection", public_access=True)
        project = link_collection_to_project(db, c_manageable)
        db.add(ProjectCollection(project_id=project.project_id, collection_id=c_read_only.collection_id))
        db.commit()
        
        # 3. Grant collection:write for c_manageable
        write_perm = db.exec(select(Permission).where(
            (Permission.resource_type == "collection") & (Permission.action == "write")
        )).one()
        db.add(UserPermission(user_id=writer.user_id, project_id=project.project_id, collection_id=c_manageable.collection_id, permission_id=write_perm.permission_id))
        db.commit()

        # 4. Auth
        headers = user_authentication_headers(client=client, username="optionwriter1", password=password)

        # 5. Get
        r = client.get(
            f"{settings.API_V1_STR}/collection-options",
            headers=headers
        )
        assert r.status_code == 200
        options = r.json()["data"]
        
        manageable_opt = next((o for o in options if o["collection_id"] == c_manageable.collection_id), None)
        read_only_opt = next((o for o in options if o["collection_id"] == c_read_only.collection_id), None)
        
        assert manageable_opt is not None
        assert manageable_opt["can_manage"] is True
        
        assert read_only_opt is not None
        assert read_only_opt["can_manage"] is False
    
    def test_get_options_unauthenticated(
        self, client: TestClient
    ) -> None:
        """Unauthenticated user without project_id should get 400."""
        r = client.get(f"{settings.API_V1_STR}/collection-options")
        assert r.status_code == 400


class TestCollectionEnums:
    """Tests for collection enum endpoints."""
    
    def test_get_spheres(self, client: TestClient) -> None:
        """Get sphere options - no auth required."""
        r = client.get(f"{settings.API_V1_STR}/collection-sphere-options")
        assert r.status_code == 200
        json_resp = r.json()
        assert json_resp["code"] == 0
        spheres = json_resp["data"]
        
        assert isinstance(spheres, list)
        assert "hydrosphere" in spheres
        assert "biosphere" in spheres
        assert "atmosphere" in spheres
        assert len(spheres) == 7
    


class TestCollectionValidation:
    """Tests for collection field validation."""
    
    def test_create_with_valid_sphere(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Create collection with valid sphere value."""
        project = create_test_project(db)
        data = {
            "name": f"Test Collection {random_lower_string()[:10]}",
            "sphere": "biosphere",
            "public_access": True,
        }
        r = client.post(
            f"{settings.API_V1_STR}/collections/",
            params={"project_id": project.project_id},
            headers=superuser_token_headers,
            json=data
        )
        assert r.status_code == 201

    def test_create_with_invalid_sphere(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Create collection with invalid sphere value should fail."""
        project = create_test_project(db)
        data = {
            "name": "Test Collection",
            "sphere": "invalid_sphere",
            "public_access": True,
        }
        r = client.post(
            f"{settings.API_V1_STR}/collections",
            params={"project_id": project.project_id},
            headers=superuser_token_headers,
            json=data
        )
        assert r.status_code == 422
  # Validation error
    
class TestCollectionTaxons:
    """Tests for get and set collection taxons."""

    def test_get_collection_taxons(self, client: TestClient, db: Session, superuser_token_headers: dict[str, str]) -> None:
        superuser = user_repository.get_by_username(db, username=settings.FIRST_SUPERUSER)
        c1 = create_test_collection(db, public_access=True)
        link_collection_to_project(db, c1)
        db.add(CollectionTaxon(
            collection_id=c1.collection_id,
            col_taxon_id="111",
            cached_name="Tiger",
            asserted_by=superuser.user_id,
        ))
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/collections/{c1.collection_id}/taxons",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["cached_name"] == "Tiger"
        assert data[0]["col_taxon_id"] == "111"
        assert data[0]["asserted_by"] == superuser.user_id
        assert data[0]["asserted_by_name"] == superuser.name

    def test_get_collection_taxons_asserted_by_null(self, client: TestClient, db: Session, superuser_token_headers: dict[str, str]) -> None:
        """asserted_by_name is null when no asserter is set."""
        c1 = create_test_collection(db, public_access=True)
        link_collection_to_project(db, c1)
        db.add(CollectionTaxon(collection_id=c1.collection_id, col_taxon_id="222", cached_name="Wolf"))
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/collections/{c1.collection_id}/taxons",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["asserted_by"] is None
        assert data[0]["asserted_by_name"] is None

    def test_get_collection_taxons_with_read_permission(
        self, client: TestClient, db: Session
    ) -> None:
        """User with collection:read permission can get taxons."""

        # 1. Create a user
        email = "reader1@example.com"
        password = "testpassword123"
        user_in = UserCreate(
            username="testreader1",
            name="Test Reader 1",
            email=email,
            password=password,
        )
        reader = user_repository.create(session=db, obj_in=user_in)
        
        # 2. Create a collection and taxon
        collection = create_test_collection(db)
        project = link_collection_to_project(db, collection)
        db.add(CollectionTaxon(collection_id=collection.collection_id, col_taxon_id="111", cached_name="Lion"))
        
        # 3. Grant collection:read
        read_perm = db.exec(select(Permission).where(
            (Permission.resource_type == "collection") & (Permission.action == "read")
        )).one()
        db.add(UserPermission(user_id=reader.user_id, project_id=project.project_id, collection_id=collection.collection_id, permission_id=read_perm.permission_id))
        db.commit()

        # 4. Auth
        headers = user_authentication_headers(client=client, username="testreader1", password=password)

        # 5. Get
        r = client.get(
            f"{settings.API_V1_STR}/collections/{collection.collection_id}/taxons",
            headers=headers,
        )
        assert r.status_code == 200

    def test_get_collection_taxons_no_permission_fails(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """User without read permission cannot get taxons of private collection."""
        collection = create_test_collection(db, public_access=False)
        link_collection_to_project(db, collection)
        
        r = client.get(
            f"{settings.API_V1_STR}/collections/{collection.collection_id}/taxons",
            headers=normal_user_token_headers,
        )
        assert r.status_code == 403

    def test_get_collection_taxons_not_found(self, client: TestClient, superuser_token_headers: dict[str, str]) -> None:
        """Missing collections return 404 before permission evaluation."""
        r = client.get(
            f"{settings.API_V1_STR}/collections/999999/taxons",
            headers=superuser_token_headers,
        )
        assert r.status_code == 404

    def test_get_collection_taxons_any_project_path_permission(self, client: TestClient, db: Session) -> None:
        """A user can read taxons when any linked project path grants collection:read."""
        reader, headers = create_user_with_headers(db, client, name="Multi Project Reader")
        collection = create_test_collection(db, public_access=False)
        allowed_project = link_collection_to_project(db, collection, create_test_project(db, public=True))
        link_collection_to_project(db, collection, create_test_project(db, public=False))
        db.add(CollectionTaxon(collection_id=collection.collection_id, col_taxon_id="111", cached_name="Lion"))

        read_perm = db.exec(select(Permission).where(
            (Permission.resource_type == "collection") & (Permission.action == "read")
        )).one()
        db.add(UserPermission(
            user_id=reader.user_id,
            project_id=allowed_project.project_id,
            collection_id=collection.collection_id,
            permission_id=read_perm.permission_id,
        ))
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/collections/{collection.collection_id}/taxons",
            headers=headers,
        )
        assert r.status_code == 200
        assert r.json()["data"][0]["cached_name"] == "Lion"

    def test_get_collection_taxons_multiple_projects_without_permission_fails(
        self, client: TestClient, db: Session
    ) -> None:
        """A user without any linked project-path permission is denied."""
        collection = create_test_collection(db, public_access=False)
        link_collection_to_project(db, collection, create_test_project(db, public=False))
        link_collection_to_project(db, collection, create_test_project(db, public=False))

        _, headers = create_user_with_headers(db, client, name="No Multi Project Access")
        r = client.get(
            f"{settings.API_V1_STR}/collections/{collection.collection_id}/taxons",
            headers=headers,
        )
        assert r.status_code == 403

    def test_set_collection_taxons(self, client: TestClient, db: Session, superuser_token_headers: dict[str, str]) -> None:
        c1 = create_test_collection(db)
        link_collection_to_project(db, c1)
        
        payload = {
            "taxons": [
                {
                    "col_taxon_id": "tx1",
                    "cached_name": "Dog",
                    "col_rank": "species",
                    "notes": "Good boy"
                },
                {
                    "col_taxon_id": "tx2",
                    "cached_name": "Cat",
                    "col_rank": "species",
                    "notes": "Meow"
                }
            ]
        }

        r = client.put(
            f"{settings.API_V1_STR}/collections/{c1.collection_id}/taxons",
            headers=superuser_token_headers,
            json=payload
        )
        assert r.status_code == 200
        
        # Verify the new taxons were saved via a GET
        r2 = client.get(
            f"{settings.API_V1_STR}/collections/{c1.collection_id}/taxons",
            headers=superuser_token_headers,
        )
        assert r2.status_code == 200
        data = r2.json()["data"]
        assert len(data) == 2
        
        names = [t["cached_name"] for t in data]
        assert "Dog" in names
        assert "Cat" in names
        
        # Ensure older deletes work smoothly
        r3 = client.put(
            f"{settings.API_V1_STR}/collections/{c1.collection_id}/taxons",
            headers=superuser_token_headers,
            json={"taxons": []}
        )
        assert r3.status_code == 200
        r4 = client.get(
            f"{settings.API_V1_STR}/collections/{c1.collection_id}/taxons",
            headers=superuser_token_headers,
        )
        assert len(r4.json()["data"]) == 0

    def test_set_collection_taxons_with_write_permission(
        self, client: TestClient, db: Session
    ) -> None:
        """User with collection:write permission can set taxons."""

        # 1. Create a user
        email = "writer1@example.com"
        password = "testpassword123"
        user_in = UserCreate(
            username="testwriter1",
            name="Test Writer 1",
            email=email,
            password=password,
        )
        writer = user_repository.create(session=db, obj_in=user_in)
        
        # 2. Create a collection
        collection = create_test_collection(db)
        project = link_collection_to_project(db, collection)
        
        # 3. Grant collection:write
        write_perm = db.exec(select(Permission).where(
            (Permission.resource_type == "collection") & (Permission.action == "write")
        )).one()
        db.add(UserPermission(user_id=writer.user_id, project_id=project.project_id, collection_id=collection.collection_id, permission_id=write_perm.permission_id))
        db.commit()

        # 4. Auth
        headers = user_authentication_headers(client=client, username="testwriter1", password=password)

        # 5. Set
        payload = {"taxons": [{"col_taxon_id": "tx1", "cached_name": "Bird", "col_rank": "species"}]}
        r = client.put(
            f"{settings.API_V1_STR}/collections/{collection.collection_id}/taxons",
            headers=headers,
            json=payload
        )
        assert r.status_code == 200

    def test_set_collection_taxons_any_project_path_write_permission(
        self, client: TestClient, db: Session
    ) -> None:
        """A user can write taxons when any linked project path grants collection:write."""
        writer, headers = create_user_with_headers(db, client, name="Multi Project Writer")
        collection = create_test_collection(db, public_access=False)
        allowed_project = link_collection_to_project(db, collection, create_test_project(db, public=True))
        link_collection_to_project(db, collection, create_test_project(db, public=False))

        write_perm = db.exec(select(Permission).where(
            (Permission.resource_type == "collection") & (Permission.action == "write")
        )).one()
        db.add(UserPermission(
            user_id=writer.user_id,
            project_id=allowed_project.project_id,
            collection_id=collection.collection_id,
            permission_id=write_perm.permission_id,
        ))
        db.commit()

        payload = {"taxons": [{"col_taxon_id": "tx1", "cached_name": "Bird", "col_rank": "species"}]}
        r = client.put(
            f"{settings.API_V1_STR}/collections/{collection.collection_id}/taxons",
            headers=headers,
            json=payload
        )
        assert r.status_code == 200

    def test_set_collection_taxons_read_only_fails(
        self, client: TestClient, db: Session
    ) -> None:
        """User with only collection:read permission cannot set taxons."""

        # 1. Create a user
        email = "reader2@example.com"
        password = "testpassword123"
        user_in = UserCreate(
            username="testreader2",
            name="Test Reader 2",
            email=email,
            password=password,
        )
        reader = user_repository.create(session=db, obj_in=user_in)
        
        # 2. Create a collection
        collection = create_test_collection(db)
        project = link_collection_to_project(db, collection)
        
        # 3. Grant collection:read
        read_perm = db.exec(select(Permission).where(
            (Permission.resource_type == "collection") & (Permission.action == "read")
        )).one()
        db.add(UserPermission(user_id=reader.user_id, project_id=project.project_id, collection_id=collection.collection_id, permission_id=read_perm.permission_id))
        db.commit()

        # 4. Auth
        headers = user_authentication_headers(client=client, username="testreader2", password=password)

        # 5. Set (attempt)
        payload = {"taxons": [{"col_taxon_id": "tx1", "cached_name": "Bird", "col_rank": "species"}]}
        r = client.put(
            f"{settings.API_V1_STR}/collections/{collection.collection_id}/taxons",
            headers=headers,
            json=payload
        )
        assert r.status_code == 403


def test_collection_external_urls_are_validated_and_normalized(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    project = create_test_project(db)
    invalid = client.post(
        f"{settings.API_V1_STR}/collections",
        params={"project_id": project.project_id},
        headers=superuser_token_headers,
        json={
            "name": "Invalid External URL Collection",
            "project_url": "//example.com/project",
            "external_media_url": "data:text/plain,media",
        },
    )
    assert invalid.status_code == 422

    name = "Normalized External URL Collection"
    created = client.post(
        f"{settings.API_V1_STR}/collections",
        params={"project_id": project.project_id},
        headers=superuser_token_headers,
        json={
            "name": name,
            "project_url": "  http://192.168.1.10/project  ",
            "external_media_url": "  https://example.com/media  ",
        },
    )
    assert created.status_code == 201
    collection = db.exec(select(Collection).where(Collection.name == name)).one()
    assert collection.project_url == "http://192.168.1.10/project"
    assert collection.external_media_url == "https://example.com/media"

    cleared = client.patch(
        f"{settings.API_V1_STR}/collections/{collection.collection_id}",
        headers=superuser_token_headers,
        json={"project_url": " ", "external_media_url": "\t"},
    )
    assert cleared.status_code == 200
    db.refresh(collection)
    assert collection.project_url is None
    assert collection.external_media_url is None
