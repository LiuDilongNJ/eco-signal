import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest


def _load_script_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "migrate_from_biosounds.py"
    script_dir = str(script_path.parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    spec = importlib.util.spec_from_file_location("migrate_from_biosounds", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Air", "Air"),
        ("air", "Air"),
        ("AIR", "Air"),
        ("aIr", "Air"),
        ("Water", "Water"),
        ("water", "Water"),
        ("WATER", "Water"),
        ("wAtEr", "Water"),
        (None, None),
        ("0", "0"),
        ("Soil", "Soil"),
        (" air ", " air "),
    ],
)
def test_normalize_recording_medium_preserves_unknown_values(source, expected):
    module = _load_script_module()

    assert module.normalize_recording_medium(source) == expected


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.result = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.connection.queries.append((sql, params))
        normalized = " ".join(sql.split())
        if "FROM user_permission up LEFT JOIN collection c" in normalized:
            self.result = self.connection.legacy_rows
        elif "SELECT permission_id, name FROM permission" in normalized:
            self.result = self.connection.permission_rows
        elif "WITH project_collection_counts AS" in normalized:
            candidates = self.connection.full_project_write_candidates()
            if "SELECT COUNT(*) FROM user_write_counts" in normalized:
                self.result = [(len(candidates),)]
            else:
                self.result = candidates
        elif normalized == "SELECT site_id FROM site":
            self.result = [(row,) for row in self.connection.site_ids]
        elif normalized == "SELECT license_id FROM license":
            self.result = [(row,) for row in self.connection.license_ids]
        elif normalized == "SELECT collection_id FROM collection":
            self.result = [(row,) for row in self.connection.collection_ids]
        elif normalized == "SELECT project_id FROM project":
            self.result = [(row,) for row in self.connection.project_ids]
        elif normalized == "SELECT recorder_id FROM recorder":
            self.result = [(row,) for row in self.connection.recorder_ids]
        elif normalized == "SELECT microphone_id FROM microphone":
            self.result = [(row,) for row in self.connection.microphone_ids]
        elif normalized == 'SELECT user_id FROM "user"':
            self.result = [(row,) for row in self.connection.user_ids]
        elif normalized == "SELECT user_id, role_id, username, password, name, orcid, email, color, active, fft FROM user":
            self.result = self.connection.user_rows
        elif normalized == "SELECT media_id FROM media":
            self.result = [(row,) for row in self.connection.media_ids]
        elif normalized.startswith('INSERT INTO "user"'):
            self.connection.inserted_user_rows.append(params)
            self.result = []
            self.rowcount = 1
        elif normalized.startswith("INSERT INTO audio_setting"):
            self.connection.inserted_audio_settings.append(params)
            self.result = []
            self.rowcount = 1
        elif normalized.startswith("INSERT INTO media_collection"):
            self.connection.inserted_media_collections.append(params)
            self.result = []
            self.rowcount = 1
        elif normalized.startswith("INSERT INTO media"):
            self.connection.inserted_media_rows.append(params)
            self.result = []
            self.rowcount = 1
        elif normalized.startswith("INSERT INTO queue"):
            self.connection.inserted_queue_rows.append(params)
            self.result = []
            self.rowcount = 1
        elif normalized.startswith("INSERT INTO label (label_id, name, creator_id, type, creation_date)"):
            self.connection.inserted_label_rows.append(params)
            self.result = []
            self.rowcount = 1
        elif "SELECT 1 FROM project_collection" in normalized:
            self.result = [(1,)] if params in self.connection.project_collection_links else []
        elif normalized.startswith("INSERT INTO user_permission"):
            if (
                params not in self.connection.existing_user_permissions
                and params not in self.connection.inserted_user_permissions
            ):
                self.connection.inserted_user_permissions.append(params)
            self.result = []
            self.rowcount = 1
        elif normalized.startswith("INSERT INTO network_node"):
            self.connection.inserted_network_nodes.append(params)
            self.result = []
            self.rowcount = 1
        elif normalized.startswith("INSERT INTO site_project"):
            self.connection.inserted_site_projects.append(params)
            self.result = []
            self.rowcount = 1
        elif normalized.startswith("INSERT INTO recorder_microphone"):
            self.connection.inserted_recorder_microphones.append(params)
            self.result = []
            self.rowcount = 1
        elif normalized == "SELECT preview_id, filename FROM preview":
            self.result = self.connection.preview_rows
        elif "FROM information_schema.columns WHERE table_schema = DATABASE()" in normalized:
            table = params[0]
            self.result = [{"COLUMN_NAME": col} for col in self.connection.mysql_columns.get(table, [])]
        elif "FROM information_schema.columns WHERE table_schema='public'" in normalized:
            table = params[0]
            self.result = [(col,) for col in self.connection.pg_columns.get(table, [])]
        elif "FROM recording WHERE recording_id = %s" in normalized:
            self.result = self.connection.recording_rows
        elif normalized.startswith("UPDATE preview SET filename=%s WHERE preview_id=%s"):
            self.connection.updated_previews.append(params)
            self.result = []
            self.rowcount = 1
        elif "FROM media WHERE media_id = %s" in normalized:
            self.result = [self.connection.media_row] if self.connection.media_row else []
        elif "WHERE lower(r.name) = lower(%s)" in normalized:
            self.result = [(self.connection.admin_user_id,)] if self.connection.admin_user_id is not None else []
        elif "COUNT(*) FROM user_permission WHERE project_id IS NULL" in normalized:
            self.result = [(self.connection.null_project_count,)]
        elif "pc.collection_id IS NULL" in normalized:
            self.result = [(self.connection.broken_scope_count,)]
        elif "WHERE up.user_id = %s AND up.project_id = %s AND up.collection_id = %s" in normalized:
            self.result = [(self.connection.collection_scope_count,)]
        elif "collection_perm.name = 'collection:read'" in normalized:
            self.result = [(self.connection.missing_collection_read_count,)]
        elif "project_perm.name = 'project:read'" in normalized:
            self.result = [(self.connection.missing_project_read_count,)]
        elif "FROM user_effective_permissions uep" in normalized:
            self.result = [(self.connection.view_count,)]
        elif "WHERE is_metadata = TRUE" in normalized and "audio_setting_id IS NULL" in normalized:
            self.result = [(self.connection.metadata_without_audio_setting_count,)]
        elif "WHERE is_metadata = TRUE" in normalized and "photo_setting_id IS NOT NULL" in normalized:
            self.result = [(self.connection.metadata_with_photo_setting_count,)]
        elif "WHERE media_type = 'audio'" in normalized and "audio_setting_id IS NULL" in normalized:
            self.result = [(self.connection.audio_without_audio_setting_count,)]
        elif "SELECT COUNT(*) FROM network_node WHERE is_local = FALSE" in normalized:
            self.result = [(self.connection.remote_network_node_count,)]
        elif "FROM network_node WHERE app_url IS NULL OR app_url = ''" in normalized:
            self.result = [(self.connection.empty_network_url_count,)]
        elif "FROM network_node GROUP BY app_url HAVING COUNT(*) > 1" in normalized:
            self.result = [(self.connection.duplicate_network_url_count,)]
        elif "WHERE is_local = FALSE AND ( stat_users <> 0 OR stat_projects <> 0" in normalized:
            self.result = [(self.connection.non_zero_network_stats_count,)]
        elif "WHERE is_local = FALSE AND last_synced_at IS NULL" in normalized:
            self.result = [(self.connection.missing_network_synced_at_count,)]
        else:
            self.result = []

    def fetchall(self):
        return self.result

    def fetchone(self):
        return self.result[0] if self.result else None

    def close(self):
        return None


