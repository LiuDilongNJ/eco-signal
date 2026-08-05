from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, select

from app.core.config import settings
from app.models.collection import Collection
from app.models.index import IndexLog, IndexType
from app.models.media import Media, MediaCollection
from app.models.project import Project, ProjectCollection
from tests.utils.csv import read_csv_header


class TestIndexLogsAPI:
    @pytest.fixture(autouse=True)
    def setup_data(self, db: Session) -> None:
        from app.core.config import settings
        from app.repositories import user_repository
        
        # Get existing users
        superuser = user_repository.get_by_username(db, username=settings.FIRST_SUPERUSER)
        normal_user = user_repository.get_by_email(db, email=settings.EMAIL_TEST_USER)
        
        # Ensure normal user exists (same logic as token headers utility)
        if not normal_user:
            from app.schemas.user import UserCreate
            user_in = UserCreate(
                username="testuser",
                name="Test User",
                email=settings.EMAIL_TEST_USER,
                password="testpassword123"
            )
            normal_user = user_repository.create(db, obj_in=user_in)

        # Create some test collections, media, and index specific entities
        from app.models.media import AudioSetting
        audio_setting1 = AudioSetting(duration_s=60.0, sampling_rate_hz=44100)
        audio_setting2 = AudioSetting(duration_s=120.0, sampling_rate_hz=44100)
        db.add_all([audio_setting1, audio_setting2])
        db.commit()
        db.refresh(audio_setting1)
        db.refresh(audio_setting2)

        collection1 = Collection(name="Index Log Collection 1", creator_id=superuser.user_id)
        collection2 = Collection(name="Index Log Collection 2", creator_id=normal_user.user_id)
        collection3 = Collection(name="Index Log Collection 3", creator_id=superuser.user_id)
        db.add_all([collection1, collection2, collection3])
        db.commit()
        db.refresh(collection1)
        db.refresh(collection2)
        db.refresh(collection3)
        project = Project(
            name="Index Log Project",
            url="https://index-log.example",
            creator_id=superuser.user_id,
        )
        other_project = Project(
            name="Index Log Other Project",
            url="https://index-log-other.example",
            creator_id=superuser.user_id,
        )
        db.add_all([project, other_project])
        db.commit()
        db.refresh(project)
        db.refresh(other_project)
        db.add_all([
            ProjectCollection(project_id=project.project_id, collection_id=collection1.collection_id),
            ProjectCollection(project_id=project.project_id, collection_id=collection2.collection_id),
            ProjectCollection(project_id=other_project.project_id, collection_id=collection3.collection_id),
        ])
        db.commit()

        media1 = Media(
            name="Media 1 for Index", 
            media_type="audio",
            uploader_id=superuser.user_id,
            creator_id=superuser.user_id,
            audio_setting_id=audio_setting1.audio_setting_id
        )
        media2 = Media(
            name="Media 2 for Index", 
            media_type="audio",
            uploader_id=normal_user.user_id,
            creator_id=normal_user.user_id,
            audio_setting_id=audio_setting2.audio_setting_id
        )
        media3 = Media(
            name="Media 3 for Index",
            media_type="audio",
            uploader_id=superuser.user_id,
            creator_id=superuser.user_id,
            audio_setting_id=audio_setting1.audio_setting_id
        )
        db.add_all([media1, media2, media3])
        db.commit()
        db.refresh(media1)
        db.refresh(media2)
        db.refresh(media3)

        mc1 = MediaCollection(
            media_id=media1.media_id, 
            collection_id=collection1.collection_id,
            added_by=superuser.user_id
        )
        mc2 = MediaCollection(
            media_id=media2.media_id, 
            collection_id=collection2.collection_id,
            added_by=normal_user.user_id
        )
        mc3 = MediaCollection(
            media_id=media3.media_id,
            collection_id=collection3.collection_id,
            added_by=superuser.user_id
        )
        db.add_all([mc1, mc2, mc3])
        db.commit()

        index_type = IndexType(name="ACI", description="Acoustic Complexity Index")
        db.add(index_type)
        db.commit()
        db.refresh(index_type)

        log1 = IndexLog(
            media_id=media1.media_id,
            user_id=superuser.user_id,
            index_id=index_type.index_id,
            version="1.0",
            min_time="0",
            max_time="60",
            min_frequency="0",
            max_frequency="22050",
            variable_type="output",
            variable_order=1,
            variable_name="aci_value",
            variable_value="145.2"
        )
        log2 = IndexLog(
            media_id=media2.media_id,
            user_id=normal_user.user_id,
            index_id=index_type.index_id,
            version="2.0",
            min_time="10",
            max_time="120",
            min_frequency="100",
            max_frequency="10000",
            variable_type="input",
            variable_order=2,
            variable_name="fft_window",
            variable_value="512"
        )
        log3 = IndexLog(
            media_id=media3.media_id,
            user_id=superuser.user_id,
            index_id=index_type.index_id,
            version="3.0",
            min_time="20",
            max_time="30",
            min_frequency="200",
            max_frequency="5000",
            variable_type="output",
            variable_order=3,
            variable_name="ndsi_score",
            variable_value="0.85"
        )
        db.add_all([log1, log2, log3])
        db.commit()
        db.refresh(log1)
        db.refresh(log2)
        db.refresh(log3)

        self.log1_id = log1.log_id
        self.log1_creation_date = log1.creation_date
        self.log2_id = log2.log_id
        self.log3_id = log3.log_id
        self.log1_media_id = media1.media_id
        self.log2_media_id = media2.media_id
        self.log3_media_id = media3.media_id
        self.project_id = project.project_id
        self.other_project_id = other_project.project_id
        self.collection1_id = collection1.collection_id
        self.collection2_id = collection2.collection_id
        self.collection3_id = collection3.collection_id
        self.index_type_id = index_type.index_id
        self.normal_user_id = normal_user.user_id
        self.superuser_id = superuser.user_id

    def _delete_item(self, log_id: int, media_id: int, index_id: int) -> dict[str, int]:
        return {
            "log_id": log_id,
            "media_id": media_id,
            "index_id": index_id,
        }

    def test_get_index_logs_as_superuser(self, client: TestClient, superuser_token_headers: dict) -> None:
        response = client.get(
            f"{settings.API_V1_STR}/index-logs",
            headers=superuser_token_headers
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["code"] == 0
        # Admin should see both logs
        assert data["page_info"]["total"] >= 2
        
        # Verify joined fields exist
        items = data["data"]
        assert any(item["version"] == "1.0" for item in items)
        
        test1_item = next(item for item in items if item["version"] == "1.0")
        assert "log_id" in test1_item
        assert test1_item["media_name"] == "Media 1 for Index"
        assert test1_item["user_name"] == "Administrator"
        assert test1_item["index_name"] == "ACI"
        assert test1_item["creation_date"] == self.log1_creation_date.strftime("%Y-%m-%d %H:%M:%S")

    def test_get_index_logs_as_normal_user(self, client: TestClient, normal_user_token_headers: dict) -> None:
        response = client.get(
            f"{settings.API_V1_STR}/index-logs",
            headers=normal_user_token_headers
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        # Normal user should only see their log (log2)
        total = data["page_info"]["total"]
        assert total >= 1
        
        items = data["data"]
        versions = [item["version"] for item in items]
        assert "2.0" in versions

    def test_filter_index_logs(self, client: TestClient, superuser_token_headers: dict) -> None:
        response = client.get(
            f"{settings.API_V1_STR}/index-logs/?version=1.0",
            headers=superuser_token_headers
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["page_info"]["total"] == 1
        assert data["data"][0]["version"] == "1.0"

    def test_filter_index_logs_with_current_query_parameters(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        response = client.get(
            f"{settings.API_V1_STR}/index-logs/"
            "?user=Test User&index_type=ACI&min_t_min=10&min_t_max=10"
            "&max_t_min=120&max_t_max=120&min_f_min=100&min_f_max=100"
            "&max_f_min=10000&max_f_max=10000&var_type=input"
            "&var_order_min=2&var_order_max=2&var_name=fft_window"
            "&var_value_min=512&var_value_max=512",
            headers=superuser_token_headers,
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["page_info"]["total"] == 1
        assert data["data"][0]["version"] == "2.0"

    def test_filter_index_logs_supports_fuzzy_text_parameters(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        response = client.get(
            f"{settings.API_V1_STR}/index-logs/?user=Admin&index_type=AC&var_type=out",
            headers=superuser_token_headers,
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["page_info"]["total"] >= 1
        assert any(item["version"] == "1.0" for item in data["data"])

    def test_filter_index_logs_by_numeric_and_date_ranges(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        response = client.get(
            f"{settings.API_V1_STR}/index-logs"
            "?min_t_min=15&min_t_max=25&var_value_min=0.8&var_value_max=1"
            "&creation_date_from=2000-01-01T00:00:00Z",
            headers=superuser_token_headers,
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["page_info"]["total"] == 1
        assert data["data"][0]["version"] == "3.0"


    def test_filter_index_logs_by_project(self, client: TestClient, superuser_token_headers: dict) -> None:
        response = client.get(
            f"{settings.API_V1_STR}/index-logs?project_id={self.project_id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        versions = {item["version"] for item in data["data"]}
        assert versions == {"1.0", "2.0"}

    def test_filter_index_logs_by_collection(self, client: TestClient, superuser_token_headers: dict) -> None:
        response = client.get(
            f"{settings.API_V1_STR}/index-logs?collection_id={self.collection2_id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["page_info"]["total"] == 1
        assert data["data"][0]["version"] == "2.0"

    def test_filter_index_logs_by_media(self, client: TestClient, superuser_token_headers: dict) -> None:
        response = client.get(
            f"{settings.API_V1_STR}/index-logs?media_id={self.log3_media_id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["page_info"]["total"] == 1
        assert data["data"][0]["version"] == "3.0"

    def test_filter_index_logs_by_project_collection_media_intersection(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        response = client.get(
            f"{settings.API_V1_STR}/index-logs"
            f"?project_id={self.project_id}&collection_id={self.collection2_id}&media_id={self.log2_media_id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["page_info"]["total"] == 1
        assert data["data"][0]["version"] == "2.0"

    def test_filter_index_logs_by_project_collection_media_intersection_mismatch(
        self, client: TestClient, superuser_token_headers: dict
    ) -> None:
        response = client.get(
            f"{settings.API_V1_STR}/index-logs"
            f"?project_id={self.project_id}&collection_id={self.collection2_id}&media_id={self.log3_media_id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == HTTPStatus.OK
        data = response.json()
        assert data["page_info"]["total"] == 0
        
    def test_export_index_logs(self, client: TestClient, superuser_token_headers: dict) -> None:
        response = client.get(
            f"{settings.API_V1_STR}/index-logs/exports",
            headers=superuser_token_headers
        )
        assert response.status_code == HTTPStatus.OK
        assert "text/csv" in response.headers.get("content-type", "")
        assert response.headers.get("content-disposition") == (
            'attachment; filename="index-logs.csv"; '
            "filename*=UTF-8''index-logs.csv"
        )
        
        # Should contain CSV header with log fields 
        content = response.text
        header = read_csv_header(content)
        assert header == [
            "log_id", "media_name", "user_name", "user_id", "index_name", "version",
            "min_time", "max_time", "min_frequency", "max_frequency", "variable_type", "variable_order",
            "variable_name", "variable_value", "creation_date",
        ]
        assert "1.0" in content
        assert "2.0" in content
        assert "3.0" in content

    def test_export_index_logs_with_project_filter(self, client: TestClient, superuser_token_headers: dict) -> None:
        response = client.get(
            f"{settings.API_V1_STR}/index-logs/exports?project_id={self.project_id}",
            headers=superuser_token_headers,
        )
        assert response.status_code == HTTPStatus.OK
        content = response.text
        assert "1.0" in content
        assert "2.0" in content
        assert "3.0" not in content

    def test_export_index_logs_ignores_column_filter_parameters(self, client: TestClient, superuser_token_headers: dict) -> None:
        response = client.get(
            f"{settings.API_V1_STR}/index-logs/exports?project_id={self.project_id}&index_type=missing",
            headers=superuser_token_headers,
        )
        assert response.status_code == HTTPStatus.OK
        content = response.text
        assert "1.0" in content
        assert "2.0" in content

    def test_delete_index_logs_as_superuser(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        # Before delete
        log = db.get(IndexLog, self.log1_id)
        assert log is not None
        
        response = client.request(
            "DELETE",
            f"{settings.API_V1_STR}/index-logs",
            headers=superuser_token_headers,
            json=[self._delete_item(self.log1_id, self.log1_media_id, self.index_type_id)],
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["data"] == 1
        
        # Verify deleted
        log_after = db.get(IndexLog, self.log1_id)
        assert log_after is None

    def test_delete_index_logs_removes_full_related_group(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        from app.repositories.index_log_repository import index_log_repository

        index_log_repository.create_from_results(
            db,
            media_id=self.log1_media_id,
            user_id=self.superuser_id,
            index_id=self.index_type_id,
            version="group-delete",
            results={"ACI_sum": 10.0, "NDSI": 0.2},
            params={"Channel": "Left"},
            output_first=True,
        )
        group_log_id = db.execute(
            text("SELECT log_id FROM index_log WHERE version = :version LIMIT 1"),
            {"version": "group-delete"},
        ).scalar_one()
        before_count = db.execute(
            text("SELECT COUNT(*) FROM index_log WHERE log_id = :log_id"),
            {"log_id": group_log_id},
        ).scalar_one()
        assert before_count == 3

        response = client.request(
            "DELETE",
            f"{settings.API_V1_STR}/index-logs",
            headers=superuser_token_headers,
            json=[self._delete_item(group_log_id, self.log1_media_id, self.index_type_id)],
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["data"] == 1

        after_count = db.execute(
            text("SELECT COUNT(*) FROM index_log WHERE log_id = :log_id"),
            {"log_id": group_log_id},
        ).scalar_one()
        assert after_count == 0

    def test_delete_index_logs_as_normal_user(self, client: TestClient, normal_user_token_headers: dict, db: Session) -> None:
        # 1. Initially should fail without specific permission
        response = client.request(
            "DELETE",
            f"{settings.API_V1_STR}/index-logs",
            headers=normal_user_token_headers,
            json=[self._delete_item(self.log2_id, self.log2_media_id, self.index_type_id)],
        )
        assert response.status_code == 403

        # 2. Grant collection:write permission
        from app.models.permission import Permission, UserPermission

        perm = db.exec(select(Permission).where(Permission.resource_type == "collection", Permission.action == "write")).first()
        user_perm = UserPermission(
            user_id=self.normal_user_id,
            permission_id=perm.permission_id,
            project_id=self.project_id,
            collection_id=self.collection2_id
        )
        db.add(user_perm)
        db.commit()

        # 3. Should succeed now
        response = client.request(
            "DELETE",
            f"{settings.API_V1_STR}/index-logs",
            headers=normal_user_token_headers,
            json=[self._delete_item(self.log2_id, self.log2_media_id, self.index_type_id)],
        )
        assert response.status_code == 200
        assert response.json()["data"] == 1

    def test_delete_index_logs_deduplicates_duplicate_items(self, client: TestClient, superuser_token_headers: dict, db: Session) -> None:
        from app.repositories.index_log_repository import index_log_repository

        index_log_repository.create_from_results(
            db,
            media_id=self.log1_media_id,
            user_id=self.superuser_id,
            index_id=self.index_type_id,
            version="group-delete-dedup",
            results={"ACI_sum": 10.0},
            params={"Channel": "Left"},
            output_first=True,
        )
        group_log_id = db.execute(
            text("SELECT log_id FROM index_log WHERE version = :version LIMIT 1"),
            {"version": "group-delete-dedup"},
        ).scalar_one()

        payload = [self._delete_item(group_log_id, self.log1_media_id, self.index_type_id)] * 2
        response = client.request(
            "DELETE",
            f"{settings.API_V1_STR}/index-logs",
            headers=superuser_token_headers,
            json=payload,
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["data"] == 1

    def test_delete_index_logs_skips_missing_group(self, client: TestClient, superuser_token_headers: dict) -> None:
        response = client.request(
            "DELETE",
            f"{settings.API_V1_STR}/index-logs",
            headers=superuser_token_headers,
            json=[self._delete_item(999999, self.log1_media_id, self.index_type_id)],
        )
        assert response.status_code == HTTPStatus.OK
        assert response.json()["data"] == 0

    def test_delete_index_logs_returns_404_for_mismatched_media_or_index(self, client: TestClient, superuser_token_headers: dict) -> None:
        response = client.request(
            "DELETE",
            f"{settings.API_V1_STR}/index-logs",
            headers=superuser_token_headers,
            json=[self._delete_item(self.log1_id, self.log2_media_id, self.index_type_id)],
        )
        assert response.status_code == 404

    def test_delete_index_logs_rejects_log_id_array(self, client: TestClient, superuser_token_headers: dict) -> None:
        response = client.request(
            "DELETE",
            f"{settings.API_V1_STR}/index-logs",
            headers=superuser_token_headers,
            json=[self.log1_id],
        )
        assert response.status_code == 422
