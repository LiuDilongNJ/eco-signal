"""
Tests for recorders API routes.
"""
from fastapi.testclient import TestClient

from app.core.config import settings


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