class FakeConnection:
    def __init__(self, *, legacy_rows=None, project_collection_links=None, existing_user_permissions=None):
        self.legacy_rows = legacy_rows or []
        self.project_collection_links = project_collection_links or set()
        self.existing_user_permissions = existing_user_permissions or []
        self.permission_rows = [
            (1, "project:read"),
            (2, "project:write"),
            (3, "collection:read"),
            (4, "collection:write"),
            (10, "annotation:write"),
            (12, "review:write"),
        ]
        self.inserted_user_permissions = []
        self.inserted_network_nodes = []
        self.inserted_site_projects = []
        self.inserted_recorder_microphones = []
        self.inserted_audio_settings = []
        self.inserted_media_rows = []
        self.inserted_media_collections = []
        self.inserted_queue_rows = []
        self.inserted_label_rows = []
        self.inserted_user_rows = []
        self.preview_rows = []
        self.updated_previews = []
        self.queries = []
        self.mysql_columns = {}
        self.pg_columns = {}
        self.recording_rows = []
        self.media_row = None
        self.site_ids = set()
        self.license_ids = set()
        self.collection_ids = set()
        self.project_ids = set()
        self.recorder_ids = set()
        self.microphone_ids = set()
        self.user_ids = set()
        self.user_rows = []
        self.media_ids = set()
        self.admin_user_id = 1
        self.null_project_count = 0
        self.broken_scope_count = 0
        self.collection_scope_count = 1
        self.missing_collection_read_count = 0
        self.missing_project_read_count = 0
        self.view_count = 1
        self.metadata_without_audio_setting_count = 0
        self.metadata_with_photo_setting_count = 0
        self.audio_without_audio_setting_count = 0
        self.remote_network_node_count = 0
        self.empty_network_url_count = 0
        self.duplicate_network_url_count = 0
        self.non_zero_network_stats_count = 0
        self.missing_network_synced_at_count = 0

    def cursor(self):
        return FakeCursor(self)

    def close(self):
        return None

    def full_project_write_candidates(self):
        project_collection_counts = {}
        for project_id, collection_id in self.project_collection_links:
            project_collection_counts.setdefault(project_id, set()).add(collection_id)

        permission_name_by_id = dict(self.permission_rows)
        user_write_collections = {}
        existing_project_writes = set()
        for params in [*self.existing_user_permissions, *self.inserted_user_permissions]:
            if len(params) == 3:
                user_id, permission_id, project_id = params
                collection_id = None
            else:
                user_id, permission_id, project_id, collection_id = params
            permission_name = permission_name_by_id.get(permission_id)
            if permission_name == "collection:write" and collection_id is not None:
                user_write_collections.setdefault((user_id, project_id), set()).add(collection_id)
            if permission_name == "project:write" and collection_id is None:
                existing_project_writes.add((user_id, project_id))

        candidates = []
        for (user_id, project_id), collection_ids in user_write_collections.items():
            if not project_collection_counts.get(project_id):
                continue
            if collection_ids == project_collection_counts[project_id] and (user_id, project_id) not in existing_project_writes:
                candidates.append((user_id, project_id))
        return sorted(candidates)


def test_migrate_user_permissions_maps_view_review_access_and_manage():
    module = _load_script_module()
    legacy_rows = [
        {"user_id": 7, "project_id": 101, "collection_id": 201, "permission_id": 1},
        {"user_id": 8, "project_id": 101, "collection_id": 202, "permission_id": 2},
        {"user_id": 9, "project_id": 102, "collection_id": 203, "permission_id": 3},
        {"user_id": 10, "project_id": 103, "collection_id": 204, "permission_id": 4},
    ]
    mysql_conn = FakeConnection(legacy_rows=legacy_rows)
    pg_conn = FakeConnection(
        project_collection_links={(101, 201), (101, 202), (102, 203), (103, 204)}
    )

    migrated = module.migrate_user_permissions(mysql_conn, pg_conn, dry_run=False)

    assert migrated == 4
    assert set(pg_conn.inserted_user_permissions) == {
        (7, 1, 101, None),
        (7, 3, 101, 201),
        (8, 1, 101, None),
        (8, 3, 101, 202),
        (8, 12, 101, 202),
        (9, 1, 102, None),
        (9, 3, 102, 203),
        (9, 10, 102, 203),
        (10, 1, 103, None),
        (10, 4, 103, 204),
        (10, 2, 103),
    }


def test_migrate_user_permissions_grants_project_write_for_full_project_managers():
    module = _load_script_module()
    legacy_rows = [
        {"user_id": 10, "project_id": 103, "collection_id": 204, "permission_id": 4},
        {"user_id": 10, "project_id": 103, "collection_id": 205, "permission_id": 4},
    ]
    mysql_conn = FakeConnection(legacy_rows=legacy_rows)
    pg_conn = FakeConnection(project_collection_links={(103, 204), (103, 205)})

    migrated = module.migrate_user_permissions(mysql_conn, pg_conn, dry_run=False)

    assert migrated == 2
    assert (10, 2, 103) in pg_conn.inserted_user_permissions


def test_migrate_user_permissions_does_not_grant_project_write_for_partial_project_managers():
    module = _load_script_module()
    legacy_rows = [
        {"user_id": 10, "project_id": 103, "collection_id": 204, "permission_id": 4},
    ]
    mysql_conn = FakeConnection(legacy_rows=legacy_rows)
    pg_conn = FakeConnection(project_collection_links={(103, 204), (103, 205)})

    migrated = module.migrate_user_permissions(mysql_conn, pg_conn, dry_run=False)

    assert migrated == 1
    assert (10, 2, 103) not in pg_conn.inserted_user_permissions


def test_grant_project_write_for_full_project_managers_is_idempotent():
    module = _load_script_module()
    pg_conn = FakeConnection(
        project_collection_links={(103, 204), (103, 205)},
        existing_user_permissions=[
            (10, 4, 103, 204),
            (10, 4, 103, 205),
            (10, 2, 103),
        ],
    )

    migrated = module.grant_project_write_for_full_project_managers(pg_conn, dry_run=False)

    assert migrated == 0
    assert pg_conn.inserted_user_permissions == []


def test_migrate_user_permissions_skips_unlinked_or_unmapped_rows():
    module = _load_script_module()
    legacy_rows = [
        {"user_id": 7, "project_id": 101, "collection_id": 201, "permission_id": 1},
        {"user_id": 8, "project_id": 101, "collection_id": 202, "permission_id": 99},
        {"user_id": 9, "project_id": None, "collection_id": 203, "permission_id": 3},
    ]
    mysql_conn = FakeConnection(legacy_rows=legacy_rows)
    pg_conn = FakeConnection(project_collection_links=set())

    migrated = module.migrate_user_permissions(mysql_conn, pg_conn, dry_run=False)

    assert migrated == 0
    assert pg_conn.inserted_user_permissions == []


def test_verify_user_permission_transfer_accepts_valid_permission_state():
    module = _load_script_module()
    legacy_rows = [
        {"user_id": 8, "project_id": 101, "collection_id": 202, "permission_id": 2},
    ]
    mysql_conn = FakeConnection(legacy_rows=legacy_rows)
    pg_conn = FakeConnection()

    errors = module.verify_user_permission_migration(mysql_conn, pg_conn)

    assert errors == []


