"""Tests for models API routes."""
from fastapi.testclient import TestClient

from app.api.routes.models import _resolve_model_version
from app.core.config import settings


class TestModelsApi:
    """Tests for /models endpoints."""

    def test_list_models(self, client: TestClient) -> None:
        """Get models list with versions."""
        r = client.get(f"{settings.API_V1_STR}/models")
        assert r.status_code == 200
        json_resp = r.json()
        assert json_resp["code"] == 0
        models = json_resp["data"]

        assert isinstance(models, list)
        assert len(models) >= 2

        model_names = [m["name"] for m in models]
        assert any("birdnet" in name.lower() for name in model_names)
        assert any("batdetect" in name.lower() for name in model_names)

        # Ensure all models have versions
        for m in models:
            assert "model_id" in m
            assert "name" in m
            assert "version" in m
            assert m["version"] is not None

    def test_get_model_detail_success(self, client: TestClient) -> None:
        """Get model by ID."""
        r = client.get(f"{settings.API_V1_STR}/models/1")
        assert r.status_code == 200
        json_resp = r.json()
        assert json_resp["code"] == 0
        model = json_resp["data"]
        assert model["model_id"] == 1
        assert "BirdNET" in model["name"]
        assert model["version"] == "2.4"

    def test_get_model_detail_not_found(self, client: TestClient) -> None:
        """Get non-existent model returns 404."""
        r = client.get(f"{settings.API_V1_STR}/models/999999")
        assert r.status_code == 404


def test_resolve_model_version_fallback() -> None:
    """Test version resolution with and without DB version."""
    assert _resolve_model_version("BirdNET-Analyzer", "3.0") == "3.0"
    assert _resolve_model_version("BirdNET-Analyzer", None) == "2.4"
    assert _resolve_model_version("batdetect2", None) is not None
    assert _resolve_model_version("unknown_custom_model", None) is None
