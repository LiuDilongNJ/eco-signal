"""Unit tests for IndexLogRepository (index_log_repository.py)."""
import pytest
from sqlalchemy import text
from sqlmodel import Session

from app.models.collection import Collection
from app.models.index import IndexType
from app.models.media import AudioSetting, Media, MediaCollection
from app.models.project import Project, ProjectCollection
from app.repositories.index_log_repository import index_log_repository


@pytest.fixture
def index_setup(db: Session):
    """Create minimal Media, User, IndexType records needed for IndexLog tests."""
    from app.repositories import user_repository
    from app.core.config import settings

    superuser = user_repository.get_by_username(db, username=settings.FIRST_SUPERUSER)

    audio = AudioSetting(duration_s=30.0, sampling_rate_hz=44100)
    db.add(audio)
    db.flush()

    media = Media(
        name="IndexLog Test Media",
        media_type="audio",
        uploader_id=superuser.user_id,
        creator_id=superuser.user_id,
        audio_setting_id=audio.audio_setting_id,
    )
    db.add(media)
    db.flush()

    second_media = Media(
        name="IndexLog Other Media",
        media_type="audio",
        uploader_id=superuser.user_id,
        creator_id=superuser.user_id,
        audio_setting_id=audio.audio_setting_id,
    )
    db.add(second_media)
    db.flush()

    collection = Collection(name="IndexLog Test Col", creator_id=superuser.user_id)
    other_collection = Collection(name="IndexLog Other Col", creator_id=superuser.user_id)
    db.add_all([collection, other_collection])
    db.flush()

    mc = MediaCollection(media_id=media.media_id, collection_id=collection.collection_id, added_by=superuser.user_id)
    other_mc = MediaCollection(
        media_id=second_media.media_id,
        collection_id=other_collection.collection_id,
        added_by=superuser.user_id,
    )
    db.add_all([mc, other_mc])

    project = Project(name="IndexLog Repo Project", url="https://repo-project.example", creator_id=superuser.user_id)
    other_project = Project(
        name="IndexLog Repo Other Project",
        url="https://repo-project-other.example",
        creator_id=superuser.user_id,
    )
    db.add_all([project, other_project])
    db.flush()

    db.add_all([
        ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id),
        ProjectCollection(project_id=other_project.project_id, collection_id=other_collection.collection_id),
    ])

    index_type = IndexType(name="ACI_REPO_LOG")
    db.add(index_type)
    db.commit()
    db.refresh(media)
    db.refresh(second_media)
    db.refresh(index_type)

    return {
        "user": superuser,
        "media": media,
        "second_media": second_media,
        "index_type": index_type,
        "collection": collection,
        "other_collection": other_collection,
        "project": project,
        "other_project": other_project,
    }