def test_verify_user_permission_transfer_reports_missing_inherited_reads():
    module = _load_script_module()
    legacy_rows = [
        {"user_id": 8, "project_id": 101, "collection_id": 202, "permission_id": 2},
    ]
    mysql_conn = FakeConnection(legacy_rows=legacy_rows)
    pg_conn = FakeConnection()
    pg_conn.missing_collection_read_count = 1
    pg_conn.missing_project_read_count = 1

    errors = module.verify_user_permission_migration(mysql_conn, pg_conn)

    assert any("same-scope collection:read" in error for error in errors)
    assert any("parent project:read" in error for error in errors)


def test_verify_user_permission_transfer_reports_missing_project_write_for_full_project_managers():
    module = _load_script_module()
    mysql_conn = FakeConnection()
    pg_conn = FakeConnection(
        project_collection_links={(103, 204), (103, 205)},
        existing_user_permissions=[
            (10, 4, 103, 204),
            (10, 4, 103, 205),
        ],
    )

    errors = module.verify_user_permission_migration(mysql_conn, pg_conn)

    assert any("missing project:write" in error for error in errors)


def test_migrate_labels_copies_type_and_normalizes_system_creator():
    module = _load_script_module()
    mysql_conn = FakeConnection()
    pg_conn = FakeConnection()
    module.fetch_all = lambda conn, sql, params=None: [
        {
            "label_id": 1,
            "name": "not analysed",
            "creator_id": -1,
            "type": "public",
            "creation_date": datetime(2022, 3, 22, 3, 46, 35),
        },
        {
            "label_id": 4,
            "name": "to review",
            "creator_id": 104,
            "type": "private",
            "creation_date": datetime(2022, 3, 23, 8, 55, 39),
        },
    ]

    migrated = module.migrate_labels(mysql_conn, pg_conn, dry_run=False)

    assert migrated == 2
    assert pg_conn.inserted_label_rows == [
        (1, "not analysed", None, "public", datetime(2022, 3, 22, 3, 46, 35)),
        (4, "to review", 104, "private", datetime(2022, 3, 23, 8, 55, 39)),
    ]


def test_migrate_labels_upserts_existing_rows_and_normalizes_invalid_type():
    module = _load_script_module()
    mysql_conn = FakeConnection()
    pg_conn = FakeConnection()
    module.fetch_all = lambda conn, sql, params=None: [
        {
            "label_id": 2,
            "name": "tagged",
            "creator_id": -1,
            "type": "PUBLIC",
            "creation_date": datetime(2022, 3, 22, 3, 46, 35),
        },
        {
            "label_id": 9,
            "name": "odd",
            "creator_id": 156,
            "type": "legacy-weird",
            "creation_date": datetime(2023, 2, 16, 21, 12, 28),
        },
    ]

    migrated = module.migrate_labels(mysql_conn, pg_conn, dry_run=False)

    assert migrated == 2
    assert pg_conn.inserted_label_rows[0] == (
        2,
        "tagged",
        None,
        "public",
        datetime(2022, 3, 22, 3, 46, 35),
    )
    assert pg_conn.inserted_label_rows[1] == (
        9,
        "odd",
        156,
        "private",
        datetime(2023, 2, 16, 21, 12, 28),
    )
    assert any(
        "ON CONFLICT (label_id) DO UPDATE" in sql
        for sql, _params in pg_conn.queries
        if sql.startswith("INSERT INTO label")
    )


def test_label_field_coverage_marks_type_as_directly_mapped():
    module = _load_script_module()

    spec = next(item for item in module.LEGACY_FIELD_COVERAGE_SPEC if item["name"] == "label->label")

    assert "type" in spec["target_fields"]
    assert module.LEGACY_FIELD_MAP["label->label"]["type"] == "label.type"


def test_migrate_network_federation_maps_shared_api_rows_and_local_node(monkeypatch):
    module = _load_script_module()
    monkeypatch.delenv("LEGACY_APP_URL", raising=False)
    monkeypatch.delenv("LEGACY_HOST_URL", raising=False)
    mysql_conn = FakeConnection()
    pg_conn = FakeConnection()

    def _fetch_all(_conn, sql, _params=None):
        normalized = " ".join(sql.split())
        if normalized == "SELECT name, value FROM setting":
            return [
                {"name": "server_name", "value": "Legacy Node"},
                {"name": "app_url", "value": "https://legacy-local.example/"},
                {"name": "latitude", "value": "10.5"},
                {"name": "longitude", "value": "20.25"},
                {"name": "shared", "value": "1"},
            ]
        if "FROM api" in normalized:
            return [
                {
                    "api_id": 1,
                    "api": "aHR0cHM6Ly9ub2RlLW9uZS5leGFtcGxlLw==",
                    "server_name": "Node One",
                    "longitude": 120.5,
                    "latitude": 30.25,
                    "shared": 1,
                    "last_updated": datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
                },
                {
                    "api_id": 2,
                    "api": "aHR0cHM6Ly9ub2RlLW9uZS5leGFtcGxl",
                    "server_name": "Node One Newer",
                    "longitude": 121.5,
                    "latitude": 31.25,
                    "shared": 1,
                    "last_updated": datetime(2026, 1, 2, 4, 4, 5, tzinfo=UTC),
                },
                {
                    "api_id": 3,
                    "api": "aHR0cHM6Ly9ub2RlLXR3by5leGFtcGxl",
                    "server_name": "",
                    "longitude": 98.1,
                    "latitude": 12.3,
                    "shared": 1,
                    "last_updated": None,
                },
                {
                    "api_id": 4,
                    "api": "aHR0cHM6Ly9oaWRkZW4uZXhhbXBsZQ==",
                    "server_name": "Hidden",
                    "longitude": 1.0,
                    "latitude": 2.0,
                    "shared": 0,
                    "last_updated": None,
                },
            ]
        return []

    module.fetch_all = _fetch_all
    migrated = module.migrate_network_federation(mysql_conn, pg_conn, dry_run=False)

    assert migrated == 3
    assert len(pg_conn.inserted_network_nodes) == 3
    assert pg_conn.inserted_network_nodes[0][0] == "https://node-one.example"
    assert pg_conn.inserted_network_nodes[0][1] == "Node One Newer"
    assert pg_conn.inserted_network_nodes[0][5] is True
    assert pg_conn.inserted_network_nodes[1][0] == "https://node-two.example"
    assert pg_conn.inserted_network_nodes[1][1] == "https://node-two.example"
    assert pg_conn.inserted_network_nodes[1][5] is True
    assert pg_conn.inserted_network_nodes[2][0] == "https://legacy-local.example"
    assert pg_conn.inserted_network_nodes[2][4] is True
    assert any(
        "WHERE network_node.is_local = FALSE" in sql
        for sql, _params in pg_conn.queries
        if "INSERT INTO network_node" in sql
    )


def test_migrate_network_federation_skips_invalid_or_non_shared_rows_in_dry_run():
    module = _load_script_module()
    mysql_conn = FakeConnection()
    pg_conn = FakeConnection()

    def _fetch_all(_conn, sql, _params=None):
        normalized = " ".join(sql.split())
        if normalized == "SELECT name, value FROM setting":
            return []
        if "FROM api" in normalized:
            return [
                {"api_id": 1, "api": "not-base64", "server_name": "Bad", "longitude": None, "latitude": None, "shared": 1, "last_updated": None},
                {"api_id": 2, "api": "aHR0cHM6Ly9ub3Qtc2hhcmVkLmV4YW1wbGU=", "server_name": "Hidden", "longitude": None, "latitude": None, "shared": 0, "last_updated": None},
            ]
        return []

    module.fetch_all = _fetch_all
    migrated = module.migrate_network_federation(mysql_conn, pg_conn, dry_run=True)

    assert migrated == 0
    assert pg_conn.inserted_network_nodes == []


