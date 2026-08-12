"""
Test cases for project API routes.
"""
import re
from io import BytesIO
from datetime import datetime, timedelta, timezone

import jwt as pyjwt
from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session, select
from sqlmodel import select as sql_select

from app.core.config import settings
from app.models import (
    Annotation,
    Collection,
    CollectionContributor,
    Permission,
    Project,
    ProjectCollection,
    ProjectContributor,
    Site,
    SiteCollection,
    SiteProject,
    User,
    UserPermission,
)
from app.models.media import AudioSetting, Media, MediaCollection, PhotoSetting
from app.services.file_service import file_service
from tests.utils.csv import read_csv_header
from tests.utils.user import create_random_user
from tests.utils.utils import random_lower_string


def create_test_project(db: Session, creator_id: int = 1, **kwargs) -> Project:
    """Helper function to create a test project."""
    defaults = {
        "name": f"Test Project {random_lower_string()[:10]}",
        "url": f"https://example.com/{random_lower_string()[:10]}",
        "description": "Test description",
        "description_short": "Test",
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


def image_upload(name: str, image_format: str, content_type: str) -> tuple[str, BytesIO, str]:
    buffer = BytesIO()
    Image.new("RGB", (2, 2), "green").save(buffer, image_format)
    buffer.seek(0)
    return name, buffer, content_type


class TestProjectList:
    """Tests for GET /projects endpoint."""
    
    def test_list_projects_authenticated(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Authenticated user can list public projects."""
        create_test_project(db)
        create_test_project(db)
        
        r = client.get(
            f"{settings.API_V1_STR}/projects/",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        json_resp = r.json()
        assert json_resp["code"] == 0
        data = json_resp # paginated response structure matches
        assert "data" in data
        assert "page_info" in data
        assert len(data["data"]) >= 2
    
    def test_list_projects_with_filters(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Test project filtering functionality."""
        create_test_project(db, name="Unique Search Project", url="https://example.com/unique", public=False)
        
        # Test filter by name
        r = client.get(
            f"{settings.API_V1_STR}/projects/?name=Unique",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        json_resp = r.json()
        assert json_resp["code"] == 0
        data = json_resp
        assert len(data["data"]) >= 1
        assert any(p["name"] == "Unique Search Project" for p in data["data"])

        # Test filter by url
        r = client.get(
            f"{settings.API_V1_STR}/projects/?url=example.com/unique",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data["data"]) >= 1
        assert any(p["url"] == "https://example.com/unique" for p in data["data"])
        
        # Test filter by public status
        r = client.get(
            f"{settings.API_V1_STR}/projects/?public=false",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        data = r.json()
        assert all(p["public"] is False for p in data["data"])
        assert any(p["name"] == "Unique Search Project" for p in data["data"])

        # Test combined filters (name + public)
        r = client.get(
            f"{settings.API_V1_STR}/projects/?name=Unique&public=false",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data["data"]) >= 1
        assert any(p["name"] == "Unique Search Project" for p in data["data"])

        # Test filter by project_id
        project = create_test_project(db, name="ID Search Project")
        r = client.get(
            f"{settings.API_V1_STR}/projects/?project_id={project.project_id}",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data["data"]) == 1
        assert data["data"][0]["project_id"] == project.project_id

        # Test filter by uuid
        r = client.get(
            f"{settings.API_V1_STR}/projects/?uuid={str(project.uuid)}",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data["data"]) == 1
        assert data["data"][0]["uuid"] == str(project.uuid)

        # Test filter by active status
        create_test_project(db, name="Inactive Project", active=False)
        r = client.get(
            f"{settings.API_V1_STR}/projects/?active=false",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        data = r.json()
        assert all(p["active"] is False for p in data["data"])

        # Test fuzzy filter by doi
        project_with_doi = create_test_project(db, name="DOI Project", doi="10.1000/xyz123")
        r = client.get(
            f"{settings.API_V1_STR}/projects/?doi=xyz",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        data = r.json()
        assert any(p["doi"] == "10.1000/xyz123" for p in data["data"])

        # Test filter by creator_id
        r = client.get(
            f"{settings.API_V1_STR}/projects/?creator_id={project_with_doi.creator_id}",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data["data"]) >= 1
        assert all(p["creator_id"] == project_with_doi.creator_id for p in data["data"])

    def test_list_projects_with_date_range(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Test project filtering by creation date range."""
        now = datetime.now(timezone.utc)
        past = now - timedelta(days=5)
        
        p_past = create_test_project(db, name="Past Project")
        p_past.creation_date = past
        db.add(p_past)
        db.commit()

        # Test filter from date (Correct Format)
        r = client.get(
            f"{settings.API_V1_STR}/projects/?creation_date_from={(now - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')}",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        data = r.json()
        # All projects should be recent ones (not the p_past)
        for p in data["data"]:
             p_date = datetime.fromisoformat(p["creation_date"].replace("Z", "+00:00"))
             assert p_date.timestamp() >= (now - timedelta(days=2)).timestamp()

        # Test filter to date (Correct Format)
        r = client.get(
            f"{settings.API_V1_STR}/projects/?creation_date_to={(now - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')}",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        data = r.json()
        # Should only contain p_past or older
        for p in data["data"]:
             p_date = datetime.fromisoformat(p["creation_date"].replace("Z", "+00:00"))
             assert p_date.timestamp() <= (now - timedelta(days=0)).timestamp()

    def test_list_projects_invalid_date_format(
        self, client: TestClient, superuser_token_headers: dict[str, str]
    ) -> None:
        """Test that ISO format (T separator) is accepted, and truly invalid strings are rejected."""
        # ISO format with T separator is now valid
        r = client.get(
            f"{settings.API_V1_STR}/projects/?creation_date_from=2024-03-05T14:30:00",
            headers=superuser_token_headers
        )
        assert r.status_code == 200

        # Truly invalid string should return 422
        r = client.get(
            f"{settings.API_V1_STR}/projects/?creation_date_from=not-a-date",
            headers=superuser_token_headers
        )
        assert r.status_code == 422
    
    def test_list_projects_with_order(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Test project ordering by different fields."""
        create_test_project(db, name="AAA Project")
        create_test_project(db, name="ZZZ Project")
        
        # Order by name ascending
        r = client.get(
            f"{settings.API_V1_STR}/projects/?order_by=name&order_dir=asc",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        json_resp = r.json()
        assert json_resp["code"] == 0
        data = json_resp
        names = [p["name"] for p in data["data"]]
        assert names == sorted(names)
        
        # Order by name descending
        r = client.get(
            f"{settings.API_V1_STR}/projects/?order_by=name&order_dir=desc",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        json_resp = r.json()
        assert json_resp["code"] == 0
        data = json_resp
        names = [p["name"] for p in data["data"]]
        
    def test_list_projects_invalid_uuid(
        self, client: TestClient, superuser_token_headers: dict[str, str]
    ) -> None:
        """Test that invalid UUID string is silently ignored (returns 200, no filter applied)."""
        r = client.get(
            f"{settings.API_V1_STR}/projects/?uuid=invalid-uuid-format-here",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        assert r.json()["code"] == 0

    def test_list_projects_normal_user_forbidden(
        self, client: TestClient, normal_user_token_headers: dict[str, str]
    ) -> None:
        """Normal user without manage permission is forbidden."""
        r = client.get(
            f"{settings.API_V1_STR}/projects",
            headers=normal_user_token_headers
        )
        assert r.status_code == 403


class TestProjectCards:
    """Tests for GET /project-directory-items endpoint."""

    def test_get_project_cards_anonymous_all_active_sorted(
        self, client: TestClient, db: Session
    ) -> None:
        """Anonymous users should get all active projects sorted by id asc."""
        private_active = create_test_project(db, name="Private Active Card", public=False, active=True)
        public_inactive = create_test_project(db, name="Public Inactive Card", public=True, active=False)
        public_active_b = create_test_project(
            db,
            name="Rainforest Beta",
            public=True,
            active=True,
            picture_id="beta.jpg",
            description="Beta description",
            description_short="Beta Team",
        )
        public_active_a = create_test_project(
            db,
            name="Amazon Rainfall",
            public=True,
            active=True,
            picture_id="amazon.jpg",
            description="Monitoring the acoustic diversity.",
            description_short="BioTeam Alpha",
        )

        r = client.get(f"{settings.API_V1_STR}/project-directory-items")
        assert r.status_code == 200
        payload = r.json()
        assert payload["code"] == 0
        data = payload["data"]

        returned_ids = [item["project_id"] for item in data]
        assert public_active_a.project_id in returned_ids
        assert public_active_b.project_id in returned_ids
        assert private_active.project_id in returned_ids
        assert public_inactive.project_id not in returned_ids
        assert returned_ids == sorted(returned_ids)

        private_card = next(item for item in data if item["project_id"] == private_active.project_id)
        assert private_card["can_access"] is False
        assert private_card["url"] == ""

    def test_get_project_cards_support_name_search_and_picture_fields(
        self, client: TestClient, db: Session
    ) -> None:
        """Cards endpoint supports name search and returns prototype-related fields."""
        target = create_test_project(
            db,
            name="Amazon Rainfall Search",
            public=True,
            active=True,
            doi="10.1000/rainfall-search",
            picture_id="rainfall.jpg",
            description="Long description text.",
            description_short="BioTeam Alpha",
        )
        create_test_project(
            db,
            name="Ocean Winds Search",
            public=True,
            active=True,
        )

        r = client.get(f"{settings.API_V1_STR}/project-directory-items?name=Amazon")
        assert r.status_code == 200
        payload = r.json()
        assert payload["code"] == 0
        data = payload["data"]
        assert len(data) >= 1
        matched = [item for item in data if item["project_id"] == target.project_id]
        assert len(matched) == 1
        card = matched[0]

        assert card["name"] == "Amazon Rainfall Search"
        assert card["description_short"] == "BioTeam Alpha"
        assert card["doi"] == "10.1000/rainfall-search"
        assert card["image_url"] == "/sounds/projects/rainfall.jpg"
        assert card["can_access"] is True
        assert "creator" in card
        assert "contributors" in card
        assert isinstance(card["contributors"], list)
        assert "picture_id" not in card
        assert card["public"] is True
        assert "active" not in card
        assert "status" not in card

    def test_get_project_cards_normal_user_private_without_access_has_empty_url(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """Normal users see all active projects; inaccessible private projects have empty url."""
        private_active = create_test_project(db, name="Normal User Private Active", public=False, active=True)
        public_active = create_test_project(db, name="Normal User Public Active", public=True, active=True)

        r = client.get(
            f"{settings.API_V1_STR}/project-directory-items",
            headers=normal_user_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]

        private_card = next(item for item in data if item["project_id"] == private_active.project_id)
        public_card = next(item for item in data if item["project_id"] == public_active.project_id)

        assert private_card["can_access"] is False
        assert private_card["url"] == ""
        assert public_card["can_access"] is True
        assert public_card["url"] != ""

    def test_get_project_cards_admin_all_active_can_access_true(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Admin should see all active projects and can_access should be true."""
        private_active = create_test_project(db, name="Admin Private Active", public=False, active=True)
        public_active = create_test_project(db, name="Admin Public Active", public=True, active=True)
        inactive_project = create_test_project(db, name="Admin Inactive", public=True, active=False)

        r = client.get(
            f"{settings.API_V1_STR}/project-directory-items",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        returned_ids = [item["project_id"] for item in data]
        assert private_active.project_id in returned_ids
        assert public_active.project_id in returned_ids
        assert inactive_project.project_id not in returned_ids
        assert all(item["can_access"] is True for item in data)


class TestProjectGet:
    """Tests for GET /projects/{id} endpoint."""
    
    def test_get_project_public(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Can get public project by ID."""
        project = create_test_project(db, public=True)
        
        r = client.get(
            f"{settings.API_V1_STR}/projects/{project.project_id}",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        json_resp = r.json()
        assert json_resp["code"] == 0
        data = json_resp["data"]
        assert data["project_id"] == project.project_id
        assert data["name"] == project.name

    def test_get_project_returns_detail_fields(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Detail endpoint must return flattened creator name."""
        project = create_test_project(db, public=True)

        r = client.get(
            f"{settings.API_V1_STR}/projects/{project.project_id}",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        data = r.json()["data"]

        # New detail fields must be present
        assert "creator_name" in data
        assert isinstance(data["creator_name"], str)
        assert data["creator_name"] != ""

        # Optional field picture_url should be empty string since picture_id is None
        assert "picture_url" in data
        assert data["picture_url"] == ""

        # creation_date must match YYYY-MM-DD HH:MM:SS format
        assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", data["creation_date"]), (
            f"creation_date format invalid: {data['creation_date']}"
        )
        
    def test_get_project_with_picture_url(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Project with picture_id should return correct picture_url."""
        project = create_test_project(db, public=True, picture_id="test_pic.jpg")

        r = client.get(
            f"{settings.API_V1_STR}/projects/{project.project_id}",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        data = r.json()["data"]
        
        # Project cover URLs are rooted at the current site.
        assert "picture_url" in data
        assert data["picture_url"] == "/sounds/projects/test_pic.jpg"
    
    def test_get_project_not_found(
        self, client: TestClient, superuser_token_headers: dict[str, str]
    ) -> None:
        """Returns HTTP 404 for non-existent project."""
        r = client.get(
            f"{settings.API_V1_STR}/projects/99999",
            headers=superuser_token_headers
        )
        assert r.status_code == 404




class TestProjectCollectionLinkOptions:
    """Tests for project collection link options and sync endpoints."""

    @staticmethod
    def _normal_user_id(headers: dict[str, str]) -> int:
        token = headers["Authorization"].split(" ")[1]
        payload = pyjwt.decode(token, options={"verify_signature": False})
        return int(payload["sub"])

    @staticmethod
    def _grant_permission(
        db: Session,
        *,
        user_id: int,
        permission_name: str,
        project_id: int,
        collection_id: int | None = None,
    ) -> None:
        permission = db.exec(select(Permission).where(Permission.name == permission_name)).one()
        db.add(
            UserPermission(
                user_id=user_id,
                project_id=project_id,
                collection_id=collection_id,
                permission_id=permission.permission_id,
            )
        )

    def test_get_link_options_grouping_and_duplicates(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Should return current/other/unassigned groups and duplicate_project_ids."""
        current_project = create_test_project(db, name="Current Project")
        other_a = create_test_project(db, name="Other Project A")
        other_b = create_test_project(db, name="Other Project B")

        current_only = Collection(name="Current Only", creator_id=1)
        shared_in_current = Collection(name="Shared In Current", creator_id=1)
        duplicated_other = Collection(name="Duplicated Other", creator_id=1)
        unassigned = Collection(name="Unassigned Collection", creator_id=1)

        db.add_all([current_only, shared_in_current, duplicated_other, unassigned])
        db.commit()
        db.refresh(current_only)
        db.refresh(shared_in_current)
        db.refresh(duplicated_other)
        db.refresh(unassigned)

        db.add_all(
            [
                ProjectCollection(
                    project_id=current_project.project_id,
                    collection_id=current_only.collection_id,
                ),
                ProjectCollection(
                    project_id=current_project.project_id,
                    collection_id=shared_in_current.collection_id,
                ),
                ProjectCollection(
                    project_id=other_a.project_id,
                    collection_id=shared_in_current.collection_id,
                ),
                ProjectCollection(
                    project_id=other_a.project_id,
                    collection_id=duplicated_other.collection_id,
                ),
                ProjectCollection(
                    project_id=other_b.project_id,
                    collection_id=duplicated_other.collection_id,
                ),
            ]
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/projects/{current_project.project_id}/collection-options",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload["code"] == 0
        data = payload["data"]

        current_block = data["current_project"]
        assert current_block["project_id"] == current_project.project_id
        assert current_block["project_name"] == "Current Project"
        current_ids = {c["collection_id"] for c in current_block["collections"]}
        assert current_only.collection_id in current_ids
        assert shared_in_current.collection_id in current_ids
        assert all(c["selected"] is True for c in current_block["collections"])

        # shared_in_current is in current project, should be excluded from other projects
        other_projects = data["other_projects"]
        other_collection_ids = {
            c["collection_id"] for p in other_projects for c in p["collections"]
        }
        assert shared_in_current.collection_id not in other_collection_ids
        assert duplicated_other.collection_id in other_collection_ids

        duplicate_items = [
            c
            for p in other_projects
            for c in p["collections"]
            if c["collection_id"] == duplicated_other.collection_id
        ]
        assert len(duplicate_items) == 2
        expected_dup_project_ids = sorted([other_a.project_id, other_b.project_id])
        for item in duplicate_items:
            assert item["selected"] is False
            assert item["duplicate_project_ids"] == expected_dup_project_ids

        unassigned_ids = {
            c["collection_id"] for c in data["unassigned_collections"]
        }
        assert unassigned.collection_id in unassigned_ids

    def test_get_link_options_orders_projects_and_collections_by_name(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Project groups and collection options should be ordered by name."""
        current_project = create_test_project(db, name="Sorting Current Project")
        other_zulu = create_test_project(db, name="Sorting Zulu Project")
        other_alpha = create_test_project(db, name="Sorting Alpha Project")

        current_zulu = Collection(name="Sorting Current Zulu", creator_id=1)
        current_alpha = Collection(name="Sorting Current Alpha", creator_id=1)
        other_zulu_collection = Collection(name="Sorting Other Zulu", creator_id=1)
        other_alpha_collection = Collection(name="Sorting Other Alpha", creator_id=1)
        unassigned_zulu = Collection(name="Sorting Unassigned Zulu", creator_id=1)
        unassigned_alpha = Collection(name="Sorting Unassigned Alpha", creator_id=1)
        db.add_all(
            [
                current_zulu,
                current_alpha,
                other_zulu_collection,
                other_alpha_collection,
                unassigned_zulu,
                unassigned_alpha,
            ]
        )
        db.commit()
        for collection in (
            current_zulu,
            current_alpha,
            other_zulu_collection,
            other_alpha_collection,
        ):
            db.refresh(collection)

        db.add_all(
            [
                ProjectCollection(
                    project_id=current_project.project_id,
                    collection_id=current_zulu.collection_id,
                ),
                ProjectCollection(
                    project_id=current_project.project_id,
                    collection_id=current_alpha.collection_id,
                ),
                ProjectCollection(
                    project_id=other_zulu.project_id,
                    collection_id=other_zulu_collection.collection_id,
                ),
                ProjectCollection(
                    project_id=other_zulu.project_id,
                    collection_id=other_alpha_collection.collection_id,
                ),
                ProjectCollection(
                    project_id=other_alpha.project_id,
                    collection_id=other_zulu_collection.collection_id,
                ),
                ProjectCollection(
                    project_id=other_alpha.project_id,
                    collection_id=other_alpha_collection.collection_id,
                ),
            ]
        )
        db.commit()

        response = client.get(
            f"{settings.API_V1_STR}/projects/{current_project.project_id}/collection-options",
            headers=superuser_token_headers,
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert [
            item["name"] for item in data["current_project"]["collections"]
        ] == ["Sorting Current Alpha", "Sorting Current Zulu"]

        sorting_projects = [
            project
            for project in data["other_projects"]
            if project["project_name"].startswith("Sorting ")
        ]
        assert [project["project_name"] for project in sorting_projects] == [
            "Sorting Alpha Project",
            "Sorting Zulu Project",
        ]
        for project in sorting_projects:
            assert [item["name"] for item in project["collections"]] == [
                "Sorting Other Alpha",
                "Sorting Other Zulu",
            ]

        sorting_unassigned = [
            item["name"]
            for item in data["unassigned_collections"]
            if item["name"].startswith("Sorting Unassigned ")
        ]
        assert sorting_unassigned == [
            "Sorting Unassigned Alpha",
            "Sorting Unassigned Zulu",
        ]

    def test_get_link_options_forbidden_without_project_write(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """User without project:write should get 403."""
        project = create_test_project(db, name="No Write Project")
        r = client.get(
            f"{settings.API_V1_STR}/projects/{project.project_id}/collection-options",
            headers=normal_user_token_headers,
        )
        assert r.status_code == 403

    def test_get_link_options_project_write_sees_project_collections(
        self,
        client: TestClient,
        normal_user_token_headers: dict[str, str],
        db: Session,
    ) -> None:
        """Project managers see every collection in the managed project."""
        user_id = self._normal_user_id(normal_user_token_headers)
        project = create_test_project(db, name="Managed Target Project")
        c1 = Collection(name="Managed Target C1", creator_id=1)
        c2 = Collection(name="Managed Target C2", creator_id=1)
        db.add_all([c1, c2])
        db.commit()
        db.refresh(c1)
        db.refresh(c2)
        db.add_all(
            [
                ProjectCollection(
                    project_id=project.project_id,
                    collection_id=c1.collection_id,
                ),
                ProjectCollection(
                    project_id=project.project_id,
                    collection_id=c2.collection_id,
                ),
            ]
        )
        self._grant_permission(
            db,
            user_id=user_id,
            permission_name="project:write",
            project_id=project.project_id,
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/projects/{project.project_id}/collection-options",
            headers=normal_user_token_headers,
        )
        assert r.status_code == 200
        current_ids = {
            c["collection_id"]
            for c in r.json()["data"]["current_project"]["collections"]
        }
        assert {c1.collection_id, c2.collection_id}.issubset(current_ids)

    def test_get_link_options_collection_write_does_not_expand_to_project(
        self,
        client: TestClient,
        normal_user_token_headers: dict[str, str],
        db: Session,
    ) -> None:
        """Collection managers only see the writable collection in other projects."""
        user_id = self._normal_user_id(normal_user_token_headers)
        target_project = create_test_project(db, name="Collection Scope Target")
        other_project = create_test_project(db, name="Collection Scope Other")
        target_collection = Collection(name="Collection Scope Target C", creator_id=1)
        manageable = Collection(name="Only Writable Collection", creator_id=1)
        hidden = Collection(name="Hidden Sibling Collection", creator_id=1)
        db.add_all([target_collection, manageable, hidden])
        db.commit()
        db.refresh(target_collection)
        db.refresh(manageable)
        db.refresh(hidden)
        db.add_all(
            [
                ProjectCollection(
                    project_id=target_project.project_id,
                    collection_id=target_collection.collection_id,
                ),
                ProjectCollection(
                    project_id=other_project.project_id,
                    collection_id=manageable.collection_id,
                ),
                ProjectCollection(
                    project_id=other_project.project_id,
                    collection_id=hidden.collection_id,
                ),
            ]
        )
        self._grant_permission(
            db,
            user_id=user_id,
            permission_name="project:write",
            project_id=target_project.project_id,
        )
        self._grant_permission(
            db,
            user_id=user_id,
            permission_name="collection:write",
            project_id=other_project.project_id,
            collection_id=manageable.collection_id,
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/projects/{target_project.project_id}/collection-options",
            headers=normal_user_token_headers,
        )
        assert r.status_code == 200
        other_projects = r.json()["data"]["other_projects"]
        other_ids = {
            c["collection_id"] for p in other_projects for c in p["collections"]
        }
        assert manageable.collection_id in other_ids
        assert hidden.collection_id not in other_ids

    def test_get_link_options_read_permissions_are_not_candidates(
        self,
        client: TestClient,
        normal_user_token_headers: dict[str, str],
        db: Session,
    ) -> None:
        """Read-only project or collection permissions do not expose link options."""
        user_id = self._normal_user_id(normal_user_token_headers)
        target_project = create_test_project(db, name="Read Scope Target")
        other_project = create_test_project(db, name="Read Scope Other")
        target_collection = Collection(name="Read Scope Target C", creator_id=1)
        read_only_collection = Collection(name="Read Only Candidate", creator_id=1)
        db.add_all([target_collection, read_only_collection])
        db.commit()
        db.refresh(target_collection)
        db.refresh(read_only_collection)
        db.add_all(
            [
                ProjectCollection(
                    project_id=target_project.project_id,
                    collection_id=target_collection.collection_id,
                ),
                ProjectCollection(
                    project_id=other_project.project_id,
                    collection_id=read_only_collection.collection_id,
                ),
            ]
        )
        self._grant_permission(
            db,
            user_id=user_id,
            permission_name="project:write",
            project_id=target_project.project_id,
        )
        self._grant_permission(
            db,
            user_id=user_id,
            permission_name="project:read",
            project_id=other_project.project_id,
        )
        self._grant_permission(
            db,
            user_id=user_id,
            permission_name="collection:read",
            project_id=other_project.project_id,
            collection_id=read_only_collection.collection_id,
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/projects/{target_project.project_id}/collection-options",
            headers=normal_user_token_headers,
        )
        assert r.status_code == 200
        other_ids = {
            c["collection_id"]
            for p in r.json()["data"]["other_projects"]
            for c in p["collections"]
        }
        assert read_only_collection.collection_id not in other_ids

    def test_sync_project_collections_full_replace(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Sync endpoint should add new links and remove unchecked links."""
        project = create_test_project(db, name="Sync Target Project")
        c1 = Collection(name="Sync C1", creator_id=1)
        c2 = Collection(name="Sync C2", creator_id=1)
        c3 = Collection(name="Sync C3", creator_id=1)
        db.add_all([c1, c2, c3])
        db.commit()
        db.refresh(c1)
        db.refresh(c2)
        db.refresh(c3)

        db.add_all(
            [
                ProjectCollection(project_id=project.project_id, collection_id=c1.collection_id),
                ProjectCollection(project_id=project.project_id, collection_id=c2.collection_id),
            ]
        )
        db.commit()

        r = client.put(
            f"{settings.API_V1_STR}/projects/{project.project_id}/collections",
            headers=superuser_token_headers,
            json={"collection_ids": [c2.collection_id, c3.collection_id]},
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload["code"] == 0
        assert payload["data"] is None

        rows = db.exec(
            select(ProjectCollection.collection_id).where(
                ProjectCollection.project_id == project.project_id
            )
        ).all()
        assert sorted(rows) == sorted([c2.collection_id, c3.collection_id])

    def test_sync_project_collections_inherits_site_for_project_linked_sites(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Adding a collection to a project propagates site links for project-linked sites."""
        project = create_test_project(db, name="Sync Inherit Site Project")
        c1 = Collection(name="Inherit C1", creator_id=1)
        c2 = Collection(name="Inherit C2", creator_id=1)
        db.add_all([c1, c2])
        db.commit()
        db.refresh(c1)
        db.refresh(c2)

        db.add(ProjectCollection(project_id=project.project_id, collection_id=c1.collection_id))
        db.commit()

        site = Site(
            name=f"Inherit Site {random_lower_string()[:8]}",
            creator_id=1,
            gadm0="DefaultLand",
        )
        db.add(site)
        db.commit()
        db.refresh(site)
        db.add(SiteProject(site_id=site.site_id, project_id=project.project_id))
        db.add(SiteCollection(site_id=site.site_id, collection_id=c1.collection_id))
        db.commit()

        r = client.put(
            f"{settings.API_V1_STR}/projects/{project.project_id}/collections",
            headers=superuser_token_headers,
            json={"collection_ids": [c1.collection_id, c2.collection_id]},
        )
        assert r.status_code == 200

        inherited_rows = db.exec(
            select(SiteCollection).where(
                SiteCollection.site_id == site.site_id,
                SiteCollection.collection_id == c2.collection_id,
            )
        ).all()
        assert len(inherited_rows) == 1

    def test_sync_project_collections_rejects_public_collection_for_private_project(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Private projects cannot link public collections."""
        project = create_test_project(db, name="Sync Private Project", public=False)
        public_collection = Collection(
            name="Sync Public Collection",
            creator_id=1,
            public_access=True,
        )
        db.add(public_collection)
        db.commit()
        db.refresh(public_collection)

        r = client.put(
            f"{settings.API_V1_STR}/projects/{project.project_id}/collections",
            headers=superuser_token_headers,
            json={"collection_ids": [public_collection.collection_id]},
        )
        assert r.status_code == 400
        assert (
            r.json()["message"]
            == f"Cannot add public collection(s) to a private project: [{public_collection.collection_id}]"
        )

        rows = db.exec(
            select(ProjectCollection.collection_id).where(
                ProjectCollection.project_id == project.project_id
            )
        ).all()
        assert rows == []

    def test_sync_project_collections_allows_private_collection_for_private_project(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Private projects can link private collections."""
        project = create_test_project(db, name="Sync Private Allowed Project", public=False)
        private_collection = Collection(name="Sync Private Collection", creator_id=1)
        db.add(private_collection)
        db.commit()
        db.refresh(private_collection)

        r = client.put(
            f"{settings.API_V1_STR}/projects/{project.project_id}/collections",
            headers=superuser_token_headers,
            json={"collection_ids": [private_collection.collection_id]},
        )
        assert r.status_code == 200

        rows = db.exec(
            select(ProjectCollection.collection_id).where(
                ProjectCollection.project_id == project.project_id
            )
        ).all()
        assert rows == [private_collection.collection_id]

    def test_sync_project_collections_allows_public_collection_for_public_project(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Public projects can link public collections."""
        project = create_test_project(db, name="Sync Public Allowed Project", public=True)
        public_collection = Collection(
            name="Sync Public Collection Allowed",
            creator_id=1,
            public_access=True,
        )
        db.add(public_collection)
        db.commit()
        db.refresh(public_collection)

        r = client.put(
            f"{settings.API_V1_STR}/projects/{project.project_id}/collections",
            headers=superuser_token_headers,
            json={"collection_ids": [public_collection.collection_id]},
        )
        assert r.status_code == 200

        rows = db.exec(
            select(ProjectCollection.collection_id).where(
                ProjectCollection.project_id == project.project_id
            )
        ).all()
        assert rows == [public_collection.collection_id]

    def test_sync_project_collections_forbidden_without_project_write(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """User without project:write should not sync project collections."""
        project = create_test_project(db, name="Sync Forbidden Project")
        r = client.put(
            f"{settings.API_V1_STR}/projects/{project.project_id}/collections",
            headers=normal_user_token_headers,
            json={"collection_ids": []},
        )
        assert r.status_code == 403

class TestProjectCreate:
    """Tests for POST /projects endpoint."""
    
    def test_create_project_admin(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Admin can create a project."""
        data = {
            "name": f"New Project {random_lower_string()[:10]}",
            "url": "https://example.com/new",
            "description": "New project description",
            "public": True,
        }
        r = client.post(
            f"{settings.API_V1_STR}/projects/",
            headers=superuser_token_headers,
            json=data
        )
        assert r.status_code == 201
        json_resp = r.json()
        assert json_resp["code"] == 0
        assert isinstance(json_resp["data"]["project_id"], int)
        proj = db.exec(select(Project).where(Project.name == data["name"])).first()
        assert proj is not None
        assert json_resp["data"]["project_id"] == proj.project_id
        assert proj.url == data["url"]

    def test_create_project_ignores_picture_id_payload(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        data = {
            "name": f"No Direct Picture {random_lower_string()[:10]}",
            "url": "https://example.com/no-direct-picture",
            "picture_id": "unmanaged.png",
        }

        r = client.post(f"{settings.API_V1_STR}/projects/", headers=superuser_token_headers, json=data)

        assert r.status_code == 201
        project = db.get(Project, r.json()["data"]["project_id"])
        assert project is not None
        assert project.picture_id is None


class TestProjectPictureUpload:
    def test_upload_project_picture_uses_uuid_filename_and_replaces_old_picture(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session, tmp_path, monkeypatch
    ) -> None:
        project = create_test_project(db, picture_id="legacy-random.png")
        project_dir = tmp_path / "projects"
        project_dir.mkdir()
        old_path = project_dir / "legacy-random.png"
        old_path.write_bytes(b"old-picture")
        monkeypatch.setattr(file_service, "base_dir", tmp_path)

        r = client.put(
            f"{settings.API_V1_STR}/projects/{project.project_id}/picture",
            headers=superuser_token_headers,
            files={"file": image_upload("cover.png", "PNG", "image/png")},
        )

        assert r.status_code == 200
        data = r.json()["data"]
        expected_name = f"{project.uuid.hex}.png"
        assert data == {"picture_id": expected_name, "path": f"projects/{expected_name}"}
        assert (project_dir / expected_name).is_file()
        assert not old_path.exists()
        db.refresh(project)
        assert project.picture_id == expected_name

    def test_upload_project_picture_rejects_invalid_content_without_changing_existing_picture(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session, tmp_path, monkeypatch
    ) -> None:
        project = create_test_project(db, picture_id="existing.png")
        project_dir = tmp_path / "projects"
        project_dir.mkdir()
        old_path = project_dir / "existing.png"
        old_path.write_bytes(b"existing-picture")
        monkeypatch.setattr(file_service, "base_dir", tmp_path)

        response = client.put(
            f"{settings.API_V1_STR}/projects/{project.project_id}/picture",
            headers=superuser_token_headers,
            files={"file": ("invalid.png", BytesIO(b"not-an-image"), "image/png")},
        )

        assert response.status_code == 400
        assert old_path.read_bytes() == b"existing-picture"
        assert project.picture_id == "existing.png"

    def test_upload_project_picture_replaces_same_and_cross_extension_files(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session, tmp_path, monkeypatch
    ) -> None:
        project = create_test_project(db)
        monkeypatch.setattr(file_service, "base_dir", tmp_path)
        project_dir = tmp_path / "projects"

        first = client.put(
            f"{settings.API_V1_STR}/projects/{project.project_id}/picture",
            headers=superuser_token_headers,
            files={"file": image_upload("first.png", "PNG", "image/png")},
        )
        assert first.status_code == 200
        png_name = f"{project.uuid.hex}.png"
        png_path = project_dir / png_name
        second = client.put(
            f"{settings.API_V1_STR}/projects/{project.project_id}/picture",
            headers=superuser_token_headers,
            files={"file": image_upload("second.png", "PNG", "image/png")},
        )
        assert second.status_code == 200
        assert png_path.is_file()
        assert not (project_dir / f".{png_name}.new").exists()
        assert not (project_dir / f".{png_name}.backup").exists()

        third = client.put(
            f"{settings.API_V1_STR}/projects/{project.project_id}/picture",
            headers=superuser_token_headers,
            files={"file": image_upload("cover.jpg", "JPEG", "image/jpeg")},
        )
        assert third.status_code == 200
        jpg_name = f"{project.uuid.hex}.jpg"
        assert not png_path.exists()
        assert (project_dir / jpg_name).is_file()
        db.refresh(project)
        assert project.picture_id == jpg_name

    def test_create_project_empty_doi_persists_null(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Blank DOI input should not persist as an empty string."""
        data = {
            "name": f"Blank DOI Project {random_lower_string()[:10]}",
            "url": "https://example.com/blank-doi",
            "doi": "   ",
        }

        r = client.post(
            f"{settings.API_V1_STR}/projects/",
            headers=superuser_token_headers,
            json=data,
        )

        assert r.status_code == 201
        proj = db.exec(select(Project).where(Project.name == data["name"])).first()
        assert proj is not None
        assert proj.doi is None

    def test_create_project_normal_user_forbidden(
        self, client: TestClient, normal_user_token_headers: dict[str, str]
    ) -> None:
        """Normal user cannot create a project."""
        data = {
            "name": "Test Project",
            "url": "https://example.com",
        }
        r = client.post(
            f"{settings.API_V1_STR}/projects/",
            headers=normal_user_token_headers,
            json=data
        )
        assert r.status_code == 403

    def test_create_project_duplicate_name_case_and_trim_returns_409(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Create should reject names that are equal after trim+lower normalization."""
        create_test_project(db, name="Bird Sound Project")

        r = client.post(
            f"{settings.API_V1_STR}/projects/",
            headers=superuser_token_headers,
            json={
                "name": "  bird sound project  ",
                "url": "https://example.com/duplicate-name",
            },
        )
        assert r.status_code == 409
        assert r.json()["message"] == "Project with same name already exists"


class TestProjectUpdate:
    """Tests for PATCH /projects/{id} endpoint."""
    
    def test_update_project_admin(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Admin can update any project."""
        project = create_test_project(db)
        data = {"name": "Updated Name"}
        
        r = client.patch(
            f"{settings.API_V1_STR}/projects/{project.project_id}",
            headers=superuser_token_headers,
            json=data
        )
        assert r.status_code == 200
        json_resp = r.json()
        assert json_resp["code"] == 0
        assert json_resp["data"] is None
        db.refresh(project)
        assert project.name == "Updated Name"

    def test_update_project_empty_doi_persists_null(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Clearing DOI should store NULL rather than an empty string."""
        project = create_test_project(db, doi="10.1000/original")

        r = client.patch(
            f"{settings.API_V1_STR}/projects/{project.project_id}",
            headers=superuser_token_headers,
            json={"doi": ""},
        )

        assert r.status_code == 200
        db.refresh(project)
        assert project.doi is None

    def test_update_project_not_found(
        self, client: TestClient, superuser_token_headers: dict[str, str]
    ) -> None:
        """Returns HTTP 404 for non-existent project."""
        r = client.patch(
            f"{settings.API_V1_STR}/projects/99999",
            headers=superuser_token_headers,
            json={"name": "Updated"}
        )
        assert r.status_code == 404

    def test_update_project_duplicate_name_case_and_trim_returns_409(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Update should reject names occupied by another project after normalization."""
        target = create_test_project(db, name="Target Project")
        create_test_project(db, name="Bird Name")

        r = client.patch(
            f"{settings.API_V1_STR}/projects/{target.project_id}",
            headers=superuser_token_headers,
            json={"name": "  BIRD NAME  "},
        )
        assert r.status_code == 409
        assert r.json()["message"] == "Project with same name already exists"

    def test_update_project_same_project_name_variant_is_allowed(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Updating own name with case/trim variant should pass (self-excluded duplicate check)."""
        project = create_test_project(db, name="Bird")

        r = client.patch(
            f"{settings.API_V1_STR}/projects/{project.project_id}",
            headers=superuser_token_headers,
            json={"name": "  bIrD  "},
        )
        assert r.status_code == 200
        db.refresh(project)
        assert project.name == "  bIrD  "


class TestProjectDelete:
    """Tests for DELETE /projects/{id} endpoint."""
    
    def test_delete_project_admin(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Admin can delete a project."""
        project = create_test_project(db)
        project_id = project.project_id
        
        r = client.delete(
            f"{settings.API_V1_STR}/projects/{project_id}",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        
        # Verify project is deleted
        deleted = db.exec(select(Project).where(Project.project_id == project_id)).first()
        assert deleted is None

    def test_delete_project_admin_with_site_project_links(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Delete clears site_project links and removes the project."""
        project = create_test_project(db)
        collection = Collection(name=f"Project Delete Collection {random_lower_string()[:8]}", creator_id=1)
        db.add(collection)
        db.commit()
        db.refresh(collection)

        site = Site(
            name=f"Project Delete Site {random_lower_string()[:8]}",
            creator_id=1,
            gadm0="DefaultLand",
        )
        db.add(site)
        db.commit()
        db.refresh(site)

        db.add(SiteCollection(site_id=site.site_id, collection_id=collection.collection_id))
        db.add(SiteProject(site_id=site.site_id, project_id=project.project_id))
        db.commit()

        r = client.delete(
            f"{settings.API_V1_STR}/projects/{project.project_id}",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        assert db.exec(select(Project).where(Project.project_id == project.project_id)).first() is None
        assert db.exec(
            select(SiteProject).where(SiteProject.project_id == project.project_id)
        ).all() == []
        assert db.get(Site, site.site_id) is not None
        assert db.get(Collection, collection.collection_id) is not None

    def test_delete_project_admin_with_collection_links_and_permissions(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Delete clears project links/permissions and removes the project."""
        project = create_test_project(db)
        collection = Collection(
            name=f"Project Delete Linked Collection {random_lower_string()[:8]}",
            creator_id=1,
        )
        db.add(collection)
        db.commit()
        db.refresh(collection)

        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))

        permission = db.exec(select(Permission).where(Permission.name == "collection:write")).first()
        assert permission is not None
        db.add(
            UserPermission(
                user_id=1,
                project_id=project.project_id,
                collection_id=collection.collection_id,
                permission_id=permission.permission_id,
            )
        )
        db.commit()

        r = client.delete(
            f"{settings.API_V1_STR}/projects/{project.project_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        assert db.exec(select(Project).where(Project.project_id == project.project_id)).first() is None
        assert db.exec(
            select(ProjectCollection).where(ProjectCollection.project_id == project.project_id)
        ).all() == []
        assert db.exec(
            select(UserPermission).where(UserPermission.project_id == project.project_id)
        ).all() == []
        assert db.get(Collection, collection.collection_id) is not None

    def test_delete_project_normal_user_forbidden(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """Normal user cannot delete a project."""
        project = create_test_project(db)
        
        r = client.delete(
            f"{settings.API_V1_STR}/projects/{project.project_id}",
            headers=normal_user_token_headers
        )
        assert r.status_code == 403

    def test_delete_project_project_write_user_forbidden(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """Project managers cannot delete projects; delete is admin-only."""
        token = normal_user_token_headers["Authorization"].split(" ")[1]
        payload = pyjwt.decode(token, options={"verify_signature": False})
        user_id = int(payload["sub"])

        project = create_test_project(db)
        perm = db.exec(select(Permission).where(Permission.name == "project:write")).one()
        db.add(UserPermission(user_id=user_id, project_id=project.project_id, permission_id=perm.permission_id))
        db.commit()

        r = client.delete(
            f"{settings.API_V1_STR}/projects/{project.project_id}",
            headers=normal_user_token_headers,
        )
        assert r.status_code == 403
        assert db.exec(select(Project).where(Project.project_id == project.project_id)).first() is not None
    
    def test_delete_project_not_found(
        self, client: TestClient, superuser_token_headers: dict[str, str]
    ) -> None:
        """Returns HTTP 404 for non-existent project."""
        r = client.delete(
            f"{settings.API_V1_STR}/projects/99999",
            headers=superuser_token_headers
        )
        assert r.status_code == 404


class TestProjectExport:
    """Tests for GET /projects/exports endpoint."""
    
    def test_export_projects_admin(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Admin can export all projects to CSV."""
        create_test_project(db)
        create_test_project(db)
        
        r = client.get(
            f"{settings.API_V1_STR}/projects/exports",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")
        assert r.headers.get("content-disposition") == (
            'attachment; filename="projects.csv"; '
            "filename*=UTF-8''projects.csv"
        )
        content = r.text.strip().split("\n")
        assert len(content) >= 3  # Header + 2 projects
        assert read_csv_header(content[0]) == [
            "project_id", "uuid", "name", "url", "doi", "creator_name", "creator_id",
            "creation_date", "public", "active",
        ]
    
    def test_export_specific_project_admin(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Admin can export a specific project via project_id param."""
        project = create_test_project(db)
        
        r = client.get(
            f"{settings.API_V1_STR}/projects/exports",
            params={"project_id": project.project_id},
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        assert r.headers.get("content-disposition") == (
            'attachment; filename="projects.csv"; '
            "filename*=UTF-8''projects.csv"
        )
        content = r.text.strip().split("\n")
        assert len(content) == 2  # Header + 1 project
    
    def test_export_projects_with_write_permission(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """User with project:write permission can export their project."""
        token = normal_user_token_headers["Authorization"].split(" ")[1]
        payload = pyjwt.decode(token, options={"verify_signature": False})
        user_id = int(payload["sub"])

        project = create_test_project(db)
        
        # Grant project:write
        perm = db.exec(select(Permission).where(Permission.name == "project:write")).one()
        db.add(UserPermission(user_id=user_id, project_id=project.project_id, permission_id=perm.permission_id))
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/projects/exports",
            params={"project_id": project.project_id},
            headers=normal_user_token_headers
        )
        assert r.status_code == 200
    
    def test_export_projects_forbidden_for_normal_user(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """User without management permissions is forbidden from exporting (ActiveManager check)."""
        create_test_project(db, public=True)
        
        r = client.get(
            f"{settings.API_V1_STR}/projects/exports",
            headers=normal_user_token_headers
        )
        assert r.status_code == 403

    def test_export_projects_collection_filter(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Testing export with valid collection_id filter."""
        project = create_test_project(db)
        collection = Collection(name="Test Col", creator_id=1)
        db.add(collection)
        db.commit()
        db.refresh(collection)
        
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/projects/exports",
            params={"project_id": project.project_id, "collection_id": collection.collection_id},
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        content = r.text.strip().split("\n")
        assert len(content) == 2  # Header + 1 project

    def test_export_projects_collection_mismatch(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Testing export with mismatched collection_id (should result in empty data)."""
        project = create_test_project(db)
        unrelated_collection = Collection(name="Unrelated Col", creator_id=1)
        db.add(unrelated_collection)
        db.commit()
        db.refresh(unrelated_collection)

        r = client.get(
            f"{settings.API_V1_STR}/projects/exports",
            params={"project_id": project.project_id, "collection_id": unrelated_collection.collection_id},
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        content = r.text.strip().split("\n")
        assert len(content) == 1  # Only header
        assert read_csv_header(content[0]) == [
            "project_id", "uuid", "name", "url", "doi", "creator_name", "creator_id",
            "creation_date", "public", "active",
        ]

    def test_export_projects_anonymous_forbidden(
        self, client: TestClient, db: Session
    ) -> None:
        """Anonymous user cannot export projects."""
        project = create_test_project(db)
        r = client.get(f"{settings.API_V1_STR}/projects/exports", params={"project_id": project.project_id})
        assert r.status_code == 401


class TestProjectOptions:
    """Tests for GET /project-options endpoint."""
    
    def test_get_options_as_admin(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Admin can get project options and all projects have can_manage=True."""
        create_test_project(db, name="Option Project A")
        create_test_project(db, name="Option Project B")
        
        r = client.get(
            f"{settings.API_V1_STR}/project-options",
            headers=superuser_token_headers
        )
        assert r.status_code == 200
        json_resp = r.json()
        assert json_resp["code"] == 0
        options = json_resp["data"]
        
        assert isinstance(options, list)
        assert len(options) >= 2
        
        # Verify structure and can_manage flag
        for opt in options:
            assert "project_id" in opt
            assert "name" in opt
            assert "can_manage" in opt
            assert opt["can_manage"] is True  # Admin has write permission on all projects


    def test_get_options_as_normal_user_no_permission(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """Normal user without write permission gets can_manage=False on public projects."""
        create_test_project(db, name="No Perm Option Project", public=True)

        r = client.get(
            f"{settings.API_V1_STR}/project-options",
            headers=normal_user_token_headers
        )
        assert r.status_code == 200
        json_resp = r.json()
        assert json_resp["code"] == 0
        options = json_resp["data"]
        assert isinstance(options, list)
        # Verify can_manage field exists on every option
        for opt in options:
            assert "can_manage" in opt
        # Without any write permission, all can_manage must be False
        matched = [o for o in options if o["name"] == "No Perm Option Project"]
        assert len(matched) >= 1
        for opt in matched:
            assert opt["can_manage"] is False

    def test_get_options_with_write_permission(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """Normal user with project:write permission gets can_manage=True for that project."""
        # Create project and link it to a collection
        project = create_test_project(db, name="Write Perm Option Project", public=True)
        collection = Collection(
            name="Write Test Collection",
            public_access=True,
            public_tags=False,
            creator_id=1,
        )
        db.add(collection)
        db.commit()
        db.refresh(collection)

        pc = ProjectCollection(
            project_id=project.project_id,
            collection_id=collection.collection_id,
        )
        db.add(pc)
        db.commit()

        # Find the normal test user (role_id=2 means regular user, role_id=1 is admin)
        normal_user = db.exec(
            sql_select(User).where(User.role_id != 1)
        ).first()
        assert normal_user is not None

        # Find project:write permission
        write_perm = db.exec(
            sql_select(Permission).where(
                Permission.resource_type == "project",
                Permission.action == "write",
            )
        ).first()
        if write_perm is None:
            return  # Skip if not seeded

        # Grant project-level write permission.
        up = UserPermission(
            user_id=normal_user.user_id,
            project_id=project.project_id,
            permission_id=write_perm.permission_id,
        )
        db.add(up)
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/project-options",
            headers=normal_user_token_headers,
        )
        assert r.status_code == 200
        options = r.json()["data"]
        matched = [o for o in options if o["project_id"] == project.project_id]
        assert len(matched) == 1
        assert matched[0]["can_manage"] is True

    def test_get_options_unauthenticated(
        self, client: TestClient, db: Session
    ) -> None:
        """Unauthenticated users can access project options and get public projects with can_manage=False."""
        create_test_project(db, name="Public For Anon", public=True)

        r = client.get(f"{settings.API_V1_STR}/project-options")
        assert r.status_code == 200
        json_resp = r.json()
        assert json_resp["code"] == 0
        options = json_resp["data"]
        assert isinstance(options, list)
        # All returned projects must have can_manage=False for anonymous users
        for opt in options:
            assert "can_manage" in opt
            assert opt["can_manage"] is False

    def test_get_options_orders_by_name_for_all_user_types(
        self,
        client: TestClient,
        superuser_token_headers: dict[str, str],
        normal_user_token_headers: dict[str, str],
        db: Session,
    ) -> None:
        """Anonymous, admin, and regular-user options should share name ordering."""
        create_test_project(db, name="Sorting Zulu Option", public=True, active=True)
        create_test_project(db, name="Sorting Alpha Option", public=True, active=True)

        requests = (
            {},
            {"headers": superuser_token_headers},
            {"headers": normal_user_token_headers},
        )
        for request_kwargs in requests:
            response = client.get(
                f"{settings.API_V1_STR}/project-options",
                **request_kwargs,
            )
            assert response.status_code == 200
            names = [
                item["name"]
                for item in response.json()["data"]
                if item["name"].startswith("Sorting ")
            ]
            assert names == ["Sorting Alpha Option", "Sorting Zulu Option"]

    def test_get_options_name_filter_preserves_name_order(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """Filtered regular-user options should remain ordered by name."""
        create_test_project(db, name="Filtered Sorting Zulu", public=True)
        create_test_project(db, name="Filtered Sorting Alpha", public=True)

        response = client.get(
            f"{settings.API_V1_STR}/project-options",
            params={"name": "Filtered Sorting"},
            headers=normal_user_token_headers,
        )

        assert response.status_code == 200
        assert [item["name"] for item in response.json()["data"]] == [
            "Filtered Sorting Alpha",
            "Filtered Sorting Zulu",
        ]


class TestProjectSummary:
    """Tests for GET /project-overviews endpoint."""

    # Helper fixtures

    def _create_project_with_collection(self, db: Session, *, public: bool = True, public_access: bool = True):
        """Create a project and a linked collection, return (project, collection)."""
        project = create_test_project(db, public=public)
        collection = Collection(
            name=f"Overview Coll {random_lower_string()[:8]}",
            description="test",
            public_access=public_access,
            public_tags=False,
            creator_id=1,
        )
        db.add(collection)
        db.flush()
        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        db.commit()
        db.refresh(collection)
        db.refresh(project)
        return project, collection

    def _create_media_in_collection(
        self,
        db: Session,
        *,
        collection_id: int,
        media_type: str,
        is_metadata: bool = False,
        creator_id: int = 1,
        filename_suffix: str | None = None,
    ) -> Media:
        """Create one media record and link it to a collection."""
        audio_setting_id = None
        photo_setting_id = None

        if media_type == "audio" and not is_metadata:
            audio_setting = AudioSetting(duration_s=60.0, sampling_rate_hz=44100)
            db.add(audio_setting)
            db.flush()
            audio_setting_id = audio_setting.audio_setting_id
        elif media_type in {"photo", "video"}:
            photo_setting = PhotoSetting()
            db.add(photo_setting)
            db.flush()
            photo_setting_id = photo_setting.photo_setting_id

        media = Media(
            media_type=media_type,
            is_metadata=is_metadata,
            filename=f"overview_{media_type}_{filename_suffix or random_lower_string()[:6]}",
            name=f"overview_{media_type}",
            creator_id=creator_id,
            uploader_id=creator_id,
            audio_setting_id=audio_setting_id,
            photo_setting_id=photo_setting_id,
        )
        db.add(media)
        db.flush()
        db.add(
            MediaCollection(
                media_id=media.media_id,
                collection_id=collection_id,
                added_by=creator_id,
            )
        )
        db.commit()
        db.refresh(media)
        return media

    def _create_annotation_for_media(
        self,
        db: Session,
        *,
        media_id: int,
        creator_id: int = 1,
    ) -> Annotation:
        """Create one annotation for a media record."""
        annotation = Annotation(
            media_id=media_id,
            sound_id=1,
            creator_id=creator_id,
            min_x=0.0,
            max_x=1.0,
            min_y=0.0,
            max_y=1000.0,
        )
        db.add(annotation)
        db.commit()
        db.refresh(annotation)
        return annotation

    def _create_site_in_collection(
        self,
        db: Session,
        *,
        collection_id: int,
        creator_id: int = 1,
    ) -> Site:
        """Create one site record and link it to a collection."""
        site = Site(
            name=f"Overview Site {random_lower_string()[:8]}",
            creator_id=creator_id,
        )
        db.add(site)
        db.flush()
        db.add(SiteCollection(site_id=site.site_id, collection_id=collection_id))
        db.commit()
        db.refresh(site)
        return site

    # Project scope (no collection_id)

    def test_summary_project_anonymous_public(
        self, client: TestClient, db: Session
    ) -> None:
        """Anonymous user can access summary of a public project."""
        project, _ = self._create_project_with_collection(db)

        r = client.get(
            f"{settings.API_V1_STR}/project-overviews",
            params={"project_id": project.project_id},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert "scope_type" not in data
        assert "scope" not in data
        assert "stats" in data
        assert "contributors" in data
        stats = data["stats"]
        for key in ("users", "collections_or_projects", "audios", "photos", "annotations", "sites"):
            assert key in stats

    def test_summary_project_anonymous_private_denied(
        self, client: TestClient, db: Session
    ) -> None:
        """Anonymous user cannot access summary of a private project."""
        project = create_test_project(db, public=False)

        r = client.get(
            f"{settings.API_V1_STR}/project-overviews",
            params={"project_id": project.project_id},
        )
        assert r.status_code == 403

    def test_summary_project_missing_project_id(
        self, client: TestClient, superuser_token_headers: dict[str, str]
    ) -> None:
        """Missing project_id returns 422."""
        r = client.get(
            f"{settings.API_V1_STR}/project-overviews",
            headers=superuser_token_headers,
        )
        assert r.status_code == 422

    def test_summary_project_not_found(
        self, client: TestClient, superuser_token_headers: dict[str, str]
    ) -> None:
        """Non-existent project_id returns 403 (can_access_project returns False)."""
        r = client.get(
            f"{settings.API_V1_STR}/project-overviews",
            params={"project_id": 999999},
            headers=superuser_token_headers,
        )
        assert r.status_code == 403

    def test_summary_project_admin_access(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Admin can access summary of any project."""
        project, collection = self._create_project_with_collection(db)

        r = client.get(
            f"{settings.API_V1_STR}/project-overviews",
            params={"project_id": project.project_id},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert "scope_type" not in data
        # At least 1 collection was created
        assert data["stats"]["collections_or_projects"] >= 1

    def test_summary_project_user_with_permission(
        self,
        client: TestClient,
        normal_user_token_headers: dict[str, str],
        db: Session,
    ) -> None:
        """Logged-in user with project:read permission can access private project summary."""
        import jwt as pyjwt

        token = normal_user_token_headers["Authorization"].split(" ")[1]
        payload = pyjwt.decode(token, options={"verify_signature": False})
        user_id = payload["sub"]

        project = create_test_project(db, public=False)
        perm = db.exec(
            select(Permission).where(
                Permission.resource_type == "project", Permission.action == "read"
            )
        ).first()
        assert perm is not None
        db.add(UserPermission(user_id=user_id, project_id=project.project_id, permission_id=perm.permission_id))
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/project-overviews",
            params={"project_id": project.project_id},
            headers=normal_user_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert "scope_type" not in data

    def test_summary_project_user_no_permission_denied(
        self,
        client: TestClient,
        normal_user_token_headers: dict[str, str],
        db: Session,
    ) -> None:
        """Logged-in user without permission cannot access private project summary."""
        project = create_test_project(db, public=False)

        r = client.get(
            f"{settings.API_V1_STR}/project-overviews",
            params={"project_id": project.project_id},
            headers=normal_user_token_headers,
        )
        assert r.status_code == 403

    # Collection scope (collection_id provided)

    def test_summary_collection_anonymous_public(
        self, client: TestClient, db: Session
    ) -> None:
        """Anonymous user can access collection summary when both project and collection are public."""
        project, collection = self._create_project_with_collection(db, public=True, public_access=True)

        r = client.get(
            f"{settings.API_V1_STR}/project-overviews",
            params={"project_id": project.project_id, "collection_id": collection.collection_id},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert "scope_type" not in data
        assert "scope" not in data
        stats = data["stats"]
        for key in ("users", "collections_or_projects", "audios", "photos", "annotations", "sites"):
            assert key in stats

    def test_summary_collection_anonymous_private_denied(
        self, client: TestClient, db: Session
    ) -> None:
        """Anonymous user cannot access collection summary when collection is private."""
        project, collection = self._create_project_with_collection(db, public=True, public_access=False)

        r = client.get(
            f"{settings.API_V1_STR}/project-overviews",
            params={"project_id": project.project_id, "collection_id": collection.collection_id},
        )
        assert r.status_code == 403

    def test_summary_collection_wrong_project_returns_400(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """collection_id not belonging to project_id is denied."""
        project, _ = self._create_project_with_collection(db)
        # Create a collection NOT linked to the above project
        unrelated = Collection(
            name=f"Unrelated {random_lower_string()[:8]}",
            public_access=True,
            public_tags=False,
            creator_id=1,
        )
        db.add(unrelated)
        db.commit()
        db.refresh(unrelated)

        r = client.get(
            f"{settings.API_V1_STR}/project-overviews",
            params={"project_id": project.project_id, "collection_id": unrelated.collection_id},
            headers=superuser_token_headers,
        )
        assert r.status_code == 403

    def test_summary_collection_contributors_list_present(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """When collection_id is provided, contributors list is present."""
        project, collection = self._create_project_with_collection(db)

        r = client.get(
            f"{settings.API_V1_STR}/project-overviews",
            params={"project_id": project.project_id, "collection_id": collection.collection_id},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert "scope_type" not in data
        assert isinstance(data["contributors"], list)

    def test_summary_collection_user_with_collection_permission(
        self,
        client: TestClient,
        normal_user_token_headers: dict[str, str],
        db: Session,
    ) -> None:
        """Logged-in user with collection:read permission can access private collection summary."""
        import jwt as pyjwt

        token = normal_user_token_headers["Authorization"].split(" ")[1]
        payload = pyjwt.decode(token, options={"verify_signature": False})
        user_id = payload["sub"]

        project, collection = self._create_project_with_collection(db, public=True, public_access=False)

        # Grant project:read + collection:read
        proj_read = db.exec(
            select(Permission).where(
                Permission.resource_type == "project", Permission.action == "read"
            )
        ).first()
        coll_read = db.exec(
            select(Permission).where(
                Permission.resource_type == "collection", Permission.action == "read"
            )
        ).first()
        assert proj_read and coll_read
        db.add(UserPermission(user_id=user_id, project_id=project.project_id, permission_id=proj_read.permission_id))
        db.add(UserPermission(user_id=user_id, project_id=project.project_id, collection_id=collection.collection_id, permission_id=coll_read.permission_id))
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/project-overviews",
            params={"project_id": project.project_id, "collection_id": collection.collection_id},
            headers=normal_user_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert "scope_type" not in data

    def test_summary_project_counts_audio_and_photo_media_separately(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Project summary separates audio/photo counts and excludes other media types."""
        project, collection = self._create_project_with_collection(db)

        self._create_media_in_collection(db, collection_id=collection.collection_id, media_type="audio")
        self._create_media_in_collection(db, collection_id=collection.collection_id, media_type="audio")
        self._create_media_in_collection(db, collection_id=collection.collection_id, media_type="photo")
        self._create_media_in_collection(db, collection_id=collection.collection_id, media_type="video")
        self._create_media_in_collection(db, collection_id=collection.collection_id, media_type="audio", is_metadata=True)

        r = client.get(
            f"{settings.API_V1_STR}/project-overviews",
            params={"project_id": project.project_id},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        stats = r.json()["data"]["stats"]
        assert stats["audios"] == 2
        assert stats["photos"] == 1
        assert stats["audios"] + stats["photos"] != 5

    def test_summary_collection_counts_audio_and_photo_media_separately(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Collection summary separates audio/photo counts and excludes other media types."""
        project, collection = self._create_project_with_collection(db)

        self._create_media_in_collection(db, collection_id=collection.collection_id, media_type="audio")
        self._create_media_in_collection(db, collection_id=collection.collection_id, media_type="photo")
        self._create_media_in_collection(db, collection_id=collection.collection_id, media_type="photo")
        self._create_media_in_collection(db, collection_id=collection.collection_id, media_type="video")
        self._create_media_in_collection(db, collection_id=collection.collection_id, media_type="audio", is_metadata=True)

        r = client.get(
            f"{settings.API_V1_STR}/project-overviews",
            params={"project_id": project.project_id, "collection_id": collection.collection_id},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        stats = r.json()["data"]["stats"]
        assert stats["audios"] == 1
        assert stats["photos"] == 2
        assert stats["audios"] + stats["photos"] != 5

    def test_summary_project_deduplicates_media_linked_to_multiple_project_collections(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Project summary counts one media once even when linked to multiple collections."""
        project, first_collection = self._create_project_with_collection(db)
        second_collection = Collection(
            name=f"Overview Coll {random_lower_string()[:8]}",
            description="test",
            public_access=True,
            public_tags=False,
            creator_id=1,
        )
        db.add(second_collection)
        db.flush()
        db.add(
            ProjectCollection(
                project_id=project.project_id,
                collection_id=second_collection.collection_id,
            )
        )

        shared_audio = self._create_media_in_collection(
            db,
            collection_id=first_collection.collection_id,
            media_type="audio",
        )
        db.add(
            MediaCollection(
                media_id=shared_audio.media_id,
                collection_id=second_collection.collection_id,
                added_by=1,
            )
        )
        self._create_media_in_collection(
            db,
            collection_id=second_collection.collection_id,
            media_type="photo",
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/project-overviews",
            params={"project_id": project.project_id},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        stats = r.json()["data"]["stats"]
        assert stats["audios"] == 1
        assert stats["photos"] == 1

    def test_summary_project_counts_overview_stats_with_metadata_media(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Project summary ignores metadata media while preserving media, annotation, and site counts."""
        project, collection = self._create_project_with_collection(db)
        audio = self._create_media_in_collection(
            db,
            collection_id=collection.collection_id,
            media_type="audio",
        )
        photo = self._create_media_in_collection(
            db,
            collection_id=collection.collection_id,
            media_type="photo",
        )
        for _ in range(3):
            self._create_media_in_collection(
                db,
                collection_id=collection.collection_id,
                media_type="audio", is_metadata=True,
            )
        self._create_annotation_for_media(db, media_id=audio.media_id)
        self._create_annotation_for_media(db, media_id=audio.media_id)
        self._create_annotation_for_media(db, media_id=photo.media_id)
        self._create_site_in_collection(db, collection_id=collection.collection_id)

        r = client.get(
            f"{settings.API_V1_STR}/project-overviews",
            params={"project_id": project.project_id},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        stats = r.json()["data"]["stats"]
        assert stats["collections_or_projects"] == 1
        assert stats["audios"] == 1
        assert stats["photos"] == 1
        assert stats["annotations"] == 3
        assert stats["sites"] == 1

    def test_summary_project_returns_zero_without_audio_or_photo_media(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Project summary returns zero media and annotation counts when only metadata media exists."""
        project, collection = self._create_project_with_collection(db)
        self._create_media_in_collection(
            db,
            collection_id=collection.collection_id,
            media_type="audio", is_metadata=True,
        )

        r = client.get(
            f"{settings.API_V1_STR}/project-overviews",
            params={"project_id": project.project_id},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        stats = r.json()["data"]["stats"]
        assert stats["audios"] == 0
        assert stats["photos"] == 0
        assert stats["annotations"] == 0

    def test_summary_project_creator_first_then_project_contributors(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Project summary contributors should put creator first, then project contributors."""
        creator = db.exec(select(User).where(User.user_id == 1)).first()
        assert creator is not None
        project = create_test_project(db, creator_id=creator.user_id, public=True)

        contributor_user = create_random_user(db)
        db.add(
            ProjectContributor(
                project_id=project.project_id,
                user_id=contributor_user.user_id,
                contribution_role="editor",
            )
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/project-overviews",
            params={"project_id": project.project_id},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        contributors = r.json()["data"]["contributors"]
        assert len(contributors) >= 2
        assert contributors[0]["user_id"] == creator.user_id
        assert contributors[0]["email"] == creator.email
        assert contributors[0]["contribution_role"] == "PROJECT CREATOR"
        assert contributors[1]["user_id"] == contributor_user.user_id
        assert contributors[1]["email"] == contributor_user.email
        assert contributors[1]["contribution_role"] == "editor"

    def test_summary_collection_creator_first_then_collection_contributors(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Collection summary contributors should put creator first, then collection contributors."""
        creator = db.exec(select(User).where(User.user_id == 1)).first()
        assert creator is not None
        project, collection = self._create_project_with_collection(
            db,
            public=True,
            public_access=True,
        )

        contributor_user = create_random_user(db)
        db.add(
            CollectionContributor(
                collection_id=collection.collection_id,
                user_id=contributor_user.user_id,
                contribution_role="annotator",
            )
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/project-overviews",
            params={"project_id": project.project_id, "collection_id": collection.collection_id},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        contributors = r.json()["data"]["contributors"]
        assert len(contributors) >= 2
        assert contributors[0]["user_id"] == creator.user_id
        assert contributors[0]["email"] == creator.email
        assert contributors[0]["contribution_role"] == "COLLECTION CREATOR"
        assert contributors[1]["user_id"] == contributor_user.user_id
        assert contributors[1]["email"] == contributor_user.email
        assert contributors[1]["contribution_role"] == "annotator"


def test_project_urls_are_validated_and_normalized(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    invalid = client.post(
        f"{settings.API_V1_STR}/projects/",
        headers=superuser_token_headers,
        json={"name": "Invalid URL Project", "url": "javascript:alert(1)"},
    )
    assert invalid.status_code == 422

    name = f"Trimmed URL Project {random_lower_string()[:8]}"
    created = client.post(
        f"{settings.API_V1_STR}/projects/",
        headers=superuser_token_headers,
        json={"name": name, "url": "  https://example.com/trimmed  "},
    )
    assert created.status_code == 201
    project = db.exec(select(Project).where(Project.name == name)).one()
    assert project.url == "https://example.com/trimmed"

    cleared = client.patch(
        f"{settings.API_V1_STR}/projects/{project.project_id}",
        headers=superuser_token_headers,
        json={"url": "   "},
    )
    assert cleared.status_code == 200
    db.refresh(project)
    assert project.url == ""