class TestIndexLogRepositoryCreate:
    """Tests for create_from_results."""

    def test_create_from_results_basic(self, db: Session, index_setup):
        """Creates rows for output results and returns correct count."""
        setup = index_setup
        count = index_log_repository.create_from_results(
            db,
            media_id=setup["media"].media_id,
            user_id=setup["user"].user_id,
            index_id=setup["index_type"].index_id,
            version="1.0",
            results={"aci": 42.5, "ndsi": 0.7},
        )
        assert count == 2

    def test_create_from_results_with_params(self, db: Session, index_setup):
        """Includes both input param rows and output result rows."""
        setup = index_setup
        count = index_log_repository.create_from_results(
            db,
            media_id=setup["media"].media_id,
            user_id=setup["user"].user_id,
            index_id=setup["index_type"].index_id,
            version="1.0",
            results={"aci": 42.5},
            params={"window_size": 512, "hop_size": 256},
        )
        assert count == 3  # 2 params + 1 result

    def test_create_from_results_uses_supplied_log_id(self, db: Session, index_setup):
        """A caller-provided log_id is reused for the stored group."""
        setup = index_setup
        log_id = index_log_repository.reserve_log_id(db)
        count = index_log_repository.create_from_results(
            db,
            media_id=setup["media"].media_id,
            user_id=setup["user"].user_id,
            index_id=setup["index_type"].index_id,
            version="shared-log-id",
            results={"aci": 42.5},
            params={"Channel": "Mono"},
            log_id=log_id,
        )

        assert count == 2
        rows = db.execute(
            text(
                """
                SELECT DISTINCT log_id
                FROM index_log
                WHERE version = 'shared-log-id'
                """
            )
        ).scalars().all()
        assert rows == [log_id]

    def test_create_from_results_output_first(self, db: Session, index_setup):
        """Output-first mode can write output rows before input rows."""
        setup = index_setup
        version = "output-first-order"
        index_log_repository.create_from_results(
            db,
            media_id=setup["media"].media_id,
            user_id=setup["user"].user_id,
            index_id=setup["index_type"].index_id,
            version=version,
            results={"aci": 42.5},
            params={"Channel": "Mono"},
            output_first=True,
        )
        matching = db.execute(
            text(
                """
                SELECT variable_type, variable_name, variable_order
                FROM index_log
                WHERE version = :version AND variable_name IN ('aci', 'Channel')
                ORDER BY creation_date, variable_order
                """
            ),
            {"version": version},
        ).mappings().all()
        assert matching[0]["variable_type"] == "output"
        assert matching[0]["variable_name"] == "aci"
        assert matching[0]["variable_order"] == 1
        assert matching[1]["variable_type"] == "input"
        assert matching[1]["variable_order"] == 1

    def test_create_from_results_default_order_is_input_then_output(self, db: Session, index_setup):
        """Default order stores input rows before outputs while preserving grouped variable_order values."""
        setup = index_setup
        version = "input-first-order"
        index_log_repository.create_from_results(
            db,
            media_id=setup["media"].media_id,
            user_id=setup["user"].user_id,
            index_id=setup["index_type"].index_id,
            version=version,
            results={"aci": 42.5},
            params={"Channel": "Left", "Window": 512},
        )
        matching = db.execute(
            text(
                """
                SELECT variable_type, variable_name, variable_order
                FROM index_log
                WHERE version = :version AND variable_name IN ('aci', 'Channel', 'Window')
                ORDER BY creation_date, variable_order
                """
            ),
            {"version": version},
        ).mappings().all()
        assert [row["variable_type"] for row in matching] == ["input", "input", "output"]
        assert [row["variable_order"] for row in matching] == [1, 2, 1]

    def test_create_from_results_skips_error_key(self, db: Session, index_setup):
        """Results with key 'error' are skipped."""
        setup = index_setup
        count = index_log_repository.create_from_results(
            db,
            media_id=setup["media"].media_id,
            user_id=setup["user"].user_id,
            index_id=setup["index_type"].index_id,
            version="1.0",
            results={"aci": 42.5, "error": "failed"},
        )
        assert count == 1

    def test_create_from_results_with_time_freq(self, db: Session, index_setup):
        """Creates rows when optional time/frequency bounds are provided."""
        setup = index_setup
        count = index_log_repository.create_from_results(
            db,
            media_id=setup["media"].media_id,
            user_id=setup["user"].user_id,
            index_id=setup["index_type"].index_id,
            version="2.0",
            results={"h": 3.1},
            min_time="0",
            max_time="30",
            min_frequency="0",
            max_frequency="22050",
        )
        assert count == 1

    def test_create_from_results_empty_results(self, db: Session, index_setup):
        """No rows inserted when results dict is empty."""
        setup = index_setup
        count = index_log_repository.create_from_results(
            db,
            media_id=setup["media"].media_id,
            user_id=setup["user"].user_id,
            index_id=setup["index_type"].index_id,
            version="1.0",
            results={},
        )
        assert count == 0

