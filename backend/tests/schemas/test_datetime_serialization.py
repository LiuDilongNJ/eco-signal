from datetime import UTC, datetime

from app.schemas.annotation import AnnotationPublic
from app.schemas.device import SensorPublic
from app.schemas.index_log import IndexLogRead
from app.schemas.media import MediaBrowseListItem, MediaTimelineRange
from app.schemas.review import ReviewRead
from app.schemas.site import SitePublic
from app.schemas.task import TaskPublic
from app.schemas.user import ContributorPublic

EXPECTED_DATETIME = "2026-03-17 14:30:00"
DATETIME_VALUE = datetime(2026, 3, 17, 14, 30, tzinfo=UTC)


def test_sensor_public_serializes_creation_date() -> None:
    schema = SensorPublic(
        sensor_id=1,
        uuid="00000000-0000-0000-0000-000000000001",
        name="Sensor",
        sensor_type="audio",
        creation_date=DATETIME_VALUE,
    )

    assert schema.model_dump(mode="json")["creation_date"] == EXPECTED_DATETIME


def test_review_read_serializes_creation_date() -> None:
    schema = ReviewRead(
        annotation_id=1,
        reviewer_id=2,
        annotation_review_status_id=3,
        creation_date=DATETIME_VALUE,
        media_type="audio",
        reviewer_name="Reviewer",
        status_name="Reviewed",
    )

    assert schema.model_dump(mode="json")["creation_date"] == EXPECTED_DATETIME


def test_index_log_read_serializes_creation_date() -> None:
    schema = IndexLogRead(
        log_id=1,
        media_id=2,
        user_id=3,
        index_id=4,
        variable_order=1,
        creation_date=DATETIME_VALUE,
    )

    assert schema.model_dump(mode="json")["creation_date"] == EXPECTED_DATETIME


def test_contributor_public_serializes_added_date() -> None:
    schema = ContributorPublic(added_date=DATETIME_VALUE)

    assert schema.model_dump(mode="json")["added_date"] == EXPECTED_DATETIME


def test_media_browse_list_serializes_date_time() -> None:
    schema = MediaBrowseListItem(
        media_id=1,
        media_type="audio",
        date_time=DATETIME_VALUE,
    )

    assert schema.model_dump(mode="json")["date_time"] == EXPECTED_DATETIME


def test_media_timeline_range_preserves_null_dates() -> None:
    schema = MediaTimelineRange(min=None, max=None)

    assert schema.model_dump(mode="json") == {"min": None, "max": None}


def test_task_public_normalizes_datetime_and_null() -> None:
    required_fields = {
        "task_id": 1,
        "type": "media",
        "media_type": "audio",
        "assigner_id": 2,
        "assignee_id": 3,
        "status": "assigned",
    }

    dated = TaskPublic(**required_fields, datetime=DATETIME_VALUE)
    empty = TaskPublic(**required_fields, datetime=None)

    assert dated.model_dump(mode="json")["datetime"] == EXPECTED_DATETIME
    assert empty.model_dump(mode="json")["datetime"] is None


def test_response_serializers_preserve_null_dates_defensively() -> None:
    site = SitePublic.model_construct(creation_date=None)
    annotation = AnnotationPublic.model_construct(creation_date=None)

    assert site.model_dump(mode="json")["creation_date"] is None
    assert annotation.model_dump(mode="json")["creation_date"] is None
