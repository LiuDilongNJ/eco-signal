"""
Tests for licenses API routes.
"""
from fastapi.testclient import TestClient

from app.core.config import settings


class TestLicenseOptions:
    """Tests for GET /license-options endpoint."""
    
    def test_get_options(self, client: TestClient) -> None:
        """Get license options - no auth required."""
        r = client.get(f"{settings.API_V1_STR}/license-options")
        assert r.status_code == 200
        json_resp = r.json()
        assert json_resp["code"] == 0
        options = json_resp["data"]
        
        assert isinstance(options, list)
        # Verify structure if any options exist
        if options:
            for opt in options:
                assert "license_id" in opt
                assert "name" in opt
