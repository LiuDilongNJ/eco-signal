"""
Tests for microphones API routes.
"""
from fastapi.testclient import TestClient

from app.core.config import settings


class TestMicrophoneOptions:
    """Tests for GET /microphone-options endpoint."""
    
    def test_get_options(self, client: TestClient) -> None:
        """Get microphone options - no auth required."""
        r = client.get(f"{settings.API_V1_STR}/microphone-options")
        assert r.status_code == 200
        json_resp = r.json()
        assert json_resp["code"] == 0
        options = json_resp["data"]
        
        assert isinstance(options, list)
        # Verify structure if any options exist
        if options:
            for opt in options:
                assert "microphone_id" in opt
                assert "name" in opt
    
    def test_get_options_with_recorder_filter(self, client: TestClient) -> None:
        """Get microphone options filtered by recorder_id."""
        r = client.get(f"{settings.API_V1_STR}/microphone-options?recorder_id=1")
        assert r.status_code == 200
        json_resp = r.json()
        assert json_resp["code"] == 0
        options = json_resp["data"]
        
        assert isinstance(options, list)
