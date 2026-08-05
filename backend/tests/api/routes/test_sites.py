"""
Test cases for site API routes.
"""
import csv
from datetime import datetime, UTC, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, select

from app.core.config import settings
from app.models import Collection, Project, Permission, UserPermission, ProjectCollection
from app.models.media import Media, MediaCollection, PhotoSetting
from app.models.site import Site, SiteCollection, SiteProject, IucnGet
from app.repositories import user_repository
from app.schemas import UserCreate
from tests.utils.csv import read_csv_header
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_lower_string, random_email


def ensure_default_gadm(db: Session) -> None:
    """Seed ADM_0/1/2 hierarchy required by create/update validations."""
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS adm_0 (
            "GID_0" VARCHAR(20) PRIMARY KEY,
            "COUNTRY" VARCHAR(255) NOT NULL,
            geometry geometry(MULTIPOLYGON, 4326)
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS adm_1 (
            "GID_1" VARCHAR(40) PRIMARY KEY,
            "GID_0" VARCHAR(20) NOT NULL,
            "NAME_1" VARCHAR(255) NOT NULL,
            geometry geometry(MULTIPOLYGON, 4326)
        )
    """))
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS adm_2 (
            "GID_2" VARCHAR(60) PRIMARY KEY,
            "GID_1" VARCHAR(40) NOT NULL,
            "GID_0" VARCHAR(20) NOT NULL,
            "NAME_2" VARCHAR(255) NOT NULL,
            geometry geometry(MULTIPOLYGON, 4326)
        )
    """))
    db.execute(text("""
        INSERT INTO adm_0 ("GID_0", "COUNTRY", geometry) VALUES
        ('DFT', 'DefaultLand', ST_Multi(ST_GeomFromText('POLYGON((0 0, 200 0, 200 200, 0 200, 0 0))', 4326)))
        ON CONFLICT ("GID_0") DO NOTHING
    """))
    db.execute(text("""
        INSERT INTO adm_1 ("GID_1", "GID_0", "NAME_1", geometry) VALUES
        ('DFT.1_1', 'DFT', 'DefaultState', ST_Multi(ST_GeomFromText('POLYGON((10 10, 190 10, 190 190, 10 190, 10 10))', 4326)))
        ON CONFLICT ("GID_1") DO NOTHING
    """))
    db.execute(text("""
        INSERT INTO adm_2 ("GID_2", "GID_1", "GID_0", "NAME_2", geometry) VALUES
        ('DFT.1.1_1', 'DFT.1_1', 'DFT', 'DefaultCity', ST_Multi(ST_GeomFromText('POLYGON((20 20, 180 20, 180 180, 20 180, 20 20))', 4326)))
        ON CONFLICT ("GID_2") DO NOTHING
    """))
    db.commit()

