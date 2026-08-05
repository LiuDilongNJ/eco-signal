from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import User
from app.models.annotation import Annotation
from app.models.media import AudioSetting, Media
from app.models.taxon import SoundClassification
from tests.utils.csv import read_csv_rows

BASE = f"{settings.API_V1_STR}/sound-classification-records"
OPTIONS = f"{settings.API_V1_STR}/sound-classifications"


def _create_sound(
    db: Session,
    component: str = "test-biophony",
    sound_type: str | None = "test-call",
) -> SoundClassification:
    item = SoundClassification(soundscape_component=component, sound_type=sound_type)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _reference_sound(db: Session, sound_id: int) -> None:
    user = db.exec(select(User)).first()
    assert user is not None
    audio_setting = AudioSetting(duration_s=10, sampling_rate_hz=44100)
    db.add(audio_setting)
    db.flush()
    media = Media(
        media_type="audio",
        audio_setting_id=audio_setting.audio_setting_id,
        creator_id=user.user_id,
        uploader_id=user.user_id,
    )
    db.add(media)
    db.flush()
    db.add(
        Annotation(
            sound_id=sound_id,
            media_id=media.media_id,
            creator_id=user.user_id,
            min_x=0,
            max_x=1,
            min_y=0,
            max_y=1,
        )
    )
    db.commit()


def test_options_are_public_and_stably_sorted(client: TestClient, db: Session) -> None:
    first = _create_sound(db, "zz-test-component", "b")
    second = _create_sound(db, "zz-test-component", "a")

    response = client.get(OPTIONS)

    assert response.status_code == 200
    matches = [
        item for item in response.json()["data"]
        if item["sound_id"] in {first.sound_id, second.sound_id}
    ]
    assert [item["sound_id"] for item in matches] == [second.sound_id, first.sound_id]


def test_management_requires_admin(
    client: TestClient,
    normal_user_token_headers: dict,
) -> None:
    assert client.get(BASE).status_code in (401, 403)
    assert client.get(BASE, headers=normal_user_token_headers).status_code == 403
    assert client.post(
        f"{BASE}/imports",
        headers=normal_user_token_headers,
        files={"file": ("sounds.csv", b"soundscape_component,sound_type\nother,test\n", "text/csv")},
    ).status_code == 403


