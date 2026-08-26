from datetime import datetime

from fastapi.testclient import TestClient
from sqlmodel import Session, select, text

from app.core.config import settings
from app.models.annotation import Annotation
from app.models.media import AudioSetting, Media
from app.models.taxon import SoundClassification, Taxon, TaxonSoundType
from tests.utils.csv import read_csv_rows


def create_test_taxon(db: Session, **kwargs) -> Taxon:
    """Helper function to create a test taxon in local database."""
    defaults = {
        "col_species_id": "sp123",
        "cached_scientific_name": "Panthera leo",
        "cached_common_name": "Lion",
        "taxonomy_source": "CatalogueOfLife"
    }
    defaults.update(kwargs)
    taxon = Taxon(**defaults)
    db.add(taxon)
    db.commit()
    db.refresh(taxon)
    return taxon


def create_test_sound_classification(db: Session, soundscape_component: str, sound_type: str | None = None) -> SoundClassification:
    sc = SoundClassification(soundscape_component=soundscape_component, sound_type=sound_type)
    db.add(sc)
    db.commit()
    db.refresh(sc)
    return sc


def create_test_taxon_sound_type(db: Session, name: str, taxon_class: str, taxon_order: str = "") -> TaxonSoundType:
    tst = TaxonSoundType(name=name, taxon_class=taxon_class, taxon_order=taxon_order)
    db.add(tst)
    db.commit()
    db.refresh(tst)
    return tst


def create_test_annotation_with_taxon(db: Session, taxon_id: int) -> Annotation:
    """Create an Annotation that references the given taxon to test deletion constraint."""
    sc = SoundClassification(soundscape_component="biophony", sound_type="bird")
    db.add(sc)
    db.flush()
    audio_setting = AudioSetting(duration_s=10.0, sampling_rate_hz=44100)
    db.add(audio_setting)
    db.flush()
    media = Media(media_type="audio", audio_setting_id=audio_setting.audio_setting_id, creator_id=1)
    db.add(media)
    db.flush()
    annotation = Annotation(
        sound_id=sc.sound_id,
        media_id=media.media_id,
        creator_id=1,
        taxon_id=taxon_id,
        min_x=0.0, max_x=1.0, min_y=0.0, max_y=1.0,
    )
    db.add(annotation)
    db.commit()
    db.refresh(annotation)
    return annotation


def seed_remote_taxon_dictionary(db: Session) -> None:
    db.exec(
        text(
            """
            DROP TABLE IF EXISTS geo_col_xr_taxon_species;
            CREATE TABLE geo_col_xr_taxon_species (
                col_species_id VARCHAR(64),
                cached_scientific_name VARCHAR(255),
                cached_common_name VARCHAR(255),
                col_genus_id VARCHAR(64),
                col_genus_name VARCHAR(255),
                col_family_id VARCHAR(64),
                col_family_name VARCHAR(255),
                col_order_id VARCHAR(64),
                col_order_name VARCHAR(255),
                col_class_id VARCHAR(64),
                col_class_name VARCHAR(255),
                taxonomy_source VARCHAR(50),
                run_id VARCHAR(64),
                imported_at TIMESTAMP
            );
            """
        )
    )
    db.exec(
        text(
            """
            INSERT INTO geo_col_xr_taxon_species (
                col_species_id, cached_scientific_name, cached_common_name,
                col_genus_id, col_genus_name,
                col_family_id, col_family_name,
                col_order_id, col_order_name,
                col_class_id, col_class_name,
                taxonomy_source, run_id, imported_at
            ) VALUES
            (
                'SP1', 'Potamocypris granulosa', 'Seed shrimp',
                'GEN1', 'Potamocypris',
                'FAM1', 'Cyprididae',
                'ORD1', 'Podocopida',
                'CLS1', 'Ostracoda',
                'CatalogueOfLife-XR', 'col_xr_263', '2026-04-19 00:00:00'
            ),
            (
                'SP2', 'Cypridopsis vidua', 'Common seed shrimp',
                'GEN2', 'Cypridopsis',
                'FAM1', 'Cyprididae',
                'ORD1', 'Podocopida',
                'CLS1', 'Ostracoda',
                'CatalogueOfLife-XR', 'col_xr_263', '2026-04-19 00:00:00'
            )
            """
        )
    )
    db.commit()


def taxon_csv_upload(content: str) -> dict[str, tuple[str, str, str]]:
    return {"file": ("taxons.csv", content, "text/csv")}


class TestTaxonsAPI:
    """Test cases for the taxonomic local dictionary search API."""

    def test_search_taxons_empty_query(self, client: TestClient, db: Session) -> None:
        """Search without query returns default list limit."""
        create_test_taxon(db)
        r = client.get(f"{settings.API_V1_STR}/taxons/suggestions")
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) >= 1

    def test_search_taxons_with_query(self, client: TestClient, db: Session) -> None:
        """Search using a specific keyword."""
        create_test_taxon(db, cached_scientific_name="Canis lupus", cached_common_name="Wolf")
        create_test_taxon(db, cached_scientific_name="Felis catus", cached_common_name="Cat")

        # By scientific name part
        r = client.get(f"{settings.API_V1_STR}/taxons/suggestions?q=cani")
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) >= 1
        assert any(t["cached_scientific_name"] == "Canis lupus" for t in data)

        # By common name part
        r2 = client.get(f"{settings.API_V1_STR}/taxons/suggestions?q=cat")
        assert r2.status_code == 200
        data2 = r2.json()["data"]
        assert len(data2) >= 1
        assert any(t["cached_scientific_name"] == "Felis catus" for t in data2)

    def test_search_taxons_supports_stable_offset_pages(
        self,
        client: TestClient,
        db: Session,
    ) -> None:
        create_test_taxon(
            db,
            cached_scientific_name="Offset alpha",
            cached_common_name="Offset first",
        )
        create_test_taxon(
            db,
            cached_scientific_name="Offset beta",
            cached_common_name="Offset second",
        )

        first = client.get(
            f"{settings.API_V1_STR}/taxons/suggestions",
            params={"q": "Offset", "limit": 1, "offset": 0},
        )
        second = client.get(
            f"{settings.API_V1_STR}/taxons/suggestions",
            params={"q": "Offset", "limit": 1, "offset": 1},
        )

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["data"][0]["taxon_id"] != second.json()["data"][0]["taxon_id"]


