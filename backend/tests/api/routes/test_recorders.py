"""
Tests for recorders API routes.
"""
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import Recorder


class TestRecorderOptions:
    """Tests for GET /recorder-options endpoint."""
    
    def test_get_options(self, client: TestClient) -> None:
        """Get recorder options - no auth required."""
        r = client.get(f"{settings.API_V1_STR}/recorder-options")
        assert r.status_code == 200
        json_resp = r.json()
        assert json_resp["code"] == 0
        options = json_resp["data"]
        
        assert isinstance(options, list)
        # Verify structure if any options exist
        if options:
            for opt in options:
                assert "recorder_id" in opt
                assert "name" in opt


class TestRecorderImports:
    def test_txt_json_dry_run_then_commit(
        self,
        client: TestClient,
        superuser_token_headers: dict[str, str],
        db: Session,
    ) -> None:
        name = "TXT JSON Recorder Import"
        source = f'[{{"name":"{name}","version":"1","brand":"Example"}}]'.encode()

        validation = client.post(
            f"{settings.API_V1_STR}/recorders/imports",
            headers=superuser_token_headers,
            data={"dry_run": "true"},
            files={"file": ("recorders.txt", source, "text/plain")},
        )

        assert validation.status_code == 200
        validation_data = validation.json()["data"]
        assert validation_data["source_format"] == "json"
        assert validation_data["succeeded"] == 1
        assert validation_data["committed"] is False
        assert db.exec(select(Recorder).where(Recorder.name == name)).first() is None

        committed = client.post(
            f"{settings.API_V1_STR}/recorders/imports",
            headers=superuser_token_headers,
            data={"dry_run": "false"},
            files={"file": ("recorders.txt", source, "text/plain")},
        )

        assert committed.status_code == 200
        assert committed.json()["data"]["committed"] is True
        assert db.exec(select(Recorder).where(Recorder.name == name)).first() is not None

    def test_semicolon_text_is_detected(
        self,
        client: TestClient,
        superuser_token_headers: dict[str, str],
    ) -> None:
        response = client.post(
            f"{settings.API_V1_STR}/recorders/imports",
            headers=superuser_token_headers,
            data={"dry_run": "true"},
            files={
                "file": (
                    "recorders.txt",
                    b"name;version;brand\nSemicolon Recorder;1;Example\n",
                    "text/plain",
                )
            },
        )

        assert response.status_code == 200
        assert response.json()["data"]["delimiter"] == ";"
