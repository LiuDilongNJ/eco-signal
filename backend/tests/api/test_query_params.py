from datetime import UTC, datetime

from app.api.query_params import MediaFilterQueryParams


def test_media_filter_query_params_to_filter_dict_parses_uuid_and_ranges() -> None:
    params = MediaFilterQueryParams(
        uuid="550e8400-e29b-41d4-a716-446655440000",
        sampling_rate_hz="32000,48000",
        bit_depth="16,24",
        channel_num="1,2",
        duration_s="1.5,8.5",
        size_b="1024,4096",
        recording_gain_db="-6,12",
        exposure_ms="5,20",
        aperture="1.8,4",
        iso="100,800",
        duty_cycle_period="30,120",
        duty_cycle_recording="10,20",
    )

    filters = params.to_filter_dict()

    assert str(filters["uuid"]) == "550e8400-e29b-41d4-a716-446655440000"
    assert filters["sampling_rate_hz_min"] == 32000.0
    assert filters["sampling_rate_hz_max"] == 48000.0
    assert filters["bit_depth_min"] == 16.0
    assert filters["bit_depth_max"] == 24.0
    assert filters["channel_num_min"] == 1.0
    assert filters["channel_num_max"] == 2.0
    assert filters["duration_s_min"] == 1.5
    assert filters["duration_s_max"] == 8.5
    assert filters["size_b_min"] == 1024.0
    assert filters["size_b_max"] == 4096.0
    assert filters["recording_gain_db_min"] == -6.0
    assert filters["recording_gain_db_max"] == 12.0
    assert filters["exposure_ms_min"] == 5.0
    assert filters["exposure_ms_max"] == 20.0
    assert filters["aperture_min"] == 1.8
    assert filters["aperture_max"] == 4.0
    assert filters["iso_min"] == 100.0
    assert filters["iso_max"] == 800.0
    assert filters["duty_cycle_period_min"] == 30.0
    assert filters["duty_cycle_period_max"] == 120.0
    assert filters["duty_cycle_recording_min"] == 10.0
    assert filters["duty_cycle_recording_max"] == 20.0


def test_media_filter_query_params_to_filter_dict_filters_empty_values() -> None:
    params = MediaFilterQueryParams(
        search="bird",
        medium="Air",
        site_id=7,
        creator_id=12,
        label_id=15,
        media_id=18,
    )

    filters = params.to_filter_dict()

    assert filters == {
        "search": "bird",
        "site_id": 7,
        "medium": "Air",
        "creator_id": 12,
        "label_id": 15,
        "media_id": 18,
    }


def test_media_filter_query_params_can_exclude_site_filter() -> None:
    params = MediaFilterQueryParams(site_id=9, sensor_id=11, name="Alpha")

    filters = params.to_filter_dict(include_site_filter=False)

    assert "site_id" not in filters
    assert filters["sensor_id"] == 11
    assert filters["name"] == "Alpha"


def test_media_filter_query_params_preserves_datetime_filters() -> None:
    dt_from = datetime(2026, 1, 1, 8, 0, 0, tzinfo=UTC)
    dt_to = datetime(2026, 1, 31, 18, 30, 0, tzinfo=UTC)
    creation_from = datetime(2026, 2, 1, 9, 0, 0)
    creation_to = datetime(2026, 2, 28, 17, 0, 0)

    params = MediaFilterQueryParams(
        date_time_from=dt_from,
        date_time_to=dt_to,
        creation_date_from=creation_from,
        creation_date_to=creation_to,
        uploader_id=5,
        note="alpha",
    )

    filters = params.to_filter_dict()

    assert filters["date_time_from"] == dt_from
    assert filters["date_time_to"] == dt_to
    assert filters["creation_date_from"] == creation_from
    assert filters["creation_date_to"] == creation_to
    assert filters["uploader_id"] == 5
    assert filters["note"] == "alpha"