class TestSoundClassificationsAPI:
    """Test cases for the sound classifications dropdown API."""

    def test_get_sound_classifications_returns_list(self, client: TestClient, db: Session) -> None:
        """Endpoint returns a non-empty list with required fields."""
        create_test_sound_classification(db, soundscape_component="biophony", sound_type="bird chorus")
        r = client.get(f"{settings.API_V1_STR}/sound-classifications")
        assert r.status_code == 200
        data = r.json()["data"]
        assert isinstance(data, list)
        assert len(data) >= 1
        item = data[0]
        assert "sound_id" in item
        assert "soundscape_component" in item
        assert "sound_type" in item

    def test_get_sound_classifications_contains_created_entry(self, client: TestClient, db: Session) -> None:
        """Newly created entry appears in the response."""
        sc = create_test_sound_classification(db, soundscape_component="geophony", sound_type="rain")
        r = client.get(f"{settings.API_V1_STR}/sound-classifications")
        assert r.status_code == 200
        data = r.json()["data"]
        ids = [item["sound_id"] for item in data]
        assert sc.sound_id in ids

    def test_get_sound_classifications_null_sound_type_allowed(self, client: TestClient, db: Session) -> None:
        """Entries with null sound_type are returned correctly."""
        sc = create_test_sound_classification(db, soundscape_component="other", sound_type=None)
        r = client.get(f"{settings.API_V1_STR}/sound-classifications")
        assert r.status_code == 200
        data = r.json()["data"]
        match = next((item for item in data if item["sound_id"] == sc.sound_id), None)
        assert match is not None
        assert match["sound_type"] is None

    def test_get_sound_classifications_no_auth_required(self, client: TestClient, db: Session) -> None:
        """Endpoint is publicly accessible without authentication."""
        r = client.get(f"{settings.API_V1_STR}/sound-classifications")
        assert r.status_code == 200


class TestAnimalSoundTypesAPI:
    """Test cases for the animal sound types dropdown API."""

    def test_get_all_animal_sound_types(self, client: TestClient, db: Session) -> None:
        """No filter returns all entries."""
        create_test_taxon_sound_type(db, name="(Bird) Song", taxon_class="AVES")
        create_test_taxon_sound_type(db, name="(Bat) Searching", taxon_class="MAMMALIA", taxon_order="CHIROPTERA")
        r = client.get(f"{settings.API_V1_STR}/animal-sound-types")
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) >= 2

    def test_filter_by_taxon_class(self, client: TestClient, db: Session) -> None:
        """taxon_class filter returns only matching entries."""
        create_test_taxon_sound_type(db, name="(Bird) Call", taxon_class="AVES")
        create_test_taxon_sound_type(db, name="(Bat) Social", taxon_class="MAMMALIA", taxon_order="CHIROPTERA")
        r = client.get(f"{settings.API_V1_STR}/animal-sound-types?taxon_class=AVES")
        assert r.status_code == 200
        data = r.json()["data"]
        assert all(item["name"].startswith("(Bird)") for item in data if item["name"].startswith("(Bird)") or item["name"].startswith("(Bat)"))
        names = [item["name"] for item in data]
        assert "(Bird) Call" in names
        assert "(Bat) Social" not in names

    def test_filter_by_taxon_order_takes_priority(self, client: TestClient, db: Session) -> None:
        """taxon_order filter takes priority over taxon_class."""
        create_test_taxon_sound_type(db, name="(Bat) Feeding", taxon_class="MAMMALIA", taxon_order="CHIROPTERA")
        create_test_taxon_sound_type(db, name="(Primate) Song", taxon_class="MAMMALIA", taxon_order="PRIMATA")
        r = client.get(f"{settings.API_V1_STR}/animal-sound-types?taxon_class=MAMMALIA&taxon_order=CHIROPTERA")
        assert r.status_code == 200
        data = r.json()["data"]
        names = [item["name"] for item in data]
        assert "(Bat) Feeding" in names
        assert "(Primate) Song" not in names

    def test_response_fields(self, client: TestClient, db: Session) -> None:
        """Response items contain taxon_sound_type_id and name."""
        create_test_taxon_sound_type(db, name="(Bird) Non-vocal", taxon_class="AVES")
        r = client.get(f"{settings.API_V1_STR}/animal-sound-types?taxon_class=AVES")
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) >= 1
        item = data[0]
        assert "taxon_sound_type_id" in item
        assert "name" in item

    def test_no_auth_required(self, client: TestClient, db: Session) -> None:
        """Endpoint is publicly accessible without authentication."""
        r = client.get(f"{settings.API_V1_STR}/animal-sound-types")
        assert r.status_code == 200