def create_test_project(db: Session, creator_id: int = 1, **kwargs) -> Project:
    """Create a test project."""
    defaults = {
        "name": f"Site Test Project {random_lower_string()[:8]}",
        "url": f"https://example.com/{random_lower_string()[:8]}",
        "description": "Test",
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


def create_test_collection(db: Session, creator_id: int = 1, **kwargs) -> Collection:
    """Create a test collection."""
    ensure_default_gadm(db)
    auto_link_project = kwargs.pop("auto_link_project", True)
    defaults = {
        "name": f"Site Test Collection {random_lower_string()[:8]}",
        "public_access": False,
        "creator_id": creator_id,
    }
    defaults.update(kwargs)
    collection = Collection(**defaults)
    db.add(collection)
    db.commit()
    db.refresh(collection)
    if auto_link_project:
        project = create_test_project(db, creator_id=creator_id)
        link_collection_to_project(db, project.project_id, collection.collection_id)
    return collection


def link_collection_to_project(db: Session, project_id: int, collection_id: int) -> None:
    """Associate a collection with a project."""
    pc = ProjectCollection(project_id=project_id, collection_id=collection_id)
    db.add(pc)
    db.commit()


def create_test_site(db: Session, collection_id: int, creator_id: int = 1, **kwargs) -> Site:
    """Create a test site with minimal geometry (using raw SQL-compatible approach)."""
    defaults = {
        "name": f"Test Site {random_lower_string()[:8]}",
        "creator_id": creator_id,
        "topography_m": 100.0,
        "freshwater_depth_m": 5.0,
        "gadm0": "DefaultLand",
    }
    defaults.update(kwargs)

    site = Site(**defaults)
    db.add(site)
    db.commit()
    db.refresh(site)

    # Set location from GADM polygon if possible; set longitude/latitude directly
    if site.gadm0_gid:
        db.execute(
            text("""
                UPDATE site SET location = (
                    SELECT ST_SimplifyPreserveTopology(geometry, 0.01)
                    FROM adm_0 WHERE "GID_0" = :gid LIMIT 1
                ) WHERE site_id = :id
            """),
            {"gid": site.gadm0_gid, "id": site.site_id}
        )
    db.commit()
    db.refresh(site)

    # Bind to collection
    sc = SiteCollection(site_id=site.site_id, collection_id=collection_id)
    db.add(sc)
    db.commit()
    return site


def create_test_media(
    db: Session,
    collection_id: int,
    creator_id: int = 1,
    **kwargs,
) -> Media:
    """Create a test media item linked to a collection."""
    defaults = {
        "media_type": "audio",
        "is_metadata": True,
        "creator_id": creator_id,
        "filename": f"{random_lower_string()[:8]}.wav",
        "name": f"Media {random_lower_string()[:6]}",
        "date_time": datetime.now(UTC),
    }
    defaults.update(kwargs)
    media = Media(**defaults)
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


def grant_permission(db: Session, user_id: int, resource_type: str, action: str,
                     collection_id: int = None, project_id: int = None) -> None:
    """Grant a permission to a user."""
    if collection_id is not None and project_id is None:
        project_ids = db.exec(
            select(ProjectCollection.project_id).where(
                ProjectCollection.collection_id == collection_id
            )
        ).all()
        if len(project_ids) == 0:
            project = create_test_project(db)
            link_collection_to_project(db, project.project_id, collection_id)
            project_id = project.project_id
        else:
            project_id = project_ids[-1]
    perm = db.exec(
        select(Permission).where(
            Permission.resource_type == resource_type,
            Permission.action == action
        )
    ).one()
    up = UserPermission(
        user_id=user_id,
        permission_id=perm.permission_id,
        collection_id=collection_id,
        project_id=project_id,
    )
    db.add(up)
    db.commit()


def create_user_with_headers(db: Session, client: TestClient, **kwargs):
    """Create a user and return (user, auth_headers)."""

    email = random_email()
    password = "testpassword123"
    username = random_lower_string()[:20]
    user_in = UserCreate(
        username=username, name="Test User",
        email=email, password=password,
    )
    user = user_repository.create(session=db, obj_in=user_in)
    headers = user_authentication_headers(client=client, username=username, password=password)
    return user, headers



class TestSiteOptions:
    """Tests for GET /site-options and /iucn-typology-options."""

    @staticmethod
    def _realm_names(data: dict) -> list[str]:
        return [realm["name"] for realm in data["realms"]]

    @staticmethod
    def _biome_names(realm: dict) -> list[str]:
        return [biome["name"] for biome in realm["children"]]

    @staticmethod
    def _functional_type_names(biome: dict) -> list[str]:
        return [item["name"] for item in biome["children"]]

    def test_get_site_options_no_auth(self, client: TestClient, db: Session) -> None:
        """Options endpoint requires no authentication."""
        collection = create_test_collection(db, public_access=True)
        create_test_site(db, collection.collection_id)
        r = client.get(f"{settings.API_V1_STR}/site-options")
        assert r.status_code == 200
        assert "data" in r.json()

    def test_get_site_options_filtered_by_collection(self, client: TestClient, db: Session) -> None:
        """Options endpoint filters by collection_id correctly."""
        col1 = create_test_collection(db, public_access=True)
        col2 = create_test_collection(db, public_access=True)
        site1 = create_test_site(db, col1.collection_id, name="Site Alpha")
        site2 = create_test_site(db, col2.collection_id, name="Site Beta")

        r = client.get(f"{settings.API_V1_STR}/site-options?collection_id={col1.collection_id}")
        assert r.status_code == 200
        names = [s["name"] for s in r.json()["data"]]
        assert site1.name in names
        assert site2.name not in names

    def test_get_site_options_filtered_by_project(self, client: TestClient, db: Session) -> None:
        """project_id scope returns all visible project sites, even without media."""
        project = create_test_project(db)
        in_project_col = create_test_collection(db, public_access=True, auto_link_project=False)
        out_project_col = create_test_collection(db, public_access=True, auto_link_project=False)
        link_collection_to_project(db, project.project_id, in_project_col.collection_id)
        other_project = create_test_project(db)
        link_collection_to_project(db, other_project.project_id, out_project_col.collection_id)

        in_project_site = create_test_site(db, in_project_col.collection_id, name="In Project Site")
        out_project_site = create_test_site(db, out_project_col.collection_id, name="Out Project Site")

        r = client.get(f"{settings.API_V1_STR}/site-options?project_id={project.project_id}")
        assert r.status_code == 200
        names = [s["name"] for s in r.json()["data"]]
        assert in_project_site.name in names
        assert out_project_site.name not in names

    def test_get_site_options_filtered_by_project_and_collection(self, client: TestClient, db: Session) -> None:
        """project + collection scope only returns scoped site master data."""
        project = create_test_project(db)
        project_col = create_test_collection(db, public_access=True, auto_link_project=False)
        other_col = create_test_collection(db, public_access=True, auto_link_project=False)
        link_collection_to_project(db, project.project_id, project_col.collection_id)
        link_collection_to_project(db, project.project_id, other_col.collection_id)

        in_both = create_test_site(db, project_col.collection_id, name="In Both Scope")
        out_of_collection = create_test_site(db, other_col.collection_id, name="Out Of Collection")

        r = client.get(
            f"{settings.API_V1_STR}/site-options?project_id={project.project_id}&collection_id={project_col.collection_id}"
        )
        assert r.status_code == 200
        names = [s["name"] for s in r.json()["data"]]
        assert in_both.name in names
        assert out_of_collection.name not in names

    def test_get_site_options_filtered_by_name(self, client: TestClient, db: Session) -> None:
        """Options endpoint filters by name correctly."""
        col = create_test_collection(db, public_access=True)
        create_test_site(db, col.collection_id, name="Station Alpha")
        create_test_site(db, col.collection_id, name="Monitor Beta")

        r = client.get(f"{settings.API_V1_STR}/site-options?name=Alpha")
        assert r.status_code == 200
        names = [s["name"] for s in r.json()["data"]]
        assert "Station Alpha" in names
        assert "Monitor Beta" not in names

    def test_get_site_options_project_scope_filters_by_site_name(
        self, client: TestClient, db: Session
    ) -> None:
        """When project_id is present, name should filter matching site names."""
        project = create_test_project(db)
        collection = create_test_collection(db, public_access=True, auto_link_project=False)
        link_collection_to_project(db, project.project_id, collection.collection_id)

        alpha_site = create_test_site(db, collection.collection_id, name="Alpha Delta Site")
        create_test_site(db, collection.collection_id, name="Omega Site")

        response = client.get(
            f"{settings.API_V1_STR}/site-options",
            params={"project_id": project.project_id, "name": "Alpha"},
        )
        assert response.status_code == 200
        assert response.json()["data"] == [
            {"site_id": alpha_site.site_id, "name": alpha_site.name}
        ]

    def test_get_site_options_project_scope_ignores_current_site_filter(
        self, client: TestClient, db: Session
    ) -> None:
        """Unknown query params such as site_id do not narrow site candidates."""
        project = create_test_project(db)
        collection = create_test_collection(db, public_access=True, auto_link_project=False)
        link_collection_to_project(db, project.project_id, collection.collection_id)

        site_a = create_test_site(db, collection.collection_id, name="Switch A")
        site_b = create_test_site(db, collection.collection_id, name="Switch B")

        response = client.get(
            f"{settings.API_V1_STR}/site-options",
            params={"project_id": project.project_id, "site_id": site_a.site_id},
        )
        assert response.status_code == 200
        names = [row["name"] for row in response.json()["data"]]
        assert names == ["Switch A", "Switch B"]

    def test_get_site_options_project_scope_merges_public_and_accessible_sites(
        self, client: TestClient, db: Session
    ) -> None:
        """Authenticated users should see public + accessible private collection sites."""
        user, headers = create_user_with_headers(db, client)
        project = create_test_project(db, public=True)
        public_col = create_test_collection(db, public_access=True, auto_link_project=False)
        private_col = create_test_collection(db, public_access=False, auto_link_project=False)
        hidden_col = create_test_collection(db, public_access=False, auto_link_project=False)
        link_collection_to_project(db, project.project_id, public_col.collection_id)
        link_collection_to_project(db, project.project_id, private_col.collection_id)
        link_collection_to_project(db, project.project_id, hidden_col.collection_id)

        public_site = create_test_site(db, public_col.collection_id, name="Public Scoped")
        private_site = create_test_site(db, private_col.collection_id, name="Private Scoped")
        hidden_site = create_test_site(db, hidden_col.collection_id, name="Hidden Scoped")
        grant_permission(
            db,
            user.user_id,
            "site",
            "read",
            collection_id=private_col.collection_id,
            project_id=project.project_id,
        )
        grant_permission(
            db,
            user.user_id,
            "project",
            "read",
            project_id=project.project_id,
        )

        response = client.get(
            f"{settings.API_V1_STR}/site-options",
            headers=headers,
            params={"project_id": project.project_id},
        )
        assert response.status_code == 200
        names = [row["name"] for row in response.json()["data"]]
        assert names == ["Private Scoped", "Public Scoped"]

    def test_get_iucn_options_no_auth(self, client: TestClient, db: Session) -> None:
        """IUCN options endpoint requires no authentication."""
        r = client.get(f"{settings.API_V1_STR}/iucn-typology-options")
        assert r.status_code == 200
        assert "data" in r.json()
        data = r.json()["data"]
        assert "realms" in data
        assert all(realm["id"] != 0 for realm in data["realms"])

    def test_get_iucn_options_project_scope_returns_used_nodes_only(
        self, client: TestClient, db: Session
    ) -> None:
        """Project scope should prune the tree to nodes used by visible map sites."""
        project = create_test_project(db, public=True)
        in_scope_col = create_test_collection(db, public_access=True, auto_link_project=False)
        out_scope_col = create_test_collection(db, public_access=True, auto_link_project=False)
        link_collection_to_project(db, project.project_id, in_scope_col.collection_id)
        other_project = create_test_project(db, public=True)
        link_collection_to_project(db, other_project.project_id, out_scope_col.collection_id)

        db.add_all(
            [
                IucnGet(iucn_get_id=9101, pid=0, name="Realm-A", level=1),
                IucnGet(iucn_get_id=9102, pid=9101, name="Biome-A", level=2),
                IucnGet(iucn_get_id=9103, pid=9102, name="Group-A", level=3),
                IucnGet(iucn_get_id=9201, pid=0, name="Realm-B", level=1),
                IucnGet(iucn_get_id=9202, pid=9201, name="Biome-B", level=2),
                IucnGet(iucn_get_id=9203, pid=9202, name="Group-B", level=3),
            ]
        )
        db.commit()

        in_scope_site = create_test_site(
            db,
            in_scope_col.collection_id,
            name="Scoped Site",
            longitude=118.2,
            latitude=26.3,
            realm_id=9101,
            biome_id=9102,
            functional_type_id=9103,
        )
        out_scope_site = create_test_site(
            db,
            out_scope_col.collection_id,
            name="Out Scope Site",
            longitude=118.4,
            latitude=26.5,
            realm_id=9201,
            biome_id=9202,
            functional_type_id=9203,
        )
        create_test_media(db, in_scope_col.collection_id, site_id=in_scope_site.site_id)
        create_test_media(db, out_scope_col.collection_id, site_id=out_scope_site.site_id)

        response = client.get(
            f"{settings.API_V1_STR}/iucn-typology-options",
            params={"project_id": project.project_id},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert self._realm_names(data) == ["Realm-A"]
        assert self._biome_names(data["realms"][0]) == ["Biome-A"]
        assert self._functional_type_names(data["realms"][0]["children"][0]) == ["Group-A"]

    def test_get_iucn_options_collection_scope_only_returns_that_collection_usage(
        self, client: TestClient, db: Session
    ) -> None:
        """project + collection scope should narrow the tree to the selected collection."""
        project = create_test_project(db, public=True)
        target_col = create_test_collection(db, public_access=True, auto_link_project=False)
        other_col = create_test_collection(db, public_access=True, auto_link_project=False)
        link_collection_to_project(db, project.project_id, target_col.collection_id)
        link_collection_to_project(db, project.project_id, other_col.collection_id)

        db.add_all(
            [
                IucnGet(iucn_get_id=9301, pid=0, name="Realm-C", level=1),
                IucnGet(iucn_get_id=9302, pid=9301, name="Biome-C", level=2),
                IucnGet(iucn_get_id=9303, pid=9302, name="Group-C", level=3),
                IucnGet(iucn_get_id=9401, pid=0, name="Realm-D", level=1),
            ]
        )
        db.commit()

        target_site = create_test_site(
            db,
            target_col.collection_id,
            name="Target Collection Site",
            longitude=118.6,
            latitude=26.8,
            realm_id=9301,
            biome_id=9302,
            functional_type_id=9303,
        )
        other_site = create_test_site(
            db,
            other_col.collection_id,
            name="Other Collection Site",
            longitude=118.9,
            latitude=27.1,
        )
        create_test_media(db, target_col.collection_id, site_id=target_site.site_id)
        create_test_media(db, other_col.collection_id, site_id=other_site.site_id)

        response = client.get(
            f"{settings.API_V1_STR}/iucn-typology-options",
            params={
                "project_id": project.project_id,
                "collection_id": target_col.collection_id,
            },
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert self._realm_names(data) == ["Realm-C"]
        assert self._biome_names(data["realms"][0]) == ["Biome-C"]
        assert self._functional_type_names(data["realms"][0]["children"][0]) == ["Group-C"]

    def test_get_iucn_options_project_scope_merges_public_and_accessible_usage(
        self, client: TestClient, db: Session
    ) -> None:
        """Authenticated users should see public + accessible private collection IUCN usage."""
        user, headers = create_user_with_headers(db, client)
        project = create_test_project(db, public=True)
        public_col = create_test_collection(db, public_access=True, auto_link_project=False)
        private_col = create_test_collection(db, public_access=False, auto_link_project=False)
        hidden_col = create_test_collection(db, public_access=False, auto_link_project=False)
        link_collection_to_project(db, project.project_id, public_col.collection_id)
        link_collection_to_project(db, project.project_id, private_col.collection_id)
        link_collection_to_project(db, project.project_id, hidden_col.collection_id)

        db.add_all(
            [
                IucnGet(iucn_get_id=9501, pid=0, name="Realm-E", level=1),
                IucnGet(iucn_get_id=9502, pid=9501, name="Biome-E", level=2),
                IucnGet(iucn_get_id=9503, pid=9502, name="Group-E", level=3),
                IucnGet(iucn_get_id=9601, pid=0, name="Realm-F", level=1),
                IucnGet(iucn_get_id=9701, pid=0, name="Realm-G", level=1),
            ]
        )
        db.commit()

        public_site = create_test_site(
            db,
            public_col.collection_id,
            name="Public IUCN Site",
            longitude=119.2,
            latitude=28.1,
            realm_id=9501,
            biome_id=9502,
            functional_type_id=9503,
        )
        private_site = create_test_site(
            db,
            private_col.collection_id,
            name="Private Visible Site",
            longitude=119.4,
            latitude=28.3,
            realm_id=9601,
        )
        hidden_site = create_test_site(
            db,
            hidden_col.collection_id,
            name="Private Hidden Site",
            longitude=119.6,
            latitude=28.5,
            realm_id=9701,
        )
        create_test_media(db, public_col.collection_id, site_id=public_site.site_id)
        create_test_media(db, private_col.collection_id, site_id=private_site.site_id)
        create_test_media(db, hidden_col.collection_id, site_id=hidden_site.site_id)
        grant_permission(
            db,
            user.user_id,
            "site",
            "read",
            collection_id=private_col.collection_id,
            project_id=project.project_id,
        )
        grant_permission(
            db, user.user_id, "audio", "read", collection_id=private_col.collection_id
        )
        grant_permission(
            db,
            user.user_id,
            "project",
            "read",
            project_id=project.project_id,
        )

        response = client.get(
            f"{settings.API_V1_STR}/iucn-typology-options",
            headers=headers,
            params={"project_id": project.project_id},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert self._realm_names(data) == ["Realm-E", "Realm-F"]

    def test_get_iucn_options_anonymous_only_uses_public_scope(
        self, client: TestClient, db: Session
    ) -> None:
        """Anonymous users should only receive IUCN usage from public map scope."""
        project = create_test_project(db, public=True)
        public_col = create_test_collection(db, public_access=True, auto_link_project=False)
        private_col = create_test_collection(db, public_access=False, auto_link_project=False)
        link_collection_to_project(db, project.project_id, public_col.collection_id)
        link_collection_to_project(db, project.project_id, private_col.collection_id)

        db.add_all(
            [
                IucnGet(iucn_get_id=9801, pid=0, name="Realm-H", level=1),
                IucnGet(iucn_get_id=9901, pid=0, name="Realm-I", level=1),
            ]
        )
        db.commit()

        public_site = create_test_site(
            db,
            public_col.collection_id,
            name="Public Realm Site",
            longitude=120.1,
            latitude=29.2,
            realm_id=9801,
        )
        private_site = create_test_site(
            db,
            private_col.collection_id,
            name="Private Realm Site",
            longitude=120.3,
            latitude=29.4,
            realm_id=9901,
        )
        create_test_media(db, public_col.collection_id, site_id=public_site.site_id)
        create_test_media(db, private_col.collection_id, site_id=private_site.site_id)

        response = client.get(
            f"{settings.API_V1_STR}/iucn-typology-options",
            params={"project_id": project.project_id},
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert self._realm_names(data) == ["Realm-H"]

    def test_get_iucn_options_appends_no_selected_at_each_used_level(
        self, client: TestClient, db: Session
    ) -> None:
        """Scoped null assignments add No selected only to their matching level."""
        project = create_test_project(db, public=True)
        collection = create_test_collection(db, public_access=True, auto_link_project=False)
        link_collection_to_project(db, project.project_id, collection.collection_id)

        db.add_all([
            IucnGet(iucn_get_id=9831, pid=0, name="Realm-Nulls", level=1),
            IucnGet(iucn_get_id=9832, pid=9831, name="Biome-Nulls", level=2),
            IucnGet(iucn_get_id=9833, pid=9832, name="Group-Nulls", level=3),
            IucnGet(iucn_get_id=9841, pid=0, name="Realm-Complete", level=1),
            IucnGet(iucn_get_id=9842, pid=9841, name="Biome-Complete", level=2),
            IucnGet(iucn_get_id=9843, pid=9842, name="Group-Complete", level=3),
        ])
        db.commit()

        sites = [
            create_test_site(db, collection.collection_id, name="No Realm", longitude=120.0, latitude=29.0),
            create_test_site(db, collection.collection_id, name="No Biome", longitude=120.1, latitude=29.1, realm_id=9831),
            create_test_site(db, collection.collection_id, name="No Group", longitude=120.2, latitude=29.2, realm_id=9831, biome_id=9832),
            create_test_site(db, collection.collection_id, name="Complete Null Branch", longitude=120.3, latitude=29.3, realm_id=9831, biome_id=9832, functional_type_id=9833),
            create_test_site(db, collection.collection_id, name="Complete Other Branch", longitude=120.4, latitude=29.4, realm_id=9841, biome_id=9842, functional_type_id=9843),
        ]
        for site in sites:
            create_test_media(db, collection.collection_id, site_id=site.site_id)

        response = client.get(
            f"{settings.API_V1_STR}/iucn-typology-options",
            params={"project_id": project.project_id},
        )
        assert response.status_code == 200
        realms = response.json()["data"]["realms"]
        assert [node["name"] for node in realms] == ["Realm-Nulls", "Realm-Complete", "No selected"]
        assert [node["name"] for node in realms[0]["children"]] == ["Biome-Nulls", "No selected"]
        assert [node["name"] for node in realms[0]["children"][0]["children"]] == ["Group-Nulls", "No selected"]
        assert [node["name"] for node in realms[1]["children"]] == ["Biome-Complete"]
        assert realms[-1] == {"id": 0, "name": "No selected", "children": []}

    def test_get_iucn_options_excludes_sites_without_media(
        self, client: TestClient, db: Session
    ) -> None:
        """Sites with IUCN assignments but no scoped media should not appear in the tree."""
        project = create_test_project(db, public=True)
        collection = create_test_collection(db, public_access=True, auto_link_project=False)
        link_collection_to_project(db, project.project_id, collection.collection_id)

        db.add_all(
            [
                IucnGet(iucn_get_id=9811, pid=0, name="Realm-No-Media", level=1),
                IucnGet(iucn_get_id=9812, pid=9811, name="Biome-No-Media", level=2),
                IucnGet(iucn_get_id=9813, pid=9812, name="Group-No-Media", level=3),
            ]
        )
        db.commit()

        create_test_site(
            db,
            collection.collection_id,
            name="No Media IUCN Site",
            longitude=121.0,
            latitude=30.0,
            realm_id=9811,
            biome_id=9812,
            functional_type_id=9813,
        )
        create_test_site(
            db, collection.collection_id, name="No Media Unassigned", longitude=121.1, latitude=30.1
        )

        response = client.get(
            f"{settings.API_V1_STR}/iucn-typology-options",
            params={"project_id": project.project_id},
        )
        assert response.status_code == 200
        assert response.json()["data"]["realms"] == []

    def test_get_iucn_options_requires_audio_visibility(
        self, client: TestClient, db: Session
    ) -> None:
        """Users with site:read but no audio:read should receive an empty IUCN tree."""
        user, headers = create_user_with_headers(db, client)
        project = create_test_project(db, public=False)
        collection = create_test_collection(db, public_access=False, auto_link_project=False)
        link_collection_to_project(db, project.project_id, collection.collection_id)

        db.add(IucnGet(iucn_get_id=9821, pid=0, name="Realm-Site-Only", level=1))
        db.commit()

        site = create_test_site(
            db,
            collection.collection_id,
            name="Site Read Only IUCN",
            longitude=121.5,
            latitude=30.5,
            realm_id=9821,
        )
        create_test_media(db, collection.collection_id, creator_id=user.user_id, site_id=site.site_id)
        grant_permission(db, user.user_id, "site", "read", collection_id=collection.collection_id)
        grant_permission(db, user.user_id, "project", "read", project_id=project.project_id)

        response = client.get(
            f"{settings.API_V1_STR}/iucn-typology-options",
            headers=headers,
            params={"project_id": project.project_id},
        )
        assert response.status_code == 200
        assert response.json()["data"]["realms"] == []

    def test_get_iucn_options_invalid_project_collection_path_returns_400(
        self, client: TestClient, db: Session
    ) -> None:
        """collection_id must belong to the provided project path."""
        project = create_test_project(db, public=True)
        other_project = create_test_project(db, public=True)
        collection = create_test_collection(db, public_access=True, auto_link_project=False)
        link_collection_to_project(db, other_project.project_id, collection.collection_id)

        response = client.get(
            f"{settings.API_V1_STR}/iucn-typology-options",
            params={
                "project_id": project.project_id,
                "collection_id": collection.collection_id,
            },
        )
        assert response.status_code == 400
        assert response.json()["message"] == "collection_id does not belong to the given project_id"

    def test_get_iucn_options_collection_without_unique_project_returns_400(
        self, client: TestClient, db: Session
    ) -> None:
        """collection-only requests should require a unique project path."""
        project_a = create_test_project(db, public=True)
        project_b = create_test_project(db, public=True)
        collection = create_test_collection(db, public_access=True, auto_link_project=False)
        link_collection_to_project(db, project_a.project_id, collection.collection_id)
        link_collection_to_project(db, project_b.project_id, collection.collection_id)

        response = client.get(
            f"{settings.API_V1_STR}/iucn-typology-options",
            params={"collection_id": collection.collection_id},
        )
        assert response.status_code == 400
        assert response.json()["message"] == "project_id is required when collection belongs to multiple projects"



class TestSiteMap:
    """Tests for GET /site-map-items."""

    @staticmethod
    def _create_site_media(
        db: Session,
        *,
        site_id: int,
        collection_id: int,
        creator_id: int = 1,
        media_type: str = "audio",
        is_metadata: bool = True,
    ) -> Media:
        media = Media(media_type=media_type, is_metadata=is_metadata, creator_id=creator_id, site_id=site_id)
        db.add(media)
        db.flush()
        db.add(
            MediaCollection(
                media_id=media.media_id,
                collection_id=collection_id,
                added_by=creator_id,
            )
        )
        db.flush()
        return media

    def test_map_sites_anonymous_only_public(
        self, client: TestClient, db: Session
    ) -> None:
        """Anonymous users should only see sites in public collections."""
        project = create_test_project(db)
        public_col = create_test_collection(db, public_access=True)
        private_col = create_test_collection(db, public_access=False)
        link_collection_to_project(db, project.project_id, public_col.collection_id)
        link_collection_to_project(db, project.project_id, private_col.collection_id)

        public_site = create_test_site(
            db, public_col.collection_id, name="Public Map Site", longitude=120.1, latitude=23.5
        )
        create_test_site(
            db, private_col.collection_id, name="Private Map Site", longitude=121.1, latitude=24.5
        )

        media_public = Media(media_type="audio", is_metadata=True, creator_id=1, site_id=public_site.site_id)
        db.add(media_public)
        db.flush()
        db.add(
            MediaCollection(
                media_id=media_public.media_id,
                collection_id=public_col.collection_id,
                added_by=1,
            )
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/site-map-items",
            params={"project_id": project.project_id},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["count"] == 1
        assert len(data["markers"]) == 1
        marker = data["markers"][0]
        assert marker["site_id"] == public_site.site_id
        assert marker["media_count"] == 1
        # default map endpoint is lightweight: geometry contains point only
        assert isinstance(marker["geometry"], dict)
        assert set(marker["geometry"].keys()) == {"point"}
        # center is computed from resolved coordinates
        assert data["center"] is not None

    def test_map_sites_support_iucn_filters(
        self, client: TestClient, db: Session
    ) -> None:
        """Authenticated users can filter map sites by realm/biome/group."""
        user, headers = create_user_with_headers(db, client)
        project = create_test_project(db)
        private_col = create_test_collection(db, public_access=False)
        link_collection_to_project(db, project.project_id, private_col.collection_id)
        grant_permission(db, user.user_id, "site", "read", collection_id=private_col.collection_id)
        grant_permission(db, user.user_id, "audio", "read", collection_id=private_col.collection_id)
        grant_permission(db, user.user_id, "project", "read", project_id=project.project_id)

        db.add(IucnGet(iucn_get_id=9001, pid=0, name="Realm-X", level=1))
        db.add(IucnGet(iucn_get_id=9002, pid=9001, name="Biome-X", level=2))
        db.add(IucnGet(iucn_get_id=9003, pid=9002, name="Group-X", level=3))
        db.commit()

        filtered_site = create_test_site(
            db,
            private_col.collection_id,
            name="Filtered Site",
            longitude=118.2,
            latitude=26.3,
            realm_id=9001,
            biome_id=9002,
            functional_type_id=9003,
        )
        create_test_site(
            db,
            private_col.collection_id,
            name="Other Site",
            longitude=118.4,
            latitude=26.5,
        )
        self._create_site_media(
            db,
            site_id=filtered_site.site_id,
            collection_id=private_col.collection_id,
            creator_id=user.user_id,
        )

        r = client.get(
            f"{settings.API_V1_STR}/site-map-items",
            headers=headers,
            params={"project_id": project.project_id, "realm_id": 9001},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        markers = data["markers"]
        assert len(markers) == 1
        assert markers[0]["site_id"] == filtered_site.site_id
        assert markers[0]["realm_id"] == 9001
        assert markers[0]["biome_id"] == 9002
        assert markers[0]["functional_type_id"] == 9003

        empty_res = client.get(
            f"{settings.API_V1_STR}/site-map-items",
            headers=headers,
            params={"project_id": project.project_id, "realm_id": 999999},
        )
        assert empty_res.status_code == 200
        empty_data = empty_res.json()["data"]
        assert empty_data["count"] == 0
        assert empty_data["markers"] == []

    def test_map_sites_default_keeps_media_count_without_polygon_geometry(
        self, client: TestClient, db: Session
    ) -> None:
        """Default map mode should keep media_count while omitting polygon geometry payload."""
        project = create_test_project(db)
        public_col = create_test_collection(db, public_access=True)
        link_collection_to_project(db, project.project_id, public_col.collection_id)
        site = create_test_site(
            db,
            public_col.collection_id,
            name="Light Mode Site",
            longitude=113.2,
            latitude=22.1,
        )
        self._create_site_media(
            db,
            site_id=site.site_id,
            collection_id=public_col.collection_id,
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/site-map-items",
            params={"project_id": project.project_id},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["count"] == 1
        marker = data["markers"][0]
        assert set(marker.keys()) == {
            "site_id",
            "name",
            "geometry",
            "media_count",
            "realm_id",
            "realm_name",
            "biome_id",
            "functional_type_id",
        }
        assert marker["site_id"] == site.site_id
        assert marker["name"] == "Light Mode Site"
        assert marker["media_count"] == 1
        assert set(marker["geometry"].keys()) == {"point"}
        assert marker["geometry"]["point"] is not None

    def test_map_site_geometries_on_demand_returns_requested_sites(
        self, client: TestClient, db: Session
    ) -> None:
        """Geometry endpoint should return polygon payload for requested visible site IDs."""
        project = create_test_project(db)
        public_col = create_test_collection(db, public_access=True)
        link_collection_to_project(db, project.project_id, public_col.collection_id)
        site_a = create_test_site(
            db, public_col.collection_id, name="Geom Site A", longitude=118.1, latitude=26.2
        )
        site_b = create_test_site(
            db, public_col.collection_id, name="Geom Site B", longitude=118.3, latitude=26.4
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/site-map-items/geometries",
            params={
                "project_id": project.project_id,
                "site_ids": f"{site_a.site_id},{site_b.site_id}",
            },
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["count"] == 2
        returned_site_ids = [item["site_id"] for item in data["items"]]
        assert returned_site_ids == sorted([site_a.site_id, site_b.site_id])
        first_geometry = data["items"][0]["geometry"]
        assert "point" in first_geometry
        assert "location" in first_geometry
        assert "location_iho" in first_geometry

    def test_map_site_geometries_invalid_site_ids(
        self, client: TestClient, db: Session
    ) -> None:
        """Geometry endpoint should reject invalid site_ids format."""
        project = create_test_project(db)
        r = client.get(
            f"{settings.API_V1_STR}/site-map-items/geometries",
            params={"project_id": project.project_id, "site_ids": "1,a,3"},
        )
        assert r.status_code == 400
        payload = r.json()
        error_text = str(payload.get("detail") or payload.get("message") or payload)
        assert "site_ids" in error_text

    def test_map_sites_collection_scope_media_count(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """collection_id narrows marker/media_count to that collection scope."""
        project = create_test_project(db)
        col_a = create_test_collection(db, public_access=True, name="Map Scope A")
        col_b = create_test_collection(db, public_access=True, name="Map Scope B")
        link_collection_to_project(db, project.project_id, col_a.collection_id)
        link_collection_to_project(db, project.project_id, col_b.collection_id)

        site = create_test_site(
            db,
            col_a.collection_id,
            name="Scoped Media Site",
            longitude=101.1,
            latitude=21.1,
        )
        db.add(SiteCollection(site_id=site.site_id, collection_id=col_b.collection_id))
        db.flush()

        media_a = Media(media_type="audio", is_metadata=True, creator_id=1, site_id=site.site_id)
        media_b = Media(media_type="audio", is_metadata=True, creator_id=1, site_id=site.site_id)
        db.add(media_a)
        db.add(media_b)
        db.flush()
        db.add(MediaCollection(media_id=media_a.media_id, collection_id=col_a.collection_id, added_by=1))
        db.add(MediaCollection(media_id=media_b.media_id, collection_id=col_b.collection_id, added_by=1))
        db.commit()

        all_res = client.get(
            f"{settings.API_V1_STR}/site-map-items",
            headers=superuser_token_headers,
            params={"project_id": project.project_id},
        )
        assert all_res.status_code == 200
        all_data = all_res.json()["data"]
        all_markers = all_data["markers"]
        assert len(all_markers) == 1
        assert all_markers[0]["media_count"] == 2
        media_all = client.get(
            f"{settings.API_V1_STR}/media",
            headers=superuser_token_headers,
            params={"project_id": project.project_id, "site_id": site.site_id},
        )
        assert media_all.status_code == 200
        assert media_all.json()["page_info"]["total"] == 2

        only_a = client.get(
            f"{settings.API_V1_STR}/site-map-items",
            headers=superuser_token_headers,
            params={"project_id": project.project_id, "collection_id": col_a.collection_id},
        )
        assert only_a.status_code == 200
        data_a = only_a.json()["data"]
        markers_a = data_a["markers"]
        assert len(markers_a) == 1
        assert markers_a[0]["media_count"] == 1
        assert markers_a[0]["site_id"] == site.site_id
        media_only_a = client.get(
            f"{settings.API_V1_STR}/media",
            headers=superuser_token_headers,
            params={
                "project_id": project.project_id,
                "collection_id": col_a.collection_id,
                "site_id": site.site_id,
            },
        )
        assert media_only_a.status_code == 200
        assert media_only_a.json()["page_info"]["total"] == 1

        only_b = client.get(
            f"{settings.API_V1_STR}/site-map-items",
            headers=superuser_token_headers,
            params={"project_id": project.project_id, "collection_id": col_b.collection_id},
        )
        assert only_b.status_code == 200
        data_b = only_b.json()["data"]
        markers_b = data_b["markers"]
        assert len(markers_b) == 1
        assert markers_b[0]["media_count"] == 1
        assert markers_b[0]["site_id"] == site.site_id
        media_only_b = client.get(
            f"{settings.API_V1_STR}/media",
            headers=superuser_token_headers,
            params={
                "project_id": project.project_id,
                "collection_id": col_b.collection_id,
                "site_id": site.site_id,
            },
        )
        assert media_only_b.status_code == 200
        assert media_only_b.json()["page_info"]["total"] == 1

    def test_media_total_matches_map_media_count_across_project_collections(
        self, client: TestClient, db: Session
    ) -> None:
        """Media total and map media_count align for the same site scope."""
        user, headers = create_user_with_headers(db, client)
        project = create_test_project(db)
        col_a = create_test_collection(db, public_access=False, name="Aligned A")
        col_b = create_test_collection(db, public_access=False, name="Aligned B")
        link_collection_to_project(db, project.project_id, col_a.collection_id)
        link_collection_to_project(db, project.project_id, col_b.collection_id)
        grant_permission(db, user.user_id, "site", "read", collection_id=col_a.collection_id)
        grant_permission(db, user.user_id, "site", "read", collection_id=col_b.collection_id)
        grant_permission(db, user.user_id, "audio", "read", collection_id=col_a.collection_id)
        grant_permission(db, user.user_id, "audio", "read", collection_id=col_b.collection_id)

        site = create_test_site(
            db, col_a.collection_id, name="Aligned Site", longitude=110.0, latitude=20.0
        )
        db.add(SiteCollection(site_id=site.site_id, collection_id=col_b.collection_id))
        db.flush()
        self._create_site_media(db, site_id=site.site_id, collection_id=col_a.collection_id)
        self._create_site_media(db, site_id=site.site_id, collection_id=col_b.collection_id)
        db.commit()

        media_resp = client.get(
            f"{settings.API_V1_STR}/media",
            headers=headers,
            params={"project_id": project.project_id, "site_id": site.site_id},
        )
        assert media_resp.status_code == 200
        assert media_resp.json()["page_info"]["total"] == 2

        map_resp = client.get(
            f"{settings.API_V1_STR}/site-map-items",
            headers=headers,
            params={"project_id": project.project_id},
        )
        assert map_resp.status_code == 200
        map_data = map_resp.json()["data"]
        marker = next(
            m for m in map_data["markers"] if m["site_id"] == site.site_id
        )
        assert marker["media_count"] == 2

    def test_map_media_count_deduplicates_media_linked_to_multiple_project_collections(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Project map counts a media item once even when linked to multiple project collections."""
        project = create_test_project(db)
        col_a = create_test_collection(db, public_access=True, name="Map Dedup A")
        col_b = create_test_collection(db, public_access=True, name="Map Dedup B")
        link_collection_to_project(db, project.project_id, col_a.collection_id)
        link_collection_to_project(db, project.project_id, col_b.collection_id)

        site = create_test_site(
            db,
            col_a.collection_id,
            name="Map Dedup Site",
            longitude=110.0,
            latitude=20.0,
        )
        db.add(SiteCollection(site_id=site.site_id, collection_id=col_b.collection_id))
        db.flush()
        media = self._create_site_media(
            db,
            site_id=site.site_id,
            collection_id=col_a.collection_id,
        )
        db.add(
            MediaCollection(
                media_id=media.media_id,
                collection_id=col_b.collection_id,
                added_by=1,
            )
        )
        db.commit()

        map_resp = client.get(
            f"{settings.API_V1_STR}/site-map-items",
            headers=superuser_token_headers,
            params={"project_id": project.project_id},
        )
        assert map_resp.status_code == 200
        marker = next(
            m for m in map_resp.json()["data"]["markers"]
            if m["site_id"] == site.site_id
        )
        assert marker["media_count"] == 1

    def test_media_project_scope_does_not_leak_via_accessible_external_collection(
        self, client: TestClient, db: Session
    ) -> None:
        """Media linked to an accessible external collection should not leak into project totals."""
        user, headers = create_user_with_headers(db, client)
        project = create_test_project(db)
        project_col = create_test_collection(db, public_access=False, name="Project Private")
        external_col = create_test_collection(db, public_access=False, name="External Private")
        link_collection_to_project(db, project.project_id, project_col.collection_id)
        grant_permission(db, user.user_id, "site", "read", collection_id=project_col.collection_id)
        grant_permission(db, user.user_id, "audio", "read", collection_id=external_col.collection_id)

        site = create_test_site(
            db, project_col.collection_id, name="Scoped Private Site", longitude=100.0, latitude=30.0
        )
        media = self._create_site_media(db, site_id=site.site_id, collection_id=project_col.collection_id)
        db.add(
            MediaCollection(
                media_id=media.media_id,
                collection_id=external_col.collection_id,
                added_by=user.user_id,
            )
        )
        db.commit()

        media_resp = client.get(
            f"{settings.API_V1_STR}/media",
            headers=headers,
            params={"project_id": project.project_id, "site_id": site.site_id},
        )
        assert media_resp.status_code == 200
        assert media_resp.json()["page_info"]["total"] == 0

        map_resp = client.get(
            f"{settings.API_V1_STR}/site-map-items",
            headers=headers,
            params={"project_id": project.project_id},
        )
        assert map_resp.status_code == 200
        map_data = map_resp.json()["data"]
        assert map_data["count"] == 0
        assert map_data["markers"] == []

    def test_map_marker_hidden_without_audio_read(
        self, client: TestClient, db: Session
    ) -> None:
        """Site markers should be hidden when the user lacks audio:read."""
        user, headers = create_user_with_headers(db, client)
        project = create_test_project(db)
        private_col = create_test_collection(db, public_access=False, name="Site Only Access")
        link_collection_to_project(db, project.project_id, private_col.collection_id)
        grant_permission(db, user.user_id, "site", "read", collection_id=private_col.collection_id)

        site = create_test_site(
            db, private_col.collection_id, name="Site Read Only", longitude=118.0, latitude=28.0
        )
        self._create_site_media(db, site_id=site.site_id, collection_id=private_col.collection_id)
        db.commit()

        map_resp = client.get(
            f"{settings.API_V1_STR}/site-map-items",
            headers=headers,
            params={"project_id": project.project_id},
        )
        assert map_resp.status_code == 200
        map_data = map_resp.json()["data"]
        assert map_data["count"] == 0
        assert map_data["markers"] == []

        media_resp = client.get(
            f"{settings.API_V1_STR}/media",
            headers=headers,
            params={"project_id": project.project_id, "site_id": site.site_id},
        )
        assert media_resp.status_code == 200
        assert media_resp.json()["page_info"]["total"] == 0

    def test_map_sites_exclude_sites_without_map_geometry(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Sites without full coordinates or stored geometry should be excluded from map endpoint."""
        project = create_test_project(db)
        collection = create_test_collection(db, public_access=True)
        link_collection_to_project(db, project.project_id, collection.collection_id)
        create_test_site(db, collection.collection_id, name="No Coordinates Site")
        partial_site = create_test_site(
            db, collection.collection_id, name="Longitude Only Site", longitude=110.5, latitude=21.5
        )
        partial_site.latitude = None
        db.add(partial_site)
        with_coords_site = create_test_site(
            db, collection.collection_id, name="With Coordinates Site", longitude=110.0, latitude=21.0
        )
        create_test_media(db, collection.collection_id, site_id=with_coords_site.site_id)
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/site-map-items",
            headers=superuser_token_headers,
            params={"project_id": project.project_id},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        site_ids = [marker["site_id"] for marker in data["markers"]]
        assert with_coords_site.site_id in site_ids
        assert partial_site.site_id not in site_ids

    def test_map_geometry_from_location_iho_fallback(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Map point falls back to location_iho center for IHO-only sites without manual coords."""
        project = create_test_project(db)
        collection = create_test_collection(db, public_access=True)
        link_collection_to_project(db, project.project_id, collection.collection_id)

        db.execute(text(
            "INSERT INTO iho_sea_area (id, name, geometry) VALUES "
            "(9901, 'FallbackSea', ST_Multi(ST_SetSRID(ST_MakeBox2D(ST_Point(50, 10), ST_Point(60, 20)), 4326)))"
        ))
        db.commit()

        payload = {
            "name": "IHO Only No Manual",
            "iho_id": 9901,
            "collection_id": collection.collection_id,
        }
        r = client.post(
            f"{settings.API_V1_STR}/sites",
            headers=superuser_token_headers,
            json=payload,
        )
        assert r.status_code == 201
        assert "created" in r.json()["message"].lower()
        # longitude/latitude remain NULL when not manually provided (no auto-fill from location_iho)
        created_site = db.exec(select(Site).where(Site.name == "IHO Only No Manual")).first()
        assert created_site.longitude is None
        assert created_site.latitude is None
        self._create_site_media(
            db,
            site_id=created_site.site_id,
            collection_id=collection.collection_id,
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/site-map-items",
            headers=superuser_token_headers,
            params={"project_id": project.project_id},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        markers = data["markers"]
        assert len(markers) == 1
        # default lightweight response only returns point
        geo = markers[0]["geometry"]
        assert geo is not None
        assert set(geo.keys()) == {"point"}
        assert geo["point"] == {"latitude": 15.0, "longitude": 55.0}

    def test_map_geometry_structure_with_explicit_coords(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Lightweight map geometry includes point only when explicit coordinates exist."""
        project = create_test_project(db)
        collection = create_test_collection(db, public_access=True)
        link_collection_to_project(db, project.project_id, collection.collection_id)
        point_only_site = create_test_site(
            db, collection.collection_id,
            name="Point Only Site", longitude=120.5, latitude=30.2,
        )
        self._create_site_media(
            db,
            site_id=point_only_site.site_id,
            collection_id=collection.collection_id,
        )

        r = client.get(
            f"{settings.API_V1_STR}/site-map-items",
            headers=superuser_token_headers,
            params={"project_id": project.project_id},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        marker = data["markers"][0]
        geo = marker["geometry"]
        assert set(geo.keys()) == {"point"}
        assert geo["point"] == {"latitude": 30.2, "longitude": 120.5}

    def test_map_geometry_structure_with_gadm_polygon(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Lightweight map geometry stays point-only even when GADM polygon exists."""
        project = create_test_project(db)
        collection = create_test_collection(db, public_access=True)
        link_collection_to_project(db, project.project_id, collection.collection_id)

        db.execute(text("DELETE FROM adm_2 WHERE \"GID_0\" = 'CHN'"))
        db.execute(text("DELETE FROM adm_1 WHERE \"GID_0\" = 'CHN'"))
        db.execute(text("DELETE FROM adm_0 WHERE \"GID_0\" = 'CHN'"))
        db.execute(text("""
            INSERT INTO adm_0 ("GID_0", "COUNTRY", geometry) VALUES
            ('CHN', 'China', ST_Multi(ST_SetSRID(ST_MakeBox2D(ST_Point(100, 10), ST_Point(140, 50)), 4326)))
            ON CONFLICT ("GID_0") DO NOTHING
        """))
        db.commit()

        payload = {
            "name": "GADM Polygon Geo Site",
            "gadm0_gid": "CHN",
            "collection_id": collection.collection_id,
        }
        r = client.post(
            f"{settings.API_V1_STR}/sites",
            headers=superuser_token_headers,
            json=payload,
        )
        assert r.status_code == 201
        created_site = db.exec(select(Site).where(Site.name == "GADM Polygon Geo Site")).first()
        self._create_site_media(
            db,
            site_id=created_site.site_id,
            collection_id=collection.collection_id,
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/site-map-items",
            headers=superuser_token_headers,
            params={"project_id": project.project_id},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        markers = data["markers"]
        assert len(markers) == 1
        geo = markers[0]["geometry"]
        assert set(geo.keys()) == {"point"}
        assert geo["point"] == {"latitude": 30.0, "longitude": 120.0}

    def test_map_geometry_structure_with_coords_and_iho(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Lightweight map geometry remains point-only when site has both coords and IHO."""
        project = create_test_project(db)
        collection = create_test_collection(db, public_access=True)
        link_collection_to_project(db, project.project_id, collection.collection_id)

        db.execute(text(
            "INSERT INTO iho_sea_area (id, name, geometry) VALUES "
            "(9910, 'ComboSea', ST_Multi(ST_SetSRID(ST_MakeBox2D(ST_Point(55, 5), ST_Point(65, 15)), 4326)))"
        ))
        db.commit()

        payload = {
            "name": "Coords and IHO Site",
            "longitude": 60.0,
            "latitude": 10.0,
            "iho_id": 9910,
            "collection_id": collection.collection_id,
        }
        r = client.post(
            f"{settings.API_V1_STR}/sites",
            headers=superuser_token_headers,
            json=payload,
        )
        assert r.status_code == 201
        created_site = db.exec(select(Site).where(Site.name == "Coords and IHO Site")).first()
        self._create_site_media(
            db,
            site_id=created_site.site_id,
            collection_id=collection.collection_id,
        )
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/site-map-items",
            headers=superuser_token_headers,
            params={"project_id": project.project_id},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        markers = data["markers"]
        assert len(markers) == 1
        geo = markers[0]["geometry"]
        assert set(geo.keys()) == {"point"}
        assert geo["point"] == {"latitude": 10.0, "longitude": 60.0}

    def test_map_sites_collection_not_in_project_returns_400(
        self, client: TestClient, db: Session
    ) -> None:
        """collection_id outside the project should be rejected."""
        project = create_test_project(db)
        in_project_col = create_test_collection(db, public_access=True)
        other_col = create_test_collection(db, public_access=True)
        link_collection_to_project(db, project.project_id, in_project_col.collection_id)

        r = client.get(
            f"{settings.API_V1_STR}/site-map-items",
            params={
                "project_id": project.project_id,
                "collection_id": other_col.collection_id,
            },
        )
        assert r.status_code == 400
        message = r.json().get("message")
        assert message is not None
        assert "collection_id does not belong" in str(message)

    def test_map_sites_false_when_accessible_sites_lack_map_geometry(
        self, client: TestClient, db: Session
    ) -> None:
        """Accessible sites without coordinates or geometry should not count as map sites."""
        project = create_test_project(db)
        public_col = create_test_collection(db, public_access=True)
        link_collection_to_project(db, project.project_id, public_col.collection_id)
        create_test_site(db, public_col.collection_id, name="Unmappable Public Site")

        r = client.get(
            f"{settings.API_V1_STR}/site-map-items",
            params={"project_id": project.project_id},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["count"] == 0
        assert data["markers"] == []

    def test_map_sites_media_type_filter(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """media_type filter should scope media_count to the requested type."""
        project = create_test_project(db)
        col = create_test_collection(db, public_access=True)
        link_collection_to_project(db, project.project_id, col.collection_id)

        site = create_test_site(
            db, col.collection_id, name="MT Filter Site", longitude=120.0, latitude=23.0,
        )

        # 2 audio media
        for _ in range(2):
            self._create_site_media(
                db, site_id=site.site_id, collection_id=col.collection_id, media_type="audio",
            )
        # 1 photo media (needs photo_setting for DB constraint)
        photo_setting = PhotoSetting()
        db.add(photo_setting)
        db.flush()
        photo_media = Media(
            media_type="photo", is_metadata=True, creator_id=1,
            site_id=site.site_id, photo_setting_id=photo_setting.photo_setting_id,
        )
        db.add(photo_media)
        db.flush()
        db.add(MediaCollection(
            media_id=photo_media.media_id, collection_id=col.collection_id, added_by=1,
        ))
        db.commit()

        # all (default): media_count == 3
        r_all = client.get(
            f"{settings.API_V1_STR}/site-map-items",
            headers=superuser_token_headers,
            params={"project_id": project.project_id, "media_type": "all"},
        )
        assert r_all.status_code == 200
        marker_all = r_all.json()["data"]["markers"][0]
        assert marker_all["media_count"] == 3

        # audio: media_count == 2
        r_audio = client.get(
            f"{settings.API_V1_STR}/site-map-items",
            headers=superuser_token_headers,
            params={"project_id": project.project_id, "media_type": "audio"},
        )
        assert r_audio.status_code == 200
        marker_audio = r_audio.json()["data"]["markers"][0]
        assert marker_audio["media_count"] == 2

        # photo: media_count == 1
        r_photo = client.get(
            f"{settings.API_V1_STR}/site-map-items",
            headers=superuser_token_headers,
            params={"project_id": project.project_id, "media_type": "photo"},
        )
        assert r_photo.status_code == 200
        marker_photo = r_photo.json()["data"]["markers"][0]
        assert marker_photo["media_count"] == 1


class TestSiteCreate:
    """Tests for POST /sites."""

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("latitude", -90.1),
            ("latitude", 90.1),
            ("longitude", -180.1),
            ("longitude", 180.1),
        ],
    )
    def test_create_site_rejects_out_of_range_coordinates(
        self,
        client: TestClient,
        superuser_token_headers: dict,
        db: Session,
        field: str,
        value: float,
    ) -> None:
        """Creating a site rejects coordinates outside WGS84 bounds."""
        collection = create_test_collection(db)
        payload = {
            "name": "Out of Range Site",
            "longitude": 120.0,
            "latitude": 30.0,
            "collection_id": collection.collection_id,
        }
        payload[field] = value

        response = client.post(
            f"{settings.API_V1_STR}/sites",
            headers=superuser_token_headers,
            json=payload,
        )

        assert response.status_code == 422

    @pytest.mark.parametrize(
        ("longitude", "latitude"),
        [(-180.0, -90.0), (180.0, 90.0)],
    )
    def test_create_site_accepts_coordinate_boundaries(
        self,
        client: TestClient,
        superuser_token_headers: dict,
        db: Session,
        longitude: float,
        latitude: float,
    ) -> None:
        """Creating a site accepts inclusive WGS84 coordinate boundaries."""
        collection = create_test_collection(db)
        response = client.post(
            f"{settings.API_V1_STR}/sites",
            headers=superuser_token_headers,
            json={
                "name": "Boundary Site",
                "longitude": longitude,
                "latitude": latitude,
                "collection_id": collection.collection_id,
            },
        )

        assert response.status_code == 201

    def test_create_site_with_collection_write(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Admin can create a site with collection_id."""
        collection = create_test_collection(db)
        payload = {
            "name": "New Test Site",
            "longitude": 116.3,
            "latitude": 39.9,
            "topography_m": 200.0,
            "gadm0_gid": "DFT",
            "collection_id": collection.collection_id,
        }
        r = client.post(
            f"{settings.API_V1_STR}/sites",
            headers=superuser_token_headers,
            json=payload,
        )
        assert r.status_code == 201
        assert "created" in r.json()["message"].lower()
        created_site = db.exec(select(Site).where(Site.name == "New Test Site")).first()
        assert created_site is not None
        site_col_ids = [sc.collection_id for sc in db.exec(select(SiteCollection).where(SiteCollection.site_id == created_site.site_id)).all()]
        assert collection.collection_id in site_col_ids
        assert created_site.creator_id is not None
        assert created_site.gadm0_gid == "DFT"

    def test_create_site_with_iho_only(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Site can be created with only IHO selected."""
        collection = create_test_collection(db)
        db.execute(text(
            "INSERT INTO iho_sea_area (id, name, geometry) VALUES "
            "(9900, 'IhoOnlySea', ST_SetSRID(ST_MakeBox2D(ST_Point(100, 10), ST_Point(110, 20)), 4326))"
        ))
        db.commit()

        payload = {
            "name": "IHO Only Site",
            "longitude": 1.0,
            "latitude": 2.0,
            "iho_id": 9900,
            "collection_id": collection.collection_id,
        }
        r = client.post(
            f"{settings.API_V1_STR}/sites",
            headers=superuser_token_headers,
            json=payload,
        )
        assert r.status_code == 201
        assert "created" in r.json()["message"].lower()
        created_site = db.exec(select(Site).where(Site.name == "IHO Only Site")).first()
        assert created_site.iho == "IhoOnlySea"
        assert created_site.gadm0 is None

    def test_create_site_with_project_id(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Site created with project_id binds to all project collections."""
        project = create_test_project(db)
        col1 = create_test_collection(db)
        col2 = create_test_collection(db)
        link_collection_to_project(db, project.project_id, col1.collection_id)
        link_collection_to_project(db, project.project_id, col2.collection_id)

        payload = {
            "name": "Project Site",
            "longitude": 10.0,
            "latitude": 20.0,
            "gadm0_gid": "DFT",
            "project_id": project.project_id,
        }
        r = client.post(
            f"{settings.API_V1_STR}/sites",
            headers=superuser_token_headers,
            json=payload,
        )
        assert r.status_code == 201
        assert "created" in r.json()["message"].lower()
        created_site = db.exec(select(Site).where(Site.name == "Project Site")).first()
        site_col_ids = [sc.collection_id for sc in db.exec(select(SiteCollection).where(SiteCollection.site_id == created_site.site_id)).all()]
        assert col1.collection_id in site_col_ids
        assert col2.collection_id in site_col_ids
        linked_project_ids = [
            sp.project_id
            for sp in db.exec(select(SiteProject).where(SiteProject.site_id == created_site.site_id)).all()
        ]
        assert linked_project_ids == [project.project_id]

    def test_create_site_with_gadm_names(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Site can be created with GADM names instead of IDs."""
        collection = create_test_collection(db)
        # Note: We use coordinates that we know might map to some GADM in a real DB or test DB 
        # But here we mainly test that the API accepts the strings.
        payload = {
            "name": "GADM Name Site",
            "longitude": 116.3,
            "latitude": 39.9,
            "collection_id": collection.collection_id,
            "gadm0_gid": "CHN",
            "gadm1_gid": "CHN.1_1",
            "gadm2_gid": "CHN.1.1_1",
        }
        db.execute(text("""
            INSERT INTO adm_0 ("GID_0", "COUNTRY", geometry)
            VALUES ('CHN', 'China', ST_Multi(ST_GeomFromText('POLYGON((100 10, 140 10, 140 50, 100 50, 100 10))', 4326)))
            ON CONFLICT ("GID_0") DO NOTHING
        """))
        db.execute(text("""
            INSERT INTO adm_1 ("GID_1", "GID_0", "NAME_1", geometry)
            VALUES ('CHN.1_1', 'CHN', 'Beijing', ST_Multi(ST_GeomFromText('POLYGON((110 20, 130 20, 130 40, 110 40, 110 20))', 4326)))
            ON CONFLICT ("GID_1") DO NOTHING
        """))
        db.execute(text("""
            INSERT INTO adm_2 ("GID_2", "GID_1", "GID_0", "NAME_2", geometry)
            VALUES ('CHN.1.1_1', 'CHN.1_1', 'CHN', 'Dongcheng', ST_Multi(ST_GeomFromText('POLYGON((116 39, 117 39, 117 40, 116 40, 116 39))', 4326)))
            ON CONFLICT ("GID_2") DO NOTHING
        """))
        db.commit()

        r = client.post(
            f"{settings.API_V1_STR}/sites",
            headers=superuser_token_headers,
            json=payload,
        )
        assert r.status_code == 201
        assert "created" in r.json()["message"].lower()
        created_site = db.exec(select(Site).where(Site.name == "GADM Name Site")).first()
        assert created_site.gadm0 == "China"
        assert created_site.gadm2 == "Dongcheng"
        assert created_site.gadm2_gid == "CHN.1.1_1"

    def test_create_site_uses_lowest_selected_gadm_level(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Verify location uses the lowest selected GADM level."""
        collection = create_test_collection(db)

        db.execute(text("DELETE FROM adm_2 WHERE \"GID_0\" = 'CHN'"))
        db.execute(text("DELETE FROM adm_1 WHERE \"GID_0\" = 'CHN'"))
        db.execute(text("DELETE FROM adm_0 WHERE \"GID_0\" = 'CHN'"))
        db.execute(text("""
            INSERT INTO adm_0 ("GID_0", "COUNTRY", geometry) VALUES
            ('CHN', 'China', ST_Multi(ST_SetSRID(ST_MakeBox2D(ST_Point(100, 10), ST_Point(140, 50)), 4326)))
        """))
        db.execute(text("""
            INSERT INTO adm_1 ("GID_1", "GID_0", "NAME_1", geometry) VALUES
            ('CHN.1_1', 'CHN', 'Beijing', ST_Multi(ST_SetSRID(ST_MakeBox2D(ST_Point(110, 20), ST_Point(130, 40)), 4326)))
        """))
        db.execute(text("""
            INSERT INTO adm_2 ("GID_2", "GID_1", "GID_0", "NAME_2", geometry) VALUES
            ('CHN.1.1_1', 'CHN.1_1', 'CHN', 'Dongcheng', ST_Multi(ST_SetSRID(ST_MakeBox2D(ST_Point(116, 39), ST_Point(117, 40)), 4326)))
        """))
        db.commit()

        payload = {
            "name": "Lowest Level Site",
            "longitude": 116.3,
            "latitude": 39.9,
            "collection_id": collection.collection_id,
            "gadm0_gid": "CHN",
            "gadm1_gid": "CHN.1_1",
            "gadm2_gid": "CHN.1.1_1",
        }
        r = client.post(
            f"{settings.API_V1_STR}/sites",
            headers=superuser_token_headers,
            json=payload,
        )
        assert r.status_code == 201
        assert "created" in r.json()["message"].lower()
        created_site = db.exec(select(Site).where(Site.name == "Lowest Level Site")).first()
        assert created_site.gadm2 == "Dongcheng"
        assert created_site.gadm0 == "China"
        assert created_site.gadm1 == "Beijing"
        assert created_site.gadm2_gid == "CHN.1.1_1"

    def test_create_site_invalid_gadm_name(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Providing a GADM name that doesn't exist returns 400."""
        collection = create_test_collection(db)
        payload = {
            "name": "Invalid GADM",
            "longitude": 10.0,
            "latitude": 20.0,
            "collection_id": collection.collection_id,
            "gadm0_gid": "NON_EXISTENT_GID",
        }
        r = client.post(
            f"{settings.API_V1_STR}/sites",
            headers=superuser_token_headers,
            json=payload,
        )
        assert r.status_code == 400
        message = r.json().get("message")
        assert message is not None
        assert "Invalid GADM" in str(message)

    def test_create_site_without_gadm0_is_allowed_with_manual_coords(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Creating a site without GADM is valid when manual coordinates are provided."""
        collection = create_test_collection(db)
        payload = {
            "name": "Manual Without GADM",
            "longitude": 116.3,
            "latitude": 39.9,
            "collection_id": collection.collection_id,
        }
        r = client.post(
            f"{settings.API_V1_STR}/sites",
            headers=superuser_token_headers,
            json=payload,
        )
        assert r.status_code == 201

    def test_create_site_no_permission(
        self, client: TestClient, db: Session
    ) -> None:
        """User without collection:write gets 403."""
        _, headers = create_user_with_headers(db, client)
        collection = create_test_collection(db)
        payload = {
            "name": "Forbidden Site",
            "longitude": 10.0,
            "latitude": 20.0,
            "gadm0_gid": "DFT",
            "collection_id": collection.collection_id,
        }
        r = client.post(
            f"{settings.API_V1_STR}/sites",
            headers=headers,
            json=payload,
        )
        assert r.status_code == 403

    def test_create_site_unauthenticated(self, client: TestClient, db: Session) -> None:
        """Unauthenticated request is rejected."""
        collection = create_test_collection(db)
        payload = {
            "name": "Anon Site",
            "longitude": 10.0,
            "latitude": 20.0,
            "gadm0_gid": "DFT",
            "collection_id": collection.collection_id,
        }
        r = client.post(f"{settings.API_V1_STR}/sites", json=payload)
        assert r.status_code == 401

    def test_create_site_gadm_only_derives_coords_from_polygon(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Creating a site with GADM only (no manual coords) stores a simplified polygon
        in location; longitude/latitude remain NULL."""
        collection = create_test_collection(db)

        db.execute(text("DELETE FROM adm_2 WHERE \"GID_0\" = 'CHN'"))
        db.execute(text("DELETE FROM adm_1 WHERE \"GID_0\" = 'CHN'"))
        db.execute(text("DELETE FROM adm_0 WHERE \"GID_0\" = 'CHN'"))
        db.execute(text("""
            INSERT INTO adm_0 ("GID_0", "COUNTRY", geometry) VALUES
            ('CHN', 'China', ST_Multi(ST_SetSRID(ST_MakeBox2D(ST_Point(100, 10), ST_Point(140, 50)), 4326)))
            ON CONFLICT ("GID_0") DO NOTHING
        """))
        db.execute(text("""
            INSERT INTO adm_1 ("GID_1", "GID_0", "NAME_1", geometry) VALUES
            ('CHN.1_1', 'CHN', 'Beijing', ST_Multi(ST_SetSRID(ST_MakeBox2D(ST_Point(110, 20), ST_Point(130, 40)), 4326)))
            ON CONFLICT ("GID_1") DO NOTHING
        """))
        db.execute(text("""
            INSERT INTO adm_2 ("GID_2", "GID_1", "GID_0", "NAME_2", geometry) VALUES
            ('CHN.1.1_1', 'CHN.1_1', 'CHN', 'Dongcheng', ST_Multi(ST_SetSRID(ST_MakeBox2D(ST_Point(116, 39), ST_Point(117, 40)), 4326)))
            ON CONFLICT ("GID_2") DO NOTHING
        """))
        db.commit()

        payload = {
            "name": "GADM Only Site",
            "gadm0_gid": "CHN",
            "gadm2_gid": "CHN.1.1_1",
            "collection_id": collection.collection_id,
        }
        r = client.post(
            f"{settings.API_V1_STR}/sites",
            headers=superuser_token_headers,
            json=payload,
        )
        assert r.status_code == 201
        assert "created" in r.json()["message"].lower()
        created_site = db.exec(select(Site).where(Site.name == "GADM Only Site")).first()
        assert created_site.gadm2 == "Dongcheng"
        # longitude/latitude remain NULL when not manually provided (no auto-fill from GADM polygon)
        assert created_site.longitude is None
        assert created_site.latitude is None

    def test_create_site_iho_only_no_manual_coords(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Creating a site with IHO only (no manual coords) stores a simplified polygon
        in location_iho, clears location; longitude/latitude remain NULL."""
        collection = create_test_collection(db)
        db.execute(text(
            "INSERT INTO iho_sea_area (id, name, geometry) VALUES "
            "(9902, 'TestSea', ST_Multi(ST_SetSRID(ST_MakeBox2D(ST_Point(70, 10), ST_Point(80, 20)), 4326)))"
        ))
        db.commit()

        payload = {
            "name": "IHO No Manual Site",
            "iho_id": 9902,
            "collection_id": collection.collection_id,
        }
        r = client.post(
            f"{settings.API_V1_STR}/sites",
            headers=superuser_token_headers,
            json=payload,
        )
        assert r.status_code == 201
        assert "created" in r.json()["message"].lower()
        created_site = db.exec(select(Site).where(Site.name == "IHO No Manual Site")).first()
        assert created_site.iho == "TestSea"
        # longitude/latitude remain NULL when not manually provided (no auto-fill from location_iho)
        assert created_site.longitude is None
        assert created_site.latitude is None

def test_list_sites_supports_fuzzy_text_filters(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    ensure_default_gadm(db)
    realm = IucnGet(iucn_get_id=39001, pid=0, name="Temperate Realm", level=1)
    biome = IucnGet(iucn_get_id=39002, pid=39001, name="Moist Biome", level=2)
    functional_type = IucnGet(iucn_get_id=39003, pid=39002, name="Forest Functional Type", level=3)
    db.add_all([realm, biome, functional_type])
    db.commit()
    db.refresh(realm)
    db.refresh(biome)
    db.refresh(functional_type)

    collection = create_test_collection(db, public_access=False)
    project_id = db.exec(
        select(ProjectCollection.project_id).where(ProjectCollection.collection_id == collection.collection_id)
    ).one()
    create_test_site(
        db,
        collection.collection_id,
        name="Fuzzy Site",
        gadm0="DefaultLand",
        gadm1="DefaultState",
        gadm2="DefaultCity",
        iho="Pacific Ocean",
        realm_id=realm.iucn_get_id,
        biome_id=biome.iucn_get_id,
        functional_type_id=functional_type.iucn_get_id,
    )

    response = client.get(
        f"{settings.API_V1_STR}/sites",
        params={
            "project_id": project_id,
            "gadm0": "faultl",
            "gadm1": "state",
            "gadm2": "city",
            "iho": "pacif",
            "realm_name": "temperate",
            "biome_name": "moist",
            "functional_type_name": "forest",
        },
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    assert response.json()["page_info"]["total"] == 1


class TestSiteList:
    """Tests for GET /sites."""

    def test_list_sites_requires_project_id(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        """Missing project_id returns 422."""
        r = client.get(f"{settings.API_V1_STR}/sites", headers=superuser_token_headers)
        assert r.status_code == 422

    def test_list_sites_admin_sees_all(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Admin can list all sites in a project."""
        project = create_test_project(db)
        collection = create_test_collection(db)
        link_collection_to_project(db, project.project_id, collection.collection_id)
        create_test_site(db, collection.collection_id)
        create_test_site(db, collection.collection_id)

        r = client.get(
            f"{settings.API_V1_STR}/sites",
            params={"project_id": project.project_id},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        page_info = r.json()["page_info"]
        assert page_info["total"] >= 2

    def test_list_sites_pagination(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Pagination works: page and page_size constrain results."""
        project = create_test_project(db)
        collection = create_test_collection(db)
        link_collection_to_project(db, project.project_id, collection.collection_id)
        for _ in range(5):
            create_test_site(db, collection.collection_id)

        r = client.get(
            f"{settings.API_V1_STR}/sites",
            params={"project_id": project.project_id, "page": 1, "page_size": 2},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        page_info = r.json()["page_info"]
        assert len(data) == 2
        assert page_info["total"] >= 5

    def test_list_sites_filter_by_name(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Name filter (fuzzy) returns only matching sites."""
        project = create_test_project(db)
        collection = create_test_collection(db)
        link_collection_to_project(db, project.project_id, collection.collection_id)
        create_test_site(db, collection.collection_id, name="Rainforest Alpha Station")
        create_test_site(db, collection.collection_id, name="Ocean Beta Monitor")

        r = client.get(
            f"{settings.API_V1_STR}/sites",
            params={"project_id": project.project_id, "name": "Rainforest"},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        names = [s["name"] for s in r.json()["data"]]
        assert all("Rainforest" in n for n in names)
        assert "Ocean Beta Monitor" not in names

    def test_list_sites_with_comprehensive_filters(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        project = create_test_project(db)
        collection = create_test_collection(db)
        link_collection_to_project(db, project.project_id, collection.collection_id)
        
        # Site 1
        s1 = create_test_site(
            db, collection.collection_id, 
            name="Filter Site 1", 
            latitude=10.0, 
            longitude=20.0,
            iho_id=1,
            realm_id=1,
            gadm0="CountryA",
            gadm0_gid="DFT",
        )
        s1.creation_date = datetime.now(UTC) - timedelta(days=10)
        db.add(s1)
        
        # Site 2
        s2 = create_test_site(
            db, collection.collection_id, 
            name="Filter Site 2", 
            latitude=30.0, 
            longitude=40.0,
            iho_id=2,
            realm_id=2,
            gadm0="CountryB",
        )
        s2.creation_date = datetime.now(UTC) - timedelta(days=2)
        db.add(s2)
        db.commit()
        
        # Filter by collection_id
        r = client.get(
            f"{settings.API_V1_STR}/sites",
            params={"project_id": project.project_id, "collection_id": collection.collection_id},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        assert len(r.json()["data"]) >= 2
        
        # Filter by latitude min/max
        r = client.get(
            f"{settings.API_V1_STR}/sites",
            params={"project_id": project.project_id, "latitude": "25.0,35.0"},
            headers=superuser_token_headers,
        )
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["site_id"] == s2.site_id
        
        # Filter by longitude min/max
        r = client.get(
            f"{settings.API_V1_STR}/sites",
            params={"project_id": project.project_id, "longitude": "15.0,25.0"},
            headers=superuser_token_headers,
        )
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["site_id"] == s1.site_id
        
        # Filter by gadm0_gid
        r = client.get(
            f"{settings.API_V1_STR}/sites",
            params={"project_id": project.project_id, "gadm0_gid": "DFT"},
            headers=superuser_token_headers,
        )
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["site_id"] == s1.site_id

        # Filter by realm_id
        r = client.get(
            f"{settings.API_V1_STR}/sites",
            params={"project_id": project.project_id, "realm_id": 2},
            headers=superuser_token_headers,
        )
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["site_id"] == s2.site_id

        # Filter by creator_id
        r = client.get(
            f"{settings.API_V1_STR}/sites",
            params={"project_id": project.project_id, "creator_id": 1},
            headers=superuser_token_headers,
        )
        data = r.json()["data"]
        assert len(data) >= 2
        
        # Filter by creation_date_from
        from_dt = (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=5)).isoformat()
        r = client.get(
            f"{settings.API_V1_STR}/sites",
            params={"project_id": project.project_id, "creation_date_from": from_dt},
            headers=superuser_token_headers,
        )
        data = r.json()["data"]
        assert len(data) >= 1
        assert any(s["site_id"] == s2.site_id for s in data)
        
        # Filter by creation_date_to
        to_dt = (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=5)).isoformat()
        r = client.get(
            f"{settings.API_V1_STR}/sites",
            params={"project_id": project.project_id, "creation_date_to": to_dt},
            headers=superuser_token_headers,
        )
        data = r.json()["data"]
        assert len(data) >= 1
        assert any(s["site_id"] == s1.site_id for s in data)

    def test_list_sites_user_permission_filter(
        self, client: TestClient, db: Session
    ) -> None:
        """Regular user only sees sites in their accessible collections."""
        user, headers = create_user_with_headers(db, client)

        project = create_test_project(db)
        col_accessible = create_test_collection(db)
        col_private = create_test_collection(db)
        link_collection_to_project(db, project.project_id, col_accessible.collection_id)
        link_collection_to_project(db, project.project_id, col_private.collection_id)

        grant_permission(db, user.user_id, "site", "read",
                         collection_id=col_accessible.collection_id)
        # Also need project:read as required by permission system convention
        grant_permission(db, user.user_id, "project", "read",
                         project_id=project.project_id)

        site_visible = create_test_site(db, col_accessible.collection_id,
                                        name="Visible Site")
        site_hidden = create_test_site(db, col_private.collection_id,
                                       name="Hidden Site")

        r = client.get(
            f"{settings.API_V1_STR}/sites",
            params={"project_id": project.project_id},
            headers=headers,
        )
        assert r.status_code == 200
        names = [s["name"] for s in r.json()["data"]]
        assert site_visible.name in names
        assert site_hidden.name not in names

    def test_list_sites_unauthenticated(self, client: TestClient, db: Session) -> None:
        """Unauthenticated request is rejected."""
        r = client.get(
            f"{settings.API_V1_STR}/sites",
            params={"project_id": 1},
        )
        assert r.status_code == 401

    def test_list_sites_filter_by_site_id(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Filter by exact site_id returns only the matching site."""
        project = create_test_project(db)
        collection = create_test_collection(db)
        link_collection_to_project(db, project.project_id, collection.collection_id)

        s1 = create_test_site(db, collection.collection_id, name="SiteID A")
        s2 = create_test_site(db, collection.collection_id, name="SiteID B")

        p_id = project.project_id

        # Filter by s1's site_id: only s1 returned
        r = client.get(
            f"{settings.API_V1_STR}/sites",
            params={"project_id": p_id, "site_id": s1.site_id},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["site_id"] == s1.site_id

        # Non-existent site_id: empty result
        r = client.get(
            f"{settings.API_V1_STR}/sites",
            params={"project_id": p_id, "site_id": 999999},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        assert len(r.json()["data"]) == 0

        # Confirm s2 is found when filtering by its own id
        r = client.get(
            f"{settings.API_V1_STR}/sites",
            params={"project_id": p_id, "site_id": s2.site_id},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        assert r.json()["data"][0]["site_id"] == s2.site_id

    def test_list_sites_filter_by_uuid(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Filter by exact uuid returns only the matching site."""
        project = create_test_project(db)
        collection = create_test_collection(db)
        link_collection_to_project(db, project.project_id, collection.collection_id)

        s1 = create_test_site(db, collection.collection_id, name="UUID Site A")
        s2 = create_test_site(db, collection.collection_id, name="UUID Site B")

        p_id = project.project_id

        r = client.get(
            f"{settings.API_V1_STR}/sites",
            params={"project_id": p_id, "uuid": str(s1.uuid)},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["site_id"] == s1.site_id

        # s2's uuid should not match
        r = client.get(
            f"{settings.API_V1_STR}/sites",
            params={"project_id": p_id, "uuid": str(s2.uuid)},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        assert r.json()["data"][0]["site_id"] == s2.site_id

    def test_list_sites_order_by_latitude(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """order_by=latitude returns 200 and results in correct order."""
        project = create_test_project(db)
        collection = create_test_collection(db)
        link_collection_to_project(db, project.project_id, collection.collection_id)

        s_low = create_test_site(db, collection.collection_id, name="Low Lat", latitude=10.0, longitude=100.0)
        s_high = create_test_site(db, collection.collection_id, name="High Lat", latitude=50.0, longitude=100.0)

        p_id = project.project_id

        r = client.get(
            f"{settings.API_V1_STR}/sites",
            params={"project_id": p_id, "order_by": "latitude", "order_dir": "asc"},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        site_ids = [d["site_id"] for d in data]
        assert site_ids.index(s_low.site_id) < site_ids.index(s_high.site_id)

        # desc order reverses the result
        r = client.get(
            f"{settings.API_V1_STR}/sites",
            params={"project_id": p_id, "order_by": "latitude", "order_dir": "desc"},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        site_ids = [d["site_id"] for d in data]
        assert site_ids.index(s_high.site_id) < site_ids.index(s_low.site_id)



class TestSiteDetail:
    """Tests for GET /sites/{site_id}."""

    def test_get_site_admin(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Admin can get any site detail."""
        collection = create_test_collection(db)
        site = create_test_site(db, collection.collection_id)

        r = client.get(
            f"{settings.API_V1_STR}/sites/{site.site_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["site_id"] == site.site_id
        assert data["name"] == site.name

    def test_get_site_not_found(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        """Non-existent site returns 404."""
        r = client.get(
            f"{settings.API_V1_STR}/sites/99999999",
            headers=superuser_token_headers,
        )
        assert r.status_code == 404

    def test_get_site_no_permission(
        self, client: TestClient, db: Session
    ) -> None:
        """User without read permission on the site's collection gets 403."""
        _, headers = create_user_with_headers(db, client)
        collection = create_test_collection(db)
        site = create_test_site(db, collection.collection_id)

        r = client.get(
            f"{settings.API_V1_STR}/sites/{site.site_id}",
            headers=headers,
        )
        assert r.status_code == 403

    def test_get_site_with_read_permission(
        self, client: TestClient, db: Session
    ) -> None:
        """User with site:read permission can get site detail."""
        user, headers = create_user_with_headers(db, client)
        collection = create_test_collection(db)
        site = create_test_site(db, collection.collection_id)
        grant_permission(db, user.user_id, "site", "read",
                         collection_id=collection.collection_id)
        project_id = db.exec(
            select(ProjectCollection.project_id).where(
                ProjectCollection.collection_id == collection.collection_id
            )
        ).first()

        r = client.get(
            f"{settings.API_V1_STR}/sites/{site.site_id}",
            headers=headers,
            params={"project_id": project_id},
        )
        assert r.status_code == 200

    def test_get_site_returns_coordinates(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Site detail includes longitude and latitude when explicitly provided."""
        collection = create_test_collection(db)
        site = create_test_site(db, collection.collection_id, longitude=116.3, latitude=39.9)

        r = client.get(
            f"{settings.API_V1_STR}/sites/{site.site_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["longitude"] == 116.3
        assert data["latitude"] == 39.9



class TestSiteUpdate:
    """Tests for PATCH /sites/{site_id}."""

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("latitude", -90.1),
            ("latitude", 90.1),
            ("longitude", -180.1),
            ("longitude", 180.1),
        ],
    )
    def test_update_site_rejects_out_of_range_coordinates(
        self,
        client: TestClient,
        superuser_token_headers: dict,
        db: Session,
        field: str,
        value: float,
    ) -> None:
        """Updating a site rejects coordinates outside WGS84 bounds."""
        collection = create_test_collection(db)
        site = create_test_site(db, collection.collection_id, longitude=120.0, latitude=30.0)

        response = client.patch(
            f"{settings.API_V1_STR}/sites/{site.site_id}",
            headers=superuser_token_headers,
            json={field: value},
        )

        assert response.status_code == 422

    @pytest.mark.parametrize(
        ("longitude", "latitude"),
        [(-180.0, -90.0), (180.0, 90.0)],
    )
    def test_update_site_accepts_coordinate_boundaries(
        self,
        client: TestClient,
        superuser_token_headers: dict,
        db: Session,
        longitude: float,
        latitude: float,
    ) -> None:
        """Updating a site accepts inclusive WGS84 coordinate boundaries."""
        collection = create_test_collection(db)
        site = create_test_site(db, collection.collection_id, longitude=120.0, latitude=30.0)

        response = client.patch(
            f"{settings.API_V1_STR}/sites/{site.site_id}",
            headers=superuser_token_headers,
            json={"longitude": longitude, "latitude": latitude},
        )

        assert response.status_code == 200
        db.refresh(site)
        assert site.longitude == longitude
        assert site.latitude == latitude

    def test_update_site_admin(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Admin can update any site."""
        collection = create_test_collection(db)
        site = create_test_site(db, collection.collection_id)

        r = client.patch(
            f"{settings.API_V1_STR}/sites/{site.site_id}",
            headers=superuser_token_headers,
            json={"name": "Updated Site Name", "topography_m": 999.9, "gadm0_gid": "DFT"},
        )
        assert r.status_code == 200
        assert "updated" in r.json()["message"].lower()
        db.refresh(site)
        assert site.name == "Updated Site Name"
        assert site.topography_m == 999.9

    def test_update_site_with_write_permission(
        self, client: TestClient, db: Session
    ) -> None:
        """User with site:write permission can update the site."""
        user, headers = create_user_with_headers(db, client)
        collection = create_test_collection(db)
        site = create_test_site(db, collection.collection_id)
        grant_permission(db, user.user_id, "site", "write",
                         collection_id=collection.collection_id)
        project_id = db.exec(
            select(ProjectCollection.project_id).where(
                ProjectCollection.collection_id == collection.collection_id
            )
        ).first()

        r = client.patch(
            f"{settings.API_V1_STR}/sites/{site.site_id}",
            headers=headers,
            params={"project_id": project_id},
            json={"name": "Manager Updated", "gadm0_gid": "DFT"},
        )
        assert r.status_code == 200
        db.refresh(site)
        assert site.name == "Manager Updated"

    def test_update_site_no_permission(
        self, client: TestClient, db: Session
    ) -> None:
        """User without site:write gets 403."""
        _, headers = create_user_with_headers(db, client)
        collection = create_test_collection(db)
        site = create_test_site(db, collection.collection_id)

        r = client.patch(
            f"{settings.API_V1_STR}/sites/{site.site_id}",
            headers=headers,
            json={"name": "Forbidden Update", "gadm0_gid": "DFT"},
        )
        assert r.status_code == 403

    def test_update_site_not_found(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        """Updating non-existent site returns 404."""
        r = client.patch(
            f"{settings.API_V1_STR}/sites/99999999",
            headers=superuser_token_headers,
            json={"name": "Ghost", "gadm0_gid": "DFT"},
        )
        assert r.status_code == 404

    def test_update_site_without_geo_fields_is_allowed(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Updating a site without geo fields should still work."""
        collection = create_test_collection(db)
        site = create_test_site(db, collection.collection_id)
        r = client.patch(
            f"{settings.API_V1_STR}/sites/{site.site_id}",
            headers=superuser_token_headers,
            json={"name": "Missing GADM0"},
        )
        assert r.status_code == 200



class TestSiteDelete:
    """Tests for DELETE /sites/{site_id}."""

    def test_delete_site_admin(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Admin can delete any site."""
        collection = create_test_collection(db)
        site = create_test_site(db, collection.collection_id)
        site_id = site.site_id

        r = client.delete(
            f"{settings.API_V1_STR}/sites/{site_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        assert db.get(Site, site_id) is None

    def test_delete_site_by_creator_without_site_write_fails(
        self, client: TestClient, db: Session
    ) -> None:
        """Creator without site:write cannot delete their own site."""
        user, headers = create_user_with_headers(db, client)
        collection = create_test_collection(db)
        site = create_test_site(db, collection.collection_id, creator_id=user.user_id)
        site_id = site.site_id

        r = client.delete(
            f"{settings.API_V1_STR}/sites/{site_id}",
            headers=headers,
        )
        assert r.status_code == 403
        assert db.get(Site, site_id) is not None

    def test_delete_site_with_site_write_permission(
        self, client: TestClient, db: Session
    ) -> None:
        """User with site:write can delete a site."""
        user, headers = create_user_with_headers(db, client)
        collection = create_test_collection(db)
        project = create_test_project(db)
        link_collection_to_project(db, project.project_id, collection.collection_id)
        site = create_test_site(db, collection.collection_id)
        site_id = site.site_id
        grant_permission(
            db,
            user.user_id,
            "site",
            "write",
            collection_id=collection.collection_id,
            project_id=project.project_id,
        )

        r = client.delete(
            f"{settings.API_V1_STR}/sites/{site_id}?project_id={project.project_id}",
            headers=headers,
        )
        assert r.status_code == 200
        assert db.get(Site, site_id) is None

    def test_delete_site_removes_site_project_links(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Deleting a site also removes link rows from site_collection and site_project."""
        project = create_test_project(db)
        collection = create_test_collection(db)
        link_collection_to_project(db, project.project_id, collection.collection_id)
        site = create_test_site(db, collection.collection_id)

        db.add(SiteProject(site_id=site.site_id, project_id=project.project_id))
        db.commit()

        r = client.delete(
            f"{settings.API_V1_STR}/sites/{site.site_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        assert db.get(Site, site.site_id) is None
        assert db.exec(
            select(SiteCollection).where(SiteCollection.site_id == site.site_id)
        ).all() == []
        assert db.exec(
            select(SiteProject).where(SiteProject.site_id == site.site_id)
        ).all() == []

    def test_delete_site_by_non_creator(
        self, client: TestClient, db: Session
    ) -> None:
        """Non-creator non-admin gets 403."""
        _, headers = create_user_with_headers(db, client)
        collection = create_test_collection(db)
        site = create_test_site(db, collection.collection_id, creator_id=1)

        r = client.delete(
            f"{settings.API_V1_STR}/sites/{site.site_id}",
            headers=headers,
        )
        assert r.status_code == 403

    def test_delete_site_with_media_returns_409(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Cannot delete a site that still has associated media (409 Conflict)."""

        collection = create_test_collection(db)
        site = create_test_site(db, collection.collection_id)

        # Create a minimal media record linked to this site via raw SQL
        db.execute(text(
            "INSERT INTO media (site_id, creator_id, media_type, is_metadata) "
            "VALUES (:site_id, 1, 'audio', TRUE)"
        ), {"site_id": site.site_id})
        db.commit()

        r = client.delete(
            f"{settings.API_V1_STR}/sites/{site.site_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 409

    def test_delete_site_not_found(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        """Deleting non-existent site returns 404."""
        r = client.delete(
            f"{settings.API_V1_STR}/sites/99999999",
            headers=superuser_token_headers,
        )
        assert r.status_code == 404



class TestSiteExport:
    """Tests for GET /sites/exports."""

    def test_export_sites_admin(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Admin can export sites as CSV."""
        project = create_test_project(db)
        collection = create_test_collection(db)
        link_collection_to_project(db, project.project_id, collection.collection_id)
        create_test_site(db, collection.collection_id)

        r = client.get(
            f"{settings.API_V1_STR}/sites/exports",
            params={"project_id": project.project_id},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")
        assert r.headers.get("content-disposition") == (
            'attachment; filename="sites.csv"; '
            "filename*=UTF-8''sites.csv"
        )
        # CSV headers should be present
        content = r.text
        header = read_csv_header(content)
        assert header == [
            "site_id", "uuid", "name", "latitude", "longitude", "topography_m",
            "freshwater_depth_m", "gadm0", "gadm1", "gadm2", "iho", "realm_name",
            "biome_name", "functional_type_name", "creator_name", "creator_id", "creation_date",
        ]

    def test_export_sites_unauthenticated(self, client: TestClient, db: Session) -> None:
        """Unauthenticated export is rejected."""
        r = client.get(
            f"{settings.API_V1_STR}/sites/exports",
            params={"project_id": 1},
        )
        assert r.status_code == 401

    def test_export_sites_missing_project_id(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        """Missing project_id returns 422."""
        r = client.get(
            f"{settings.API_V1_STR}/sites/exports",
            headers=superuser_token_headers,
        )
        assert r.status_code == 422

    def test_export_sites_non_admin(
        self, client: TestClient, db: Session
    ) -> None:
        """Regular user can export sites within their accessible collections."""
        user, headers = create_user_with_headers(db, client)
        project = create_test_project(db)
        collection = create_test_collection(db, public_access=False)
        link_collection_to_project(db, project.project_id, collection.collection_id)
        grant_permission(db, user.user_id, "site", "read", collection_id=collection.collection_id)
        grant_permission(db, user.user_id, "project", "read", project_id=project.project_id)
        create_test_site(db, collection.collection_id, name="User Accessible Site")

        r = client.get(
            f"{settings.API_V1_STR}/sites/exports",
            params={"project_id": project.project_id},
            headers=headers,
        )
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")
        assert "User Accessible Site" in r.text

    def test_export_sites_empty_result(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Export with no matching sites returns an empty CSV."""
        project = create_test_project(db)
        collection = create_test_collection(db)
        link_collection_to_project(db, project.project_id, collection.collection_id)

        r = client.get(
            f"{settings.API_V1_STR}/sites/exports",
            params={"project_id": project.project_id},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        header = read_csv_header(r.text)
        assert header == [
            "site_id", "uuid", "name", "latitude", "longitude", "topography_m",
            "freshwater_depth_m", "gadm0", "gadm1", "gadm2", "iho", "realm_name",
            "biome_name", "functional_type_name", "creator_name", "creator_id", "creation_date",
        ]



class TestSiteLinkOptions:
    """Tests for GET /sites/{site_id}/collection-options."""

    def test_get_site_link_options_admin_returns_grouped_and_selected(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Admin gets grouped options plus selected project/collection IDs."""
        current_project = create_test_project(db, name="Current Link Project")
        other_project = create_test_project(db, name="Other Link Project")

        current_collection = create_test_collection(db, name="Current Link Collection")
        other_collection = create_test_collection(db, name="Other Link Collection")
        unassigned_collection = create_test_collection(
            db, name="Unassigned Link Collection", auto_link_project=False
        )

        link_collection_to_project(db, current_project.project_id, current_collection.collection_id)
        link_collection_to_project(db, other_project.project_id, other_collection.collection_id)

        site = create_test_site(db, current_collection.collection_id, name="Link Option Site")
        db.add(SiteCollection(site_id=site.site_id, collection_id=other_collection.collection_id))
        db.add(SiteProject(site_id=site.site_id, project_id=current_project.project_id))
        db.commit()

        r = client.get(
            f"{settings.API_V1_STR}/sites/{site.site_id}/collection-options",
            headers=superuser_token_headers,
            params={"project_id": current_project.project_id},
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload["code"] == 0
        data = payload["data"]

        assert sorted(data["selected_collection_ids"]) == sorted(
            [current_collection.collection_id, other_collection.collection_id]
        )
        assert data["selected_project_ids"] == [current_project.project_id]

        assert data["current_project"]["project_id"] == current_project.project_id
        current_ids = {c["collection_id"] for c in data["current_project"]["collections"]}
        assert current_collection.collection_id in current_ids
        assert any(
            c["collection_id"] == current_collection.collection_id and c["selected"] is True
            for c in data["current_project"]["collections"]
        )

        other_ids = {
            c["collection_id"] for p in data["other_projects"] for c in p["collections"]
        }
        assert other_collection.collection_id in other_ids
        assert any(
            c["collection_id"] == other_collection.collection_id and c["selected"] is True
            for p in data["other_projects"]
            for c in p["collections"]
        )

        unassigned_ids = {c["collection_id"] for c in data["unassigned_collections"]}
        assert unassigned_collection.collection_id in unassigned_ids

    def test_get_site_link_options_no_project_write_permission(
        self, client: TestClient, db: Session
    ) -> None:
        """User without write permission on target project gets 403."""
        user, headers = create_user_with_headers(db, client)
        project = create_test_project(db)
        collection = create_test_collection(db)
        link_collection_to_project(db, project.project_id, collection.collection_id)
        site = create_test_site(db, collection.collection_id, creator_id=user.user_id)

        grant_permission(db, user.user_id, "site", "read", collection_id=collection.collection_id)

        r = client.get(
            f"{settings.API_V1_STR}/sites/{site.site_id}/collection-options",
            headers=headers,
            params={"project_id": project.project_id},
        )
        assert r.status_code == 403

    def test_get_site_link_options_project_not_found(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Unknown project_id returns 404."""
        collection = create_test_collection(db)
        site = create_test_site(db, collection.collection_id)

        r = client.get(
            f"{settings.API_V1_STR}/sites/{site.site_id}/collection-options",
            headers=superuser_token_headers,
            params={"project_id": 999999},
        )
        assert r.status_code == 404


class TestSyncSiteCollections:
    """Tests for PUT /sites/{site_id}/collections."""

    def test_sync_collections_admin(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Admin can sync a site's collection bindings."""
        col1 = create_test_collection(db)
        col2 = create_test_collection(db)
        site = create_test_site(db, col1.collection_id)

        r = client.put(
            f"{settings.API_V1_STR}/sites/{site.site_id}/collections",
            headers=superuser_token_headers,
            json={"collection_ids": [col1.collection_id, col2.collection_id]},
        )
        assert r.status_code == 200
        assert r.json()["data"] is None
        ids = db.exec(
            select(SiteCollection.collection_id).where(SiteCollection.site_id == site.site_id)
        ).all()
        assert sorted(ids) == sorted([col1.collection_id, col2.collection_id])

    def test_sync_collections_and_projects_admin(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Admin can sync a site's project-level and collection-level links together."""
        project = create_test_project(db)
        col1 = create_test_collection(db)
        col2 = create_test_collection(db)
        link_collection_to_project(db, project.project_id, col1.collection_id)
        link_collection_to_project(db, project.project_id, col2.collection_id)
        site = create_test_site(db, col1.collection_id)

        r = client.put(
            f"{settings.API_V1_STR}/sites/{site.site_id}/collections",
            headers=superuser_token_headers,
            json={
                "project_ids": [project.project_id],
                "collection_ids": [col1.collection_id, col2.collection_id],
            },
        )
        assert r.status_code == 200
        site_project_ids = db.exec(
            select(SiteProject.project_id).where(SiteProject.site_id == site.site_id)
        ).all()
        assert site_project_ids == [project.project_id]

    def test_sync_collections_site_not_found(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Returns 404 when site does not exist."""
        r = client.put(
            f"{settings.API_V1_STR}/sites/999999/collections",
            headers=superuser_token_headers,
            json={"collection_ids": []},
        )
        assert r.status_code == 404

    def test_sync_collections_no_permission(
        self, client: TestClient, db: Session
    ) -> None:
        """User without site:write permission gets 403."""
        _, headers = create_user_with_headers(db, client)
        collection = create_test_collection(db)
        site = create_test_site(db, collection.collection_id, creator_id=1)

        r = client.put(
            f"{settings.API_V1_STR}/sites/{site.site_id}/collections",
            headers=headers,
            json={"collection_ids": [collection.collection_id]},
        )
        assert r.status_code == 403

    def test_sync_collections_unauthenticated(
        self, client: TestClient, db: Session
    ) -> None:
        """Unauthenticated request is rejected."""
        collection = create_test_collection(db)
        site = create_test_site(db, collection.collection_id)

        r = client.put(
            f"{settings.API_V1_STR}/sites/{site.site_id}/collections",
            json={"collection_ids": [collection.collection_id]},
        )
        assert r.status_code == 401



class TestSiteGeoEdgeCases:
    """Tests for geo validation and IHO/GADM update paths."""

    def test_create_site_lat_without_lon_returns_400(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Providing only latitude (without longitude) should return 400."""
        collection = create_test_collection(db)
        payload = {
            "name": "Half Coord Site",
            "latitude": 39.9,
            "gadm0_gid": "DFT",
            "collection_id": collection.collection_id,
        }
        r = client.post(
            f"{settings.API_V1_STR}/sites",
            headers=superuser_token_headers,
            json=payload,
        )
        assert r.status_code in (400, 422)

    def test_create_site_gadm1_without_gadm0_returns_400(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Providing gadm1_gid without gadm0_gid should return 400."""
        collection = create_test_collection(db)
        payload = {
            "name": "No GADM0",
            "gadm1_gid": "DFT.1_1",
            "collection_id": collection.collection_id,
        }
        r = client.post(
            f"{settings.API_V1_STR}/sites",
            headers=superuser_token_headers,
            json=payload,
        )
        assert r.status_code in (400, 422)

    def test_create_site_invalid_iho_id_returns_400(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Using a non-existent IHO id should return 400."""
        collection = create_test_collection(db)
        payload = {
            "name": "Bad IHO Site",
            "iho_id": 99999,
            "collection_id": collection.collection_id,
        }
        r = client.post(
            f"{settings.API_V1_STR}/sites",
            headers=superuser_token_headers,
            json=payload,
        )
        assert r.status_code == 400

    def test_update_site_change_to_iho_only(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Updating a site to IHO-only stores a simplified IHO polygon in location_iho
        and clears location."""
        collection = create_test_collection(db)
        site = create_test_site(db, collection.collection_id, longitude=10.0, latitude=20.0)
        db.execute(text(
            "INSERT INTO iho_sea_area (id, name, geometry) VALUES "
            "(9903, 'UpdateSea', ST_Multi(ST_SetSRID(ST_MakeBox2D(ST_Point(30, 5), ST_Point(40, 15)), 4326)))"
        ))
        db.commit()

        r = client.patch(
            f"{settings.API_V1_STR}/sites/{site.site_id}",
            headers=superuser_token_headers,
            json={"iho_id": 9903, "longitude": None, "latitude": None},
        )
        assert r.status_code == 200
        assert "updated" in r.json()["message"].lower()
        db.refresh(site)
        assert site.iho == "UpdateSea"
        # longitude/latitude become NULL when explicitly cleared (no auto-fill from location_iho)
        assert site.longitude is None
        assert site.latitude is None

    def test_list_sites_filter_by_biome_and_topography(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """List can be filtered by biome_id, functional_type_id, topography, and freshwater depth."""
        project = create_test_project(db)
        collection = create_test_collection(db)
        link_collection_to_project(db, project.project_id, collection.collection_id)

        db.add(IucnGet(iucn_get_id=8001, pid=0, name="Realm-Z", level=1))
        db.add(IucnGet(iucn_get_id=8002, pid=8001, name="Biome-Z", level=2))
        db.add(IucnGet(iucn_get_id=8003, pid=8002, name="FT-Z", level=3))
        db.commit()

        s1 = create_test_site(
            db, collection.collection_id,
            name="Topo Site", longitude=10.0, latitude=10.0,
            realm_id=8001, biome_id=8002, functional_type_id=8003,
            topography_m=500.0, freshwater_depth_m=10.0,
        )
        create_test_site(
            db, collection.collection_id,
            name="Other Site", longitude=20.0, latitude=20.0,
            topography_m=100.0, freshwater_depth_m=1.0,
        )

        # Filter by biome_id
        r = client.get(
            f"{settings.API_V1_STR}/sites",
            params={"project_id": project.project_id, "biome_id": 8002},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        ids = [s["site_id"] for s in r.json()["data"]]
        assert s1.site_id in ids

        # Filter by functional_type_id
        r = client.get(
            f"{settings.API_V1_STR}/sites",
            params={"project_id": project.project_id, "functional_type_id": 8003},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        ids = [s["site_id"] for s in r.json()["data"]]
        assert s1.site_id in ids

        # Filter by topography range
        r = client.get(
            f"{settings.API_V1_STR}/sites",
            params={"project_id": project.project_id, "topography_m": "400.0,600.0"},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        ids = [s["site_id"] for s in r.json()["data"]]
        assert s1.site_id in ids

        # Filter by freshwater depth range
        r = client.get(
            f"{settings.API_V1_STR}/sites",
            params={"project_id": project.project_id, "freshwater_depth_m": "8.0,15.0"},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        ids = [s["site_id"] for s in r.json()["data"]]
        assert s1.site_id in ids

    def test_create_site_with_functional_type_id_resolves_parent_ids(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Creating a site with functional_type_id automatically resolves realm_id and biome_id."""
        collection = create_test_collection(db)

        db.add(IucnGet(iucn_get_id=7001, pid=0, name="Realm-W", level=1))
        db.add(IucnGet(iucn_get_id=7002, pid=7001, name="Biome-W", level=2))
        db.add(IucnGet(iucn_get_id=7003, pid=7002, name="FT-W", level=3))
        db.commit()

        payload = {
            "name": "FT Auto-resolve Site",
            "longitude": 10.0,
            "latitude": 20.0,
            "gadm0_gid": "DFT",
            "collection_id": collection.collection_id,
            "functional_type_id": 7003,
        }
        r = client.post(
            f"{settings.API_V1_STR}/sites",
            headers=superuser_token_headers,
            json=payload,
        )
        assert r.status_code == 201
        assert "created" in r.json()["message"].lower()
        created_site = db.exec(select(Site).where(Site.name == "FT Auto-resolve Site")).first()
        assert created_site.functional_type_id == 7003
        assert created_site.biome_id == 7002
        assert created_site.realm_id == 7001

    def test_create_site_with_biome_id_resolves_realm_id(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Creating a site with biome_id automatically resolves realm_id."""
        collection = create_test_collection(db)

        db.add(IucnGet(iucn_get_id=6001, pid=0, name="Realm-V", level=1))
        db.add(IucnGet(iucn_get_id=6002, pid=6001, name="Biome-V", level=2))
        db.commit()

        payload = {
            "name": "Biome Auto-resolve Site",
            "longitude": 10.0,
            "latitude": 20.0,
            "gadm0_gid": "DFT",
            "collection_id": collection.collection_id,
            "biome_id": 6002,
        }
        r = client.post(
            f"{settings.API_V1_STR}/sites",
            headers=superuser_token_headers,
            json=payload,
        )
        assert r.status_code == 201
        assert "created" in r.json()["message"].lower()
        created_site = db.exec(select(Site).where(Site.name == "Biome Auto-resolve Site")).first()
        assert created_site.biome_id == 6002
        assert created_site.realm_id == 6001

    def test_create_site_with_invalid_functional_type_id_returns_422(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Providing a non-existent or wrong-level functional_type_id returns 422."""
        collection = create_test_collection(db)
        payload = {
            "name": "Invalid FT Site",
            "longitude": 10.0,
            "latitude": 20.0,
            "gadm0_gid": "DFT",
            "collection_id": collection.collection_id,
            "functional_type_id": 999999,
        }
        r = client.post(
            f"{settings.API_V1_STR}/sites",
            headers=superuser_token_headers,
            json=payload,
        )
        assert r.status_code == 422

    def test_create_site_via_project_no_project_permission_returns_403(
        self, client: TestClient, db: Session
    ) -> None:
        """User without collection:write on a project's collections gets 403."""
        _, headers = create_user_with_headers(db, client)
        project = create_test_project(db)
        col = create_test_collection(db)
        link_collection_to_project(db, project.project_id, col.collection_id)

        payload = {
            "name": "No Project Perm Site",
            "longitude": 10.0,
            "latitude": 20.0,
            "gadm0_gid": "DFT",
            "project_id": project.project_id,
        }
        r = client.post(
            f"{settings.API_V1_STR}/sites",
            headers=headers,
            json=payload,
        )
        assert r.status_code == 403

    def test_create_site_with_realm_id_only(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Creating a site with realm_id only sets realm_id and leaves biome/ft as None."""
        collection = create_test_collection(db)

        db.add(IucnGet(iucn_get_id=5001, pid=0, name="Realm-U", level=1))
        db.commit()

        payload = {
            "name": "Realm Only Site",
            "longitude": 10.0,
            "latitude": 20.0,
            "gadm0_gid": "DFT",
            "collection_id": collection.collection_id,
            "realm_id": 5001,
        }
        r = client.post(
            f"{settings.API_V1_STR}/sites",
            headers=superuser_token_headers,
            json=payload,
        )
        assert r.status_code == 201
        assert "created" in r.json()["message"].lower()
        created_site = db.exec(select(Site).where(Site.name == "Realm Only Site")).first()
        assert created_site.realm_id == 5001
        assert created_site.biome_id is None
        assert created_site.functional_type_id is None

    def test_create_site_project_has_no_collections_returns_404(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Creating a site via project_id when the project has no collections returns 404."""
        project = create_test_project(db)

        payload = {
            "name": "Empty Project Site",
            "longitude": 10.0,
            "latitude": 20.0,
            "gadm0_gid": "DFT",
            "project_id": project.project_id,
        }
        r = client.post(
            f"{settings.API_V1_STR}/sites",
            headers=superuser_token_headers,
            json=payload,
        )
        assert r.status_code == 404

    def test_map_empty_when_no_accessible_sites(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Map endpoint returns empty response when no accessible sites exist."""
        project = create_test_project(db)
        collection = create_test_collection(db)
        link_collection_to_project(db, project.project_id, collection.collection_id)

        r = client.get(
            f"{settings.API_V1_STR}/site-map-items",
            headers=superuser_token_headers,
            params={"project_id": project.project_id},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["count"] == 0
        assert data["markers"] == []
        assert data["center"] is None

    def test_create_site_gadm1_only_derives_coords_from_adm1_polygon(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Creating a site with gadm0+gadm1 (no gadm2) stores adm_1 simplified polygon in location."""
        collection = create_test_collection(db)

        db.execute(text("DELETE FROM adm_2 WHERE \"GID_0\" = 'CHN'"))
        db.execute(text("DELETE FROM adm_1 WHERE \"GID_0\" = 'CHN'"))
        db.execute(text("DELETE FROM adm_0 WHERE \"GID_0\" = 'CHN'"))
        db.execute(text("""
            INSERT INTO adm_0 ("GID_0", "COUNTRY", geometry) VALUES
            ('CHN', 'China', ST_Multi(ST_SetSRID(ST_MakeBox2D(ST_Point(100, 10), ST_Point(140, 50)), 4326)))
            ON CONFLICT ("GID_0") DO NOTHING
        """))
        db.execute(text("""
            INSERT INTO adm_1 ("GID_1", "GID_0", "NAME_1", geometry) VALUES
            ('CHN.1_1', 'CHN', 'Beijing', ST_Multi(ST_SetSRID(ST_MakeBox2D(ST_Point(110, 20), ST_Point(130, 40)), 4326)))
            ON CONFLICT ("GID_1") DO NOTHING
        """))
        db.commit()

        payload = {
            "name": "ADM1 Only Site",
            "gadm0_gid": "CHN",
            "gadm1_gid": "CHN.1_1",
            "collection_id": collection.collection_id,
        }
        r = client.post(
            f"{settings.API_V1_STR}/sites",
            headers=superuser_token_headers,
            json=payload,
        )
        assert r.status_code == 201
        assert "created" in r.json()["message"].lower()
        created_site = db.exec(select(Site).where(Site.name == "ADM1 Only Site")).first()
        assert created_site.gadm1 == "Beijing"
        # longitude/latitude remain NULL when not manually provided (no auto-fill from GADM polygon)
        assert created_site.longitude is None
        assert created_site.latitude is None

    def test_map_project_with_no_collections_returns_empty(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Map returns empty when project has no linked collections."""
        project = create_test_project(db)

        r = client.get(
            f"{settings.API_V1_STR}/site-map-items",
            headers=superuser_token_headers,
            params={"project_id": project.project_id},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["count"] == 0
        assert data["markers"] == []

    def test_map_biome_and_functional_type_filters(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Map supports filtering by biome_id and functional_type_id."""
        project = create_test_project(db)
        collection = create_test_collection(db, public_access=True)
        link_collection_to_project(db, project.project_id, collection.collection_id)

        db.add(IucnGet(iucn_get_id=4001, pid=0, name="Realm-M", level=1))
        db.add(IucnGet(iucn_get_id=4002, pid=4001, name="Biome-M", level=2))
        db.add(IucnGet(iucn_get_id=4003, pid=4002, name="FT-M", level=3))
        db.commit()

        target = create_test_site(
            db, collection.collection_id,
            name="Map Biome Site", longitude=50.0, latitude=5.0,
            biome_id=4002, functional_type_id=4003,
        )
        create_test_media(db, collection.collection_id, site_id=target.site_id)
        create_test_site(
            db, collection.collection_id,
            name="Other Map Site", longitude=51.0, latitude=6.0,
        )

        r = client.get(
            f"{settings.API_V1_STR}/site-map-items",
            headers=superuser_token_headers,
            params={"project_id": project.project_id, "biome_id": 4002},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        ids = [m["site_id"] for m in data["markers"]]
        assert target.site_id in ids
        assert len(ids) == 1

        r = client.get(
            f"{settings.API_V1_STR}/site-map-items",
            headers=superuser_token_headers,
            params={"project_id": project.project_id, "functional_type_id": 4003},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        ids = [m["site_id"] for m in data["markers"]]
        assert target.site_id in ids
        assert len(ids) == 1

    def test_map_zero_filters_null_iucn_levels(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Zero filters null values while preserving real parent filters."""
        project = create_test_project(db)
        collection = create_test_collection(db, public_access=True)
        link_collection_to_project(db, project.project_id, collection.collection_id)

        db.add_all([
            IucnGet(iucn_get_id=4101, pid=0, name="Realm-Z", level=1),
            IucnGet(iucn_get_id=4102, pid=4101, name="Biome-Z", level=2),
            IucnGet(iucn_get_id=4103, pid=4102, name="Group-Z", level=3),
        ])
        db.commit()

        no_realm = create_test_site(
            db, collection.collection_id,
            name="No Realm", longitude=60.0, latitude=10.0,
        )
        no_biome = create_test_site(
            db, collection.collection_id,
            name="No Biome", longitude=61.0, latitude=11.0, realm_id=4101,
        )
        no_group = create_test_site(
            db, collection.collection_id,
            name="No Group", longitude=62.0, latitude=12.0, realm_id=4101, biome_id=4102,
        )
        complete = create_test_site(
            db, collection.collection_id,
            name="Complete IUCN", longitude=63.0, latitude=13.0,
            realm_id=4101, biome_id=4102, functional_type_id=4103,
        )
        for site in (no_realm, no_biome, no_group, complete):
            create_test_media(db, collection.collection_id, site_id=site.site_id)

        cases = [
            ({"realm_id": 0}, no_realm.site_id),
            ({"realm_id": 4101, "biome_id": 0}, no_biome.site_id),
            ({"biome_id": 4102, "functional_type_id": 0}, no_group.site_id),
        ]
        for filters, expected_site_id in cases:
            response = client.get(
                f"{settings.API_V1_STR}/site-map-items",
                headers=superuser_token_headers,
                params={"project_id": project.project_id, **filters},
            )
            assert response.status_code == 200
            assert [m["site_id"] for m in response.json()["data"]["markers"]] == [expected_site_id]

    def test_list_sites_filter_by_iho_id_gadm1_gadm2_and_asc_order(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """List supports filtering by iho_id, gadm1_gid, gadm2_gid and ascending sort order."""
        project = create_test_project(db)
        collection = create_test_collection(db)
        link_collection_to_project(db, project.project_id, collection.collection_id)

        db.execute(text(
            "INSERT INTO iho_sea_area (id, name, geometry) VALUES "
            "(9904, 'FilterSea', ST_Multi(ST_SetSRID(ST_MakeBox2D(ST_Point(10, 5), ST_Point(20, 15)), 4326)))"
        ))
        db.commit()

        s1 = create_test_site(
            db, collection.collection_id,
            name="IHO Filter Site", longitude=15.0, latitude=10.0,
            iho="FilterSea",
            gadm0="TestLand",
            gadm1="TestProvince",
            gadm2="TestCity",
            gadm0_gid="DFT",
            gadm1_gid="DFT.1_1",
            gadm2_gid="DFT.1.1_1",
        )
        create_test_site(
            db, collection.collection_id,
            name="No IHO Site", longitude=30.0, latitude=20.0,
        )

        # Filter by iho_id
        r = client.get(
            f"{settings.API_V1_STR}/sites",
            params={"project_id": project.project_id, "iho_id": 9904},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        ids = [s["site_id"] for s in r.json()["data"]]
        assert s1.site_id in ids

        # Filter by gadm1_gid
        r = client.get(
            f"{settings.API_V1_STR}/sites",
            params={"project_id": project.project_id, "gadm1_gid": "DFT.1_1"},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        ids = [s["site_id"] for s in r.json()["data"]]
        assert s1.site_id in ids

        # Filter by gadm2_gid
        r = client.get(
            f"{settings.API_V1_STR}/sites",
            params={"project_id": project.project_id, "gadm2_gid": "DFT.1.1_1"},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        ids = [s["site_id"] for s in r.json()["data"]]
        assert s1.site_id in ids

        # Ascending sort order
        r = client.get(
            f"{settings.API_V1_STR}/sites",
            params={"project_id": project.project_id, "order_dir": "asc", "order_by": "name"},
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        names = [s["name"] for s in r.json()["data"]]
        assert names == sorted(names)

    def test_create_site_with_invalid_biome_id_returns_422(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Providing a non-existent or wrong-level biome_id returns 422."""
        collection = create_test_collection(db)
        payload = {
            "name": "Invalid Biome Site",
            "longitude": 10.0,
            "latitude": 20.0,
            "gadm0_gid": "DFT",
            "collection_id": collection.collection_id,
            "biome_id": 999999,
        }
        r = client.post(
            f"{settings.API_V1_STR}/sites",
            headers=superuser_token_headers,
            json=payload,
        )
        assert r.status_code == 422

    def test_create_site_with_invalid_realm_id_returns_422(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Providing a non-existent or wrong-level realm_id returns 422."""
        collection = create_test_collection(db)
        payload = {
            "name": "Invalid Realm Site",
            "longitude": 10.0,
            "latitude": 20.0,
            "gadm0_gid": "DFT",
            "collection_id": collection.collection_id,
            "realm_id": 999999,
        }
        r = client.post(
            f"{settings.API_V1_STR}/sites",
            headers=superuser_token_headers,
            json=payload,
        )
        assert r.status_code == 422

    def test_update_site_with_gadm1_gid(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Updating a site with gadm1_gid normalizes and stores the value."""
        collection = create_test_collection(db)
        site = create_test_site(db, collection.collection_id, longitude=10.0, latitude=20.0)

        r = client.patch(
            f"{settings.API_V1_STR}/sites/{site.site_id}",
            headers=superuser_token_headers,
            json={"gadm0_gid": "DFT", "gadm1_gid": "DFT.1_1"},
        )
        assert r.status_code == 200
        assert "updated" in r.json()["message"].lower()
        db.refresh(site)
        assert site.gadm1_gid == "DFT.1_1"

    def test_update_site_manual_plus_iho(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Updating a site with both manual coords and iho_id sets location as manual point
        and location_iho as the IHO polygon."""
        collection = create_test_collection(db)
        site = create_test_site(db, collection.collection_id, longitude=10.0, latitude=20.0)
        db.execute(text(
            "INSERT INTO iho_sea_area (id, name, geometry) VALUES "
            "(9905, 'ManualIHOSea', ST_Multi(ST_SetSRID(ST_MakeBox2D(ST_Point(50, 5), ST_Point(60, 15)), 4326)))"
        ))
        db.commit()

        r = client.patch(
            f"{settings.API_V1_STR}/sites/{site.site_id}",
            headers=superuser_token_headers,
            json={"longitude": 55.0, "latitude": 10.0, "iho_id": 9905, "gadm0_gid": "DFT"},
        )
        assert r.status_code == 200
        assert "updated" in r.json()["message"].lower()
        db.refresh(site)
        assert site.longitude == 55.0
        assert site.latitude == 10.0
        assert site.iho == "ManualIHOSea"