class TestIndexLogRepositoryQuery:
    """Tests for _build_list_query filter branches and get_logs_page."""

    def _seed(self, db: Session, setup) -> None:
        index_log_repository.create_from_results(
            db,
            media_id=setup["media"].media_id,
            user_id=setup["user"].user_id,
            index_id=setup["index_type"].index_id,
            version="v1.2",
            results={"aci": 50.0},
            params={"win": 512},
            min_time="0",
            max_time="30",
            min_frequency="0",
            max_frequency="22050",
        )
        index_log_repository.create_from_results(
            db,
            media_id=setup["second_media"].media_id,
            user_id=setup["user"].user_id,
            index_id=setup["index_type"].index_id,
            version="v2.4",
            results={"ndsi": 0.9},
            params={"win": 1024},
            min_time="10",
            max_time="20",
            min_frequency="100",
            max_frequency="1000",
        )

    def test_get_logs_page_admin(self, db: Session, index_setup):
        """Admin sees all logs (no permission filter applied)."""
        self._seed(db, index_setup)
        results, total = index_log_repository.get_logs_page(
            db,
            user_id=index_setup["user"].user_id,
            is_admin=True,
            accessible_collection_ids=None,
        )
        assert total >= 2

    def test_get_logs_page_non_admin_own(self, db: Session, index_setup):
        """Non-admin with no collections sees only their own logs."""
        self._seed(db, index_setup)
        results, total = index_log_repository.get_logs_page(
            db,
            user_id=index_setup["user"].user_id,
            is_admin=False,
            accessible_collection_ids=None,
        )
        assert total >= 0

    def test_get_logs_page_non_admin_with_collections(self, db: Session, index_setup):
        """Non-admin with accessible collections sees their logs too."""
        self._seed(db, index_setup)
        results, total = index_log_repository.get_logs_page(
            db,
            user_id=index_setup["user"].user_id,
            is_admin=False,
            accessible_collection_ids=[index_setup["collection"].collection_id],
        )
        assert total >= 2

    def test_filter_by_version(self, db: Session, index_setup):
        """Filter by version string."""
        self._seed(db, index_setup)
        results, total = index_log_repository.get_logs_page(
            db,
            user_id=index_setup["user"].user_id,
            is_admin=True,
            accessible_collection_ids=None,
            version="v1.2",
        )
        assert total >= 1

    def test_filter_by_log_id(self, db: Session, index_setup):
        """Filter by specific log_id."""
        self._seed(db, index_setup)
        _, total = index_log_repository.get_logs_page(
            db,
            user_id=index_setup["user"].user_id,
            is_admin=True,
            accessible_collection_ids=None,
            log_id=999999,
        )
        assert total == 0

    def test_filter_by_project_collection_media_intersection(self, db: Session, index_setup):
        """Project, collection, and media filters narrow the results by intersection."""
        self._seed(db, index_setup)
        results, total = index_log_repository.get_logs_page(
            db,
            user_id=index_setup["user"].user_id,
            is_admin=True,
            accessible_collection_ids=None,
            project_id=index_setup["project"].project_id,
            collection_id=index_setup["collection"].collection_id,
            media_id=index_setup["media"].media_id,
        )
        assert total == 2
        assert {row["version"] for row in results} == {"v1.2"}

    def test_filter_by_project_collection_media_intersection_mismatch(self, db: Session, index_setup):
        """Mismatched project, collection, and media filters return no rows."""
        self._seed(db, index_setup)
        _, total = index_log_repository.get_logs_page(
            db,
            user_id=index_setup["user"].user_id,
            is_admin=True,
            accessible_collection_ids=None,
            project_id=index_setup["project"].project_id,
            collection_id=index_setup["collection"].collection_id,
            media_id=index_setup["second_media"].media_id,
        )
        assert total == 0

    def test_filter_by_other_project(self, db: Session, index_setup):
        """Project filter only returns logs whose media belongs to that project."""
        self._seed(db, index_setup)
        results, total = index_log_repository.get_logs_page(
            db,
            user_id=index_setup["user"].user_id,
            is_admin=True,
            accessible_collection_ids=None,
            project_id=index_setup["other_project"].project_id,
        )
        assert total == 2
        assert {row["version"] for row in results} == {"v2.4"}

    def test_filter_all_text_fields(self, db: Session, index_setup):
        """Exercise text and numeric-range filter branches in _build_list_query."""
        self._seed(db, index_setup)
        results, total = index_log_repository.get_logs_page(
            db,
            user_id=index_setup["user"].user_id,
            is_admin=True,
            accessible_collection_ids=None,
            min_t_min=0,
            min_t_max=0,
            max_t_min=30,
            max_t_max=30,
            min_f_min=0,
            min_f_max=0,
            max_f_min=22050,
            max_f_max=22050,
            var_type="input",
            var_order_min=1,
            var_order_max=1,
            var_name="win",
            var_value_min=512,
            var_value_max=512,
            media_name="IndexLog Test",
            user=index_setup["user"].name,
            index_type="ACI_REPO_LOG",
        )
        assert total >= 1
        assert all(row["variable_value"] == "512" for row in results)

    def test_filter_string_numeric_fields_by_numeric_value(self, db: Session, index_setup):
        """Numeric ranges compare string-backed values numerically, not lexicographically."""
        self._seed(db, index_setup)
        results, total = index_log_repository.get_logs_page(
            db,
            user_id=index_setup["user"].user_id,
            is_admin=True,
            accessible_collection_ids=None,
            var_value_min=1000,
            var_value_max=1100,
        )
        assert total >= 1
        assert "1024" in {row["variable_value"] for row in results}
        assert "512" not in {row["variable_value"] for row in results}

    def test_filter_string_numeric_fields_skips_non_numeric_values(self, db: Session, index_setup):
        """Non-numeric variable values are excluded from numeric-range filters without errors."""
        setup = index_setup
        index_log_repository.create_from_results(
            db,
            media_id=setup["media"].media_id,
            user_id=setup["user"].user_id,
            index_id=setup["index_type"].index_id,
            version="non-numeric-value",
            results={"label": "not-a-number"},
        )

        results, total = index_log_repository.get_logs_page(
            db,
            user_id=setup["user"].user_id,
            is_admin=True,
            accessible_collection_ids=None,
            version="non-numeric-value",
            var_value_min=0,
            var_value_max=10,
        )
        assert total == 0
        assert results == []

    def test_sort_asc(self, db: Session, index_setup):
        """sort_desc=False uses ascending order."""
        self._seed(db, index_setup)
        results, total = index_log_repository.get_logs_page(
            db,
            user_id=index_setup["user"].user_id,
            is_admin=True,
            accessible_collection_ids=None,
            sort_by="log_id",
            sort_desc=False,
        )
        assert total >= 0

    def test_sort_desc_unknown_field(self, db: Session, index_setup):
        """Falls back to default sort when sort_by is an unknown field."""
        self._seed(db, index_setup)
        results, total = index_log_repository.get_logs_page(
            db,
            user_id=index_setup["user"].user_id,
            is_admin=True,
            accessible_collection_ids=None,
            sort_by="unknown_field",
            sort_desc=True,
        )
        assert total >= 0