class TestTaxonAdminAPI:
    """Admin CRUD tests for /taxons endpoints."""

    BASE = f"{settings.API_V1_STR}/taxons"
    ADMIN_BASE = f"{settings.API_V1_STR}/taxons"

    def test_list_taxons_requires_admin(self, client: TestClient, normal_user_token_headers: dict) -> None:
        """Non-admin users are rejected with 403."""
        r = client.get(self.ADMIN_BASE, headers=normal_user_token_headers)
        assert r.status_code == 403

    def test_list_taxons_requires_auth(self, client: TestClient) -> None:
        """Unauthenticated requests are rejected with 401."""
        r = client.get(self.ADMIN_BASE)
        assert r.status_code == 401

    def test_list_taxons_returns_paged_result(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Admin can retrieve a paginated taxon list."""
        create_test_taxon(db, cached_scientific_name="Canis lupus", cached_common_name="Wolf")
        create_test_taxon(db, cached_scientific_name="Felis catus", cached_common_name="Cat")
        r = client.get(self.ADMIN_BASE, headers=superuser_token_headers)
        assert r.status_code == 200
        body = r.json()
        assert "data" in body
        assert body["page_info"]["total"] >= 2

    def test_list_taxons_ignores_remote_dictionary(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """The admin list only includes locally created taxon rows."""
        seed_remote_taxon_dictionary(db)
        local_taxon = create_test_taxon(
            db,
            cached_scientific_name="Localus onlyensis",
            cached_common_name="Local Only",
        )

        r = client.get(f"{self.ADMIN_BASE}?q=Localus", headers=superuser_token_headers)

        assert r.status_code == 200
        body = r.json()
        assert body["page_info"]["total"] == 1
        assert [item["taxon_id"] for item in body["data"]] == [local_taxon.taxon_id]
        assert all("Potamocypris granulosa" != item["cached_scientific_name"] for item in body["data"])

    def test_list_taxons_filter_by_q(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Keyword q filters by scientific or common name (OR logic)."""
        create_test_taxon(db, cached_scientific_name="Aquila chrysaetos", cached_common_name="Golden Eagle")
        create_test_taxon(db, cached_scientific_name="Bufo bufo", cached_common_name="Common Toad")
        r = client.get(f"{self.ADMIN_BASE}?q=eagle", headers=superuser_token_headers)
        assert r.status_code == 200
        names = [t["cached_scientific_name"] for t in r.json()["data"]]
        assert "Aquila chrysaetos" in names
        assert "Bufo bufo" not in names

    def test_list_taxons_filter_by_taxonomy_source(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Filter by exact taxonomy_source value."""
        create_test_taxon(db, cached_scientific_name="Parus major", taxonomy_source="CatalogueOfLife")
        create_test_taxon(db, cached_scientific_name="Turdus merula", taxonomy_source="BirdNET")
        r = client.get(f"{self.ADMIN_BASE}?taxonomy_source=BirdNET", headers=superuser_token_headers)
        assert r.status_code == 200
        names = [t["cached_scientific_name"] for t in r.json()["data"]]
        assert "Turdus merula" in names
        assert "Parus major" not in names

    def test_list_taxons_filter_by_cached_scientific_name(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        create_test_taxon(db, cached_scientific_name="Vulpes vulpes")
        create_test_taxon(db, cached_scientific_name="Lepus europaeus")
        r = client.get(f"{self.ADMIN_BASE}?cached_scientific_name=vulpes", headers=superuser_token_headers)
        assert r.status_code == 200
        names = [t["cached_scientific_name"] for t in r.json()["data"]]
        assert "Vulpes vulpes" in names
        assert "Lepus europaeus" not in names

    def test_list_taxons_filter_by_cached_common_name(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        create_test_taxon(db, cached_scientific_name="Pica pica", cached_common_name="Eurasian Magpie")
        create_test_taxon(db, cached_scientific_name="Corvus corax", cached_common_name="Raven")
        r = client.get(f"{self.ADMIN_BASE}?cached_common_name=magpie", headers=superuser_token_headers)
        assert r.status_code == 200
        names = [t["cached_scientific_name"] for t in r.json()["data"]]
        assert "Pica pica" in names
        assert "Corvus corax" not in names

    def test_list_taxons_filter_by_last_synced_range(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        create_test_taxon(
            db,
            cached_scientific_name="Synced Early",
            last_synced=datetime(2024, 1, 10, 8, 0, 0),
        )
        create_test_taxon(
            db,
            cached_scientific_name="Synced Late",
            last_synced=datetime(2024, 2, 10, 8, 0, 0),
        )
        r = client.get(
            f"{self.ADMIN_BASE}?last_synced_from=2024-02-01&last_synced_to=2024-02-28",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        names = [t["cached_scientific_name"] for t in r.json()["data"]]
        assert "Synced Late" in names
        assert "Synced Early" not in names

    def test_list_taxons_filter_by_taxon_id(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        target = create_test_taxon(db, cached_scientific_name="Target Taxon By Id")
        create_test_taxon(db, cached_scientific_name="Other Taxon By Id")
        r = client.get(f"{self.ADMIN_BASE}?taxon_id={target.taxon_id}", headers=superuser_token_headers)
        assert r.status_code == 200
        items = r.json()["data"]
        assert len(items) == 1
        assert items[0]["taxon_id"] == target.taxon_id

    def test_list_taxons_filter_taxon_id_and_q_intersection(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        target = create_test_taxon(db, cached_scientific_name="Target Intersection Taxon")
        r_ok = client.get(
            f"{self.ADMIN_BASE}?taxon_id={target.taxon_id}&q=Intersection",
            headers=superuser_token_headers,
        )
        assert r_ok.status_code == 200
        ok_items = r_ok.json()["data"]
        assert len(ok_items) == 1
        assert ok_items[0]["taxon_id"] == target.taxon_id

        r_empty = client.get(
            f"{self.ADMIN_BASE}?taxon_id={target.taxon_id}&q=NoSuchKeyword",
            headers=superuser_token_headers,
        )
        assert r_empty.status_code == 200
        assert r_empty.json()["data"] == []

    def test_list_taxons_filter_by_col_class(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Filter by col_class_id."""
        create_test_taxon(db, cached_scientific_name="Anas platyrhynchos", col_class_id="AVES")
        create_test_taxon(db, cached_scientific_name="Rana temporaria", col_class_id="AMPHIBIA")
        r = client.get(f"{self.ADMIN_BASE}?col_class_id=AVES", headers=superuser_token_headers)
        assert r.status_code == 200
        names = [t["cached_scientific_name"] for t in r.json()["data"]]
        assert "Anas platyrhynchos" in names
        assert "Rana temporaria" not in names

    def test_list_taxons_sort_by_common_name(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """order_by=common_name returns results sorted alphabetically."""
        create_test_taxon(db, cached_scientific_name="Sp A", cached_common_name="Zebra")
        create_test_taxon(db, cached_scientific_name="Sp B", cached_common_name="Aardvark")
        r = client.get(f"{self.ADMIN_BASE}?order_by=common_name&order_dir=asc", headers=superuser_token_headers)
        assert r.status_code == 200
        names = [t["cached_common_name"] for t in r.json()["data"] if t["cached_common_name"] in ("Aardvark", "Zebra")]
        assert names.index("Aardvark") < names.index("Zebra")

    def test_list_taxons_pagination(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """page_size limits results and page selects the correct slice."""
        for i in range(5):
            create_test_taxon(db, cached_scientific_name=f"Species {i:03d}", cached_common_name=f"Common {i:03d}")
        r = client.get(
            f"{self.ADMIN_BASE}?page=1&page_size=2&order_by=scientific_name",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["data"]) <= 2
        assert body["page_info"]["total"] >= 5

    def test_list_taxons_returns_hierarchy_names_without_rank(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        seed_remote_taxon_dictionary(db)
        taxon = create_test_taxon(
            db,
            col_species_id="SP1",
            col_genus_id="GEN1",
            col_family_id="FAM1",
            col_order_id="ORD1",
            col_class_id="CLS1",
            cached_scientific_name="Potamocypris granulosa",
        )

        response = client.get(
            f"{self.ADMIN_BASE}?taxon_id={taxon.taxon_id}",
            headers=superuser_token_headers,
        )

        assert response.status_code == 200
        expected = {
            "taxon_id": taxon.taxon_id,
            "col_species_name": "Potamocypris granulosa",
            "col_genus_name": "Potamocypris",
            "col_family_name": "Cyprididae",
            "col_order_name": "Podocopida",
            "col_class_name": "Ostracoda",
        }
        item = response.json()["data"][0]
        assert expected.items() <= item.items()
        assert "lowest_rank" not in item

    def test_list_taxons_filters_and_sorts_hierarchy_before_pagination(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        seed_remote_taxon_dictionary(db)
        create_test_taxon(
            db,
            col_species_id="SP1",
            col_genus_id="GEN1",
            col_family_id="FAM1",
            col_order_id="ORD1",
            col_class_id="CLS1",
            cached_scientific_name="Potamocypris granulosa",
        )
        create_test_taxon(
            db,
            col_species_id="SP2",
            col_genus_id="GEN2",
            col_family_id="FAM1",
            col_order_id="ORD1",
            col_class_id="CLS1",
            cached_scientific_name="Cypridopsis vidua",
        )

        response = client.get(
            f"{self.ADMIN_BASE}?col_class_name=ostracoda"
            "&order_by=col_genus_name&order_dir=desc&page=1&page_size=1",
            headers=superuser_token_headers,
        )

        assert response.status_code == 200
        assert response.json()["page_info"]["total"] == 2
        assert response.json()["data"][0]["col_genus_name"] == "Potamocypris"

    def test_list_taxons_filters_by_species_name(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        seed_remote_taxon_dictionary(db)
        create_test_taxon(
            db,
            col_species_id="SP1",
            col_genus_id="GEN1",
            col_family_id="FAM1",
            col_order_id="ORD1",
            col_class_id="CLS1",
            cached_scientific_name="Potamocypris granulosa",
        )
        create_test_taxon(
            db,
            col_species_id="SP2",
            col_genus_id="GEN2",
            col_family_id="FAM1",
            col_order_id="ORD1",
            col_class_id="CLS1",
            cached_scientific_name="Cypridopsis vidua",
        )

        response = client.get(
            f"{self.ADMIN_BASE}?col_species_name=granulosa",
            headers=superuser_token_headers,
        )

        assert response.status_code == 200
        assert response.json()["page_info"]["total"] == 1
        assert response.json()["data"][0]["col_species_name"] == "Potamocypris granulosa"

    def test_list_taxons_sorts_by_species_name(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        seed_remote_taxon_dictionary(db)
        create_test_taxon(
            db,
            col_species_id="SP1",
            col_genus_id="GEN1",
            col_family_id="FAM1",
            col_order_id="ORD1",
            col_class_id="CLS1",
            cached_scientific_name="Potamocypris granulosa",
        )
        create_test_taxon(
            db,
            col_species_id="SP2",
            col_genus_id="GEN2",
            col_family_id="FAM1",
            col_order_id="ORD1",
            col_class_id="CLS1",
            cached_scientific_name="Cypridopsis vidua",
        )

        response = client.get(
            f"{self.ADMIN_BASE}?col_class_name=ostracoda"
            "&order_by=col_species_name&order_dir=desc&page=1&page_size=1",
            headers=superuser_token_headers,
        )

        assert response.status_code == 200
        assert response.json()["page_info"]["total"] == 2
        assert response.json()["data"][0]["col_species_name"] == "Potamocypris granulosa"

    def test_list_taxons_species_sort_requires_dictionary(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        db.exec(text("DROP TABLE IF EXISTS geo_col_xr_taxon_species"))
        db.commit()
        create_test_taxon(db, cached_scientific_name="Local only")

        response = client.get(
            f"{self.ADMIN_BASE}?order_by=col_species_name",
            headers=superuser_token_headers,
        )

        assert response.status_code == 503

    def test_list_taxons_hierarchy_sort_requires_dictionary(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        db.exec(text("DROP TABLE IF EXISTS geo_col_xr_taxon_species"))
        db.commit()
        create_test_taxon(db, cached_scientific_name="Local only")

        response = client.get(
            f"{self.ADMIN_BASE}?order_by=col_genus_name",
            headers=superuser_token_headers,
        )

        assert response.status_code == 503

    def test_export_taxons_accepts_sorting_only(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        taxon = create_test_taxon(
            db,
            cached_scientific_name="Exportus localis",
            cached_common_name="Local Export",
            col_class_id="AVES",
        )
        r = client.get(
            f"{self.ADMIN_BASE}/exports?taxon_id={taxon.taxon_id}&q=Exportus&col_class_id=AVES&order_by=scientific_name",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        assert r.headers.get("content-disposition") == (
            'attachment; filename="taxons.csv"; '
            "filename*=UTF-8''taxons.csv"
        )
        rows = read_csv_rows(r.text)
        assert rows[0] == [
            "taxon_id",
            "cached_scientific_name",
            "cached_common_name",
            "col_species_id",
            "col_genus_id",
            "col_family_id",
            "col_order_id",
            "col_class_id",
            "col_species_name",
            "col_genus_name",
            "col_family_name",
            "col_order_name",
            "col_class_name",
            "taxonomy_source",
            "creation_date",
            "last_synced",
        ]
        assert any(row[0] == str(taxon.taxon_id) for row in rows[1:])

    def test_export_taxons_matches_list_hierarchy_fields(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        seed_remote_taxon_dictionary(db)
        taxon = create_test_taxon(
            db,
            col_species_id="SP1",
            col_genus_id="GEN1",
            col_family_id="FAM1",
            col_order_id="ORD1",
            col_class_id="CLS1",
            cached_scientific_name="Potamocypris granulosa",
            cached_common_name="Imported common name",
            taxonomy_source="CatalogueOfLife-XR",
            creation_date=datetime(2026, 3, 17, 14, 30, 0),
            last_synced=datetime(2026, 4, 19, 8, 15, 30),
        )

        response = client.get(
            f"{self.ADMIN_BASE}/exports?order_by=col_genus_name",
            headers=superuser_token_headers,
        )

        assert response.status_code == 200
        row = next(
            item for item in read_csv_rows(response.text)[1:]
            if item[0] == str(taxon.taxon_id)
        )
        assert row[1:3] == [
            "Potamocypris granulosa",
            "Imported common name",
        ]
        assert row[8:13] == [
            "Potamocypris granulosa",
            "Potamocypris",
            "Cyprididae",
            "Podocopida",
            "Ostracoda",
        ]
        assert row[13] == "CatalogueOfLife-XR"
        # Must match TaxonListItem serializers / API list format, not str(datetime).
        assert row[14:16] == ["2026-03-17 14:30:00", "2026-04-19 08:15:30"]

    def test_import_taxons_infers_all_supported_ranks(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        seed_remote_taxon_dictionary(db)
        content = (
            "cached_scientific_name,cached_common_name,col_genus_name,col_family_name,col_order_name,col_class_name,taxonomy_source\n"
            "Potamocypris granulosa,Species common,Potamocypris,Cyprididae,Podocopida,Ostracoda,CatalogueOfLife-XR\n"
            "Potamocypris,Genus common,,Cyprididae,Podocopida,Ostracoda,CatalogueOfLife-XR\n"
            "Cyprididae,Family common,,,Podocopida,Ostracoda,CatalogueOfLife-XR\n"
            "Podocopida,Order common,,,,Ostracoda,CatalogueOfLife-XR\n"
            "Ostracoda,Class common,,,,,CatalogueOfLife-XR\n"
        )

        response = client.post(
            f"{self.ADMIN_BASE}/imports",
            headers=superuser_token_headers,
            data={"dry_run": "false"},
            files=taxon_csv_upload(content),
        )

        assert response.status_code == 200
        assert response.json()["data"]["committed"] is True
        assert response.json()["data"]["succeeded"] == 5
        imported = list(
            db.exec(
                select(Taxon)
                .where(Taxon.taxonomy_source == "CatalogueOfLife-XR")
                .order_by(Taxon.taxon_id.desc())
                .limit(5)
            ).all()
        )
        assert {
            next(
                value
                for value in (
                    item.col_species_id,
                    item.col_genus_id,
                    item.col_family_id,
                    item.col_order_id,
                    item.col_class_id,
                )
                if value
            )
            for item in imported
        } == {"SP1", "GEN1", "FAM1", "ORD1", "CLS1"}

    def test_import_taxons_tolerates_exported_columns_and_order(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        # An exported taxon CSV carries extra columns (ID, Species, Created,
        # Last synced) in a different order; re-importing it must ignore the
        # extras and map the rest by name.
        seed_remote_taxon_dictionary(db)
        content = (
            "taxon_id,cached_scientific_name,cached_common_name,col_species_id,col_genus_id,col_family_id,col_order_id,col_class_id,col_species_name,col_genus_name,col_family_name,col_order_name,col_class_name,taxonomy_source,creation_date,last_synced\n"
            "1,Potamocypris granulosa,Common,SP1,GEN1,FAM1,ORD1,CLS1,Potamocypris granulosa,Potamocypris,Cyprididae,Podocopida,Ostracoda,CatalogueOfLife-XR,2026-03-17 14:30:00,2026-04-19 08:15:30\n"
        )
        response = client.post(
            f"{self.ADMIN_BASE}/imports",
            headers=superuser_token_headers,
            data={"dry_run": "false"},
            files=taxon_csv_upload(content),
        )
        assert response.status_code == 200
        assert response.json()["data"]["committed"] is True
        assert response.json()["data"]["succeeded"] == 1

    def test_import_taxons_skips_blank_rows(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        header = "cached_scientific_name,cached_common_name,col_genus_name,col_family_name,col_order_name,col_class_name,taxonomy_source\n"
        empty_response = client.post(
            f"{self.ADMIN_BASE}/imports",
            headers=superuser_token_headers,
            data={"dry_run": "false"},
            files=taxon_csv_upload(header + ",,,,,,\n"),
        )
        assert empty_response.status_code == 200
        assert empty_response.json()["data"]["committed"] is True
        assert empty_response.json()["data"]["skipped"] == 1

    def test_import_taxons_rejects_unknown_and_rolls_back(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        seed_remote_taxon_dictionary(db)
        before = len(db.exec(select(Taxon)).all())
        content = (
            "cached_scientific_name,cached_common_name,col_genus_name,col_family_name,col_order_name,col_class_name,taxonomy_source\n"
            "Potamocypris granulosa,Valid,Potamocypris,Cyprididae,Podocopida,Ostracoda,CatalogueOfLife-XR\n"
            "Unknown species,Unknown,,,,,CatalogueOfLife-XR\n"
        )

        response = client.post(
            f"{self.ADMIN_BASE}/imports",
            headers=superuser_token_headers,
            data={"dry_run": "false"},
            files=taxon_csv_upload(content),
        )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["committed"] is False
        assert data["failed"] == 2
        assert data["rows"][1]["reason"].startswith("Unknown binomial")
        assert len(db.exec(select(Taxon)).all()) == before

    def test_import_taxons_rejects_hierarchy_mismatch(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        seed_remote_taxon_dictionary(db)
        content = (
            "cached_scientific_name,cached_common_name,col_genus_name,col_family_name,col_order_name,col_class_name,taxonomy_source\n"
            "Potamocypris granulosa,Common,Wrong genus,Cyprididae,Podocopida,Ostracoda,CatalogueOfLife-XR\n"
        )

        response = client.post(
            f"{self.ADMIN_BASE}/imports",
            headers=superuser_token_headers,
            data={"dry_run": "false"},
            files=taxon_csv_upload(content),
        )

        assert response.status_code == 200
        assert response.json()["data"]["committed"] is False
        assert "Taxonomic hierarchy does not match" in response.json()["data"]["rows"][0]["reason"]

    def test_import_taxons_rejects_ambiguous_name(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        seed_remote_taxon_dictionary(db)
        db.exec(
            text(
                """
                INSERT INTO geo_col_xr_taxon_species
                    (col_species_id, cached_scientific_name, col_genus_id,
                     col_genus_name, col_family_id, col_family_name,
                     col_order_id, col_order_name, col_class_id, col_class_name)
                VALUES
                    ('SP3', 'Potamocypris granulosa', 'GEN1', 'Potamocypris',
                     'FAM1', 'Cyprididae', 'ORD1', 'Podocopida', 'CLS1', 'Ostracoda')
                """
            )
        )
        db.commit()
        content = (
            "cached_scientific_name,cached_common_name,col_genus_name,col_family_name,col_order_name,col_class_name,taxonomy_source\n"
            "Potamocypris granulosa,Common,Potamocypris,Cyprididae,Podocopida,Ostracoda,CatalogueOfLife-XR\n"
        )

        response = client.post(
            f"{self.ADMIN_BASE}/imports",
            headers=superuser_token_headers,
            data={"dry_run": "false"},
            files=taxon_csv_upload(content),
        )

        assert response.status_code == 200
        assert response.json()["data"]["committed"] is False
        assert "Ambiguous binomial" in response.json()["data"]["rows"][0]["reason"]

    def test_import_taxons_rejects_file_and_database_duplicates(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        seed_remote_taxon_dictionary(db)
        header = "cached_scientific_name,cached_common_name,col_genus_name,col_family_name,col_order_name,col_class_name,taxonomy_source\n"
        row = "Potamocypris granulosa,Common,Potamocypris,Cyprididae,Podocopida,Ostracoda,CatalogueOfLife-XR\n"
        duplicate_response = client.post(
            f"{self.ADMIN_BASE}/imports",
            headers=superuser_token_headers,
            data={"dry_run": "false"},
            files=taxon_csv_upload(header + row + row),
        )
        assert duplicate_response.status_code == 200
        assert duplicate_response.json()["data"]["committed"] is True
        assert duplicate_response.json()["data"]["succeeded"] == 1
        assert duplicate_response.json()["data"]["skipped"] == 1

        create_test_taxon(
            db,
            col_species_id="sp1",
            col_genus_id="GEN1",
            col_family_id="FAM1",
            col_order_id="ORD1",
            col_class_id="CLS1",
        )
        existing_response = client.post(
            f"{self.ADMIN_BASE}/imports",
            headers=superuser_token_headers,
            data={"dry_run": "false"},
            files=taxon_csv_upload(header + row),
        )
        assert existing_response.status_code == 200
        assert existing_response.json()["data"]["committed"] is True
        assert existing_response.json()["data"]["skipped"] == 1

    def test_import_taxons_validates_header_and_permissions(
        self,
        client: TestClient,
        normal_user_token_headers: dict,
        superuser_token_headers: dict,
    ) -> None:
        invalid = "lowest_col_id,cached_common_name,taxonomy_source\nSP1,Common,COL\n"
        admin_response = client.post(
            f"{self.ADMIN_BASE}/imports",
            headers=superuser_token_headers,
            files=taxon_csv_upload(invalid),
        )
        user_response = client.post(
            f"{self.ADMIN_BASE}/imports",
            headers=normal_user_token_headers,
            files=taxon_csv_upload(invalid),
        )
        anonymous_response = client.post(
            f"{self.ADMIN_BASE}/imports",
            files=taxon_csv_upload(invalid),
        )

        assert admin_response.status_code == 200
        assert admin_response.json()["data"]["global_errors"]
        assert user_response.status_code == 403
        assert anonymous_response.status_code == 401

    def test_export_taxons_ignores_filter_parameters(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        seed_remote_taxon_dictionary(db)
        taxon = create_test_taxon(
            db,
            cached_scientific_name="Exportus localis",
            cached_common_name="Local Export",
            taxonomy_source="CatalogueOfLife-XR",
            col_class_id="CLS1",
            last_synced=datetime(2026, 4, 19, 0, 0, 0),
        )
        r = client.get(
            f"{self.ADMIN_BASE}/exports?taxonomy_source=CatalogueOfLife-XR&col_class_id=CLS1&last_synced_from=2026-04-01&last_synced_to=2026-04-30",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        assert r.headers.get("content-disposition") == (
            'attachment; filename="taxons.csv"; '
            "filename*=UTF-8''taxons.csv"
        )
        rows = read_csv_rows(r.text)
        assert rows[0][0] == "taxon_id"
        assert any(
            row[0] == str(taxon.taxon_id) and row[1] == "Exportus localis"
            for row in rows[1:]
        )

    def test_get_taxon_options_returns_id_and_name_only(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        seed_remote_taxon_dictionary(db)
        r = client.get(
            f"{settings.API_V1_STR}/taxons/options?rank=class",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data == [{"id": "CLS1", "name": "Ostracoda"}]

    def test_get_taxon_options_filters_hierarchy(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        seed_remote_taxon_dictionary(db)
        r = client.get(
            f"{settings.API_V1_STR}/taxons/options?rank=genus&class_id=CLS1&order_id=ORD1&family_id=FAM1&q=cypridop",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        assert r.json()["data"] == [{"id": "GEN2", "name": "Cypridopsis"}]

    def test_get_taxon_options_species_rank_with_full_hierarchy_filters(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        seed_remote_taxon_dictionary(db)
        r = client.get(
            f"{settings.API_V1_STR}/taxons/options?rank=species&class_id=CLS1&order_id=ORD1&family_id=FAM1&genus_id=GEN1&q=gran",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        assert r.json()["data"] == [{"id": "SP1", "name": "Potamocypris granulosa"}]

    def test_create_taxon_success(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Admin can create a new taxon and the response contains the new record."""
        seed_remote_taxon_dictionary(db)
        payload = {
            "cached_common_name": "Eurasian Lynx",
            "col_genus_id": "GEN1",
            "taxonomy_source": "CatalogueOfLife-XR",
        }
        r = client.post(self.BASE, headers=superuser_token_headers, json=payload)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["cached_scientific_name"] == "Potamocypris"
        assert data["cached_common_name"] == "Eurasian Lynx"
        assert data["col_class_id"] == "CLS1"
        assert data["col_order_id"] == "ORD1"
        assert data["col_family_id"] == "FAM1"
        assert data["col_genus_id"] == "GEN1"
        assert data["col_genus_name"] == "Potamocypris"
        assert data["col_family_name"] == "Cyprididae"
        assert data["col_order_name"] == "Podocopida"
        assert data["col_class_name"] == "Ostracoda"
        assert data["lowest_col_id"] == "GEN1"
        assert "lowest_rank" not in data
        assert "taxon_id" in data

    def test_create_taxon_with_species_lowest_fills_full_hierarchy(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        seed_remote_taxon_dictionary(db)
        payload = {
            "cached_common_name": "Seed shrimp alias",
            "col_species_id": "SP1",
            "taxonomy_source": "CatalogueOfLife-XR",
        }
        r = client.post(self.BASE, headers=superuser_token_headers, json=payload)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["cached_scientific_name"] == "Potamocypris granulosa"
        assert data["cached_common_name"] == "Seed shrimp alias"
        assert data["col_species_id"] == "SP1"
        assert data["col_species_name"] == "Potamocypris granulosa"
        assert data["col_genus_id"] == "GEN1"
        assert data["col_family_id"] == "FAM1"
        assert data["col_order_id"] == "ORD1"
        assert data["col_class_id"] == "CLS1"
        assert data["lowest_col_id"] == "SP1"
        assert "lowest_rank" not in data

    def test_create_taxon_requires_admin(
        self, client: TestClient, normal_user_token_headers: dict
    ) -> None:
        """Non-admin users cannot create taxons."""
        r = client.post(self.BASE, headers=normal_user_token_headers, json={"col_genus_id": "GEN1"})
        assert r.status_code == 403

    def test_create_taxon_requires_auth(self, client: TestClient) -> None:
        """Unauthenticated create is rejected with 401."""
        r = client.post(self.BASE, json={"col_genus_id": "GEN1"})
        assert r.status_code == 401

    def test_get_taxon_detail_success(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Admin can fetch a single taxon by ID."""
        seed_remote_taxon_dictionary(db)
        taxon = create_test_taxon(
            db,
            cached_scientific_name="Potamocypris granulosa",
            cached_common_name="Seed shrimp",
            col_species_id="SP1",
            col_genus_id="GEN1",
            col_family_id="FAM1",
            col_order_id="ORD1",
            col_class_id="CLS1",
        )
        r = client.get(f"{self.BASE}/{taxon.taxon_id}", headers=superuser_token_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["taxon_id"] == taxon.taxon_id
        assert data["cached_scientific_name"] == "Potamocypris granulosa"
        assert data["col_genus_name"] == "Potamocypris"
        assert data["col_family_name"] == "Cyprididae"
        assert data["col_order_name"] == "Podocopida"
        assert data["col_class_name"] == "Ostracoda"
        assert data["lowest_col_id"] == "SP1"
        assert "lowest_rank" not in data

    def test_get_taxon_not_found(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        """Returns 404 for a non-existent taxon ID."""
        r = client.get(f"{self.BASE}/999999", headers=superuser_token_headers)
        assert r.status_code == 404

    def test_get_taxon_requires_admin(
        self, client: TestClient, normal_user_token_headers: dict, db: Session
    ) -> None:
        """Non-admin users cannot access taxon detail."""
        taxon = create_test_taxon(db)
        r = client.get(f"{self.BASE}/{taxon.taxon_id}", headers=normal_user_token_headers)
        assert r.status_code == 403

    def test_update_taxon_success(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Admin can update taxon fields; unset fields are unchanged."""
        seed_remote_taxon_dictionary(db)
        taxon = create_test_taxon(db, cached_scientific_name="Old Name", cached_common_name="Old Common")
        r = client.put(
            f"{self.BASE}/{taxon.taxon_id}",
            headers=superuser_token_headers,
            json={"col_family_id": "FAM1", "cached_common_name": "Updated Common"},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["cached_scientific_name"] == "Cyprididae"
        assert data["cached_common_name"] == "Updated Common"
        assert data["col_class_id"] == "CLS1"
        assert data["col_order_id"] == "ORD1"
        assert data["col_family_id"] == "FAM1"
        assert data["col_genus_id"] is None
        assert data["col_family_name"] == "Cyprididae"
        assert data["col_order_name"] == "Podocopida"
        assert data["col_class_name"] == "Ostracoda"
        assert data["lowest_col_id"] == "FAM1"
        assert "lowest_rank" not in data

    def test_update_taxon_to_species_recomputes_all_levels(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        seed_remote_taxon_dictionary(db)
        taxon = create_test_taxon(
            db,
            cached_scientific_name="Old Name",
            cached_common_name="Old Common",
            col_species_id=None,
            col_genus_id="GEN1",
            col_family_id="FAM1",
            col_order_id="ORD1",
            col_class_id="CLS1",
        )
        r = client.put(
            f"{self.BASE}/{taxon.taxon_id}",
            headers=superuser_token_headers,
            json={"col_species_id": "SP2"},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["cached_scientific_name"] == "Cypridopsis vidua"
        assert data["col_species_id"] == "SP2"
        assert data["col_genus_id"] == "GEN2"
        assert data["col_family_id"] == "FAM1"
        assert data["col_order_id"] == "ORD1"
        assert data["col_class_id"] == "CLS1"
        assert data["lowest_col_id"] == "SP2"
        assert "lowest_rank" not in data

    def test_update_taxon_common_name_keeps_existing_hierarchy(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        taxon = create_test_taxon(
            db,
            cached_scientific_name="Potamocypris granulosa",
            cached_common_name="Seed shrimp",
            col_species_id="SP1",
            col_genus_id="GEN1",
            col_family_id="FAM1",
            col_order_id="ORD1",
            col_class_id="CLS1",
        )
        r = client.put(
            f"{self.BASE}/{taxon.taxon_id}",
            headers=superuser_token_headers,
            json={"cached_common_name": "Updated Seed Shrimp"},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["cached_common_name"] == "Updated Seed Shrimp"
        assert data["col_species_id"] == "SP1"
        assert data["col_genus_id"] == "GEN1"
        assert data["col_family_id"] == "FAM1"
        assert data["col_order_id"] == "ORD1"
        assert data["col_class_id"] == "CLS1"
        assert data["lowest_col_id"] == "SP1"
        assert "lowest_rank" not in data

    def test_update_taxon_clears_optional_text_and_rebuilds_from_remaining_level(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        seed_remote_taxon_dictionary(db)
        taxon = create_test_taxon(
            db,
            cached_scientific_name="Potamocypris granulosa",
            cached_common_name="Seed shrimp",
            taxonomy_source="Catalogue",
            col_species_id="SP1",
            col_genus_id="GEN1",
            col_family_id="FAM1",
            col_order_id="ORD1",
            col_class_id="CLS1",
        )

        r = client.put(
            f"{self.BASE}/{taxon.taxon_id}",
            headers=superuser_token_headers,
            json={
                "cached_common_name": None,
                "taxonomy_source": None,
                "col_species_id": None,
                "col_genus_id": "GEN1",
                "col_family_id": None,
                "col_order_id": None,
                "col_class_id": None,
            },
        )

        assert r.status_code == 200
        data = r.json()["data"]
        assert data["cached_common_name"] is None
        assert data["taxonomy_source"] is None
        assert data["col_species_id"] is None
        assert data["col_genus_id"] == "GEN1"
        assert data["lowest_col_id"] == "GEN1"
        assert "lowest_rank" not in data

    def test_update_taxon_not_found(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        """Returns 404 when updating a non-existent taxon."""
        r = client.put(f"{self.BASE}/999999", headers=superuser_token_headers, json={"cached_scientific_name": "X"})
        assert r.status_code == 404

    def test_update_taxon_requires_admin(
        self, client: TestClient, normal_user_token_headers: dict, db: Session
    ) -> None:
        """Non-admin users cannot update taxons."""
        taxon = create_test_taxon(db)
        r = client.put(f"{self.BASE}/{taxon.taxon_id}", headers=normal_user_token_headers, json={"cached_scientific_name": "X"})
        assert r.status_code == 403

    def test_delete_taxon_success(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Admin can delete an unreferenced taxon."""
        taxon = create_test_taxon(db, cached_scientific_name="Ephemeral Species")
        r = client.delete(f"{self.BASE}/{taxon.taxon_id}", headers=superuser_token_headers)
        assert r.status_code == 200
        # Confirm gone
        r2 = client.get(f"{self.BASE}/{taxon.taxon_id}", headers=superuser_token_headers)
        assert r2.status_code == 404

    def test_delete_taxon_not_found(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        """Returns 404 when deleting a non-existent taxon."""
        r = client.delete(f"{self.BASE}/999999", headers=superuser_token_headers)
        assert r.status_code == 404

    def test_delete_taxon_referenced_by_annotation_rejected(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        """Deletion is rejected with 400 when the taxon is referenced by an annotation."""
        taxon = create_test_taxon(db, cached_scientific_name="Protected Bird")
        create_test_annotation_with_taxon(db, taxon.taxon_id)
        r = client.delete(f"{self.BASE}/{taxon.taxon_id}", headers=superuser_token_headers)
        assert r.status_code == 400
        assert "referenced" in r.json()["message"].lower()

    def test_delete_taxon_requires_admin(
        self, client: TestClient, normal_user_token_headers: dict, db: Session
    ) -> None:
        """Non-admin users cannot delete taxons."""
        taxon = create_test_taxon(db)
        r = client.delete(f"{self.BASE}/{taxon.taxon_id}", headers=normal_user_token_headers)
        assert r.status_code == 403
