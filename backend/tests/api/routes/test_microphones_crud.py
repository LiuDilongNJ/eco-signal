"""
Tests for Microphone CRUD endpoints.

Covers: list, create, get, update, delete, options, permissions.
"""
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models.device import Microphone, Sensor
from tests.utils.csv import read_csv_rows

BASE = f"{settings.API_V1_STR}/microphones"
OPTIONS = f"{settings.API_V1_STR}/microphone-options"


# Helpers

def _make_microphone(db: Session, name: str = "SMM-A2", element: str = "Electret") -> Microphone:
    obj = Microphone(name=name, microphone_element=element, sensitivity=-35, signal_to_noise_ratio=80)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


# GET /microphone-options  (public)

class TestMicrophoneOptions:
    def test_options_public(self, client: TestClient, db: Session) -> None:
        _make_microphone(db, "OptionMic")
        r = client.get(OPTIONS)
        assert r.status_code == 200
        data = r.json()["data"]
        assert any(item["name"] == "OptionMic" for item in data)

    def test_options_filter_by_recorder(self, client: TestClient, db: Session) -> None:
        """Filter by recorder_id returns only associated microphones."""
        from app.models.device import Recorder, RecorderMicrophone
        recorder = Recorder(name="FilterRecorder")
        db.add(recorder)
        db.commit()
        db.refresh(recorder)
        mic = _make_microphone(db, "FilteredMic")
        assoc = RecorderMicrophone(recorder_id=recorder.recorder_id, microphone_id=mic.microphone_id)
        db.add(assoc)
        db.commit()
        r = client.get(f"{OPTIONS}?recorder_id={recorder.recorder_id}")
        assert r.status_code == 200
        data = r.json()["data"]
        assert all(item["microphone_id"] == mic.microphone_id for item in data)


# GET /microphones  (admin)