def test_resolve_local_network_url_prefers_explicit_and_normalizes():
    module = _load_script_module()

    app_url, source = module._resolve_local_network_url(
        explicit_app_url="https://local.example/",
        stored_app_url="https://stored.example",
        host_url="https://host.example",
        server_name="Legacy Node",
        latitude="10.5",
        longitude="20.25",
        nodes=[],
    )

    assert app_url == "https://local.example"
    assert source == "explicit/config APP_URL"


def test_resolve_local_network_url_uses_source_setting_before_inference():
    module = _load_script_module()

    app_url, source = module._resolve_local_network_url(
        explicit_app_url=None,
        stored_app_url="https://stored.example/",
        host_url="https://host.example",
        server_name="Source Node",
        latitude=10.5,
        longitude=20.25,
        nodes=[
            {
                "app_url": "https://host.example",
                "name": "Source Node",
                "latitude": 10.5,
                "longitude": 20.25,
            }
        ],
    )

    assert app_url == "https://stored.example"
    assert source == "source setting app_url"


def test_resolve_local_network_url_uses_unique_identity_and_host_match():
    module = _load_script_module()
    nodes = [
        {
            "app_url": "https://other.example",
            "name": "Legacy Node",
            "latitude": 10.5,
            "longitude": 20.25,
        },
        {
            "app_url": "https://host.example/",
            "name": "Legacy Node",
            "latitude": 10.5,
            "longitude": 20.25,
        },
    ]

    app_url, source = module._resolve_local_network_url(
        explicit_app_url=None,
        stored_app_url=None,
        host_url="https://host.example",
        server_name="Legacy Node",
        latitude="10.5",
        longitude="20.25",
        nodes=nodes,
    )

    assert app_url == "https://host.example"
    assert source == "unique identity match equal to HOST_URL"


def test_resolve_local_network_url_rejects_ambiguous_candidates():
    module = _load_script_module()
    nodes = [
        {"app_url": "https://one.example", "name": "Legacy", "latitude": 1, "longitude": 2},
        {"app_url": "https://two.example", "name": "Legacy", "latitude": 1, "longitude": 2},
    ]

    with pytest.raises(RuntimeError, match="--legacy-app-url"):
        module._resolve_local_network_url(
            explicit_app_url=None,
            stored_app_url=None,
            host_url=None,
            server_name="Legacy",
            latitude=1,
            longitude=2,
            nodes=nodes,
        )


def test_resolve_local_network_url_rejects_missing_identity_match():
    module = _load_script_module()

    with pytest.raises(RuntimeError, match="candidates: none"):
        module._resolve_local_network_url(
            explicit_app_url=None,
            stored_app_url=None,
            host_url="https://host.example",
            server_name="Local Node",
            latitude=1,
            longitude=2,
            nodes=[
                {
                    "app_url": "https://remote.example",
                    "name": "Remote Node",
                    "latitude": 3,
                    "longitude": 4,
                }
            ],
        )


def test_resolve_local_network_url_rejects_invalid_explicit_url():
    module = _load_script_module()

    with pytest.raises(ValueError, match="LEGACY_APP_URL"):
        module._resolve_local_network_url(
            explicit_app_url="file:///tmp/legacy",
            stored_app_url=None,
            host_url=None,
            server_name=None,
            latitude=None,
            longitude=None,
            nodes=[],
        )


def test_repair_network_federation_promotes_existing_remote_node(monkeypatch):
    module = _load_script_module()
    monkeypatch.delenv("LEGACY_APP_URL", raising=False)
    monkeypatch.setenv("LEGACY_HOST_URL", "https://host.example/")
    result_sets = iter(
        [
            [
                {"name": "server_name", "value": "Legacy Node"},
                {"name": "latitude", "value": "10.5"},
                {"name": "longitude", "value": "20.25"},
                {"name": "shared", "value": "1"},
            ],
            [
                {
                    "app_url": "https://host.example",
                    "name": "Legacy Node",
                    "latitude": 10.5,
                    "longitude": 20.25,
                    "is_local": False,
                    "shared": True,
                },
                {
                    "app_url": "https://remote.example",
                    "name": "Remote",
                    "latitude": None,
                    "longitude": None,
                    "is_local": False,
                    "shared": True,
                },
            ],
        ]
    )
    monkeypatch.setattr(module, "_pg_fetch_dicts", lambda *_args, **_kwargs: next(result_sets))
    local_updates = []
    host_updates = []
    monkeypatch.setattr(module, "_upsert_local_network_node", lambda *_args, **kwargs: local_updates.append(kwargs))
    monkeypatch.setattr(module, "_write_network_host_url", lambda _conn, value: host_updates.append(value))

    result = module.repair_network_federation(FakeConnection(), dry_run=False)

    assert result["app_url"] == "https://host.example"
    assert result["existing_role"] == "remote"
    assert local_updates == [
        {
            "app_url": "https://host.example",
            "server_name": "Legacy Node",
            "latitude": "10.5",
            "longitude": "20.25",
            "shared": True,
        }
    ]
    assert host_updates == ["https://host.example"]


def test_repair_network_federation_dry_run_writes_nothing(monkeypatch):
    module = _load_script_module()
    monkeypatch.setenv("LEGACY_APP_URL", "https://explicit.example")
    monkeypatch.delenv("LEGACY_HOST_URL", raising=False)
    result_sets = iter([[], []])
    monkeypatch.setattr(module, "_pg_fetch_dicts", lambda *_args, **_kwargs: next(result_sets))
    monkeypatch.setattr(
        module,
        "_upsert_local_network_node",
        lambda *_args, **_kwargs: pytest.fail("dry-run must not write a local node"),
    )

    result = module.repair_network_federation(FakeConnection(), dry_run=True)

    assert result["dry_run"] is True
    assert result["existing_role"] == "missing"


def test_normalize_preview_filename_uses_basename_only():
    module = _load_script_module()
    assert module.normalize_preview_filename("21808571-small_s.png") == "21808571-small_s.png"
    assert (
        module.normalize_preview_filename("sounds/images/1514/52/21808571-small_s.png")
        == "21808571-small_s.png"
    )
    assert (
        module.normalize_preview_filename(r"sounds\images\1514\52\21808571-player_s.png")
        == "21808571-player_s.png"
    )


def test_transfer_users_preserves_source_color_and_fft():
    module = _load_script_module()
    mysql_conn = FakeConnection()
    mysql_conn.user_rows = [
        {
            "user_id": 7,
            "role_id": 2,
            "username": "annotator",
            "password": "hashed",
            "name": "Annotator",
            "orcid": None,
            "email": "annotator@example.com",
            "color": "#12ab34",
            "active": 1,
            "fft": 2048,
        }
    ]
    pg_conn = FakeConnection()

    migrated = module.migrate_users(mysql_conn, pg_conn, dry_run=False)

    assert migrated == 1
    assert pg_conn.inserted_user_rows == [
        (7, 2, "annotator", "hashed", "Annotator", None, "annotator@example.com", "#12ab34", True)
    ]
    assert any(
        sql.startswith("INSERT INTO user_preference") and params[0] == 7 and params[1] == 2048
        for sql, params in pg_conn.queries
    )


def test_repair_preview_filenames_updates_path_values_only():
    module = _load_script_module()
    pg_conn = FakeConnection()
    pg_conn.preview_rows = [
        (1, "sounds/images/1514/52/21808571-small_s.png"),
        (2, "21808571-player_s.png"),
        (3, None),
    ]

    stats = module.repair_preview_filenames(pg_conn, dry_run=False)

    assert stats == {"updated": 1, "unchanged": 1, "skipped": 1, "ambiguous": 0}
    assert pg_conn.updated_previews == [("21808571-small_s.png", 1)]


