from pathlib import Path


def test_project_seed_data_uses_empty_string_for_url() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    data_sql = repo_root / "app" / "alembic" / "data.sql"
    content = data_sql.read_text(encoding="utf-8")

    assert "INSERT INTO project (project_id, name, creator_id, url, description, description_short, public, active)" in content
    assert "VALUES (1, 'Demo Project', 1, '', 'This is a demo project." in content


def test_project_table_defaults_url_to_empty_string() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    app_sql = repo_root / "app" / "alembic" / "app.sql"
    content = app_sql.read_text(encoding="utf-8")

    assert "url VARCHAR(255) NOT NULL DEFAULT ''" in content