class TestListMicrophones:
    def test_list_requires_auth(self, client: TestClient) -> None:
        r = client.get(BASE)
        assert r.status_code in (401, 403)

    def test_list_normal_user_forbidden(self, client: TestClient, normal_user_token_headers: dict) -> None:
        r = client.get(BASE, headers=normal_user_token_headers)
        assert r.status_code == 403

    def test_list_admin(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        _make_microphone(db)
        r = client.get(BASE, headers=superuser_token_headers)
        assert r.status_code == 200
        assert r.json()["page_info"]["total"] >= 1

    def test_list_omits_recorder_relationship_fields(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        microphone = _make_microphone(db, "NoRelationshipFieldsMic")

        r = client.get(f"{BASE}?microphone_id={microphone.microphone_id}", headers=superuser_token_headers)

        assert r.status_code == 200
        item = r.json()["data"][0]
        assert "recorder_count" not in item
        assert "recorders" not in item

    def test_list_filter_by_microphone_id_and_uuid(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        target = _make_microphone(db, "TargetMic", "MEMS")
        _make_microphone(db, "OtherMic", "Electret")
        r = client.get(
            f"{BASE}?microphone_id={target.microphone_id}&uuid={target.uuid}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["microphone_id"] == target.microphone_id

    def test_list_filter_microphone_id_with_range(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        target = _make_microphone(db, "RangeTarget", "Electret")
        target.sensitivity = -35
        target.signal_to_noise_ratio = 80
        other = _make_microphone(db, "RangeOther", "Electret")
        other.sensitivity = -20
        other.signal_to_noise_ratio = 40
        db.add(target)
        db.add(other)
        db.commit()
        db.refresh(target)
        db.refresh(other)

        r = client.get(
            f"{BASE}?microphone_id={target.microphone_id}&sensitivity=-36,-34",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["microphone_id"] == target.microphone_id

    def test_list_invalid_uuid_is_ignored(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        _make_microphone(db, "UuidIgnoredMic")
        r = client.get(f"{BASE}?uuid=not-a-uuid", headers=superuser_token_headers)
        assert r.status_code == 200
        assert r.json()["page_info"]["total"] >= 1

    def test_list_sort_by_microphone_element(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        alpha = _make_microphone(db, "AlphaElementMic", "Alpha")
        beta = _make_microphone(db, "BetaElementMic", "Beta")

        r = client.get(
            f"{BASE}?order_by=microphone_element&order_dir=asc&page_size=100",
            headers=superuser_token_headers,
        )

        assert r.status_code == 200
        items = [item for item in r.json()["data"] if item["microphone_id"] in {alpha.microphone_id, beta.microphone_id}]
        assert items[0]["microphone_id"] == alpha.microphone_id
        assert items[1]["microphone_id"] == beta.microphone_id


class TestExportMicrophones:
    def test_export_microphones_with_filters(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        mic = _make_microphone(db, "ExportMic", "MEMS")

        r = client.get(
            f"{BASE}/exports?microphone_id={mic.microphone_id}&uuid={mic.uuid}&sensitivity=-36,-34&signal_to_noise_ratio=79,81",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        assert r.headers.get("content-disposition") == (
            'attachment; filename="microphones.csv"; '
            "filename*=UTF-8''microphones.csv"
        )
        rows = read_csv_rows(r.text)
        assert rows[0] == ["microphone_id", "uuid", "name", "microphone_element", "sensitivity", "signal_to_noise_ratio"]
        assert len(rows) == 2
        assert rows[1][0] == str(mic.microphone_id)
        assert rows[1][-1] == "80"

# POST /microphones/imports  (admin)

class TestImportMicrophones:
    def test_import_requires_auth(self, client: TestClient) -> None:
        r = client.post(
            f"{BASE}/imports",
            files={"file": ("microphones.csv", "name,microphone_element,sensitivity,signal_to_noise_ratio\nMic,,,\n", "text/csv")},
        )
        assert r.status_code in (401, 403)

    def test_import_requires_admin(
        self, client: TestClient, normal_user_token_headers: dict
    ) -> None:
        r = client.post(
            f"{BASE}/imports",
            headers=normal_user_token_headers,
            files={"file": ("microphones.csv", "name,microphone_element,sensitivity,signal_to_noise_ratio\nMic,,,\n", "text/csv")},
        )
        assert r.status_code == 403

    def test_import_creates_microphone_with_values(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        content = (
            "name,microphone_element,sensitivity,signal_to_noise_ratio\n"
            "Import Values Mic,MEMS,-42,65\n"
        )
        r = client.post(
            f"{BASE}/imports",
            headers=superuser_token_headers,
            data={"dry_run": "false"},
            files={"file": ("microphones.csv", content, "text/csv")},
        )
        assert r.status_code == 200
        assert r.json()["data"]["committed"] is True
        assert r.json()["data"]["succeeded"] == 1
        mic = db.exec(
            select(Microphone).where(Microphone.name == "Import Values Mic")
        ).one()
        assert mic.microphone_element == "MEMS"
        assert mic.sensitivity == -42
        assert mic.signal_to_noise_ratio == 65

    def test_import_exported_csv_with_blank_numeric_cells(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        # Exported CSV of microphones without sensitivity/SNR carries extra
        # display columns and blank numeric cells; both must import cleanly.
        content = (
            "microphone_id,uuid,name,microphone_element,sensitivity,signal_to_noise_ratio\n"
            "7,abc-uuid,Reimport Blank Mic,,,\n"
        )
        r = client.post(
            f"{BASE}/imports",
            headers=superuser_token_headers,
            data={"dry_run": "false"},
            files={"file": ("microphones.csv", content, "text/csv")},
        )
        assert r.status_code == 200
        assert r.json()["data"]["committed"] is True
        assert r.json()["data"]["succeeded"] == 1
        mic = db.exec(
            select(Microphone).where(Microphone.name == "Reimport Blank Mic")
        ).one()
        assert mic.microphone_element is None
        assert mic.sensitivity is None
        assert mic.signal_to_noise_ratio is None

    def test_import_rejects_non_numeric_sensitivity(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        content = (
            "name,microphone_element,sensitivity,signal_to_noise_ratio\n"
            "Bad Sensitivity Mic,,abc,\n"
        )
        r = client.post(
            f"{BASE}/imports",
            headers=superuser_token_headers,
            data={"dry_run": "false"},
            files={"file": ("microphones.csv", content, "text/csv")},
        )
        assert r.status_code == 200
        assert r.json()["data"]["committed"] is False
        assert r.json()["data"]["rows"][0]["field"] == "sensitivity"
        assert db.exec(
            select(Microphone).where(Microphone.name == "Bad Sensitivity Mic")
        ).all() == []

    def test_import_rejects_existing_microphone_name(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        _make_microphone(db, "Import Existing Mic")
        content = (
            "name,microphone_element,sensitivity,signal_to_noise_ratio\n"
            " import existing mic ,Electret,-35,80\n"
        )
        r = client.post(
            f"{BASE}/imports",
            headers=superuser_token_headers,
            data={"dry_run": "false"},
            files={"file": ("microphones.csv", content, "text/csv")},
        )
        assert r.status_code == 200
        assert r.json()["data"]["committed"] is True
        assert r.json()["data"]["skipped"] == 1
        assert "Microphone name already exists" in r.json()["data"]["rows"][0]["reason"]

    def test_import_rejects_conflicting_existing_microphone_name(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        _make_microphone(db, "Import Conflicting Mic")
        content = (
            "name,microphone_element,sensitivity,signal_to_noise_ratio\n"
            "Import Conflicting Mic,condenser,12,80\n"
        )

        response = client.post(
            f"{BASE}/imports",
            headers=superuser_token_headers,
            files={"file": ("microphones.csv", content, "text/csv")},
        )

        result = response.json()["data"]
        assert response.status_code == 200
        assert result["committed"] is False
        assert result["failed"] == 1
        assert "conflicts with an existing record" in result["rows"][0]["reason"]

    def test_import_rejects_duplicate_names_within_file(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        content = (
            "name,microphone_element,sensitivity,signal_to_noise_ratio\n"
            "Import Duplicate Mic,,,\n"
            " import duplicate mic ,,,\n"
        )
        r = client.post(
            f"{BASE}/imports",
            headers=superuser_token_headers,
            data={"dry_run": "false"},
            files={"file": ("microphones.csv", content, "text/csv")},
        )
        assert r.status_code == 200
        assert r.json()["data"]["committed"] is True
        assert r.json()["data"]["succeeded"] == 1
        assert r.json()["data"]["skipped"] == 1
        assert db.exec(
            select(Microphone).where(Microphone.name == "Import Duplicate Mic")
        ).one()


# POST /microphones  (admin)

class TestCreateMicrophone:
    def test_create_requires_auth(self, client: TestClient) -> None:
        r = client.post(BASE, json={"name": "X"})
        assert r.status_code in (401, 403)

    def test_create_normal_user_forbidden(self, client: TestClient, normal_user_token_headers: dict) -> None:
        r = client.post(BASE, headers=normal_user_token_headers, json={"name": "X"})
        assert r.status_code == 403

    def test_create_success(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        payload = {
            "name": "NewMic",
            "microphone_element": "MEMS",
            "sensitivity": -42,
            "signal_to_noise_ratio": 65,
        }
        r = client.post(BASE, headers=superuser_token_headers, json=payload)
        assert r.status_code == 200
        assert r.json()["data"] is None
        mic = db.exec(select(Microphone).where(Microphone.name == "NewMic").order_by(Microphone.microphone_id.desc())).first()
        assert mic is not None
        assert mic.sensitivity == -42
        assert mic.uuid is not None

    def test_create_requires_name(self, client: TestClient, superuser_token_headers: dict) -> None:
        r = client.post(BASE, headers=superuser_token_headers, json={})
        assert r.status_code == 422
        assert r.json()["message"] == "name is required"


# GET /microphones/{microphone_id}  (admin)

class TestGetMicrophone:
    def test_get_requires_auth(self, client: TestClient, db: Session) -> None:
        microphone = _make_microphone(db, "PrivateMic")
        r = client.get(f"{BASE}/{microphone.microphone_id}")
        assert r.status_code in (401, 403)

    def test_get_normal_user_forbidden(
        self, client: TestClient, normal_user_token_headers: dict, db: Session
    ) -> None:
        microphone = _make_microphone(db, "RestrictedMic")
        r = client.get(f"{BASE}/{microphone.microphone_id}", headers=normal_user_token_headers)
        assert r.status_code == 403

    def test_get_not_found(self, client: TestClient, superuser_token_headers: dict) -> None:
        r = client.get(f"{BASE}/999999", headers=superuser_token_headers)
        assert r.status_code == 404

    def test_get_success(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        obj = _make_microphone(db)
        r = client.get(f"{BASE}/{obj.microphone_id}", headers=superuser_token_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["microphone_id"] == obj.microphone_id
        assert data["name"] == obj.name
        assert data["microphone_element"] == obj.microphone_element
        assert "recorders" not in data


# PUT /microphones/{microphone_id}  (admin)

class TestUpdateMicrophone:
    def test_update_not_found(self, client: TestClient, superuser_token_headers: dict) -> None:
        r = client.put(f"{BASE}/999999", headers=superuser_token_headers, json={"name": "X"})
        assert r.status_code == 404

    def test_update_success(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        obj = _make_microphone(db)
        r = client.put(
            f"{BASE}/{obj.microphone_id}",
            headers=superuser_token_headers,
            json={"name": "Updated Mic", "sensitivity": -40},
        )
        assert r.status_code == 200
        assert r.json()["data"] is None
        db.refresh(obj)
        assert obj.name == "Updated Mic"
        assert obj.sensitivity == -40

    def test_update_null_clears_fields_and_omitted_field_is_preserved(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        obj = _make_microphone(db)
        obj.microphone_element = "Condenser"
        obj.sensitivity = -42
        obj.signal_to_noise_ratio = 80
        db.add(obj)
        db.commit()

        r = client.put(
            f"{BASE}/{obj.microphone_id}",
            headers=superuser_token_headers,
            json={"microphone_element": None, "sensitivity": None},
        )

        assert r.status_code == 200
        db.refresh(obj)
        assert obj.microphone_element is None
        assert obj.sensitivity is None
        assert obj.signal_to_noise_ratio == 80


# DELETE /microphones/{microphone_id}  (admin)

class TestDeleteMicrophone:
    def test_delete_not_found(self, client: TestClient, superuser_token_headers: dict) -> None:
        r = client.delete(f"{BASE}/999999", headers=superuser_token_headers)
        assert r.status_code == 404

    def test_delete_success(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        obj = _make_microphone(db, "DeleteMic")
        r = client.delete(f"{BASE}/{obj.microphone_id}", headers=superuser_token_headers)
        assert r.status_code == 200
        r2 = client.get(f"{BASE}/{obj.microphone_id}", headers=superuser_token_headers)
        assert r2.status_code == 404

    def test_delete_in_use_rejected(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        from app.models.device import Recorder
        mic = _make_microphone(db, "UsedMic")
        recorder = Recorder(name="RecForMic")
        db.add(recorder)
        db.commit()
        db.refresh(recorder)
        sensor = Sensor(name="S1", sensor_type="audio",
                        microphone_id=mic.microphone_id, recorder_id=recorder.recorder_id)
        db.add(sensor)
        db.commit()
        r = client.delete(f"{BASE}/{mic.microphone_id}", headers=superuser_token_headers)
        assert r.status_code == 400