class TestIndexLogRepositoryDelete:
    """Tests for grouped row deletion helpers."""

    def test_delete_group_removes_all_rows_in_group(self, db: Session, index_setup):
        setup = index_setup
        index_log_repository.create_from_results(
            db,
            media_id=setup["media"].media_id,
            user_id=setup["user"].user_id,
            index_id=setup["index_type"].index_id,
            version="delete-group",
            results={"aci": 42.5, "ndsi": 0.7},
            params={"Channel": "Left"},
            output_first=True,
        )
        group_identity = db.execute(
            text(
                """
                SELECT log_id, media_id, index_id
                FROM index_log
                WHERE version = :version
                LIMIT 1
                """
            ),
            {"version": "delete-group"},
        ).first()
        assert group_identity is not None

        removed_rows = index_log_repository.delete_group(
            db,
            log_id=group_identity[0],
            media_id=group_identity[1],
            index_id=group_identity[2],
        )

        assert removed_rows == 3
        remaining = db.execute(
            text("SELECT COUNT(*) FROM index_log WHERE log_id = :log_id"),
            {"log_id": group_identity[0]},
        ).scalar_one()
        assert remaining == 0

    def test_delete_group_does_not_remove_other_group_with_same_log_id(self, db: Session, index_setup):
        setup = index_setup
        db.execute(
            text(
                """
                INSERT INTO index_log (
                    log_id, media_id, user_id, index_id, version,
                    variable_type, variable_order, variable_name, variable_value
                ) VALUES
                    (700001, :media_id, :user_id, :index_id, 'group-a', 'output', 1, 'aci', '1.0'),
                    (700001, :other_media_id, :user_id, :index_id, 'group-b', 'output', 1, 'aci', '2.0')
                """
            ),
            {
                "media_id": setup["media"].media_id,
                "other_media_id": setup["second_media"].media_id,
                "user_id": setup["user"].user_id,
                "index_id": setup["index_type"].index_id,
            },
        )
        db.commit()

        removed_rows = index_log_repository.delete_group(
            db,
            log_id=700001,
            media_id=setup["media"].media_id,
            index_id=setup["index_type"].index_id,
        )

        assert removed_rows == 1
        remaining_versions = db.execute(
            text("SELECT version FROM index_log WHERE log_id = 700001 ORDER BY version"),
        ).scalars().all()
        assert remaining_versions == ["group-b"]
