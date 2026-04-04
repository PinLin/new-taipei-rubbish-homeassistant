"""Tests for NTPC Rubbish coordinator helpers."""
from datetime import datetime

from custom_components.ntpc_rubbish.coordinator import (
    _extract_official_live_data,
    _estimate_official_arrival_dt,
    _official_site_time_interval,
    _official_site_weekday,
    _official_collection_status,
    _parse_official_timestamp,
    _scheduled_collection_time_for_routes,
    _select_display_route_items,
    _select_live_route_items,
)
from homeassistant.util import dt as dt_util


def test_estimate_official_arrival_dt_uses_point_time_plus_diff() -> None:
    """Official fallback estimate should mirror the site logic."""
    now = dt_util.as_local(
        datetime(2026, 4, 3, 16, 50, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    )
    actual = _estimate_official_arrival_dt(
        arrival_rank=4,
        diff_minutes=-5,
        point_rank=7,
        point_time="17:10",
        barcode="241009",
        now=now,
    )
    assert actual is not None
    assert actual.strftime("%H:%M") == "17:05"


def test_parse_official_timestamp() -> None:
    """Official timestamp should be parsed as a local datetime."""
    actual = _parse_official_timestamp("20260403170838")
    assert actual is not None
    assert actual.strftime("%Y-%m-%d %H:%M:%S") == "2026-04-03 17:08:38"


def test_official_site_query_context_matches_map_page() -> None:
    """Official map requests should use the site's weekday and time buckets."""
    morning = dt_util.as_local(
        datetime(2026, 4, 5, 8, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    )
    afternoon = dt_util.as_local(
        datetime(2026, 4, 4, 15, 23, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    )
    night = dt_util.as_local(
        datetime(2026, 4, 4, 19, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    )

    assert _official_site_weekday(morning) == 0
    assert _official_site_weekday(afternoon) == 6
    assert _official_site_time_interval(morning) == 1
    assert _official_site_time_interval(afternoon) == 2
    assert _official_site_time_interval(night) == 3


def test_official_collection_status_maps_incinerator_and_default() -> None:
    """Official status should follow the NTPC site barcode mapping."""
    assert _official_collection_status("000014", "241009") == "前往焚化廠"
    assert _official_collection_status("", "220057") == "非收運時間"


def test_select_live_route_items_prefers_next_upcoming_run() -> None:
    """Live data should switch to the next run after the earlier one passes."""
    now = dt_util.as_local(
        datetime(2026, 4, 3, 15, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    )
    routes = [
        {"lineid": "220005", "rank": "51", "time": "14:39", "garbagefriday": "Y"},
        {"lineid": "220057", "rank": "51", "time": "19:33", "garbagefriday": "Y"},
    ]

    actual = _select_live_route_items(routes, now)
    assert [route["lineid"] for route in actual] == ["220057"]


def test_select_display_route_items_keeps_current_run_until_point_is_passed() -> None:
    """Displayed scheduled time should stay on the current run before the next run opens."""
    now = dt_util.as_local(
        datetime(2026, 4, 3, 15, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    )
    routes = [
        {"lineid": "220005", "rank": "51", "time": "14:39", "garbagefriday": "Y"},
        {"lineid": "220057", "rank": "51", "time": "19:33", "garbagefriday": "Y"},
    ]
    payload = {
        "Line": [
            {
                "LineID": "220005",
                "ArrivalRank": 40,
                "Point": [{"PointRank": 51, "Arrival": ""}],
            },
        ]
    }

    actual = _select_display_route_items(routes, payload, now)
    assert [route["lineid"] for route in actual] == ["220005"]


def test_select_display_route_items_switches_when_next_run_opens() -> None:
    """Displayed scheduled time should switch as soon as the next run has live data."""
    now = dt_util.as_local(
        datetime(2026, 4, 3, 19, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    )
    routes = [
        {"lineid": "220005", "rank": "51", "time": "14:39", "garbagefriday": "Y"},
        {"lineid": "220057", "rank": "51", "time": "19:33", "garbagefriday": "Y"},
    ]
    payload = {
        "Line": [
            {
                "LineID": "220005",
                "ArrivalRank": 55,
                "Point": [{"PointRank": 51, "Arrival": "14:45"}],
            },
            {
                "LineID": "220057",
                "ArrivalRank": 0,
                "Point": [{"PointRank": 51, "Arrival": ""}],
            },
        ]
    }

    actual = _select_display_route_items(routes, payload, now)
    assert [route["lineid"] for route in actual] == ["220057"]


def test_select_display_route_items_keeps_last_started_today_run_without_live_line() -> None:
    """Displayed schedule should stay on today's last started run until midnight."""
    now = dt_util.as_local(
        datetime(2026, 4, 3, 21, 30, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    )
    routes = [
        {"lineid": "220005", "rank": "51", "time": "14:39", "garbagefriday": "Y"},
        {"lineid": "220057", "rank": "51", "time": "19:33", "garbagefriday": "Y"},
    ]

    actual = _select_display_route_items(routes, {"Line": []}, now)
    assert [route["lineid"] for route in actual] == ["220057"]


def test_scheduled_collection_time_for_routes_uses_next_day_for_future_run() -> None:
    """Displayed scheduled time should not be forced back onto today for tomorrow's run."""
    now = dt_util.as_local(
        datetime(2026, 4, 3, 21, 30, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    )
    routes = [
        {"lineid": "220005", "rank": "51", "time": "14:39", "garbagefriday": "Y", "garbagesaturday": "Y"},
    ]

    actual = _scheduled_collection_time_for_routes(routes, {"Line": []}, now)
    assert actual is not None
    assert actual.strftime("%Y-%m-%d %H:%M") == "2026-04-04 14:39"


def test_scheduled_collection_time_for_routes_keeps_today_for_active_run() -> None:
    """Displayed scheduled time should stay on today's run while the point is still active."""
    now = dt_util.as_local(
        datetime(2026, 4, 3, 19, 53, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    )
    routes = [
        {"lineid": "220057", "rank": "51", "time": "19:33", "garbagefriday": "Y"},
    ]
    payload = {
        "Line": [
            {
                "LineID": "220057",
                "BarCode": "000015",
                "ArrivalRank": 66,
                "Point": [{"PointRank": 51, "Arrival": "19:32"}],
            }
        ]
    }

    actual = _scheduled_collection_time_for_routes(routes, payload, now)
    assert actual is not None
    assert actual.strftime("%Y-%m-%d %H:%M") == "2026-04-03 19:33"


def test_extract_official_live_data_uses_location_and_timestamp() -> None:
    """Official line payload should drive live distance, ETA, and update time."""
    now = dt_util.as_local(
        datetime(2026, 4, 3, 16, 50, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    )
    payload = {
        "TimeStamp": "20260403170838",
        "Line": [
            {
                "LineID": "241009",
                "ArrivalRank": 6,
                "Diff": -1,
                "BarCode": "000014",
                "Location": "新北市三重區三和路四段221號",
                "LocationLat": 25.0799,
                "LocationLon": 121.481603333333,
                "Point": [
                    {"PointRank": 7, "PointTime": "17:10", "Arrival": ""},
                ],
            }
        ],
    }

    actual = _extract_official_live_data(
        payload,
        [{"lineid": "241009", "rank": "7"}],
        point_latitude=25.080758,
        point_longitude=121.481782,
        now=now,
    )

    assert actual["nearest_truck_distance"] is not None
    assert actual["nearest_truck_distance"] < 200
    assert actual["nearest_truck_location"] == "新北市三重區三和路四段221號"
    assert actual["nearest_truck_lat"] == 25.0799
    assert actual["nearest_truck_lon"] == 121.481603333333
    assert actual["last_vehicle_update"] is not None
    assert actual["last_vehicle_update"].strftime("%H:%M:%S") == "17:08:38"
    assert actual["estimated_arrival_time"] is not None
    assert actual["estimated_arrival_time"].strftime("%H:%M") == "17:09"
    assert actual["collection_status"] == "前往焚化廠"
    assert actual["collection_status_code"] == "000014"


def test_extract_official_live_data_preserves_zero_diff_for_future_stop() -> None:
    """A zero official diff is valid and should not be treated as 65535."""
    now = dt_util.as_local(
        datetime(2026, 4, 4, 16, 36, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    )
    payload = {
        "TimeStamp": "20260404163621",
        "Line": [
            {
                "LineID": "241009",
                "ArrivalRank": 3,
                "Diff": 0,
                "BarCode": "241009",
                "Location": "新北市三重區三和路四段203巷48號",
                "LocationLat": 25.0796883333333,
                "LocationLon": 121.482905,
                "Point": [
                    {"PointRank": 7, "PointTime": "17:10", "Arrival": ""},
                ],
            }
        ],
    }

    actual = _extract_official_live_data(
        payload,
        [{"lineid": "241009", "rank": "7"}],
        point_latitude=25.07987,
        point_longitude=121.481147,
        now=now,
    )

    assert actual["estimated_arrival_time"] is not None
    assert actual["estimated_arrival_time"].strftime("%H:%M") == "17:10"
    assert actual["truck_departed"] is False
    assert actual["truck_departed_at"] is None


def test_extract_official_live_data_marks_departed_when_arrival_exists() -> None:
    """A populated point Arrival means the truck has already left this point."""
    now = dt_util.as_local(
        datetime(2026, 4, 4, 16, 36, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    )
    payload = {
        "TimeStamp": "20260404163621",
        "Line": [
            {
                "LineID": "241009",
                "ArrivalRank": 7,
                "Diff": 0,
                "BarCode": "241009",
                "Point": [
                    {"PointRank": 7, "PointTime": "17:10", "Arrival": "17:09"},
                ],
            }
        ],
    }

    actual = _extract_official_live_data(
        payload,
        [{"lineid": "241009", "rank": "7"}],
        point_latitude=25.07987,
        point_longitude=121.481147,
        now=now,
    )

    assert actual["truck_departed"] is True
    assert actual["truck_departed_at"] is not None
    assert actual["truck_departed_at"].strftime("%H:%M") == "17:09"


def test_extract_official_live_data_marks_departed_when_arrival_rank_has_passed() -> None:
    """ArrivalRank beyond this point should mark it as already departed."""
    now = dt_util.as_local(
        datetime(2026, 4, 4, 16, 40, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    )
    payload = {
        "TimeStamp": "20260404164021",
        "Line": [
            {
                "LineID": "241009",
                "ArrivalRank": 8,
                "Diff": 0,
                "BarCode": "241009",
                "Point": [
                    {"PointRank": 7, "PointTime": "17:10", "Arrival": ""},
                ],
            }
        ],
    }

    actual = _extract_official_live_data(
        payload,
        [{"lineid": "241009", "rank": "7"}],
        point_latitude=25.07987,
        point_longitude=121.481147,
        now=now,
    )

    assert actual["truck_departed"] is True
    assert actual["truck_departed_at"] is not None
    assert actual["truck_departed_at"].strftime("%H:%M") == "17:10"


def test_extract_official_live_data_supports_get_around_points_payload() -> None:
    """Official map payload should expose ETA even when GetArrival is empty."""
    now = dt_util.as_local(
        datetime(2026, 4, 4, 15, 23, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    )
    payload = {
        "TimeStamp": "20260404152354",
        "Line": [
            {
                "LineID": "220005",
                "LineName": "A05路線下午",
                "ArrivalRank": 68,
                "Diff": -5,
                "BarCode": "",
                "Point": [
                    {
                        "PointRank": 51,
                        "PointTime": "14:39",
                        "Arrival": "14:38",
                    }
                ],
            }
        ],
    }

    actual = _extract_official_live_data(
        payload,
        [{"lineid": "220005", "rank": "51"}],
        point_latitude=24.99144709,
        point_longitude=121.4607099,
        now=now,
    )

    assert actual["estimated_arrival_time"] is not None
    assert actual["estimated_arrival_time"].strftime("%H:%M") == "14:38"
    assert actual["last_vehicle_update"] is not None
    assert actual["last_vehicle_update"].strftime("%H:%M:%S") == "15:23:54"


def test_extract_official_live_data_defaults_to_non_collection_without_line() -> None:
    """Missing line data should surface as the official non-collection status."""
    actual = _extract_official_live_data(
        {"TimeStamp": "20260403175211", "Line": []},
        [{"lineid": "220057", "rank": "51"}],
        point_latitude=25.013,
        point_longitude=121.46,
        now=dt_util.as_local(
            datetime(2026, 4, 3, 19, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)
        ),
    )

    assert actual["collection_status"] == "非收運時間"
    assert actual["collection_status_code"] is None
    assert actual["car_no"] is None
