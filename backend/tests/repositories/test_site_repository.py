"""Unit tests for SiteRepository with new geo priority rules."""
import pytest
from sqlalchemy import text
from sqlmodel import Session

from app.core.exceptions import AppValidationError
from app.models import Collection, Role, User
from app.repositories.site_repository import site_repository
from app.schemas.site import SiteCreate, SiteUpdate


def _get_iho_point(db: Session, site_id: int) -> tuple[float | None, float | None]:
    row = db.execute(
        text(
            """
            SELECT
                ST_X(ST_PointOnSurface(location_iho)),
                ST_Y(ST_PointOnSurface(location_iho))
            FROM site
            WHERE site_id = :id AND location_iho IS NOT NULL
            """
        ),
        {"id": site_id},
    ).first()
    return (row[0], row[1]) if row else (None, None)


@pytest.fixture
def test_setup(db: Session):
    """Seed minimal user/collection and geo tables for site tests."""
    role = Role(name="Site Repo Role")
    db.add(role)
    db.flush()

    user = User(
        username="site_repo_user",
        name="Site Repo User",
        email="site_repo_user@example.com",
        role_id=role.role_id,
        password="p",
    )
    db.add(user)
    db.flush()

    collection = Collection(name="Site Repo Collection", creator_id=user.user_id)
    db.add(collection)
    db.flush()

    db.execute(text("""
        CREATE TABLE IF NOT EXISTS adm_0 (
            "GID_0" VARCHAR(20) PRIMARY KEY,
            "COUNTRY" VARCHAR(255) NOT NULL,
            geometry geometry(MULTIPOLYGON, 4326)
        )
    """))
    db.execute(text("""
        ALTER TABLE site
        ADD COLUMN IF NOT EXISTS location_iho geometry(POINT, 4326)
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
    db.flush()

    db.execute(text("""
        INSERT INTO adm_0 ("GID_0", "COUNTRY", geometry)
        VALUES ('TST', 'TestLand', ST_Multi(ST_GeomFromText('POLYGON((100 10, 120 10, 120 30, 100 30, 100 10))', 4326)))
        ON CONFLICT ("GID_0") DO NOTHING
    """))
    db.execute(text("""
        INSERT INTO adm_1 ("GID_1", "GID_0", "NAME_1", geometry)
        VALUES ('TST.1_1', 'TST', 'TestState', ST_Multi(ST_GeomFromText('POLYGON((102 12, 118 12, 118 28, 102 28, 102 12))', 4326)))
        ON CONFLICT ("GID_1") DO NOTHING
    """))
    db.execute(text("""
        INSERT INTO adm_2 ("GID_2", "GID_1", "GID_0", "NAME_2", geometry)
        VALUES ('TST.1.1_1', 'TST.1_1', 'TST', 'TestCity', ST_Multi(ST_GeomFromText('POLYGON((105 15, 115 15, 115 25, 105 25, 105 15))', 4326)))
        ON CONFLICT ("GID_2") DO NOTHING
    """))
    db.execute(text("""
        INSERT INTO iho_sea_area (id, name, geometry)
        VALUES (9001, 'TestSea', ST_Multi(ST_GeomFromText('POLYGON((80 0, 140 0, 140 40, 80 40, 80 0))', 4326)))
        ON CONFLICT (id) DO NOTHING
    """))
    db.commit()

    return {"user": user, "collection": collection}


class TestSiteRepository:
    """Repository tests for site create/update priority rules."""

    def test_create_site_manual_only(self, db: Session, test_setup):
        user = test_setup["user"]
        col = test_setup["collection"]
        site = site_repository.create_site(
            db,
            data=SiteCreate(
                name="Manual Only",
                longitude=121.0,
                latitude=31.0,
                collection_id=col.collection_id,
            ),
            creator_id=user.user_id,
        )
        iho_lon, iho_lat = _get_iho_point(db, site.site_id)
        assert site.longitude == pytest.approx(121.0)
        assert site.latitude == pytest.approx(31.0)
        assert site.iho is None
        assert site.gadm0 is None
        assert iho_lon is None
        assert iho_lat is None

    def test_create_site_iho_only(self, db: Session, test_setup):
        user = test_setup["user"]
        col = test_setup["collection"]
        site = site_repository.create_site(
            db,
            data=SiteCreate(
                name="IHO Only",
                iho_id=9001,
                collection_id=col.collection_id,
            ),
            creator_id=user.user_id,
        )
        iho_lon, iho_lat = _get_iho_point(db, site.site_id)
        assert site.iho == "TestSea"
        # longitude/latitude remain NULL when not manually provided (no auto-fill from location_iho)
        assert site.longitude is None
        assert site.latitude is None
        assert iho_lon is not None
        assert iho_lat is not None

    def test_create_site_gadm_only(self, db: Session, test_setup):
        user = test_setup["user"]
        col = test_setup["collection"]
        site = site_repository.create_site(
            db,
            data=SiteCreate(
                name="GADM Only",
                gadm0_gid="TST",
                gadm1_gid="TST.1_1",
                gadm2_gid="TST.1.1_1",
                collection_id=col.collection_id,
            ),
            creator_id=user.user_id,
        )
        iho_lon, iho_lat = _get_iho_point(db, site.site_id)
        assert site.gadm0 == "TestLand"
        assert site.gadm1 == "TestState"
        assert site.gadm2 == "TestCity"
        assert site.gadm0_gid == "TST"
        assert site.gadm1_gid == "TST.1_1"
        assert site.gadm2_gid == "TST.1.1_1"
        # longitude/latitude remain NULL when not manually provided (no auto-fill from GADM polygon)
        assert site.longitude is None
        assert site.latitude is None
        assert iho_lon is None
        assert iho_lat is None

    def test_create_site_all_sources_prefers_manual(self, db: Session, test_setup):
        user = test_setup["user"]
        col = test_setup["collection"]
        site = site_repository.create_site(
            db,
            data=SiteCreate(
                name="All Sources",
                longitude=118.2,
                latitude=24.6,
                iho_id=9001,
                gadm0_gid="TST",
                gadm1_gid="TST.1_1",
                gadm2_gid="TST.1.1_1",
                collection_id=col.collection_id,
            ),
            creator_id=user.user_id,
        )
        iho_lon, iho_lat = _get_iho_point(db, site.site_id)
        assert site.longitude == pytest.approx(118.2)
        assert site.latitude == pytest.approx(24.6)
        assert site.iho == "TestSea"
        assert site.gadm2 == "TestCity"
        assert iho_lon is not None
        assert iho_lat is not None

    def test_update_site_keeps_manual_priority(self, db: Session, test_setup):
        user = test_setup["user"]
        col = test_setup["collection"]
        site = site_repository.create_site(
            db,
            data=SiteCreate(
                name="Update Priority",
                longitude=120.0,
                latitude=30.0,
                iho_id=9001,
                gadm0_gid="TST",
                collection_id=col.collection_id,
            ),
            creator_id=user.user_id,
        )
        updated = site_repository.update_site(
            db,
            db_obj=site,
            data=SiteUpdate(iho_id=9001, gadm0_gid="TST", gadm1_gid="TST.1_1"),
        )
        iho_lon, iho_lat = _get_iho_point(db, updated.site_id)
        assert updated.longitude == pytest.approx(120.0)
        assert updated.latitude == pytest.approx(30.0)
        assert updated.gadm1 == "TestState"
        assert iho_lon is not None
        assert iho_lat is not None

    def test_update_site_fallback_to_iho_when_manual_cleared(self, db: Session, test_setup):
        user = test_setup["user"]
        col = test_setup["collection"]
        site = site_repository.create_site(
            db,
            data=SiteCreate(
                name="Fallback IHO",
                longitude=119.5,
                latitude=29.5,
                iho_id=9001,
                collection_id=col.collection_id,
            ),
            creator_id=user.user_id,
        )
        updated = site_repository.update_site(
            db,
            db_obj=site,
            data=SiteUpdate(longitude=None, latitude=None, iho_id=9001),
        )
        iho_lon, iho_lat = _get_iho_point(db, updated.site_id)
        assert updated.iho == "TestSea"
        assert iho_lon is not None
        assert iho_lat is not None

    def test_create_site_invalid_gadm_raises(self, db: Session, test_setup):
        user = test_setup["user"]
        col = test_setup["collection"]
        with pytest.raises(AppValidationError):
            site_repository.create_site(
                db,
                data=SiteCreate(
                    name="Invalid GADM",
                    gadm0_gid="MISSING_GID",
                    collection_id=col.collection_id,
                ),
                creator_id=user.user_id,
            )