def test_parse_source_date_time_handles_string_inputs():
    module = _load_script_module()
    parsed = module.parse_legacy_date_time("2024-12-31", "23:59:58")
    assert parsed is not None
    assert parsed.year == 2024
    assert parsed.month == 12
    assert parsed.day == 31
    assert parsed.hour == 23
    assert parsed.minute == 59
    assert parsed.second == 58


def test_transfer_queue_maps_source_statuses_to_target_values():
    module = _load_script_module()
    mysql_conn = FakeConnection()
    pg_conn = FakeConnection()

    legacy_rows = [
        {"queue_id": 101, "type": "upload", "user_id": 7, "completed": 0, "total": 3, "status": 2,
         "start_time": None, "stop_time": None, "error": None, "warning": None},
        {"queue_id": 102, "type": "upload", "user_id": 7, "completed": 1, "total": 3, "status": 0,
         "start_time": None, "stop_time": None, "error": None, "warning": None},
        {"queue_id": 103, "type": "birdnet", "user_id": 7, "completed": 3, "total": 3, "status": 1,
         "start_time": None, "stop_time": None, "error": None, "warning": None},
        {"queue_id": 104, "type": "birdnet", "user_id": 7, "completed": 1, "total": 3, "status": -1,
         "start_time": None, "stop_time": None, "error": "worker crashed", "warning": None},
        {"queue_id": 105, "type": "upload", "user_id": 7, "completed": 0, "total": 3, "status": -2,
         "start_time": None, "stop_time": None, "error": "being cancelled.", "warning": None},
    ]

    module.fetch_all = lambda conn, sql, params=None: legacy_rows

    migrated = module.migrate_queue(mysql_conn, pg_conn, dry_run=False)

    assert migrated == 5
    assert [row[5] for row in pg_conn.inserted_queue_rows] == [0, 1, 2, 3, 3]
    assert pg_conn.inserted_queue_rows[-1][8] == "being cancelled."


def test_migrate_queue_unknown_status_defaults_to_error_and_logs_warning(caplog):
    module = _load_script_module()
    mysql_conn = FakeConnection()
    pg_conn = FakeConnection()
    module.fetch_all = lambda conn, sql, params=None: [
        {"queue_id": 201, "type": "upload", "user_id": 7, "completed": 0, "total": 1, "status": 99,
         "start_time": None, "stop_time": None, "error": "source odd state", "warning": None},
    ]

    with caplog.at_level("WARNING"):
        migrated = module.migrate_queue(mysql_conn, pg_conn, dry_run=False)

    assert migrated == 1
    assert len(pg_conn.inserted_queue_rows) == 1
    assert pg_conn.inserted_queue_rows[0][5] == 3
    assert pg_conn.inserted_queue_rows[0][8] == "source odd state"
    assert "Unknown source queue status" in caplog.text
    assert "queue_id=201" in caplog.text


def test_transfer_tasks_maps_source_task_types():
    module = _load_script_module()
    mysql_conn = FakeConnection()
    pg_conn = FakeConnection()
    inserted_rows = []

    module.fetch_all = lambda conn, sql, params=None: [
        {
            "task_id": 1,
            "type": "recording",
            "recording_id": 101,
            "tag_id": None,
            "assigner_id": 7,
            "assignee_id": 8,
            "status": "assigned",
            "comment": "review media",
            "datetime": datetime(2024, 1, 1, 12, 0, 0),
        },
        {
            "task_id": 2,
            "type": "tag",
            "recording_id": 101,
            "tag_id": 202,
            "assigner_id": 7,
            "assignee_id": 9,
            "status": "reviewed",
            "comment": "review annotation",
            "datetime": datetime(2024, 1, 2, 12, 0, 0),
        },
    ]
    module.pg_exec = lambda conn, sql, params=None: inserted_rows.append(params) or 1

    migrated = module.migrate_tasks(mysql_conn, pg_conn, dry_run=False)

    assert migrated == 2
    assert inserted_rows[0][1] == "media"
    assert inserted_rows[1][1] == "annotation"


def test_migrate_tasks_raises_for_unknown_source_task_type():
    module = _load_script_module()
    mysql_conn = FakeConnection()
    pg_conn = FakeConnection()

    module.fetch_all = lambda conn, sql, params=None: [
        {
            "task_id": 3,
            "type": "unknown",
            "recording_id": 101,
            "tag_id": None,
            "assigner_id": 7,
            "assignee_id": 8,
            "status": "assigned",
            "comment": None,
            "datetime": None,
        }
    ]

    with pytest.raises(ValueError, match="Unsupported source task type"):
        module.migrate_tasks(mysql_conn, pg_conn, dry_run=False)


def test_migrate_recordings_maps_meta_data_to_metadata_with_audio_setting(monkeypatch):
    module = _load_script_module()
    mysql_conn = FakeConnection()
    pg_conn = FakeConnection()
    pg_conn.user_ids = {7}
    pg_conn.site_ids = {8}
    pg_conn.license_ids = {9}
    pg_conn.collection_ids = {10}

    monkeypatch.setattr(module, "_get_sensor_id_map", lambda conn: {})
    monkeypatch.setattr(
        module,
        "iter_mysql_rows",
        lambda conn, sql, params=None: [{
            "recording_id": 101,
            "data_type": "meta-data",
            "col_id": 10,
            "directory": "52",
            "filename": "meta.csv",
            "name": "Metadata row",
            "user_id": 7,
            "site_id": 8,
            "recorder_id": None,
            "microphone_id": None,
            "license_id": 9,
            "type": None,
            "medium": "air",
            "recording_gain": None,
            "duty_cycle_recording": 30,
            "duty_cycle_period": 60,
            "note": "n",
            "file_date": "2024-01-01",
            "file_time": "12:01:02",
            "file_size": 123,
            "md5_hash": "abc",
            "sampling_rate": 48000,
            "bitdepth": 24,
            "channel_num": 2,
            "duration": 10.5,
            "DOI": "doi-x",
            "creation_date": module.parse_legacy_date_time("2024-01-02", "03:04:05"),
        }],
    )

    migrated = module.migrate_recordings(mysql_conn, pg_conn, dry_run=False)

    assert migrated == 1
    assert len(pg_conn.inserted_audio_settings) == 1
    assert pg_conn.inserted_audio_settings[0] == (
        101,
        48000,
        24,
        2,
        10.5,
        None,
        module.parse_legacy_date_time("2024-01-02", "03:04:05"),
    )
    assert len(pg_conn.inserted_media_rows) == 1
    assert pg_conn.inserted_media_rows[0][2] == "audio"
    assert pg_conn.inserted_media_rows[0][3] is True
    assert pg_conn.inserted_media_rows[0][12] == 101
    assert pg_conn.inserted_media_rows[0][20] == "Air"
    assert pg_conn.inserted_media_collections == [(101, 10, 7, pg_conn.inserted_media_rows[0][21])]


