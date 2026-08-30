"""
Tests for Recorder CRUD endpoints and recorder-microphone association management.

Covers: list, create, get, update, delete, add/remove microphone associations, options, permissions.
"""
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models.device import Microphone, Recorder, RecorderMicrophone, Sensor
from tests.utils.csv import read_csv_rows

BASE = f"{settings.API_V1_STR}/recorders"
OPTIONS = f"{settings.API_V1_STR}/recorder-options"


# Helpers

def _make_recorder(db: Session, name: str = "SM4", brand: str = "Wildlife Acoustics") -> Recorder:
    obj = Recorder(name=name, brand=brand)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def _make_microphone(db: Session, name: str = "SMM-A2") -> Microphone:
    obj = Microphone(name=name)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


# GET /recorder-options  (public)

class TestRecorderOptions:
    def test_options_public(self, client: TestClient, db: Session) -> None:
        _make_recorder(db, "OptionRecorder")
        r = client.get(OPTIONS)
        assert r.status_code == 200
        data = r.json()["data"]
        assert any(item["name"] == "OptionRecorder" for item in data)


# GET /recorders  (admin)

class TestListRecorders:
    def test_list_requires_auth(self, client: TestClient) -> None:
        r = client.get(BASE)
        assert r.status_code in (401, 403)

    def test_list_normal_user_forbidden(self, client: TestClient, normal_user_token_headers: dict) -> None:
        r = client.get(BASE, headers=normal_user_token_headers)
        assert r.status_code == 403

    def test_list_admin(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        _make_recorder(db)
        r = client.get(BASE, headers=superuser_token_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0
        assert body["page_info"]["total"] >= 1

    def test_list_includes_microphone_count(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        recorder = _make_recorder(db, "CountRecorder")
        mic = _make_microphone(db, "CountMic")
        assoc = RecorderMicrophone(recorder_id=recorder.recorder_id, microphone_id=mic.microphone_id)
        db.add(assoc)
        db.commit()
        r = client.get(
            f"{BASE}?recorder_id={recorder.recorder_id}",
            headers=superuser_token_headers,
        )
        items = r.json()["data"]
        found = next((i for i in items if i["recorder_id"] == recorder.recorder_id), None)
        assert found is not None
        assert found["microphone_count"] == 1

    def test_list_filter_by_recorder_id_and_uuid(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        target = _make_recorder(db, "TargetRecorder", "BrandA")
        _make_recorder(db, "OtherRecorder", "BrandB")
        r = client.get(
            f"{BASE}?recorder_id={target.recorder_id}&uuid={target.uuid}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["recorder_id"] == target.recorder_id

    def test_list_filter_by_microphone_count(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        rec0 = _make_recorder(db, "Rec0")
        rec1 = _make_recorder(db, "Rec1")
        rec2 = _make_recorder(db, "Rec2")
        mic1 = _make_microphone(db, "Mic1")
        mic2 = _make_microphone(db, "Mic2")
        mic3 = _make_microphone(db, "Mic3")
        db.add(RecorderMicrophone(recorder_id=rec1.recorder_id, microphone_id=mic1.microphone_id))
        db.add(RecorderMicrophone(recorder_id=rec2.recorder_id, microphone_id=mic2.microphone_id))
        db.add(RecorderMicrophone(recorder_id=rec2.recorder_id, microphone_id=mic3.microphone_id))
        db.commit()

        r = client.get(f"{BASE}?microphone_count=2", headers=superuser_token_headers)
        assert r.status_code == 200
        ids = [item["recorder_id"] for item in r.json()["data"]]
        assert rec2.recorder_id in ids
        assert rec1.recorder_id not in ids
        assert rec0.recorder_id not in ids

    def test_list_filter_by_recorder_id_uuid_and_microphone_count(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        target = _make_recorder(db, "ComboRecorder")
        mic = _make_microphone(db, "ComboMic")
        db.add(RecorderMicrophone(recorder_id=target.recorder_id, microphone_id=mic.microphone_id))
        db.commit()
        r = client.get(
            f"{BASE}?recorder_id={target.recorder_id}&uuid={target.uuid}&microphone_count=1",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["recorder_id"] == target.recorder_id

    def test_list_sort_by_microphone_count_desc(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        low = _make_recorder(db, "SortMicCountLow")
        high = _make_recorder(db, "SortMicCountHigh")
        mic1 = _make_microphone(db, "SortMicCount1")
        mic2 = _make_microphone(db, "SortMicCount2")
        mic3 = _make_microphone(db, "SortMicCount3")
        mic4 = _make_microphone(db, "SortMicCount4")
        mic5 = _make_microphone(db, "SortMicCount5")
        mic6 = _make_microphone(db, "SortMicCount6")
        mic7 = _make_microphone(db, "SortMicCount7")
        db.add(RecorderMicrophone(recorder_id=low.recorder_id, microphone_id=mic1.microphone_id))
        db.add(RecorderMicrophone(recorder_id=low.recorder_id, microphone_id=mic2.microphone_id))
        db.add(RecorderMicrophone(recorder_id=low.recorder_id, microphone_id=mic3.microphone_id))
        db.add(RecorderMicrophone(recorder_id=high.recorder_id, microphone_id=mic4.microphone_id))
        db.add(RecorderMicrophone(recorder_id=high.recorder_id, microphone_id=mic5.microphone_id))
        db.add(RecorderMicrophone(recorder_id=high.recorder_id, microphone_id=mic1.microphone_id))
        db.add(RecorderMicrophone(recorder_id=high.recorder_id, microphone_id=mic6.microphone_id))
        db.add(RecorderMicrophone(recorder_id=high.recorder_id, microphone_id=mic7.microphone_id))
        db.commit()

        r = client.get(
            f"{BASE}?order_by=microphone_count&order_dir=desc&page_size=100",
            headers=superuser_token_headers,
        )

        assert r.status_code == 200
        items = [item for item in r.json()["data"] if item["recorder_id"] in {low.recorder_id, high.recorder_id}]
        assert items[0]["recorder_id"] == high.recorder_id
        assert items[0]["microphone_count"] > items[1]["microphone_count"]

    def test_list_invalid_uuid_is_ignored(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        _make_recorder(db, "UuidIgnoredRecorder")
        r = client.get(f"{BASE}?uuid=not-a-uuid", headers=superuser_token_headers)
        assert r.status_code == 200
        assert r.json()["page_info"]["total"] >= 1


class TestExportRecorders:
    def test_export_recorders_with_filters(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        recorder = _make_recorder(db, "ExportRecorder", "ExportBrand")
        mic = _make_microphone(db, "ExportRecorderMic")
        db.add(
            RecorderMicrophone(
                recorder_id=recorder.recorder_id,
                microphone_id=mic.microphone_id,
                notes="Primary rig",
            )
        )
        db.commit()

        r = client.get(
            f"{BASE}/exports?recorder_id={recorder.recorder_id}&uuid={recorder.uuid}&microphone_count=1&order_by=brand",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        assert r.headers.get("content-disposition") == (
            'attachment; filename="recorders.csv"; '
            "filename*=UTF-8''recorders.csv"
        )
        rows = read_csv_rows(r.text)
        assert rows[0] == ["recorder_id", "uuid", "name", "version", "brand", "microphone_names"]
        assert len(rows) == 2
        assert rows[1][0] == str(recorder.recorder_id)
        assert rows[1][5] == "ExportRecorderMic (Primary rig)"


# POST /recorders/imports  (admin)

class TestImportRecorders:
    def test_import_requires_admin(
        self, client: TestClient, normal_user_token_headers: dict
    ) -> None:
        response = client.post(
            f"{BASE}/imports",
            headers=normal_user_token_headers,
            files={"file": ("recorders.csv", "name,version,brand\nSM4,4.0,WA\n", "text/csv")},
        )
        assert response.status_code == 403

    def test_import_creates_recorder(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        content = (
            "name,version,brand\n"
            "Template Import SM4,4.0,Wildlife Acoustics\n"
        )

        response = client.post(
            f"{BASE}/imports",
            headers=superuser_token_headers,
            data={"dry_run": "false"},
            files={"file": ("recorders.csv", content, "text/csv")},
        )

        assert response.status_code == 200
        assert response.json()["data"]["committed"] is True
        assert response.json()["data"]["succeeded"] == 1
        recorder = db.exec(
            select(Recorder).where(Recorder.name == "Template Import SM4")
        ).one()
        assert recorder.version == "4.0"
        assert recorder.brand == "Wildlife Acoustics"
        # Import no longer creates microphone associations; sensors link manually.
        links = db.exec(
            select(RecorderMicrophone).where(
                RecorderMicrophone.recorder_id == recorder.recorder_id
            )
        ).all()
        assert links == []

    def test_import_rejects_normalized_duplicate_recorder_names(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        content = (
            "name,version,brand\n"
            "Import Duplicate Recorder A,,\n"
            " import duplicate recorder a ,,\n"
        )
        response = client.post(
            f"{BASE}/imports",
            headers=superuser_token_headers,
            data={"dry_run": "false"},
            files={"file": ("recorders.csv", content, "text/csv")},
        )
        assert response.status_code == 200
        assert response.json()["data"]["committed"] is True
        assert response.json()["data"]["succeeded"] == 1
        assert response.json()["data"]["skipped"] == 1
        imported = db.exec(
            select(Recorder).where(Recorder.name == "Import Duplicate Recorder A")
        ).all()
        assert len(imported) == 1

    def test_import_rejects_existing_recorder_name(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        _make_recorder(db, "Import Existing Recorder")
        content = (
            "name,version,brand\n"
            " import existing recorder ,,Wildlife Acoustics\n"
        )
        response = client.post(
            f"{BASE}/imports",
            headers=superuser_token_headers,
            data={"dry_run": "false"},
            files={"file": ("recorders.csv", content, "text/csv")},
        )
        assert response.status_code == 200
        assert response.json()["data"]["committed"] is True
        assert response.json()["data"]["skipped"] == 1
        assert "Recorder name already exists" in response.json()["data"]["rows"][0]["reason"]

    def test_import_rejects_unknown_header(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        response = client.post(
            f"{BASE}/imports",
            headers=superuser_token_headers,
            data={"dry_run": "false"},
            files={
                "file": (
                    "recorders.csv",
                    "Nickname,Version,Brand\nWrong Header,1,Brand\n",
                    "text/csv",
                )
            },
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert "unrecognized column" in data["global_errors"][0]
        assert data["total"] == 1
        assert data["failed"] == 1

    def test_import_rejects_missing_required_header(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        response = client.post(
            f"{BASE}/imports",
            headers=superuser_token_headers,
            data={"dry_run": "false"},
            files={
                "file": (
                    "recorders.csv",
                    "Version,Brand\n1,Brand\n",
                    "text/csv",
                )
            },
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert "missing required column" in data["global_errors"][0]
        assert data["total"] == 1
        assert data["failed"] == 1

    def test_import_tolerates_exported_columns(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        # An exported recorder CSV carries extra display columns (ID, UUID,
        # relationship counts); re-importing it must ignore them, not 422.
        content = (
            "recorder_id,uuid,name,version,brand,microphone_names\n"
            "7,abc-uuid,Reimport Recorder,2.0,BrandX,Mic A [default]\n"
        )
        response = client.post(
            f"{BASE}/imports",
            headers=superuser_token_headers,
            data={"dry_run": "false"},
            files={"file": ("recorders.csv", content, "text/csv")},
        )
        assert response.status_code == 200
        created = db.exec(
            select(Recorder).where(Recorder.name == "Reimport Recorder")
        ).first()
        assert created is not None
        assert created.version == "2.0"
        assert created.brand == "BrandX"

    def test_import_rejects_row_width_mismatch(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        # Header has 3 columns; the data row has 4 -> column shift, must 422.
        before = len(db.exec(select(Recorder)).all())
        response = client.post(
            f"{BASE}/imports",
            headers=superuser_token_headers,
            data={"dry_run": "false"},
            files={
                "file": (
                    "recorders.csv",
                    "name,version,brand\nShifted,1,BrandX,extra\n",
                    "text/csv",
                )
            },
        )
        assert response.status_code == 400
        assert len(db.exec(select(Recorder)).all()) == before


# POST /recorders  (admin)

class TestCreateRecorder:
    def test_create_requires_auth(self, client: TestClient) -> None:
        r = client.post(BASE, json={"name": "X"})
        assert r.status_code in (401, 403)

    def test_create_normal_user_forbidden(self, client: TestClient, normal_user_token_headers: dict) -> None:
        r = client.post(BASE, headers=normal_user_token_headers, json={"name": "X"})
        assert r.status_code == 403

    def test_create_success(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        payload = {"name": "AudioMoth", "version": "1.2", "brand": "Open Acoustic Devices"}
        r = client.post(BASE, headers=superuser_token_headers, json=payload)
        assert r.status_code == 200
        assert r.json()["data"] is None
        rec = db.exec(select(Recorder).where(Recorder.name == "AudioMoth").order_by(Recorder.recorder_id.desc())).first()
        assert rec is not None
        assert rec.brand == "Open Acoustic Devices"
        assert rec.uuid is not None

    def test_create_requires_name(self, client: TestClient, superuser_token_headers: dict) -> None:
        r = client.post(BASE, headers=superuser_token_headers, json={})
        assert r.status_code == 422


# GET /recorders/{recorder_id}  (admin)

class TestGetRecorder:
    def test_get_requires_auth(self, client: TestClient, db: Session) -> None:
        recorder = _make_recorder(db, "PrivateRecorder")
        r = client.get(f"{BASE}/{recorder.recorder_id}")
        assert r.status_code in (401, 403)

    def test_get_normal_user_forbidden(
        self, client: TestClient, normal_user_token_headers: dict, db: Session
    ) -> None:
        recorder = _make_recorder(db, "RestrictedRecorder")
        r = client.get(f"{BASE}/{recorder.recorder_id}", headers=normal_user_token_headers)
        assert r.status_code == 403

    def test_get_not_found(self, client: TestClient, superuser_token_headers: dict) -> None:
        r = client.get(f"{BASE}/999999", headers=superuser_token_headers)
        assert r.status_code == 404

    def test_get_success_with_microphones(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        recorder = _make_recorder(db, "GetRecorder")
        mic = _make_microphone(db, "GetMic")
        assoc = RecorderMicrophone(
            recorder_id=recorder.recorder_id,
            microphone_id=mic.microphone_id,
            notes="Primary microphone",
        )
        db.add(assoc)
        db.commit()
        r = client.get(f"{BASE}/{recorder.recorder_id}", headers=superuser_token_headers)
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["recorder_id"] == recorder.recorder_id
        assert len(data["microphones"]) == 1
        assert data["microphones"][0]["microphone_id"] == mic.microphone_id
        assert data["microphones"][0]["name"] == mic.name
        assert data["microphones"][0]["notes"] == "Primary microphone"

    def test_get_without_microphones_returns_empty_list(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        recorder = _make_recorder(db, "UnlinkedRecorder")
        r = client.get(f"{BASE}/{recorder.recorder_id}", headers=superuser_token_headers)
        assert r.status_code == 200
        assert r.json()["data"]["microphones"] == []


# PUT /recorders/{recorder_id}  (admin)

class TestUpdateRecorder:
    def test_update_not_found(self, client: TestClient, superuser_token_headers: dict) -> None:
        r = client.put(f"{BASE}/999999", headers=superuser_token_headers, json={"name": "X"})
        assert r.status_code == 404

    def test_update_success(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        recorder = _make_recorder(db)
        r = client.put(
            f"{BASE}/{recorder.recorder_id}",
            headers=superuser_token_headers,
            json={"name": "Updated", "version": "v3", "brand": "NewBrand"},
        )
        assert r.status_code == 200
        assert r.json()["data"] is None
        db.refresh(recorder)
        assert recorder.name == "Updated"
        assert recorder.brand == "NewBrand"

    def test_update_null_clears_field_and_omitted_field_is_preserved(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        recorder = _make_recorder(db)
        recorder.version = "Old version"
        recorder.brand = "Keep brand"
        db.add(recorder)
        db.commit()

        r = client.put(
            f"{BASE}/{recorder.recorder_id}",
            headers=superuser_token_headers,
            json={"name": "Renamed", "version": None},
        )

        assert r.status_code == 200
        db.refresh(recorder)
        assert recorder.name == "Renamed"
        assert recorder.version is None
        assert recorder.brand == "Keep brand"


# DELETE /recorders/{recorder_id}  (admin)

class TestDeleteRecorder:
    def test_delete_not_found(self, client: TestClient, superuser_token_headers: dict) -> None:
        r = client.delete(f"{BASE}/999999", headers=superuser_token_headers)
        assert r.status_code == 404

    def test_delete_success(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        recorder = _make_recorder(db, "DeleteMe")
        r = client.delete(f"{BASE}/{recorder.recorder_id}", headers=superuser_token_headers)
        assert r.status_code == 200
        r2 = client.get(f"{BASE}/{recorder.recorder_id}", headers=superuser_token_headers)
        assert r2.status_code == 404

    def test_delete_in_use_rejected(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        recorder = _make_recorder(db, "UsedRecorder")
        mic = _make_microphone(db, "UsedMicForRecorder")
        sensor = Sensor(name="S1", sensor_type="audio",
                        recorder_id=recorder.recorder_id, microphone_id=mic.microphone_id)
        db.add(sensor)
        db.commit()
        r = client.delete(f"{BASE}/{recorder.recorder_id}", headers=superuser_token_headers)
        assert r.status_code == 400


# POST /recorders/{recorder_id}/microphones  (admin)

class TestAddRecorderMicrophone:
    def test_add_association(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        recorder = _make_recorder(db, "AssocRecorder")
        mic = _make_microphone(db, "AssocMic")
        r = client.post(
            f"{BASE}/{recorder.recorder_id}/microphones",
            headers=superuser_token_headers,
            json={"microphone_id": mic.microphone_id, "notes": "primary"},
        )
        assert r.status_code == 200
        assert r.json()["data"] is None
        r2 = client.get(f"{BASE}/{recorder.recorder_id}", headers=superuser_token_headers)
        assert r2.status_code == 200
        mics = r2.json()["data"]["microphones"]
        assert any(m["microphone_id"] == mic.microphone_id for m in mics)

    def test_add_association_rejects_retired_default_field(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        recorder = _make_recorder(db, "RetiredDefaultRecorder")
        mic = _make_microphone(db, "RetiredDefaultMic")

        response = client.post(
            f"{BASE}/{recorder.recorder_id}/microphones",
            headers=superuser_token_headers,
            json={"microphone_id": mic.microphone_id, "is_default": True},
        )

        assert response.status_code == 422

    def test_add_duplicate_rejected(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        recorder = _make_recorder(db, "DupRecorder")
        mic = _make_microphone(db, "DupMic")
        assoc = RecorderMicrophone(recorder_id=recorder.recorder_id, microphone_id=mic.microphone_id)
        db.add(assoc)
        db.commit()
        r = client.post(
            f"{BASE}/{recorder.recorder_id}/microphones",
            headers=superuser_token_headers,
            json={"microphone_id": mic.microphone_id},
        )
        assert r.status_code == 400

    def test_add_recorder_not_found(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        mic = _make_microphone(db, "OrphanMic")
        r = client.post(
            f"{BASE}/999999/microphones",
            headers=superuser_token_headers,
            json={"microphone_id": mic.microphone_id},
        )
        assert r.status_code == 404

    def test_add_microphone_not_found(
        self, client: TestClient, superuser_token_headers: dict, db: Session
    ) -> None:
        recorder = _make_recorder(db, "NoMicRecorder")
        r = client.post(
            f"{BASE}/{recorder.recorder_id}/microphones",
            headers=superuser_token_headers,
            json={"microphone_id": 999999},
        )
        assert r.status_code == 404


# DELETE /recorders/{recorder_id}/microphones/{microphone_id}  (admin)

class TestRemoveRecorderMicrophone:
    def test_remove_association(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        recorder = _make_recorder(db, "RemoveRecorder")
        mic = _make_microphone(db, "RemoveMic")
        assoc = RecorderMicrophone(recorder_id=recorder.recorder_id, microphone_id=mic.microphone_id)
        db.add(assoc)
        db.commit()
        r = client.delete(
            f"{BASE}/{recorder.recorder_id}/microphones/{mic.microphone_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200

    def test_remove_not_found(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        recorder = _make_recorder(db, "RemoveNotFound")
        r = client.delete(
            f"{BASE}/{recorder.recorder_id}/microphones/999999",
            headers=superuser_token_headers,
        )
        assert r.status_code == 404
