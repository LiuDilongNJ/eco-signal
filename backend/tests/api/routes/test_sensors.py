"""
Tests for sensors API routes.
"""
from fastapi.testclient import TestClient

from app.core.config import settings


class TestSensorOptions:
    """Tests for GET /sensor-options endpoint."""
    
    def test_get_options(self, client: TestClient) -> None:
        """Get sensor options - no auth required."""
        r = client.get(f"{settings.API_V1_STR}/sensor-options")
        assert r.status_code == 200
        json_resp = r.json()
        assert json_resp["code"] == 0
        options = json_resp["data"]
        
        assert isinstance(options, list)
        # Verify structure if any options exist
        if options:
            for opt in options:
                assert "sensor_id" in opt
                assert "name" in opt
                assert "serial_number" in opt