def test_migrate_recordings_maps_meta_data_defaults_audio_setting_values(monkeypatch):
    module = _load_script_module()
    mysql_conn = FakeConnection()
    pg_conn = FakeConnection()
    pg_conn.user_ids = {7}
    pg_conn.site_ids = {8}
    pg_conn.license_ids = {9}
    pg_conn.collection_ids = {10}

    monkeypatch.setattr(module, "_get_sensor_id_map", lambda conn: {})
    monkeypatch.setattr(
        module,
        "iter_mysql_rows",
        lambda conn, sql, params=None: [{
            "recording_id": 111,
            "data_type": "meta-data",
            "col_id": 10,
            "directory": "53",
            "filename": "meta-defaults.csv",
            "name": "Metadata defaults",
            "user_id": 7,
            "site_id": 8,
            "recorder_id": None,
            "microphone_id": None,
            "license_id": 9,
            "type": None,
            "medium": "air",
            "recording_gain": None,
            "duty_cycle_recording": None,
            "duty_cycle_period": None,
            "note": None,
            "file_date": "2024-01-01",
            "file_time": "12:01:02",
            "file_size": 123,
            "md5_hash": "def",
            "sampling_rate": None,
            "bitdepth": None,
            "channel_num": None,
            "duration": None,
            "DOI": "doi-y",
            "creation_date": module.parse_legacy_date_time("2024-01-02", "03:04:05"),
        }],
    )

    migrated = module.migrate_recordings(mysql_conn, pg_conn, dry_run=False)

    assert migrated == 1
    assert pg_conn.inserted_audio_settings[0] == (
        111,
        44100,
        None,
        None,
        0.0,
        None,
        module.parse_legacy_date_time("2024-01-02", "03:04:05"),
    )


def test_migrate_recordings_keeps_audio_rows_bound_to_audio_setting(monkeypatch):
    module = _load_script_module()
    mysql_conn = FakeConnection()
    pg_conn = FakeConnection()
    pg_conn.user_ids = {7}
    pg_conn.site_ids = {8}
    pg_conn.license_ids = {9}
    pg_conn.collection_ids = {10}

    monkeypatch.setattr(module, "_get_sensor_id_map", lambda conn: {})
    monkeypatch.setattr(
        module,
        "iter_mysql_rows",
        lambda conn, sql, params=None: [{
            "recording_id": 202,
            "data_type": "audio data",
            "col_id": 10,
            "directory": "52",
            "filename": "audio.wav",
            "name": "Audio row",
            "user_id": 7,
            "site_id": 8,
            "recorder_id": None,
            "microphone_id": None,
            "license_id": 9,
            "type": None,
            "medium": "air",
            "recording_gain": 12,
            "duty_cycle_recording": 30,
            "duty_cycle_period": 60,
            "note": "n",
            "file_date": "2024-01-01",
            "file_time": "12:01:02",
            "file_size": 123,
            "md5_hash": "abc",
            "sampling_rate": 48000,
            "bitdepth": 24,
            "channel_num": 2,
            "duration": 10.5,
            "DOI": "doi-x",
            "creation_date": module.parse_legacy_date_time("2024-01-02", "03:04:05"),
        }],
    )

    migrated = module.migrate_recordings(mysql_conn, pg_conn, dry_run=False)

    assert migrated == 1
    assert len(pg_conn.inserted_audio_settings) == 1
    assert pg_conn.inserted_audio_settings[0][0] == 202
    assert len(pg_conn.inserted_media_rows) == 1
    assert pg_conn.inserted_media_rows[0][2] == "audio"
    assert pg_conn.inserted_media_rows[0][3] is False
    assert pg_conn.inserted_media_rows[0][12] == 202


def test_migrate_recordings_warns_and_skips_unknown_data_type(monkeypatch, caplog):
    module = _load_script_module()
    mysql_conn = FakeConnection()
    pg_conn = FakeConnection()

    monkeypatch.setattr(module, "_get_sensor_id_map", lambda conn: {})
    monkeypatch.setattr(
        module,
        "iter_mysql_rows",
        lambda conn, sql, params=None: [{
            "recording_id": 303,
            "data_type": "video data",
            "col_id": 10,
            "directory": "52",
            "filename": "bad.bin",
            "name": "Unknown row",
            "user_id": 7,
            "site_id": 8,
            "recorder_id": None,
            "microphone_id": None,
            "license_id": 9,
            "type": None,
            "medium": "air",
            "recording_gain": None,
            "duty_cycle_recording": 30,
            "duty_cycle_period": 60,
            "note": "n",
            "file_date": "2024-01-01",
            "file_time": "12:01:02",
            "file_size": 123,
            "md5_hash": "abc",
            "sampling_rate": 48000,
            "bitdepth": 24,
            "channel_num": 2,
            "duration": 10.5,
            "DOI": "doi-x",
            "creation_date": module.parse_legacy_date_time("2024-01-02", "03:04:05"),
        }],
    )

    with caplog.at_level("WARNING"):
        migrated = module.migrate_recordings(mysql_conn, pg_conn, dry_run=False)

    assert migrated == 0
    assert pg_conn.inserted_audio_settings == []
    assert pg_conn.inserted_media_rows == []
    assert pg_conn.inserted_media_collections == []
    assert "unsupported data_type" in caplog.text
    assert "recording_id=303" in caplog.text


def test_compare_media_sample_normalizes_medium_before_comparison(caplog):
    module = _load_script_module()
    mysql_conn = FakeConnection()
    pg_conn = FakeConnection()
    mysql_conn.recording_rows = [{
        "recording_id": 21808571,
        "data_type": "audio data",
        "directory": "52",
        "filename": "a.wav",
        "name": "A",
        "user_id": 7,
        "site_id": 8,
        "license_id": 9,
        "medium": "air",
        "duty_cycle_recording": 30,
        "duty_cycle_period": 60,
        "note": "n",
        "file_date": "2024-01-01",
        "file_time": "12:01:02",
        "file_size": 123,
        "md5_hash": "abc",
        "DOI": "doi-x",
    }]
    pg_conn.media_row = (
        21808571, "audio", False, 21808571, "52", "a.wav", "A", 7, 8, 9, "Air",
        30, 60, "n", module.parse_legacy_date_time("2024-01-01", "12:01:02"), 123, "abc", "doi-x",
    )

    with caplog.at_level("INFO"):
        module.compare_media_sample(mysql_conn, pg_conn, 21808571)

    assert "summary: checked=17 mismatches=0" in caplog.text


def test_verify_recording_media_transfer_accepts_valid_state():
    module = _load_script_module()
    pg_conn = FakeConnection()

    errors = module.verify_recording_media_migration(pg_conn)

    assert errors == []


def test_verify_recording_media_transfer_reports_invalid_audio_setting_links():
    module = _load_script_module()
    pg_conn = FakeConnection()
    pg_conn.metadata_without_audio_setting_count = 2
    pg_conn.metadata_with_photo_setting_count = 4
    pg_conn.audio_without_audio_setting_count = 3

    errors = module.verify_recording_media_migration(pg_conn)

    assert any("is_metadata media rows missing audio_setting_id: 2" in error for error in errors)
    assert any("is_metadata media rows should not have photo_setting_id: 4" in error for error in errors)
    assert any("audio media rows missing audio_setting_id: 3" in error for error in errors)


def test_values_equivalent_accepts_naive_and_aware_datetime_same_instant():
    module = _load_script_module()
    naive = module.parse_legacy_date_time("2024-01-01", "12:01:02")
    aware = naive.replace(tzinfo=UTC)
    assert module.values_equivalent(naive, aware) is True


