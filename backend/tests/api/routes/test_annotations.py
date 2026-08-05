"""
Tests for Annotations API endpoints.
"""
import csv
import datetime

import jwt as pyjwt
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import Permission, UserPermission, Role
from app.models.annotation import Annotation
from app.models.collection import Collection
from app.models.media import Media, MediaCollection, PhotoSetting
from app.models.project import Project, ProjectCollection
from app.models.taxon import SoundClassification
from app.models.user import User
from tests.utils.csv import read_csv_header
from tests.utils.utils import random_lower_string


def _create_normal_user(db: Session) -> User:
    role = db.exec(select(Role).where(Role.name == "User")).first()
    user = User(
        role_id=role.role_id,
        username=f"u_{random_lower_string()[:8]}",
        password="hashed",
        name="Test User",
        email=f"{random_lower_string()[:8]}@test.com",
        active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _grant_collection_perm(db: Session, user_id: int, collection_id: int, perm_name: str) -> None:
    perm = db.exec(select(Permission).where(Permission.name == perm_name)).one()
    project_id = db.exec(
        select(ProjectCollection.project_id).where(ProjectCollection.collection_id == collection_id)
    ).first()
    assert project_id is not None
    db.add(
        UserPermission(
            user_id=user_id,
            project_id=project_id,
            collection_id=collection_id,
            permission_id=perm.permission_id,
        )
    )
    db.commit()


def create_test_media(
    db: Session,
    public_access: bool = True,
    public_tags: bool = False,
    media_type: str = "audio",
    is_metadata: bool = True,
) -> tuple[Media, Collection, Project]:
    sound = db.get(SoundClassification, 1)
    if not sound:
        sound = SoundClassification(name="biophony")
        db.add(sound)
        db.commit()
        db.refresh(sound)

    col = Collection(
        name=f"ann_col_{random_lower_string()[:6]}",
        public_access=public_access,
        public_tags=public_tags,
        creator_id=1
    )
    db.add(col)
    db.commit()
    db.refresh(col)

    photo_setting_id = None
    if media_type == "photo":
        photo_setting = PhotoSetting()
        db.add(photo_setting)
        db.commit()
        db.refresh(photo_setting)
        photo_setting_id = photo_setting.photo_setting_id

    media = Media(
        name=f"test_{random_lower_string()[:6]}.wav",
        uploader_id=1,
        media_type=media_type,
        is_metadata=is_metadata,
        photo_setting_id=photo_setting_id,
        date_time=datetime.datetime.now(datetime.UTC),
    )
    db.add(media)
    db.commit()
    db.refresh(media)

    mc = MediaCollection(media_id=media.media_id, collection_id=col.collection_id, added_by=1)
    db.add(mc)

    project = Project(
        name=f"ann_proj_{random_lower_string()[:6]}",
        url=f"https://example.com/{random_lower_string()[:8]}",
        creator_id=1,
        public=True,
        active=True,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    pc = ProjectCollection(project_id=project.project_id, collection_id=col.collection_id)
    db.add(pc)
    db.commit()
    return media, col, project
def test_create_annotation(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    media, col, project = create_test_media(db)

    data = {
        "project_id": project.project_id,
        "media_id": media.media_id,
        "sound_id": 1,
        "min_x": 1.0,
        "max_x": 5.0,
        "min_y": 100.0,
        "max_y": 8000.0,
        "creator_type": "user",
        "comments": "Test annotation"
    }

    response = client.post(
        f"{settings.API_V1_STR}/annotations",
        headers=superuser_token_headers,
        json=data
    )

    assert response.status_code == 201
    content = response.json()
    assert content["code"] == 0
    assert content["data"] is None
    ann = db.exec(
        select(Annotation).where(Annotation.media_id == media.media_id).order_by(Annotation.annotation_id.desc())
    ).first()
    assert ann is not None
    assert ann.min_x == 1.0
    assert ann.comments == "Test annotation"


def test_create_annotation_for_photo_media(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    media, _col, project = create_test_media(db, media_type="photo")

    data = {
        "project_id": project.project_id,
        "media_id": media.media_id,
        "sound_id": 1,
        "min_x": 2.0,
        "max_x": 6.0,
        "min_y": 50.0,
        "max_y": 500.0,
        "creator_type": "user",
        "comments": "Photo annotation",
    }

    response = client.post(
        f"{settings.API_V1_STR}/annotations",
        headers=superuser_token_headers,
        json=data,
    )

    assert response.status_code == 201
    ann = db.exec(
        select(Annotation)
        .where(Annotation.media_id == media.media_id)
        .order_by(Annotation.annotation_id.desc())
    ).first()
    assert ann is not None
    assert ann.comments == "Photo annotation"


def test_list_annotations(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    media, col, project = create_test_media(db)
    admin = db.exec(select(User).where(User.username == settings.FIRST_SUPERUSER)).first()
    assert admin is not None
    admin.color = "#123ABC"
    db.add(admin)
    db.commit()
    data = {"project_id": project.project_id, "media_id": media.media_id, "sound_id": 1, "min_x": 0.0, "max_x": 1.0, "min_y": 0.0, "max_y": 1000.0}
    client.post(f"{settings.API_V1_STR}/annotations", headers=superuser_token_headers, json=data)

    response = client.get(
        f"{settings.API_V1_STR}/annotations?project_id={project.project_id}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    content = response.json()
    assert content["code"] == 0
    assert "data" in content
    assert "page_info" in content
    assert content["page_info"]["total"] > 0
    assert content["data"][0]["creator_color"] == "#123ABC"
    assert content["data"][0]["media_type"] == "audio"


def test_list_annotations_filters_and_orders_by_media_type(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    audio, collection, project = create_test_media(db, media_type="audio")
    photo, _, _ = create_test_media(db, media_type="photo")
    db.add(MediaCollection(media_id=photo.media_id, collection_id=collection.collection_id, added_by=1))
    db.add_all([
        Annotation(media_id=audio.media_id, sound_id=1, creator_id=1, min_x=0, max_x=1, min_y=0, max_y=1),
        Annotation(media_id=photo.media_id, sound_id=1, creator_id=1, min_x=0, max_x=1, min_y=0, max_y=1),
    ])
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/annotations",
        params={"project_id": project.project_id, "media_type": "photo", "order_by": "media_type"},
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    assert response.json()["page_info"]["total"] == 1
    assert [item["media_type"] for item in response.json()["data"]] == ["photo"]

    ordered = client.get(
        f"{settings.API_V1_STR}/annotations",
        params={"project_id": project.project_id, "order_by": "media_type", "order_dir": "desc"},
        headers=superuser_token_headers,
    )
    assert [item["media_type"] for item in ordered.json()["data"]] == ["photo", "audio"]


def test_list_annotations_supports_fuzzy_text_filters(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    media, _col, project = create_test_media(db)
    sound = db.exec(select(SoundClassification).where(SoundClassification.sound_id == 1)).first()
    assert sound is not None
    sound.soundscape_component = "Biophony"
    sound.sound_type = "Bird Call"
    db.add(sound)
    db.commit()

    response = client.post(
        f"{settings.API_V1_STR}/annotations",
        headers=superuser_token_headers,
        json={
            "project_id": project.project_id,
            "media_id": media.media_id,
            "sound_id": 1,
            "min_x": 0.0,
            "max_x": 1.0,
            "min_y": 0.0,
            "max_y": 1000.0,
            "creator_type": "BirdNET-Analyzer 2.4",
            "animal_sound_type": "song",
        },
    )
    assert response.status_code == 201

    response = client.get(
        f"{settings.API_V1_STR}/annotations",
        params={
            "project_id": project.project_id,
            "creator_type": "birdnet",
            "soundscape_component": "bio",
            "animal_sound_type": "son",
        },
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    assert response.json()["page_info"]["total"] == 1


def test_list_annotations_project_scope_orders_by_annotation_id_without_media_filter(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    first_media, first_col, project = create_test_media(db, public_access=True, public_tags=True)

    second_media = Media(
        name=f"test_{random_lower_string()[:6]}.wav",
        uploader_id=1,
        media_type="audio",
        is_metadata=True,
        date_time=datetime.datetime.now(datetime.UTC),
    )
    db.add(second_media)
    db.commit()
    db.refresh(second_media)

    db.add(MediaCollection(media_id=second_media.media_id, collection_id=first_col.collection_id, added_by=1))
    db.commit()

    annotations = [
        Annotation(
            media_id=first_media.media_id,
            sound_id=1,
            min_x=5.0,
            max_x=6.0,
            min_y=0.0,
            max_y=1000.0,
            creator_type="user",
            creator_id=1,
        ),
        Annotation(
            media_id=second_media.media_id,
            sound_id=1,
            min_x=1.0,
            max_x=2.0,
            min_y=0.0,
            max_y=1000.0,
            creator_type="user",
            creator_id=1,
        ),
        Annotation(
            media_id=first_media.media_id,
            sound_id=1,
            min_x=9.0,
            max_x=10.0,
            min_y=0.0,
            max_y=1000.0,
            creator_type="user",
            creator_id=1,
        ),
    ]
    db.add_all(annotations)
    db.commit()
    for annotation in annotations:
        db.refresh(annotation)

    response = client.get(
        f"{settings.API_V1_STR}/annotations"
        f"?project_id={project.project_id}&page=1&page_size=2&order_by=annotation_id&order_dir=asc",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    content = response.json()
    expected_ids = sorted(annotation.annotation_id for annotation in annotations)
    assert [item["annotation_id"] for item in content["data"]] == expected_ids[:2]
    assert content["page_info"]["total"] == len(expected_ids)


def test_list_annotations_deduplicates_project_collection_join_before_pagination(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    media, _first_col, project = create_test_media(db, public_access=True, public_tags=True)

    second_col = Collection(
        name=f"ann_col_{random_lower_string()[:6]}",
        public_access=True,
        public_tags=True,
        creator_id=1,
    )
    db.add(second_col)
    db.commit()
    db.refresh(second_col)

    db.add(MediaCollection(media_id=media.media_id, collection_id=second_col.collection_id, added_by=1))
    db.add(ProjectCollection(project_id=project.project_id, collection_id=second_col.collection_id))

    annotations = [
        Annotation(
            media_id=media.media_id,
            sound_id=1,
            min_x=float(i),
            max_x=float(i + 1),
            min_y=0.0,
            max_y=1000.0,
            creator_type="user",
            creator_id=1,
        )
        for i in range(3)
    ]
    db.add_all(annotations)
    db.commit()
    for annotation in annotations:
        db.refresh(annotation)

    response = client.get(
        f"{settings.API_V1_STR}/annotations"
        f"?project_id={project.project_id}&media_id={media.media_id}"
        "&page=1&page_size=100&order_by=annotation_id&order_dir=asc",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    content = response.json()
    ids = [item["annotation_id"] for item in content["data"]]
    expected_ids = sorted(annotation.annotation_id for annotation in annotations)

    assert ids == expected_ids
    assert len(ids) == len(set(ids))
    assert content["page_info"]["total"] == len(expected_ids)
    for item in content["data"]:
        assert "collection_id" not in item
        assert "collection_name" not in item
        assert "project_id" not in item
        assert "project_name" not in item

    page_one = client.get(
        f"{settings.API_V1_STR}/annotations"
        f"?project_id={project.project_id}&media_id={media.media_id}"
        "&page=1&page_size=2&order_by=annotation_id&order_dir=asc",
        headers=superuser_token_headers,
    )
    page_two = client.get(
        f"{settings.API_V1_STR}/annotations"
        f"?project_id={project.project_id}&media_id={media.media_id}"
        "&page=2&page_size=2&order_by=annotation_id&order_dir=asc",
        headers=superuser_token_headers,
    )

    assert page_one.status_code == 200
    assert page_two.status_code == 200
    page_one_ids = [item["annotation_id"] for item in page_one.json()["data"]]
    page_two_ids = [item["annotation_id"] for item in page_two.json()["data"]]
    assert page_one_ids == expected_ids[:2]
    assert page_two_ids == expected_ids[2:]
    assert page_one.json()["page_info"]["total"] == len(expected_ids)
    assert page_two.json()["page_info"]["total"] == len(expected_ids)


def test_list_annotations_project_scope_deduplicates_multi_collection_media(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    media, _first_col, project = create_test_media(db, public_access=True, public_tags=True)

    second_col = Collection(
        name=f"ann_col_{random_lower_string()[:6]}",
        public_access=True,
        public_tags=True,
        creator_id=1,
    )
    db.add(second_col)
    db.commit()
    db.refresh(second_col)

    db.add(MediaCollection(media_id=media.media_id, collection_id=second_col.collection_id, added_by=1))
    db.add(ProjectCollection(project_id=project.project_id, collection_id=second_col.collection_id))

    annotations = [
        Annotation(
            media_id=media.media_id,
            sound_id=1,
            min_x=float(i),
            max_x=float(i + 1),
            min_y=0.0,
            max_y=1000.0,
            creator_type="user",
            creator_id=1,
        )
        for i in range(4)
    ]
    db.add_all(annotations)
    db.commit()
    for annotation in annotations:
        db.refresh(annotation)

    response = client.get(
        f"{settings.API_V1_STR}/annotations"
        f"?project_id={project.project_id}&page=1&page_size=3&order_by=annotation_id&order_dir=asc",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    content = response.json()
    expected_ids = sorted(annotation.annotation_id for annotation in annotations)
    assert [item["annotation_id"] for item in content["data"]] == expected_ids[:3]
    assert len({item["annotation_id"] for item in content["data"]}) == 3
    assert content["page_info"]["total"] == len(expected_ids)


def test_list_annotations_anonymous_visible_with_public_tags(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    media, _col, project = create_test_media(db, public_access=True, public_tags=True)
    data = {"project_id": project.project_id, "media_id": media.media_id, "sound_id": 1, "min_x": 0.0, "max_x": 1.0, "min_y": 0.0, "max_y": 1000.0}
    client.post(f"{settings.API_V1_STR}/annotations", headers=superuser_token_headers, json=data)

    response = client.get(
        f"{settings.API_V1_STR}/annotations?project_id={project.project_id}&media_id={media.media_id}",
    )
    assert response.status_code == 200
    content = response.json()
    assert content["code"] == 0
    assert len(content["data"]) >= 1
    assert content["data"][0]["task"] is None


def test_list_annotations_anonymous_hidden_without_public_tags_even_if_public_access(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    media, _col, project = create_test_media(db, public_access=True, public_tags=False)
    data = {"project_id": project.project_id, "media_id": media.media_id, "sound_id": 1, "min_x": 0.0, "max_x": 1.0, "min_y": 0.0, "max_y": 1000.0}
    client.post(f"{settings.API_V1_STR}/annotations", headers=superuser_token_headers, json=data)

    response = client.get(
        f"{settings.API_V1_STR}/annotations?project_id={project.project_id}&media_id={media.media_id}",
    )
    assert response.status_code == 200
    content = response.json()
    assert content["code"] == 0
    assert content["data"] == []
    assert content["page_info"]["total"] == 0


def test_update_annotation(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    media, col, project = create_test_media(db)
    create_resp = client.post(
        f"{settings.API_V1_STR}/annotations",
        headers=superuser_token_headers,
        json={"project_id": project.project_id, "media_id": media.media_id, "sound_id": 1, "min_x": 0.0, "max_x": 2.0, "min_y": 0.0, "max_y": 500.0}
    )
    assert create_resp.json()["data"] is None
    ann_row = db.exec(
        select(Annotation).where(Annotation.media_id == media.media_id).order_by(Annotation.annotation_id.desc())
    ).first()
    assert ann_row is not None
    ann_id = ann_row.annotation_id

    update_data = {
        "min_x": 1.5,
        "comments": "Updated comments",
        "distance_not_estimable": True
    }
    response = client.patch(
        f"{settings.API_V1_STR}/annotations/{ann_id}",
        headers=superuser_token_headers,
        params={"project_id": project.project_id},
        json=update_data
    )

    assert response.status_code == 200
    content = response.json()
    assert content["code"] == 0
    assert content["data"] is None
    db.refresh(ann_row)
    assert ann_row.min_x == 1.5
    assert ann_row.comments == "Updated comments"
    assert ann_row.sound_distance_m is None
    assert ann_row.distance_not_estimable is True


def test_delete_annotation(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    media, col, project = create_test_media(db)
    create_resp = client.post(
        f"{settings.API_V1_STR}/annotations",
        headers=superuser_token_headers,
        json={"project_id": project.project_id, "media_id": media.media_id, "sound_id": 1, "min_x": 0.0, "max_x": 2.0, "min_y": 0.0, "max_y": 500.0}
    )
    assert create_resp.json()["data"] is None
    ann_row = db.exec(
        select(Annotation).where(Annotation.media_id == media.media_id).order_by(Annotation.annotation_id.desc())
    ).first()
    ann_id = ann_row.annotation_id

    response = client.delete(
        f"{settings.API_V1_STR}/annotations/{ann_id}",
        headers=superuser_token_headers,
        params={"project_id": project.project_id},
    )
    assert response.status_code == 200

    get_resp = client.get(
        f"{settings.API_V1_STR}/annotations?project_id={project.project_id}&annotation_id={ann_id}",
        headers=superuser_token_headers,
    )
    assert get_resp.status_code == 200


def test_export_annotations(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    media, col, project = create_test_media(db)
    client.post(
        f"{settings.API_V1_STR}/annotations",
        headers=superuser_token_headers,
        json={"project_id": project.project_id, "media_id": media.media_id, "sound_id": 1, "min_x": 0.0, "max_x": 2.0, "min_y": 0.0, "max_y": 500.0}
    )

    response = client.get(
        f"{settings.API_V1_STR}/annotations/exports",
        headers=superuser_token_headers,
    )

    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert response.headers["content-disposition"] == (
        'attachment; filename="annotations.csv"; '
        "filename*=UTF-8''annotations.csv"
    )

    content = response.content.decode('utf-8')
    header = read_csv_header(content)
    assert header == [
        "annotation_id", "uuid", "media_name", "media_type", "min_x", "max_x",
        "min_y", "max_y", "creator_type", "soundscape_component", "sound_type",
        "taxon_scientific_name", "animal_sound_type", "confidence", "uncertain",
        "sound_distance_m", "distance_not_estimable", "individual_num", "reference",
        "comments", "creator_name", "creator_id", "creation_date",
    ]


def test_export_annotations_viewport_filter(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    media, _col, project = create_test_media(db)
    overlap = Annotation(
        media_id=media.media_id,
        sound_id=1,
        min_x=1.0,
        max_x=2.0,
        min_y=100.0,
        max_y=200.0,
        creator_type="user",
        creator_id=1,
        comments="overlap",
    )
    outside = Annotation(
        media_id=media.media_id,
        sound_id=1,
        min_x=10.0,
        max_x=12.0,
        min_y=1000.0,
        max_y=1200.0,
        creator_type="user",
        creator_id=1,
        comments="outside",
    )
    db.add(overlap)
    db.add(outside)
    db.commit()

    response = client.get(
        f"{settings.API_V1_STR}/annotations/exports",
        headers=superuser_token_headers,
        params={
            "project_id": project.project_id,
            "media_id": media.media_id,
            "view_time_start": 0.5,
            "view_time_end": 2.5,
            "view_freq_min": 50,
            "view_freq_max": 500,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        'attachment; filename="annotations.csv"; '
        "filename*=UTF-8''annotations.csv"
    )
    content = response.text
    assert "overlap" in content
    assert "outside" not in content


def test_list_annotations_viewport_time_filter(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    media, _col, project = create_test_media(db)
    overlap = Annotation(
        media_id=media.media_id,
        sound_id=1,
        min_x=1.0,
        max_x=2.0,
        min_y=100.0,
        max_y=300.0,
        creator_type="user",
        creator_id=1,
        comments="time-overlap",
    )
    touching_edge = Annotation(
        media_id=media.media_id,
        sound_id=1,
        min_x=2.5,
        max_x=3.0,
        min_y=100.0,
        max_y=300.0,
        creator_type="user",
        creator_id=1,
        comments="time-edge",
    )
    outside = Annotation(
        media_id=media.media_id,
        sound_id=1,
        min_x=4.0,
        max_x=5.0,
        min_y=100.0,
        max_y=300.0,
        creator_type="user",
        creator_id=1,
        comments="time-outside",
    )
    db.add_all([overlap, touching_edge, outside])
    db.commit()
    for annotation in (overlap, touching_edge, outside):
        db.refresh(annotation)

    response = client.get(
        f"{settings.API_V1_STR}/annotations",
        headers=superuser_token_headers,
        params={
            "project_id": project.project_id,
            "media_id": media.media_id,
            "view_time_start": 0.5,
            "view_time_end": 2.5,
        },
    )

    assert response.status_code == 200
    ids = [row["annotation_id"] for row in response.json()["data"]]
    assert overlap.annotation_id in ids
    assert touching_edge.annotation_id not in ids
    assert outside.annotation_id not in ids


def test_list_annotations_viewport_time_and_frequency_filter(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    media, _col, project = create_test_media(db)
    overlap = Annotation(
        media_id=media.media_id,
        sound_id=1,
        min_x=1.0,
        max_x=2.0,
        min_y=100.0,
        max_y=300.0,
        creator_type="user",
        creator_id=1,
        comments="two-d-overlap",
    )
    time_only = Annotation(
        media_id=media.media_id,
        sound_id=1,
        min_x=1.0,
        max_x=2.0,
        min_y=900.0,
        max_y=1200.0,
        creator_type="user",
        creator_id=1,
        comments="time-only",
    )
    freq_only = Annotation(
        media_id=media.media_id,
        sound_id=1,
        min_x=5.0,
        max_x=6.0,
        min_y=150.0,
        max_y=250.0,
        creator_type="user",
        creator_id=1,
        comments="freq-only",
    )
    db.add_all([overlap, time_only, freq_only])
    db.commit()
    for annotation in (overlap, time_only, freq_only):
        db.refresh(annotation)

    response = client.get(
        f"{settings.API_V1_STR}/annotations",
        headers=superuser_token_headers,
        params={
            "project_id": project.project_id,
            "media_id": media.media_id,
            "view_time_start": 0.5,
            "view_time_end": 2.5,
            "view_freq_min": 50,
            "view_freq_max": 500,
        },
    )

    assert response.status_code == 200
    ids = [row["annotation_id"] for row in response.json()["data"]]
    assert overlap.annotation_id in ids
    assert time_only.annotation_id not in ids
    assert freq_only.annotation_id not in ids


def test_delete_annotation_forbidden(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    media, col, project = create_test_media(db, public_access=False)
    ann = Annotation(
        media_id=media.media_id,
        sound_id=1,
        min_x=0.0,
        max_x=2.0,
        min_y=0.0,
        max_y=500.0,
        creator_type="user",
        creator_id=1
    )
    db.add(ann)
    db.commit()
    db.refresh(ann)

    response = client.delete(
        f"{settings.API_V1_STR}/annotations/{ann.annotation_id}",
        headers=normal_user_token_headers,
        params={"project_id": project.project_id},
    )
    assert response.status_code == 403


class TestAnnotationPublicTagsPermission:
    """Test annotation visibility when collection has public_tags=True."""

    def test_normal_user_sees_others_annotation_in_public_tags_collection(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """Normal user can see others' annotations in a collection with public_tags=True."""
        # Collection with public_tags=True
        media, col, project = create_test_media(db, public_access=False, public_tags=True)
        ann = Annotation(
            media_id=media.media_id,
            sound_id=1,
            min_x=0.0, max_x=2.0, min_y=0.0, max_y=500.0,
            creator_type="user",
            creator_id=1  # Created by admin (user_id=1), not normal_user
        )
        db.add(ann)
        db.commit()
        db.refresh(ann)

        response = client.get(
            f"{settings.API_V1_STR}/annotations?project_id={project.project_id}",
            headers=normal_user_token_headers,
        )
        assert response.status_code == 200
        data = response.json()
        # Should be able to see the annotation from user_id=1 because public_tags=True
        found = any(r["annotation_id"] == ann.annotation_id for r in data["data"])
        assert found

    def test_normal_user_cannot_see_others_annotation_without_public_tags(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """Normal user CANNOT see others' annotations in a private collection without public_tags."""
        # Fully private collection
        media, col, project = create_test_media(db, public_access=False, public_tags=False)
        ann = Annotation(
            media_id=media.media_id,
            sound_id=1,
            min_x=0.0, max_x=2.0, min_y=0.0, max_y=500.0,
            creator_type="user",
            creator_id=1  # Created by admin, not normal_user
        )
        db.add(ann)
        db.commit()
        db.refresh(ann)

        response = client.get(
            f"{settings.API_V1_STR}/annotations?project_id={project.project_id}",
            headers=normal_user_token_headers,
        )
        assert response.status_code == 200
        data = response.json()
        # Should NOT be able to see the annotation
        found = any(r["annotation_id"] == ann.annotation_id for r in data["data"])
        assert not found

    def test_normal_user_always_sees_own_annotations(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """Normal user always sees their own annotations regardless of collection settings."""
        token = normal_user_token_headers["Authorization"].split(" ")[1]
        payload = pyjwt.decode(token, options={"verify_signature": False})
        normal_user_id = int(payload["sub"])

        media, col, project = create_test_media(db, public_access=False, public_tags=False)
        ann = Annotation(
            media_id=media.media_id,
            sound_id=1,
            min_x=0.0, max_x=2.0, min_y=0.0, max_y=500.0,
            creator_type="user",
            creator_id=normal_user_id  # Own annotation
        )
        db.add(ann)
        db.commit()
        db.refresh(ann)

        response = client.get(
            f"{settings.API_V1_STR}/annotations?project_id={project.project_id}",
            headers=normal_user_token_headers,
        )
        assert response.status_code == 200
        data = response.json()
        found = any(r["annotation_id"] == ann.annotation_id for r in data["data"])
        assert found

    def test_normal_user_viewport_filter_only_narrows_existing_visibility(
        self, client: TestClient, normal_user_token_headers: dict[str, str], db: Session
    ) -> None:
        """Viewport filters should narrow visible annotations without exposing private foreign annotations."""
        token = normal_user_token_headers["Authorization"].split(" ")[1]
        payload = pyjwt.decode(token, options={"verify_signature": False})
        normal_user_id = int(payload["sub"])

        media, _col, project = create_test_media(db, public_access=False, public_tags=False)
        own_overlap = Annotation(
            media_id=media.media_id,
            sound_id=1,
            min_x=1.0,
            max_x=2.0,
            min_y=100.0,
            max_y=300.0,
            creator_type="user",
            creator_id=normal_user_id,
            comments="own-overlap",
        )
        foreign_overlap = Annotation(
            media_id=media.media_id,
            sound_id=1,
            min_x=1.2,
            max_x=2.2,
            min_y=120.0,
            max_y=280.0,
            creator_type="user",
            creator_id=1,
            comments="foreign-overlap",
        )
        db.add_all([own_overlap, foreign_overlap])
        db.commit()
        for annotation in (own_overlap, foreign_overlap):
            db.refresh(annotation)

        response = client.get(
            f"{settings.API_V1_STR}/annotations",
            headers=normal_user_token_headers,
            params={
                "project_id": project.project_id,
                "media_id": media.media_id,
                "view_time_start": 0.5,
                "view_time_end": 2.5,
                "view_freq_min": 50,
                "view_freq_max": 500,
            },
        )

        assert response.status_code == 200
        ids = [row["annotation_id"] for row in response.json()["data"]]
        assert own_overlap.annotation_id in ids
        assert foreign_overlap.annotation_id not in ids


class TestAnnotationFiltersAndSort:
    """Tests for new filter parameters and sort field mapping."""

    def _create_annotation(self, db: Session, client: TestClient, headers: dict, **kwargs) -> dict:
        """Helper: create annotation via API and return minimal dict with annotation_id."""
        media, _, project = create_test_media(db, public_access=True, public_tags=True)
        payload = {"media_id": media.media_id, "sound_id": 1,
                   "project_id": project.project_id,
                   "min_x": 0.0, "max_x": 1.0, "min_y": 0.0, "max_y": 1000.0,
                   "creator_type": "user", **kwargs}
        resp = client.post(f"{settings.API_V1_STR}/annotations", headers=headers, json=payload)
        assert resp.status_code == 201
        assert resp.json()["data"] is None
        ann = db.exec(
            select(Annotation).where(Annotation.media_id == media.media_id).order_by(Annotation.annotation_id.desc())
        ).first()
        assert ann is not None
        return {"annotation_id": ann.annotation_id, "project_id": project.project_id}

    def test_filter_by_annotation_id(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Filter by annotation_id returns only that annotation."""
        ann = self._create_annotation(db, client, superuser_token_headers)
        ann_id = ann["annotation_id"]
        project_id = ann["project_id"]

        r = client.get(
            f"{settings.API_V1_STR}/annotations?project_id={project_id}&annotation_id={ann_id}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert len(data) == 1
        assert data[0]["annotation_id"] == ann_id

    def test_filter_by_invalid_uuid_returns_200(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Invalid UUID value is silently ignored – returns 200, not 422."""
        _media, _col, project = create_test_media(db, public_access=True, public_tags=True)
        r = client.get(
            f"{settings.API_V1_STR}/annotations?project_id={project.project_id}&uuid=not-a-uuid",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        assert r.json()["code"] == 0

    def test_filter_by_media_name(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """media_name fuzzy filter returns annotations belonging to matched media."""
        media, _, project = create_test_media(db, public_access=True, public_tags=True)
        # Override media filename to something unique
        unique_token = random_lower_string()[:8]
        media.name = f"unique_{unique_token}_file.wav"
        media.filename = f"unique_{unique_token}_file.wav"
        db.add(media)
        db.commit()

        ann = Annotation(
            media_id=media.media_id, sound_id=1,
            min_x=0.0, max_x=1.0, min_y=0.0, max_y=1000.0,
            creator_type="user", creator_id=1,
        )
        db.add(ann)
        db.commit()
        db.refresh(ann)

        r = client.get(
            f"{settings.API_V1_STR}/annotations?project_id={project.project_id}&media_name={unique_token}",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        data = r.json()["data"]
        assert any(a["annotation_id"] == ann.annotation_id for a in data)

    def test_filter_by_min_x_range(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """min_x range filter returns only annotations whose min_x falls in the range."""
        media, _, project = create_test_media(db, public_access=True, public_tags=True)
        ann_in = Annotation(
            media_id=media.media_id, sound_id=1,
            min_x=3.0, max_x=5.0, min_y=0.0, max_y=1000.0,
            creator_type="user", creator_id=1,
        )
        ann_out = Annotation(
            media_id=media.media_id, sound_id=1,
            min_x=10.0, max_x=12.0, min_y=0.0, max_y=1000.0,
            creator_type="user", creator_id=1,
        )
        db.add_all([ann_in, ann_out])
        db.commit()
        db.refresh(ann_in)
        db.refresh(ann_out)

        r = client.get(
            f"{settings.API_V1_STR}/annotations?project_id={project.project_id}&min_x=2.0,6.0",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        ids = [a["annotation_id"] for a in r.json()["data"]]
        assert ann_in.annotation_id in ids
        assert ann_out.annotation_id not in ids

    def test_sort_by_unknown_key_falls_back_to_default_order(
        self, client: TestClient, superuser_token_headers: dict[str, str], db: Session
    ) -> None:
        """Unknown order_by keys fall back to the default annotation_id ordering."""
        media, _, project = create_test_media(db, public_access=True, public_tags=True)
        anns = []
        for i in range(3):
            a = Annotation(
                media_id=media.media_id, sound_id=1,
                min_x=float(i), max_x=float(i + 1), min_y=0.0, max_y=1000.0,
                creator_type="user", creator_id=1,
            )
            db.add(a)
            db.commit()
            db.refresh(a)
            anns.append(a)

        r = client.get(
            f"{settings.API_V1_STR}/annotations?project_id={project.project_id}&order_by=unknown_key&order_dir=asc&page_size=100",
            headers=superuser_token_headers,
        )
        assert r.status_code == 200
        ids = [a["annotation_id"] for a in r.json()["data"]]
        # Verify the created annotations appear in ascending annotation_id order
        created_ids = [a.annotation_id for a in anns]
        returned_subset = [i for i in ids if i in created_ids]
        assert returned_subset == sorted(returned_subset)
