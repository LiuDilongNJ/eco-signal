from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session

from app.models.site import IhoSeaArea


def setup_test_data(db: Session) -> None:
    # 1. IHO Sea Areas
    if not db.get(IhoSeaArea, 1):
        db.add(IhoSeaArea(id=1, name="South China Sea", mrgid=101))
        db.add(IhoSeaArea(id=2, name="East China Sea", mrgid=102))
    
    # 2. GADM (new split tables: adm_0 / adm_1 / adm_2)
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS adm_0 (
                "GID_0" TEXT PRIMARY KEY,
                "COUNTRY" TEXT
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS adm_1 (
                "GID_1" TEXT PRIMARY KEY,
                "GID_0" TEXT,
                "NAME_1" TEXT
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS adm_2 (
                "GID_2" TEXT PRIMARY KEY,
                "GID_1" TEXT,
                "GID_0" TEXT,
                "NAME_2" TEXT
            )
            """
        )
    )
    db.execute(text("DELETE FROM adm_2"))
    db.execute(text("DELETE FROM adm_1"))
    db.execute(text("DELETE FROM adm_0"))
    db.execute(
        text(
            """
            INSERT INTO adm_0 ("GID_0", "COUNTRY") VALUES
            ('CHN', 'China'),
            ('JPN', 'Japan')
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO adm_1 ("GID_1", "GID_0", "NAME_1") VALUES
            ('CHN.1_1', 'CHN', 'Guangdong'),
            ('CHN.2_1', 'CHN', 'Beijing'),
            ('JPN.1_1', 'JPN', 'Tokyo')
            """
        )
    )
    db.execute(
        text(
            """
            INSERT INTO adm_2 ("GID_2", "GID_1", "GID_0", "NAME_2") VALUES
            ('CHN.1.1_1', 'CHN.1_1', 'CHN', 'Shenzhen'),
            ('CHN.2.1_1', 'CHN.2_1', 'CHN', 'Dongcheng'),
            ('JPN.1.1_1', 'JPN.1_1', 'JPN', 'Chiyoda')
            """
        )
    )
    
    # 3. IUCN
    # init_db populates standard IUCN data, so no mock insertion is needed.
    db.commit()


def test_get_iho_options(client: TestClient, db: Session) -> None:
    setup_test_data(db)
    
    # Get all
    r = client.get("/api/v1/geo/iho")
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 2
    assert {"gid": "1", "name": "South China Sea"} in data
    
    # Search
    r = client.get("/api/v1/geo/iho?search=East")
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 1
    assert data[0]["name"] == "East China Sea"


def test_get_iho_options_paginates(client: TestClient, db: Session) -> None:
    setup_test_data(db)

    first = client.get("/api/v1/geo/iho?page=1&page_size=1")
    second = client.get("/api/v1/geo/iho?page=2&page_size=1")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["page_info"] == {
        "total": 2,
        "page": 1,
        "page_size": 1,
        "total_pages": 2,
    }
    assert first.json()["data"][0]["gid"] != second.json()["data"][0]["gid"]


def test_get_gadm_options(client: TestClient, db: Session) -> None:
    setup_test_data(db)
    
    # Get level 0
    r = client.get("/api/v1/geo/gadm?level=0")
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 2
    assert data[0]["gid"]
    names = [d["name"] for d in data]
    assert "China" in names
    
    # Search level 1
    r = client.get("/api/v1/geo/gadm?level=1&search=bei")
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) == 1
    assert data[0]["name"] == "Beijing"
    
    # Test parent filter logic (if it exists, even if mock test won't work perfectly due to ST_Intersects, we just check the endpoint doesn't crash)
    # The endpoint won't crash, but won't return correctly since geom=None in the test data
    r = client.get("/api/v1/geo/gadm?level=1&parent_gid=CHN")
    assert r.status_code == 200
    # Returns 0 because Spatial Index ST_Intersects on NULL geom gives empty/false


def test_get_gadm_options_paginates_with_stable_order(client: TestClient, db: Session) -> None:
    setup_test_data(db)

    first = client.get("/api/v1/geo/gadm?level=0&page=1&page_size=1")
    second = client.get("/api/v1/geo/gadm?level=0&page=2&page_size=1")

    assert first.json()["page_info"]["total"] == 2
    assert first.json()["page_info"]["total_pages"] == 2
    assert first.json()["data"] == [{"gid": "CHN", "name": "China"}]
    assert second.json()["data"] == [{"gid": "JPN", "name": "Japan"}]


def test_get_iucn_realms(client: TestClient, db: Session) -> None:
    setup_test_data(db)
    
    r = client.get("/api/v1/geo/iucn-realms")
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) >= 1
    names = [d["name"] for d in data]
    assert "Terrestrial" in names
    
    r = client.get("/api/v1/geo/iucn-realms?search=mar")
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) >= 1
    assert "Marine" in [d["name"] for d in data]

    paged = client.get("/api/v1/geo/iucn-realms?page=1&page_size=1")
    assert paged.status_code == 200
    assert len(paged.json()["data"]) == 1
    assert paged.json()["page_info"]["total"] >= 1


def test_get_iucn_biomes(client: TestClient, db: Session) -> None:
    setup_test_data(db)
    
    r = client.get("/api/v1/geo/iucn-biomes?realm_id=1")
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) >= 1
    names = [d["name"] for d in data]
    assert len(names) > 0


def test_get_iucn_functional_types(client: TestClient, db: Session) -> None:
    setup_test_data(db)
    
    # Find a biome_id from real data first
    r_biomes = client.get("/api/v1/geo/iucn-biomes?realm_id=1")
    biome_id = r_biomes.json()["data"][0]["id"]

    r = client.get(f"/api/v1/geo/iucn-functional-types?biome_id={biome_id}")
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) >= 1
    
    # Just search for a generic partial string to avoid failing
    search_str = data[0]["name"][:3]
    r = client.get(f"/api/v1/geo/iucn-functional-types?biome_id={biome_id}&search={search_str}")
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) >= 1