def test_migrate_sites_uses_geo_enrichment_fields(monkeypatch):
    module = _load_script_module()
    mysql_conn = FakeConnection()
    pg_conn = FakeConnection()

    monkeypatch.setattr(
        module,
        "fetch_all",
        lambda conn, sql, params=None: [{
            "site_id": 11,
            "user_id": 7,
            "name": "Site A",
            "longitude_WGS84_dd_dddd": 1.1,
            "latitude_WGS84_dd_dddd": 2.2,
            "topography_m": 3.3,
            "freshwater_depth_m": 4.4,
            "gadm0": "CountryX",
            "gadm1": "StateX",
            "gadm2": "CityX",
            "iho": "SeaX",
            "realm_id": 1,
            "biome_id": 2,
            "functional_type_id": 3,
            "creation_date_time": "2024-01-01 00:00:00",
        }],
    )
    monkeypatch.setattr(
        module,
        "resolve_site_enrichment",
        lambda *args, **kwargs: {
            "gadm0": "CountryX",
            "gadm1": "StateX",
            "gadm2": "CityX",
            "gadm0_gid": "C0",
            "gadm1_gid": "C1",
            "gadm2_gid": "C2",
            "iho": "SeaX",
            "location_wkt": "SRID=4326;POLYGON((0 0,1 0,1 1,0 0))",
            "location_iho_wkt": "SRID=4326;POLYGON((2 2,3 2,3 3,2 2))",
        },
    )

    migrated = module.migrate_sites(mysql_conn, pg_conn, dry_run=False, geo_conn=object())

    assert migrated == 1
    insert_sql, insert_params = next(q for q in pg_conn.queries if "INSERT INTO site" in q[0])
    assert "gadm0_gid" in insert_sql
    assert insert_params[9:17] == (
        "CountryX", "StateX", "CityX", "SeaX", "C0", "C1", "C2", "SRID=4326;POLYGON((2 2,3 2,3 3,2 2))"
    )


def test_migrate_taxon_uses_xr_enrichment_fields(monkeypatch):
    module = _load_script_module()
    mysql_conn = FakeConnection()
    pg_conn = FakeConnection()

    monkeypatch.setattr(
        module,
        "fetch_all",
        lambda conn, sql, params=None: [{
            "species_id": 5,
            "binomial": "Specius example",
            "genus": "Specius",
            "family": "Familia",
            "taxon_order": "Ordera",
            "class": "Classa",
            "common_name": "Example",
            "source": "Legacy",
        }],
    )
    monkeypatch.setattr(
        module,
        "resolve_taxon_enrichment",
        lambda *args, **kwargs: {
            "col_species_id": "SP1",
            "col_genus_id": "GEN1",
            "col_family_id": "FAM1",
            "col_order_id": "ORD1",
            "col_class_id": "CLS1",
            "cached_scientific_name": "Specius example",
            "cached_common_name": "Example",
            "taxonomy_source": "CatalogueOfLife-XR",
            "last_synced": "2026-05-04 00:00:00",
        },
    )
    monkeypatch.setattr(module, "_detect_remote_taxon_table", lambda conn: "geo_col_xr_taxon_species")
    monkeypatch.setattr(module, "build_taxon_lookup_cache", lambda *args, **kwargs: {})

    migrated = module.migrate_taxon(mysql_conn, pg_conn, dry_run=False, geo_conn=object())

    assert migrated == 1
    insert_sql, insert_params = next(q for q in pg_conn.queries if "INSERT INTO taxon" in q[0])
    assert "col_species_id" in insert_sql
    assert insert_params[:10] == (
        5, "SP1", "GEN1", "FAM1", "ORD1", "CLS1", "Specius example", "Example", "CatalogueOfLife-XR", "2026-05-04 00:00:00"
    )


def test_resolve_taxon_enrichment_returns_fallback_on_ambiguous_match(monkeypatch):
    module = _load_script_module()
    monkeypatch.setattr(module, "_detect_remote_taxon_table", lambda conn: "col_xr_taxon_species")
    monkeypatch.setattr(
        module,
        "_query_taxon_match_by_name",
        lambda conn, table, rank, value: [
            {"col_species_id": "SP1"},
            {"col_species_id": "SP2"},
        ] if rank == "species" else [],
    )

    result = module.resolve_taxon_enrichment(
        object(),
        binomial="Specius example",
        genus=None,
        family=None,
        taxon_order=None,
        taxon_class=None,
        common_name="Example",
        source="Legacy",
    )

    assert result["col_species_id"] is None
    assert result["cached_scientific_name"] == "Specius example"
    assert result["cached_common_name"] == "Example"


def test_build_taxon_lookup_cache_batches_names_once_per_rank(monkeypatch):
    module = _load_script_module()
    calls = []

    monkeypatch.setattr(module, "_detect_remote_taxon_table", lambda _conn: "geo_col_xr_taxon_species")

    def fake_query(_conn, table_name, rank, values):
        calls.append((table_name, rank, tuple(values)))
        if rank == "species":
            return {
                "specius example": [{
                    "col_species_id": "SP1",
                    "col_genus_id": "GEN1",
                    "col_family_id": "FAM1",
                    "col_order_id": "ORD1",
                    "col_class_id": "CLS1",
                    "cached_scientific_name": "Specius example",
                    "cached_common_name": "Example",
                    "taxonomy_source": "CatalogueOfLife-XR",
                    "imported_at": "2026-05-04 00:00:00",
                }]
            }
        return {}

    monkeypatch.setattr(module, "_query_taxon_matches_by_names", fake_query)

    cache = module.build_taxon_lookup_cache(
        object(),
        [{
            "binomial": "Specius example",
            "genus": "Specius",
            "family": "Familia",
            "taxon_order": "Ordera",
            "class": "Classa",
        }],
    )

    assert cache["species"]["specius example"][0]["col_species_id"] == "SP1"
    assert len(calls) == 5
    assert calls[0][0] == "geo_col_xr_taxon_species"
    assert calls[0][1] == "species"


def test_resolve_taxon_enrichment_fills_missing_hierarchy_from_cached_parent_matches():
    module = _load_script_module()

    result = module.resolve_taxon_enrichment(
        object(),
        binomial="Species A",
        genus="Genus A",
        family="Family A",
        taxon_order="Order A",
        taxon_class="Class A",
        common_name="Common A",
        source="IUCN",
        lookup_cache={
            "species": {
                "species a": [{
                    "col_species_id": "sp-1",
                    "col_genus_id": None,
                    "col_family_id": "fam-1",
                    "col_order_id": "ord-1",
                    "col_class_id": "cls-1",
                    "cached_scientific_name": "Species A",
                    "cached_common_name": None,
                    "taxonomy_source": "CatalogueOfLife-XR",
                    "imported_at": "2026-01-01T00:00:00Z",
                }]
            },
            "genus": {
                "genus a": [{
                    "col_species_id": None,
                    "col_genus_id": "gen-1",
                    "col_family_id": "fam-1",
                    "col_order_id": "ord-1",
                    "col_class_id": "cls-1",
                    "cached_scientific_name": "Genus A",
                    "cached_common_name": None,
                    "taxonomy_source": "CatalogueOfLife-XR",
                    "imported_at": "2026-01-01T00:00:00Z",
                }]
            },
            "family": {},
            "order": {},
            "class": {},
        },
    )

    assert result["col_species_id"] == "sp-1"
    assert result["col_genus_id"] == "gen-1"
    assert result["col_family_id"] == "fam-1"
    assert result["col_order_id"] == "ord-1"
    assert result["col_class_id"] == "cls-1"