def test_list_filters_sorts_and_pages(
    client: TestClient,
    superuser_token_headers: dict,
    db: Session,
) -> None:
    first = _create_sound(db, "filter-component", "alpha-filter")
    second = _create_sound(db, "filter-component", "beta-filter")

    response = client.get(
        f"{BASE}?soundscape_component=filter-component&order_by=sound_type&order_dir=desc&page=1&page_size=1",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["page_info"]["total"] == 2
    assert body["data"][0]["sound_id"] == second.sound_id
    by_id = client.get(
        f"{BASE}?sound_id={first.sound_id}", headers=superuser_token_headers
    ).json()["data"]
    assert [item["sound_id"] for item in by_id] == [first.sound_id]


def test_create_get_and_update_normalize_values(
    client: TestClient,
    superuser_token_headers: dict,
) -> None:
    created = client.post(
        BASE,
        headers=superuser_token_headers,
        json={"soundscape_component": "  biophony-test  ", "sound_type": "   "},
    )
    assert created.status_code == 200
    item = created.json()["data"]
    assert item["soundscape_component"] == "biophony-test"
    assert item["sound_type"] is None

    detail = client.get(f"{BASE}/{item['sound_id']}", headers=superuser_token_headers)
    assert detail.status_code == 200

    updated = client.put(
        f"{BASE}/{item['sound_id']}",
        headers=superuser_token_headers,
        json={"soundscape_component": " geophony-test ", "sound_type": " rain "},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["soundscape_component"] == "geophony-test"
    assert updated.json()["data"]["sound_type"] == "rain"


def test_update_rejects_referenced_sound_and_preserves_values(
    client: TestClient,
    superuser_token_headers: dict,
    db: Session,
) -> None:
    referenced = _create_sound(db, "update-test", "original")
    _reference_sound(db, referenced.sound_id)

    response = client.put(
        f"{BASE}/{referenced.sound_id}",
        headers=superuser_token_headers,
        json={"soundscape_component": "changed", "sound_type": "modified"},
    )

    assert response.status_code == 409
    assert response.json()["message"] == (
        "Sound classification is referenced by annotation records"
    )
    db.expire_all()
    unchanged = db.get(SoundClassification, referenced.sound_id)
    assert unchanged is not None
    assert unchanged.soundscape_component == "update-test"
    assert unchanged.sound_type == "original"


def test_write_validation_and_not_found(
    client: TestClient,
    superuser_token_headers: dict,
) -> None:
    invalid = client.post(
        BASE,
        headers=superuser_token_headers,
        json={"soundscape_component": "   ", "sound_type": "x"},
    )
    assert invalid.status_code == 422
    assert client.get(f"{BASE}/999999", headers=superuser_token_headers).status_code == 404
    assert client.put(
        f"{BASE}/999999",
        headers=superuser_token_headers,
        json={"soundscape_component": "other", "sound_type": None},
    ).status_code == 404
    assert client.delete(f"{BASE}/999999", headers=superuser_token_headers).status_code == 404


def test_delete_unreferenced_and_reject_referenced(
    client: TestClient,
    superuser_token_headers: dict,
    db: Session,
) -> None:
    removable = _create_sound(db, "delete-test", "unused")
    assert client.delete(
        f"{BASE}/{removable.sound_id}", headers=superuser_token_headers
    ).status_code == 200

    referenced = _create_sound(db, "delete-test", "used")
    _reference_sound(db, referenced.sound_id)
    response = client.delete(
        f"{BASE}/{referenced.sound_id}", headers=superuser_token_headers
    )
    assert response.status_code == 409
    assert db.get(SoundClassification, referenced.sound_id) is not None


def test_import_success_with_bom_blank_rows_and_null_sound_type(
    client: TestClient,
    superuser_token_headers: dict,
    db: Session,
) -> None:
    content = (
        "\ufeffsoundscape_component,sound_type\n"
        " import-component , imported-type \n"
        "\n"
        "import-component,\n"
    ).encode()

    response = client.post(
        f"{BASE}/imports",
        headers=superuser_token_headers,
        files={"file": ("sounds.csv", content, "text/csv")},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "total": 3, "succeeded": 2, "skipped": 1, "failed": 0,
        "committed": True,
        "rows": [
            {"row_number": 2, "status": "succeeded", "field": None, "reason": None},
            {"row_number": 3, "status": "skipped", "field": None, "reason": "Blank row"},
            {"row_number": 4, "status": "succeeded", "field": None, "reason": None},
        ],
        "global_errors": [],
    }
    imported = list(
        db.exec(
            select(SoundClassification).where(
                SoundClassification.soundscape_component == "import-component"
            )
        ).all()
    )
    assert len(imported) == 2
    assert sum(item.sound_type is None for item in imported) == 1


def test_import_tolerates_exported_id_column(
    client: TestClient,
    superuser_token_headers: dict,
    db: Session,
) -> None:
    # The export adds an ID column; re-importing the exported CSV must ignore
    # it and map the remaining columns by name.
    content = (
        b"sound_id,soundscape_component,sound_type\n"
        b"42,reimport-component,reimport-type\n"
    )
    response = client.post(
        f"{BASE}/imports",
        headers=superuser_token_headers,
        files={"file": ("sounds.csv", content, "text/csv")},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == data["succeeded"] == 1
    assert data["committed"] is True
    created = db.exec(
        select(SoundClassification).where(
            SoundClassification.soundscape_component == "reimport-component"
        )
    ).all()
    assert len(created) == 1


def test_import_rejects_row_width_mismatch(
    client: TestClient,
    superuser_token_headers: dict,
    db: Session,
) -> None:
    # Header has 2 columns; the data row has 3 -> column shift, must 422.
    before = len(db.exec(select(SoundClassification)).all())
    content = b"soundscape_component,sound_type\nbiophony,call,extra\n"
    response = client.post(
        f"{BASE}/imports",
        headers=superuser_token_headers,
        files={"file": ("sounds.csv", content, "text/csv")},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["committed"] is False
    assert data["failed"] == 1
    assert "expected 2 columns" in data["rows"][0]["reason"]
    assert len(db.exec(select(SoundClassification)).all()) == before


def test_import_rejects_unclosed_quote(
    client: TestClient,
    superuser_token_headers: dict,
    db: Session,
) -> None:
    # Unclosed quote on row 1 swallows row 2 into one record -> rejected.
    before = len(db.exec(select(SoundClassification)).all())
    content = (
        b"soundscape_component,sound_type\n"
        b'biophony,"call\n'
        b"anthropophony,engine\n"
    )
    response = client.post(
        f"{BASE}/imports",
        headers=superuser_token_headers,
        files={"file": ("sounds.csv", content, "text/csv")},
    )
    # Rejected either by the strict pre-guard (400) or the classification parser (422).
    assert response.status_code in (400, 422)
    assert len(db.exec(select(SoundClassification)).all()) == before


def test_import_skips_duplicate_rows_and_creates_one_record(
    client: TestClient,
    superuser_token_headers: dict,
    db: Session,
) -> None:
    before = len(db.exec(select(SoundClassification)).all())
    content = (
        b"soundscape_component,sound_type\n"
        b"duplicate-component,duplicate-type\n"
        b" duplicate-component , duplicate-type \n"
    )

    response = client.post(
        f"{BASE}/imports",
        headers=superuser_token_headers,
        files={"file": ("sounds.csv", content, "text/csv")},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["committed"] is True
    assert data["succeeded"] == 1
    assert data["skipped"] == 1
    assert data["rows"][1]["reason"] == "Duplicate sound classification in file"
    assert len(db.exec(select(SoundClassification)).all()) == before + 1


def test_import_rejects_bad_files_and_rolls_back(
    client: TestClient,
    superuser_token_headers: dict,
    db: Session,
) -> None:
    before = db.exec(select(SoundClassification)).all()
    invalid = (
        b"soundscape_component,sound_type\n"
        b"rollback-component,valid\n"
        b",invalid\n"
    )

    response = client.post(
        f"{BASE}/imports",
        headers=superuser_token_headers,
        files={"file": ("sounds.csv", invalid, "text/csv")},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["committed"] is False
    assert data["failed"] == 2
    assert data["rows"][1]["field"] == "soundscape_component"
    assert len(db.exec(select(SoundClassification)).all()) == len(before)
    assert client.post(
        f"{BASE}/imports",
        headers=superuser_token_headers,
        files={"file": ("sounds.txt", b"x", "text/plain")},
    ).status_code == 400
    invalid_header = client.post(
        f"{BASE}/imports",
        headers=superuser_token_headers,
        files={"file": ("sounds.csv", b"wrong,header\na,b\n", "text/csv")},
    )
    assert invalid_header.status_code == 200
    invalid_data = invalid_header.json()["data"]
    assert invalid_data["global_errors"]
    assert invalid_data["total"] == 1
    assert invalid_data["failed"] == 1


def test_export_uses_schema_headers_and_order(
    client: TestClient,
    superuser_token_headers: dict,
    db: Session,
) -> None:
    first = _create_sound(db, "export-test", "a")
    second = _create_sound(db, "export-test", "b")

    response = client.get(
        f"{BASE}/exports?order_by=sound_id&order_dir=desc",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        'attachment; filename="sound-classifications.csv"; '
        "filename*=UTF-8''sound-classifications.csv"
    )
    rows = read_csv_rows(response.text)
    assert rows[0] == ["sound_id", "soundscape_component", "sound_type"]
    exported = [row for row in rows[1:] if int(row[0]) in {first.sound_id, second.sound_id}]
    assert [int(row[0]) for row in exported] == [second.sound_id, first.sound_id]
