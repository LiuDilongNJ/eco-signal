from app.main import app


def test_tabular_import_route_coverage() -> None:
    route_paths = {route.path for route in app.routes}

    assert {
        "/api/v1/projects/imports",
        "/api/v1/collections/imports",
        "/api/v1/sites/imports",
        "/api/v1/media/imports",
        "/api/v1/annotations/imports",
        "/api/v1/reviews/imports",
        "/api/v1/index-logs/imports",
        "/api/v1/tasks/imports",
        "/api/v1/users/imports",
        "/api/v1/recorders/imports",
        "/api/v1/microphones/imports",
        "/api/v1/cameras/imports",
        "/api/v1/lenses/imports",
        "/api/v1/taxons/imports",
        "/api/v1/sound-classification-records/imports",
    }.issubset(route_paths)

    assert "/api/v1/queues/imports" not in route_paths
    assert "/api/v1/media-metadata-imports" not in route_paths
    assert "/api/v1/data-imports" in route_paths
