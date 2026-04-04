"""Tests for config flow point-search helpers."""
from __future__ import annotations

from custom_components.ntpc_rubbish.config_flow import (
    _group_routes,
    _prepare_point_result,
)

def test_prepare_point_result_formats_distance_and_times() -> None:
    point = {
        "key": "x",
        "point": {
            "name": "測試點",
            "city": "板橋區",
            "village": "深丘里",
        },
        "routes": [
            {"time": "14:05", "lineid": "220003", "rank": "23"},
            {"time": "14:04", "lineid": "220003", "rank": "22"},
        ],
        "_dist_raw": 42.3,
    }

    prepared = _prepare_point_result(point)

    assert prepared["_dist_m"] == 42
    assert prepared["scheduled_times"] == "14:04, 14:05"
