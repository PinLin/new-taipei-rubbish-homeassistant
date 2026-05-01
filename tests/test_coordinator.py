"""Tests for NTPC Rubbish coordinator helpers."""
from datetime import datetime

from custom_components.ntpc_rubbish.coordinator import (
    _extract_official_live_data,
    _estimate_official_arrival_dt,
    _official_site_time_interval,
    _official_site_weekday,
    _official_collection_status,
    _parse_official_timestamp,
    _resolve_estimated_arrival_time,
    _resolve_truck_departure_state,
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


def test_estimate_official_arrival_dt_keeps_recent_past_eta_until_departed() -> None:
    """ETA should not disappear just because the predicted time is slightly in the past."""
    now = dt_util.as_local(
        datetime(2026, 4, 6, 20, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    )
    actual = _estimate_official_arrival_dt(
        arrival_rank=70,
        diff_minutes=1,
        point_rank=71,
        point_time="19:57",
        barcode="000015",
        now=now,
    )
    assert actual is not None
    assert actual.strftime("%H:%M") == "19:58"


def test_estimate_official_arrival_dt_supports_the_current_arrival_rank() -> None:
    """The current stop should keep an ETA while the site has not filled Arrival yet."""
    now = dt_util.as_local(
        datetime(2026, 4, 7, 13, 44, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    )
    actual = _estimate_official_arrival_dt(
        arrival_rank=9,
        diff_minutes=9,
        point_rank=9,
        point_time="13:35",
        barcode="220022",
        now=now,
    )
    assert actual is not None
    assert actual.strftime("%H:%M") == "13:44"


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
                "Location": "範例市範例區測試路100號",
                "LocationLat": 25.0001,
                "LocationLon": 121.0001,
                "Point": [
                    {"PointRank": 7, "PointTime": "17:10", "Arrival": ""},
                ],
            }
        ],
    }

    actual = _extract_official_live_data(
        payload,
        [{"lineid": "241009", "rank": "7"}],
        point_latitude=25.0008,
        point_longitude=121.0002,
        now=now,
    )

    assert actual["nearest_truck_distance"] is not None
    assert actual["nearest_truck_distance"] < 200
    assert actual["nearest_truck_location"] == "範例市範例區測試路100號"
    assert actual["nearest_truck_lat"] == 25.0001
    assert actual["nearest_truck_lon"] == 121.0001
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
                "Location": "範例市範例區測試路200號",
                "LocationLat": 25.0003,
                "LocationLon": 121.0003,
                "Point": [
                    {"PointRank": 7, "PointTime": "17:10", "Arrival": ""},
                ],
            }
        ],
    }

    actual = _extract_official_live_data(
        payload,
        [{"lineid": "241009", "rank": "7"}],
        point_latitude=25.0004,
        point_longitude=121.0004,
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
        point_latitude=25.0004,
        point_longitude=121.0004,
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
        point_latitude=25.0004,
        point_longitude=121.0004,
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
        point_latitude=25.0005,
        point_longitude=121.0005,
        now=now,
    )

    assert actual["estimated_arrival_time"] is not None
    assert actual["estimated_arrival_time"].strftime("%H:%M") == "14:38"


def test_resolve_estimated_arrival_time_keeps_departed_timestamp() -> None:
    """ETA should stay on the actual departed timestamp after the truck passes."""
    departed_at = dt_util.as_local(
        datetime(2026, 4, 6, 19, 32, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    )
    scheduled = dt_util.as_local(
        datetime(2026, 4, 6, 19, 33, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    )

    actual = _resolve_estimated_arrival_time(
        official_arrival_time=None,
        truck_departed=True,
        truck_departed_at=departed_at,
        scheduled_collection_time=scheduled,
        collection_status="執勤中",
    )

    assert actual == departed_at


def test_resolve_estimated_arrival_time_falls_back_to_schedule_when_departed() -> None:
    """ETA should not become unknown if the truck passed but no exact departed time is exposed."""
    scheduled = dt_util.as_local(
        datetime(2026, 4, 6, 19, 33, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    )

    actual = _resolve_estimated_arrival_time(
        official_arrival_time=None,
        truck_departed=True,
        truck_departed_at=None,
        scheduled_collection_time=scheduled,
        collection_status="執勤中",
    )

    assert actual == scheduled


def test_resolve_estimated_arrival_time_falls_back_to_schedule_when_line_is_active() -> None:
    """Active lines without an exposed ETA should keep the scheduled point time."""
    scheduled = dt_util.as_local(
        datetime(2026, 4, 6, 20, 21, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    )

    actual = _resolve_estimated_arrival_time(
        official_arrival_time=None,
        truck_departed=False,
        truck_departed_at=None,
        scheduled_collection_time=scheduled,
        collection_status="執勤中",
    )

    assert actual == scheduled


def test_resolve_estimated_arrival_time_falls_back_to_schedule_when_arriving() -> None:
    """Arrival should stay stable while the truck is at the point but no Arrival time is exposed."""
    scheduled = dt_util.as_local(
        datetime(2026, 4, 6, 19, 46, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    )

    actual = _resolve_estimated_arrival_time(
        official_arrival_time=None,
        truck_departed=False,
        truck_departed_at=None,
        scheduled_collection_time=scheduled,
        collection_status="前往焚化廠",
    )

    assert actual == scheduled


def test_resolve_truck_departure_state_keeps_departed_after_live_line_disappears() -> None:
    """Once today's selected run is over, the point should stay departed until midnight."""
    scheduled = dt_util.as_local(
        datetime(2026, 4, 6, 19, 57, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    )
    now = dt_util.as_local(
        datetime(2026, 4, 6, 20, 42, tzinfo=dt_util.DEFAULT_TIME_ZONE)
    )

    departed, departed_at = _resolve_truck_departure_state(
        truck_departed=False,
        truck_departed_at=None,
        scheduled_collection_time=scheduled,
        collection_status="非收運時間",
        now=now,
    )

    assert departed is True
    assert departed_at == scheduled


def test_extract_official_live_data_defaults_to_non_collection_without_line() -> None:
    """Missing line data should surface as the official non-collection status."""
    actual = _extract_official_live_data(
        {"TimeStamp": "20260403175211", "Line": []},
        [{"lineid": "220057", "rank": "51"}],
        point_latitude=25.0006,
        point_longitude=121.0006,
        now=dt_util.as_local(
            datetime(2026, 4, 3, 19, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)
        ),
    )

    assert actual["collection_status"] == "非收運時間"
    assert actual["collection_status_code"] is None
    assert actual["car_no"] is None
