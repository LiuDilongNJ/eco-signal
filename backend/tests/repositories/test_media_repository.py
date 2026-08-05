"""Unit tests for MediaRepository (full coverage)."""

from datetime import datetime

import pytest
from sqlmodel import Session, select

from app.models import (
    AudioSetting,
    Collection,
    IucnGet,
    Label,
    LabelMedia,
    Media,
    MediaCollection,
    PhotoSetting,
    Preview,
    Project,
    ProjectCollection,
    Role,
    Site,
    User,
)
from app.repositories.media_repository import media_repository


@pytest.fixture
def test_setup(db: Session):
    """Setup basic entities needed for media tests."""
    role = Role(name="Test Role")
    db.add(role)
    db.flush()

    user = User(
        username="test_user_repo",
        name="Test User",
        email="test_repo@example.com",
        role_id=role.role_id,
        password="hashed_password",
    )
    db.add(user)
    db.flush()

    return {"user": user, "role": role}


class TestMediaRepository:
    """Tests for MediaRepository."""

    def test_get_preview_by_media_and_type(self, db: Session, test_setup):
        """Preview lookup should return the first preview for the requested type."""
        user = test_setup["user"]
        media = Media(
            filename="repo.wav",
            media_type="audio", is_metadata=True,
            creator_id=user.user_id,
            uploader_id=user.user_id,
        )
        db.add(media)
        db.flush()

        first = Preview(media_id=media.media_id, filename="repo_a.png", type="thumbnail")
        second = Preview(media_id=media.media_id, filename="repo_b.png", type="thumbnail")
        db.add_all([first, second])
        db.commit()

        preview = media_repository.get_preview_by_media_and_type(
            db,
            media.media_id,
            "thumbnail",
        )

        assert preview is not None
        assert preview.filename == "repo_a.png"

    def test_apply_filters_all_fields(self, db: Session, test_setup):
        """Test as many filters as possible to reach high coverage."""
        user = test_setup["user"]
        site = Site(name="S1", code="C1", creator_id=user.user_id)
        db.add(site)
        db.flush()

        aset = AudioSetting(
            duration_s=10.0,
            sampling_rate_hz=44100,
            bit_depth=16,
            channel_num=1,
            recording_gain_db=10,
        )
        db.add(aset)
        db.flush()

        m1 = Media(
            filename="bird.wav",
            name="Bird",
            media_type="audio",
            audio_setting_id=aset.audio_setting_id,
            site_id=site.site_id,
            medium="air",
            note="Test note",
            size_b=1000,
            creator_id=user.user_id,
            uploader_id=user.user_id,
            doi="10.123/456",
            duty_cycle_recording=30,
            duty_cycle_period=60,
            date_time=datetime(2023, 1, 1),
            creation_date=datetime(2023, 1, 2),
        )
        db.add(m1)
        db.flush()

        # Test individual filters
        results = media_repository.list_filtered(db, uuid=m1.uuid)
        assert len(results) == 1

        results = media_repository.list_filtered(db, media_type="audio")
        assert len(results) == 1

        results = media_repository.list_filtered(db, medium="air")
        assert len(results) == 1

        results = media_repository.list_filtered(db, doi="10.123")
        assert len(results) == 1

        results = media_repository.list_filtered(db, note="Test")
        assert len(results) == 1

        results = media_repository.list_filtered(db, uploader_id=user.user_id)
        assert len(results) == 1

        results = media_repository.list_filtered(db, creator_id=user.user_id)
        assert len(results) == 1

        results = media_repository.list_filtered(
            db,
            creation_date_from=datetime(2023, 1, 1),
            creation_date_to=datetime(2023, 1, 3),
        )
        assert len(results) == 1

        # DUTY CYCLE
        results = media_repository.list_filtered(db, duty_cycle_recording_min=20, duty_cycle_recording_max=40)
        assert len(results) == 1
        results = media_repository.list_filtered(
            db, duty_cycle_period_min=50, duty_cycle_period_max=70
        )
        assert len(results) == 1

        # AUDIO ADVANCED
        results = media_repository.list_filtered(db, bit_depth_min=15, bit_depth_max=17)
        assert len(results) == 1
        results = media_repository.list_filtered(db, channel_num_min=1, channel_num_max=2)
        assert len(results) == 1
        results = media_repository.list_filtered(db, recording_gain_db_min=5, recording_gain_db_max=15)
        assert len(results) == 1

        # SIZE
        results = media_repository.list_filtered(db, size_b_min=900, size_b_max=1100)
        assert len(results) == 1

        # COUNT
        count = media_repository.count_filtered(db, media_type="audio")
        assert count == 1

    def test_apply_filters_supports_exact_media_type_fuzzy_medium_and_type_alias(self, db: Session, test_setup):
        """media_type matches exactly; medium stays fuzzy; type alias maps to is_metadata."""
        user = test_setup["user"]
        audio_setting = AudioSetting(
            duration_s=5.0,
            sampling_rate_hz=44100,
            bit_depth=16,
            channel_num=1,
        )
        db.add(audio_setting)
        db.flush()
        audio = Media(
            filename="fuzzy-audio.wav",
            media_type="audio",
            is_metadata=False,
            medium="air",
            audio_setting_id=audio_setting.audio_setting_id,
            creator_id=user.user_id,
        )
        metadata = Media(
            filename="fuzzy-metadata.wav",
            media_type="audio",
            is_metadata=True,
            medium="water",
            creator_id=user.user_id,
        )
        db.add_all([audio, metadata])
        db.commit()

        results = media_repository.list_filtered(db, media_type="audio")
        assert {item.filename for item in results} >= {"fuzzy-audio.wav", "fuzzy-metadata.wav"}

        # Partial values no longer match: media_type is an exact filter.
        results = media_repository.list_filtered(db, media_type="aud")
        assert results == []

        results = media_repository.list_filtered(db, medium="ai")
        assert [item.filename for item in results] == ["fuzzy-audio.wav"]

        results = media_repository.list_filtered(db, type="metadata")
        assert [item.filename for item in results] == ["fuzzy-metadata.wav"]

        results = media_repository.list_filtered(db, type="file")
        assert [item.filename for item in results] == ["fuzzy-audio.wav"]

    def test_apply_filters_audio_settings(self, db: Session, test_setup):
        """Test filters that join with AudioSetting."""
        user = test_setup["user"]
        s1 = AudioSetting(sampling_rate_hz=44100, duration_s=10.0, bit_depth=16)
        s2 = AudioSetting(sampling_rate_hz=48000, duration_s=60.0, bit_depth=24)
        db.add_all([s1, s2])
        db.flush()

        m1 = Media(
            filename="m1.wav",
            media_type="audio",
            audio_setting_id=s1.audio_setting_id,
            creator_id=user.user_id,
        )
        m2 = Media(
            filename="m2.wav",
            media_type="audio",
            audio_setting_id=s2.audio_setting_id,
            creator_id=user.user_id,
        )
        db.add_all([m1, m2])
        db.flush()

        # Sample rate filter
        results = media_repository.list_filtered(db, sampling_rate_hz_min=45000)
        assert len(results) == 1
        assert results[0].filename == "m2.wav"

        # Duration filter
        results = media_repository.list_filtered(db, duration_s_max=30.0)
        assert len(results) == 1
        assert results[0].filename == "m1.wav"

    def test_apply_filters_project_and_collection(self, db: Session, test_setup):
        """Test project and collection level filtering."""
        user = test_setup["user"]
        p = Project(name="P1", creator_id=user.user_id, url="http://p1.com")
        col = Collection(name="C1", creator_id=user.user_id)
        db.add_all([p, col])
        db.flush()

        db.add(
            ProjectCollection(project_id=p.project_id, collection_id=col.collection_id)
        )

        m1 = Media(filename="m1.wav", media_type="audio", is_metadata=True, creator_id=user.user_id)
        db.add(m1)
        db.flush()

        db.add(
            MediaCollection(
                media_id=m1.media_id,
                collection_id=col.collection_id,
                added_by=user.user_id,
            )
        )
        db.flush()

        # Collection filter
        results = media_repository.list_filtered(db, collection_id=col.collection_id)
        assert len(results) == 1

        # Project filter
        results = media_repository.list_filtered(db, project_id=p.project_id)
        assert len(results) == 1

    def test_get_media_timeline_media_returns_lightweight_deduplicated_rows(
        self, db: Session, test_setup
    ):
        """Timeline query should return one lightweight row per visible media."""
        user = test_setup["user"]
        project = Project(name="Timeline P", creator_id=user.user_id, url="http://timeline.test")
        collection_a = Collection(name="Timeline A", creator_id=user.user_id)
        collection_b = Collection(name="Timeline B", creator_id=user.user_id)
        realm = IucnGet(pid=0, name="Marine", level=1)
        db.add_all([project, collection_a, collection_b, realm])
        db.flush()

        db.add_all(
            [
                ProjectCollection(
                    project_id=project.project_id, collection_id=collection_a.collection_id
                ),
                ProjectCollection(
                    project_id=project.project_id, collection_id=collection_b.collection_id
                ),
            ]
        )
        db.flush()

        site = Site(name="Timeline Site", creator_id=user.user_id, realm_id=realm.iucn_get_id)
        audio_setting = AudioSetting(duration_s=42.5, sampling_rate_hz=44100)
        db.add_all([site, audio_setting])
        db.flush()

        shared_media = Media(
            filename="shared.wav",
            name="Shared audio",
            media_type="audio",
            creator_id=user.user_id,
            uploader_id=user.user_id,
            date_time=datetime(2026, 3, 17, 12, 0, 0),
            site_id=site.site_id,
            audio_setting_id=audio_setting.audio_setting_id,
            duty_cycle_recording=30,
            duty_cycle_period=300,
        )
        metadata_media = Media(
            filename="meta.csv",
            name="Metadata row",
            media_type="audio", is_metadata=True,
            creator_id=user.user_id,
            uploader_id=user.user_id,
            date_time=datetime(2026, 3, 17, 13, 0, 0),
        )
        db.add_all([shared_media, metadata_media])
        db.flush()

        db.add_all(
            [
                MediaCollection(
                    media_id=shared_media.media_id,
                    collection_id=collection_a.collection_id,
                    added_by=user.user_id,
                ),
                MediaCollection(
                    media_id=shared_media.media_id,
                    collection_id=collection_b.collection_id,
                    added_by=user.user_id,
                ),
                MediaCollection(
                    media_id=metadata_media.media_id,
                    collection_id=collection_a.collection_id,
                    added_by=user.user_id,
                ),
            ]
        )
        db.commit()

        rows = media_repository.get_media_timeline_media(
            db,
            project_id=project.project_id,
            visible_collection_ids=[collection_a.collection_id, collection_b.collection_id],
            include_metadata=True,
        )

        assert len(rows) == 2
        by_id = {row.media_id: row for row in rows}
        shared_row = by_id[shared_media.media_id]
        assert shared_row.name == "Shared audio"
        assert shared_row.filename == "shared.wav"
        assert shared_row.duration_s == 42.5
        assert shared_row.creator_name == user.name
        assert shared_row.site_name == "Timeline Site"
        assert shared_row.realm_name == "Marine"
        assert shared_row.duty_cycle_recording == 30
        assert shared_row.duty_cycle_period == 300

        metadata_row = by_id[metadata_media.media_id]
        assert metadata_row.name == "Metadata (1)"
        assert metadata_row.date_time.replace(tzinfo=None) == datetime(2026, 3, 1, 0, 0, 0)
        assert metadata_row.end_time is not None
        assert metadata_row.end_time.replace(tzinfo=None) == datetime(2026, 4, 1, 0, 0, 0)
        assert metadata_row.item_count == 1
        assert metadata_row.duration_s is None
        assert metadata_row.duty_cycle_period is None
        assert metadata_row.site_name is None
        assert metadata_row.realm_name is None

        detail_rows, has_more = media_repository.get_media_timeline_detail_media(
            db,
            project_id=project.project_id,
            visible_collection_ids=[collection_a.collection_id, collection_b.collection_id],
            site_key="nogeo",
            start_date=datetime(2026, 3, 17, 0, 0, 0),
            end_date=datetime(2026, 3, 18, 0, 0, 0),
            limit=10,
        )
        assert has_more is False
        assert len(detail_rows) == 1
        detail_row = detail_rows[0]
        assert detail_row.name == "Metadata row"
        assert detail_row.date_time.replace(tzinfo=None) == datetime(2026, 3, 17, 13, 0, 0)
        assert detail_row.end_time is None
        assert detail_row.duty_cycle_period is None

        limited_rows, limited_has_more = media_repository.get_media_timeline_detail_media(
            db,
            project_id=project.project_id,
            visible_collection_ids=[collection_a.collection_id, collection_b.collection_id],
            site_key="nogeo",
            start_date=datetime(2026, 3, 17, 0, 0, 0),
            end_date=datetime(2026, 3, 18, 0, 0, 0),
            limit=0,
        )
        assert limited_rows == []
        assert limited_has_more is True

    def test_timeline_detail_metadata_uses_audio_setting_duration(self, db: Session):
        role = db.exec(select(Role).order_by(Role.role_id.asc())).first()
        if role is None:
            role = Role(name="Detail Meta Role")
            db.add(role)
            db.flush()

        user = User(
            username="detailmeta",
            name="Detail Meta",
            email="detailmeta@test.com",
            password="x",
            role_id=role.role_id,
        )
        project = Project(name="Detail Meta Project", creator_id=1, url="https://detail-meta.example")
        collection = Collection(name="Detail Meta Collection", creator_id=1)
        db.add_all([user, project, collection])
        db.flush()

        db.add(ProjectCollection(project_id=project.project_id, collection_id=collection.collection_id))
        metadata_audio_setting = AudioSetting(duration_s=75.0, sampling_rate_hz=22050)
        db.add(metadata_audio_setting)
        db.flush()

        metadata_media = Media(
            filename="meta-with-audio-setting.csv",
            name="Metadata with AudioSetting",
            media_type="audio", is_metadata=True,
            creator_id=user.user_id,
            uploader_id=user.user_id,
            date_time=datetime(2026, 3, 17, 13, 0, 0),
            audio_setting_id=metadata_audio_setting.audio_setting_id,
        )
        db.add(metadata_media)
        db.flush()
        db.add(
            MediaCollection(
                media_id=metadata_media.media_id,
                collection_id=collection.collection_id,
                added_by=user.user_id,
            )
        )
        db.commit()

        detail_rows, has_more = media_repository.get_media_timeline_detail_media(
            db,
            project_id=project.project_id,
            visible_collection_ids=[collection.collection_id],
            site_key="nogeo",
            start_date=datetime(2026, 3, 17, 0, 0, 0),
            end_date=datetime(2026, 3, 18, 0, 0, 0),
            limit=10,
        )

        assert has_more is False
        assert len(detail_rows) == 1
        assert detail_rows[0].duration_s == 75.0

    def test_apply_filters_label_id(self, db: Session, test_setup):
        """Test exact label ID filtering."""
        user = test_setup["user"]
        label = Label(name="Bird", creator_id=user.user_id)
        db.add(label)
        db.flush()

        m1 = Media(filename="m1.wav", media_type="audio", is_metadata=True, creator_id=user.user_id)
        db.add(m1)
        db.flush()

        db.add(
            LabelMedia(
                media_id=m1.media_id, label_id=label.label_id, user_id=user.user_id
            )
        )
        db.flush()

        results = media_repository.list_filtered(
            db,
            label_id=label.label_id,
            label_user_id=user.user_id,
        )
        assert len(results) == 1
        assert results[0].filename == "m1.wav"

    def test_apply_filters_label_id_ignores_other_users(self, db: Session, test_setup):
        """Label ID filters should only match the current user's labels."""
        user = test_setup["user"]
        other = User(
            username="other_repo_user",
            name="Other Repo User",
            email="other_repo@example.com",
            role_id=test_setup["role"].role_id,
            password="hashed_password",
        )
        db.add(other)
        db.flush()

        label = Label(name="Other User Label", creator_id=other.user_id)
        media = Media(filename="other-label.wav", media_type="audio", is_metadata=True, creator_id=user.user_id)
        db.add_all([label, media])
        db.flush()
        db.add(
            LabelMedia(
                media_id=media.media_id,
                label_id=label.label_id,
                user_id=other.user_id,
            )
        )
        db.commit()

        results = media_repository.list_filtered(
            db,
            label_id=label.label_id,
            label_user_id=user.user_id,
        )
        assert results == []

    def test_apply_filters_label_id_distinguishes_same_name_labels(
        self, db: Session, test_setup
    ):
        """Filtering by label ID should not match a different label with the same name."""
        user = test_setup["user"]
        selected_label = Label(name="Reviewed", creator_id=user.user_id)
        other_label = Label(name="Reviewed", creator_id=user.user_id)
        selected_media = Media(
            filename="selected-label.wav",
            media_type="audio", is_metadata=True,
            creator_id=user.user_id,
        )
        other_media = Media(
            filename="other-label.wav",
            media_type="audio", is_metadata=True,
            creator_id=user.user_id,
        )
        db.add_all([selected_label, other_label, selected_media, other_media])
        db.flush()
        db.add_all(
            [
                LabelMedia(
                    media_id=selected_media.media_id,
                    label_id=selected_label.label_id,
                    user_id=user.user_id,
                ),
                LabelMedia(
                    media_id=other_media.media_id,
                    label_id=other_label.label_id,
                    user_id=user.user_id,
                ),
            ]
        )
        db.commit()

        results = media_repository.list_filtered(
            db,
            label_id=selected_label.label_id,
            label_user_id=user.user_id,
        )

        assert [media.filename for media in results] == ["selected-label.wav"]



    def test_ordering(self, db: Session, test_setup):
        """Test various ordering options."""
        user = test_setup["user"]
        s1 = AudioSetting(
            duration_s=10.0,
            sampling_rate_hz=22050,
            bit_depth=8,
            channel_num=1,
            recording_gain_db=0,
        )
        s2 = AudioSetting(
            duration_s=20.0,
            sampling_rate_hz=44100,
            bit_depth=16,
            channel_num=2,
            recording_gain_db=20,
        )
        db.add_all([s1, s2])
        db.flush()

        m1 = Media(
            filename="a.wav",
            media_type="audio",
            size_b=100,
            audio_setting_id=s1.audio_setting_id,
            creator_id=user.user_id,
            name="Media A",
        )
        m2 = Media(
            filename="b.wav",
            media_type="audio",
            size_b=50,
            audio_setting_id=s2.audio_setting_id,
            creator_id=user.user_id,
            name="Media B",
        )
        db.add_all([m1, m2])
        db.flush()

        # Test AudioSetting ordering
        res = media_repository.list_filtered(
            db, order_by="sampling_rate_hz", order_dir="desc", creator_id=user.user_id
        )
        assert res[0].filename == "b.wav"

        res = media_repository.list_filtered(
            db, order_by="duration_s", order_dir="asc", creator_id=user.user_id
        )
        assert res[0].filename == "a.wav"

        res = media_repository.list_filtered(
            db, order_by="bit_depth", order_dir="desc", creator_id=user.user_id
        )
        assert res[0].filename == "b.wav"

        res = media_repository.list_filtered(
            db, order_by="channel_num", order_dir="desc", creator_id=user.user_id
        )
        assert res[0].filename == "b.wav"

        res = media_repository.list_filtered(
            db, order_by="recording_gain_db", order_dir="desc", creator_id=user.user_id
        )
        assert res[0].filename == "b.wav"

        # Test Media ordering
        res = media_repository.list_filtered(
            db, order_by="name", order_dir="desc", creator_id=user.user_id
        )
        assert res[0].name == "Media B"

        # Type column (is_metadata) must be sortable: file (False) before metadata (True) asc.
        m1.is_metadata = False
        m2.is_metadata = True
        db.add_all([m1, m2])
        db.flush()
        res = media_repository.list_filtered(
            db, order_by="is_metadata", order_dir="asc", creator_id=user.user_id
        )
        assert [media.is_metadata for media in res] == [False, True]
        res = media_repository.list_filtered(
            db, order_by="is_metadata", order_dir="desc", creator_id=user.user_id
        )
        assert [media.is_metadata for media in res] == [True, False]

    def test_photo_setting_filtering_and_ordering(self, db: Session, test_setup):
        user = test_setup["user"]
        low = PhotoSetting(exposure_ms=5, aperture=1.8, iso=100)
        high = PhotoSetting(exposure_ms=20, aperture=4, iso=800)
        db.add_all([low, high])
        db.flush()
        db.add_all([
            Media(
                filename="low.jpg",
                media_type="photo",
                creator_id=user.user_id,
                photo_setting_id=low.photo_setting_id,
            ),
            Media(
                filename="high.jpg",
                media_type="photo",
                creator_id=user.user_id,
                photo_setting_id=high.photo_setting_id,
            ),
        ])
        db.commit()

        filtered = media_repository.list_filtered(
            db,
            creator_id=user.user_id,
            media_type="photo",
            exposure_ms_min=10,
            iso_max=800,
        )
        assert [media.filename for media in filtered] == ["high.jpg"]

        for order_by in ("exposure_ms", "aperture", "iso"):
            ordered = media_repository.list_filtered(
                db,
                creator_id=user.user_id,
                media_type="photo",
                order_by=order_by,
                order_dir="desc",
            )
            assert [media.filename for media in ordered[:2]] == ["high.jpg", "low.jpg"]

    def test_accessible_visibility(self, db: Session, test_setup):
        """Accessible media filtering is project-scoped: public collections are
        visible, private ones require a permission grant, and listings without
        a project scope are denied."""
        from app.models import Permission, UserPermission

        user = test_setup["user"]

        col = Collection(
            name="Private Col", public_access=False, creator_id=user.user_id
        )
        db.add(col)
        db.flush()

        m = Media(filename="secret.wav", media_type="audio", is_metadata=True, creator_id=user.user_id)
        db.add(m)
        db.flush()
        db.add(
            MediaCollection(
                media_id=m.media_id,
                collection_id=col.collection_id,
                added_by=user.user_id,
            )
        )

        col_pub = Collection(
            name="Public Col", public_access=True, creator_id=user.user_id
        )
        db.add(col_pub)
        db.flush()
        m2 = Media(
            filename="public.wav", media_type="audio", is_metadata=True, creator_id=user.user_id
        )
        db.add(m2)
        db.flush()
        db.add(
            MediaCollection(
                media_id=m2.media_id,
                collection_id=col_pub.collection_id,
                added_by=user.user_id,
            )
        )

        project = Project(
            name="Visibility Project",
            url="https://media-repo.example",
            public=True,
            creator_id=user.user_id,
        )
        db.add(project)
        db.flush()
        db.add_all([
            ProjectCollection(project_id=project.project_id, collection_id=col.collection_id),
            ProjectCollection(project_id=project.project_id, collection_id=col_pub.collection_id),
        ])
        db.flush()

        visitor = User(
            username="visitor",
            name="V",
            email="v@e.com",
            role_id=test_setup["role"].role_id,
            password="p",
        )
        db.add(visitor)
        db.flush()

        # Non-admin listings without a project scope are denied outright.
        res = media_repository.list_filtered(
            db, visibility="accessible", user_id=visitor.user_id
        )
        assert res == []

        res = media_repository.list_filtered(
            db,
            visibility="accessible",
            user_id=visitor.user_id,
            project_id=project.project_id,
        )
        assert any(x.filename == "public.wav" for x in res)
        assert all(x.filename != "secret.wav" for x in res)

        perm = db.exec(
            select(Permission).where(
                Permission.resource_type == "audio", Permission.action == "read"
            )
        ).first()
        if not perm:
            perm = Permission(resource_type="audio", action="read", name="audio:read")
            db.add(perm)
            db.flush()

        db.add(
            UserPermission(
                user_id=visitor.user_id,
                permission_id=perm.permission_id,
                project_id=project.project_id,
                collection_id=col.collection_id,
            )
        )
        db.flush()

        res = media_repository.list_filtered(
            db,
            visibility="accessible",
            user_id=visitor.user_id,
            project_id=project.project_id,
        )
        assert any(x.filename == "public.wav" for x in res)
        assert any(x.filename == "secret.wav" for x in res)

        count = media_repository.count_filtered(
            db,
            visibility="accessible",
            user_id=visitor.user_id,
            project_id=project.project_id,
        )
        assert count >= 2