def test_resolve_taxon_enrichment_preserves_binomial_when_only_genus_matches():
    module = _load_script_module()

    result = module.resolve_taxon_enrichment(
        object(),
        binomial="Accipiter gentilis",
        genus="Accipiter",
        family="Accipitridae",
        taxon_order="Accipitriformes",
        taxon_class="Aves",
        common_name="Northern Goshawk",
        source="IUCN",
        lookup_cache={
            "species": {},
            "genus": {
                "accipiter": [{
                    "col_species_id": None,
                    "col_genus_id": "627QR",
                    "col_family_id": "5W6",
                    "col_order_id": "MB",
                    "col_class_id": "V2",
                    "cached_scientific_name": "Accipiter",
                    "cached_common_name": None,
                    "taxonomy_source": "CatalogueOfLife-XR",
                    "imported_at": "2026-01-01T00:00:00Z",
                }]
            },
            "family": {},
            "order": {},
            "class": {},
        },
    )

    assert result["col_species_id"] is None
    assert result["col_genus_id"] == "627QR"
    assert result["col_family_id"] == "5W6"
    assert result["col_order_id"] == "MB"
    assert result["col_class_id"] == "V2"
    assert result["cached_scientific_name"] == "Accipiter gentilis"
    assert result["cached_common_name"] == "Northern Goshawk"
    assert result["taxonomy_source"] == "CatalogueOfLife-XR"


def test_resolve_taxon_enrichment_returns_fallback_when_no_rank_matches():
    module = _load_script_module()

    result = module.resolve_taxon_enrichment(
        object(),
        binomial="Phylloscartes difficilis",
        genus="Phylloscartes",
        family="Tyrannidae",
        taxon_order="Passeriformes",
        taxon_class="Aves",
        common_name="Serra do Mar Tyrannulet",
        source="IUCN",
        lookup_cache={
            "species": {},
            "genus": {},
            "family": {},
            "order": {},
            "class": {},
        },
    )

    assert result["col_species_id"] is None
    assert result["col_genus_id"] is None
    assert result["cached_scientific_name"] == "Phylloscartes difficilis"
    assert result["cached_common_name"] == "Serra do Mar Tyrannulet"
    assert result["taxonomy_source"] == "IUCN"


def test_migrate_site_projects_derives_distinct_links(monkeypatch):
    module = _load_script_module()
    mysql_conn = FakeConnection()
    pg_conn = FakeConnection()
    pg_conn.site_ids = {11, 12}
    pg_conn.project_ids = {101, 102}

    monkeypatch.setattr(
        module,
        "fetch_all",
        lambda conn, sql, params=None: [
            {"site_id": 11, "project_id": 101},
            {"site_id": 12, "project_id": 102},
        ],
    )

    migrated = module.migrate_site_projects(mysql_conn, pg_conn, dry_run=False)

    assert migrated == 2
    assert set(pg_conn.inserted_site_projects) == {(11, 101), (12, 102)}


def test_migrate_recorder_microphones_marks_most_used_as_default(monkeypatch):
    module = _load_script_module()
    mysql_conn = FakeConnection()
    pg_conn = FakeConnection()
    pg_conn.recorder_ids = {7}
    pg_conn.microphone_ids = {21, 22}

    monkeypatch.setattr(
        module,
        "fetch_all",
        lambda conn, sql, params=None: [
            {"recorder_id": 7, "microphone_id": 21, "usage_count": 5},
            {"recorder_id": 7, "microphone_id": 22, "usage_count": 3},
        ],
    )

    migrated = module.migrate_recorder_microphones(mysql_conn, pg_conn, dry_run=False)

    assert migrated == 2
    assert pg_conn.inserted_recorder_microphones == [
        (7, 21, True, None),
        (7, 22, False, None),
    ]


def test_migrate_sensors_uses_combined_device_names(monkeypatch):
    module = _load_script_module()
    mysql_conn = FakeConnection()
    pg_conn = FakeConnection()
    inserted = []

    monkeypatch.setattr(
        module,
        "fetch_all",
        lambda conn, sql, params=None: [{
            "recorder_id": 7,
            "microphone_id": 21,
            "recorder_name": " SM4  ",
            "microphone_name": "  SMM-U2 ",
        }],
    )
    monkeypatch.setattr(
        module,
        "pg_exec",
        lambda conn, sql, params=None: inserted.append(params),
    )

    migrated = module.migrate_sensors(mysql_conn, pg_conn, dry_run=False)

    assert migrated == 1
    assert inserted[0][1] == "SM4_SMM-U2"


def test_build_audio_sensor_name_falls_back_for_blank_device_names():
    module = _load_script_module()

    name = module._build_audio_sensor_name(7, 21, " ", None)

    assert name == "recorder_7_microphone_21"


def test_build_audio_sensor_name_limits_length():
    module = _load_script_module()

    name = module._build_audio_sensor_name(7, 21, "r" * 200, "m" * 200)

    assert len(name) == 255


def test_migrate_sensors_dry_run_does_not_insert(monkeypatch):
    module = _load_script_module()
    mysql_conn = FakeConnection()
    pg_conn = FakeConnection()
    inserted = []

    monkeypatch.setattr(
        module,
        "fetch_all",
        lambda conn, sql, params=None: [{
            "recorder_id": 7,
            "microphone_id": 21,
            "recorder_name": "SM4",
            "microphone_name": "SMM-U2",
        }],
    )
    monkeypatch.setattr(
        module,
        "pg_exec",
        lambda conn, sql, params=None: inserted.append(params),
    )

    migrated = module.migrate_sensors(mysql_conn, pg_conn, dry_run=True)

    assert migrated == 1
    assert inserted == []


def test_migrate_file_upload_preserves_row_when_media_missing(monkeypatch):
    module = _load_script_module()
    mysql_conn = FakeConnection()
    pg_conn = FakeConnection()
    pg_conn.user_ids = {8}
    pg_conn.media_ids = set()

    monkeypatch.setattr(
        module,
        "fetch_all",
        lambda conn, sql, params=None: [{
            "file_upload_id": 1,
            "path": "/legacy-media/sounds/101/1/a.wav",
            "status": 3,
            "filename": "a.wav",
            "name": "A",
            "user_id": 8,
            "recording_id": 999,
            "directory": 1,
            "error": None,
            "creation_date": "2026-05-05 00:00:00",
        }],
    )

    migrated = module.migrate_file_upload(mysql_conn, pg_conn, dry_run=False)

    assert migrated == 1
    insert_sql, insert_params = next(q for q in pg_conn.queries if "INSERT INTO file_upload" in q[0])
    assert "media_id" in insert_sql
    assert insert_params[6] is None


def test_transfer_settings_uses_source_value_on_conflict(monkeypatch):
    module = _load_script_module()
    mysql_conn = FakeConnection()
    pg_conn = FakeConnection()

    monkeypatch.setattr(
        module,
        "fetch_all",
        lambda conn, sql, params=None: [{"name": "site_map_zoom", "value": "7"}],
    )

    migrated = module.migrate_settings(mysql_conn, pg_conn, dry_run=False)

    assert migrated == 1
    insert_sql, insert_params = next(q for q in pg_conn.queries if "INSERT INTO setting" in q[0])
    assert "DO UPDATE SET value = EXCLUDED.value" in insert_sql
    assert insert_params == ("site_map_zoom", "7")


def test_migrate_news_requires_administrator_user(monkeypatch):
    module = _load_script_module()
    mysql_conn = FakeConnection()
    pg_conn = FakeConnection()
    pg_conn.admin_user_id = None

    monkeypatch.setattr(
        module,
        "fetch_all",
        lambda conn, sql, params=None: [{
            "news_id": 1,
            "title": "Hello",
            "content": "World",
            "creation_date": "2026-05-05 00:00:00",
        }],
    )

    try:
        module.migrate_news(mysql_conn, pg_conn, dry_run=False)
    except RuntimeError as exc:
        assert "Administrator user exists" in str(exc)
    else:
        raise AssertionError("Expected migrate_news to fail without an Administrator user")
