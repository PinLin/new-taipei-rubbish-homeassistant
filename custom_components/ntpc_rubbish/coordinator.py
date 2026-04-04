"""Data coordinator for NTPC garbage truck integration."""
from __future__ import annotations

import math
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import NtpcRubbishApiClient
from .const import (
    CONF_ROUTES,
    DAY_FIELDS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ROUTE_CACHE_TTL,
)
from .entity import format_scheduled_times, get_active_routes

# Keys for hass.data shared caches
_ROUTE_CACHE_KEY = f"{DOMAIN}_route_cache"   # dict: "{lineid}_{rank}" → {data, updated_at}
_OFFICIAL_AROUND_POINTS_CACHE_KEY = f"{DOMAIN}_official_around_points_cache"
_OFFICIAL_LINE_ARRIVAL_CACHE_KEY = f"{DOMAIN}_official_line_arrival_cache"
_OFFICIAL_LINE_ARRIVAL_CACHE_TTL = 30  # seconds – official site data is now the primary live source

_LOGGER = logging.getLogger(__name__)


@dataclass
class CollectionPointData:
    """Represents the current state of a garbage truck collection point."""

    # Static info from route data
    point_name: str
    district: str
    route_line_name: str
    latitude: float
    longitude: float
    scheduled_time: str

    # Computed from route schedule + current time
    garbage_today: bool
    recycling_today: bool
    food_scraps_today: bool
    scheduled_collection_time: datetime | None
    next_collection_type: str | None
    collection_status: str | None
    collection_status_code: str | None
    car_no: str | None

    # Computed from official live route API
    nearest_truck_distance: float | None  # metres; None if no trucks on route
    nearest_truck_location: str | None
    nearest_truck_lat: float | None
    nearest_truck_lon: float | None
    estimated_arrival_time: datetime | None
    last_vehicle_update: datetime | None
    data_staleness_seconds: int | None
    truck_departed: bool
    truck_departed_at: datetime | None


def _haversine_distance(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """Return great-circle distance between two points in metres."""
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def _is_collected(
    route_item: dict[str, Any], collection_type: str, weekday: int
) -> bool:
    """Return True if collection_type is scheduled on the given weekday."""
    day_name = DAY_FIELDS[weekday]
    return route_item.get(f"{collection_type}{day_name}", "") == "Y"


def _schedule_weekdays(
    route_item: dict[str, Any], collection_type: str
) -> list[int]:
    """Return list of weekday ints (0=Mon) when collection_type is scheduled."""
    return [
        wd
        for wd, day_name in DAY_FIELDS.items()
        if route_item.get(f"{collection_type}{day_name}", "") == "Y"
    ]


def _scheduled_collection_dt_for_date(
    target_date: datetime.date, time_str: str
) -> datetime | None:
    """Build a localized datetime for a specific date and HH:MM string."""
    try:
        hour, minute = map(int, time_str.split(":"))
    except (ValueError, AttributeError):
        return None

    return dt_util.as_local(
        datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            hour,
            minute,
            tzinfo=dt_util.DEFAULT_TIME_ZONE,
        )
    )


def _next_collection_dt(
    schedule_days: list[int], time_str: str, now: datetime | None = None
) -> datetime | None:
    """Compute the next collection datetime from a weekly schedule."""
    if not schedule_days or not time_str:
        return None
    try:
        hour, minute = map(int, time_str.split(":"))
    except (ValueError, AttributeError):
        return None

    now = now or dt_util.now()
    for days_ahead in range(8):
        candidate_date = now.date() + timedelta(days=days_ahead)
        if candidate_date.weekday() not in schedule_days:
            continue
        candidate_dt = _scheduled_collection_dt_for_date(candidate_date, time_str)
        if candidate_dt is None:
            continue
        # Skip if it's today but the time has already passed
        if days_ahead == 0 and candidate_dt <= now:
            continue
        return candidate_dt
    return None


def _parse_official_timestamp(value: Any) -> datetime | None:
    """Parse the NTPC official site timestamp format."""
    if not value:
        return None

    text = str(value).strip()
    try:
        parsed = datetime.strptime(text, "%Y%m%d%H%M%S")
    except ValueError:
        return None

    return dt_util.as_local(parsed.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE))


def _parse_hhmm_datetime(time_str: str | None, now: datetime) -> datetime | None:
    """Parse an HH:MM string into a localized datetime for today."""
    if not time_str:
        return None
    try:
        hour, minute = map(int, time_str.split(":"))
    except (ValueError, AttributeError):
        return None
    return dt_util.as_local(
        datetime(
            now.year,
            now.month,
            now.day,
            hour,
            minute,
            tzinfo=dt_util.DEFAULT_TIME_ZONE,
        )
    )


def _official_site_weekday(now: datetime) -> int:
    """Match the official site weekday numbering (0=Sun ... 6=Sat)."""
    return int(now.strftime("%w"))


def _official_site_time_interval(now: datetime) -> int:
    """Match the official site time selector for map queries."""
    if 0 <= now.hour < 12:
        return 1
    if 12 <= now.hour < 18:
        return 2
    return 3


def _safe_float(value: Any) -> float | None:
    """Convert a value to float, returning None for blanks or invalid values."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number else None


def _official_collection_status(
    barcode: str | None,
    line_id: str | None,
) -> str:
    """Map the NTPC official barcode into the site status text."""
    barcode = str(barcode or "").strip()
    line_id = str(line_id or "").strip()

    if not barcode:
        return "非收運時間"
    if barcode == "000003":
        return "暫時離開"
    if barcode == "000004":
        return "回場轉運中"
    if barcode in {line_id, "000005", "000007"}:
        return "執勤中"
    if barcode == "000006":
        return "發生路況障礙"
    if barcode in {"000013", "000014", "000015"}:
        return "前往焚化廠"
    return "非收運時間"


def _estimate_official_arrival_dt(
    arrival_rank: int,
    diff_minutes: int,
    point_rank: int,
    point_time: str | None,
    barcode: str | None,
    now: datetime,
) -> datetime | None:
    """Reproduce the NTPC site fallback estimate for upcoming stops."""
    if (
        arrival_rank == 0
        or diff_minutes == 65535
        or not barcode
        or barcode == "000006"
        or point_rank <= arrival_rank
        or point_rank > arrival_rank + 15
    ):
        return None

    point_dt = _parse_hhmm_datetime(point_time, now)
    if point_dt is None:
        return None
    estimated = point_dt + timedelta(minutes=diff_minutes)
    return estimated if estimated >= now else None


def _select_live_route_items(
    route_items: list[dict[str, Any]],
    now: datetime,
) -> list[dict[str, Any]]:
    """Choose the next upcoming route(s) to drive live truck data."""
    candidates: list[tuple[datetime, dict[str, Any]]] = []
    for route_item in route_items:
        candidate = _next_collection_dt(
            _schedule_weekdays(route_item, "garbage"),
            route_item.get("time", ""),
            now,
        )
        if candidate is not None:
            candidates.append((candidate, route_item))

    if not candidates:
        return route_items

    next_dt = min(candidate for candidate, _ in candidates)
    return [route_item for candidate, route_item in candidates if candidate == next_dt]


def _select_display_route_items(
    route_items: list[dict[str, Any]],
    eta_payload: dict[str, Any] | None,
    now: datetime,
) -> list[dict[str, Any]]:
    """Choose the route(s) that should drive displayed schedule and status context."""
    line_index = {
        str(line.get("LineID", "")): line
        for line in (eta_payload or {}).get("Line", [])
    }
    active_today_candidates: list[tuple[datetime, dict[str, Any]]] = []
    started_today_candidates: list[tuple[datetime, dict[str, Any]]] = []
    future_today_candidates: list[tuple[datetime, dict[str, Any]]] = []

    for route_item in route_items:
        if now.weekday() not in _schedule_weekdays(route_item, "garbage"):
            continue
        scheduled_dt = _scheduled_collection_dt_for_date(
            now.date(), route_item.get("time", "")
        )
        if scheduled_dt is None:
            continue

        if scheduled_dt <= now:
            started_today_candidates.append((scheduled_dt, route_item))
        else:
            future_today_candidates.append((scheduled_dt, route_item))

        line = line_index.get(str(route_item.get("lineid", "")))
        if not line:
            continue
        active_today_candidates.append((scheduled_dt, route_item))

    if active_today_candidates:
        # If a later run has already opened, switch immediately to that run.
        scheduled_dt = max(candidate for candidate, _ in active_today_candidates)
        return [
            route_item
            for candidate, route_item in active_today_candidates
            if candidate == scheduled_dt
        ]

    if started_today_candidates:
        # No live line remains, so keep today's last started run until midnight.
        scheduled_dt = max(candidate for candidate, _ in started_today_candidates)
        return [
            route_item
            for candidate, route_item in started_today_candidates
            if candidate == scheduled_dt
        ]

    if future_today_candidates:
        scheduled_dt = min(candidate for candidate, _ in future_today_candidates)
        return [
            route_item
            for candidate, route_item in future_today_candidates
            if candidate == scheduled_dt
        ]

    return _select_live_route_items(route_items, now)


def _scheduled_collection_time_for_routes(
    route_items: list[dict[str, Any]],
    eta_payload: dict[str, Any] | None,
    now: datetime,
) -> datetime | None:
    """Return the displayed scheduled collection datetime for the selected route set."""
    candidates: list[datetime] = []

    for route_item in route_items:
        if now.weekday() in _schedule_weekdays(route_item, "garbage"):
            scheduled_today = _scheduled_collection_dt_for_date(
                now.date(), route_item.get("time", "")
            )
            if scheduled_today is not None:
                candidates.append(scheduled_today)
                continue

        next_dt = _next_collection_dt(
            _schedule_weekdays(route_item, "garbage"),
            route_item.get("time", ""),
            now,
        )
        if next_dt is not None:
            candidates.append(next_dt)

    valid_candidates = [candidate for candidate in candidates if candidate is not None]
    return min(valid_candidates) if valid_candidates else None


def _extract_official_live_data(
    eta_payload: dict[str, Any],
    routes: list[dict[str, Any]],
    point_latitude: float,
    point_longitude: float,
    now: datetime,
) -> dict[str, Any]:
    """Extract official ETA, truck location, and update time from GetArrival."""
    route_index = {
        (str(route.get("lineid", "")), str(route.get("rank", ""))): route
        for route in routes
    }
    selected_lineids = {str(route.get("lineid", "")) for route in routes}
    arrival_candidates: list[datetime] = []
    departure_candidates: list[datetime] = []
    nearest_distance: float | None = None
    nearest_location: str | None = None
    nearest_truck_lat: float | None = None
    nearest_truck_lon: float | None = None
    collection_status = "非收運時間"
    collection_status_code: str | None = None
    car_no: str | None = None

    for line in eta_payload.get("Line", []):
        lineid = str(line.get("LineID", ""))
        if lineid not in selected_lineids:
            continue

        if collection_status_code is None:
            collection_status_code = str(line.get("BarCode") or "") or None
            collection_status = _official_collection_status(
                collection_status_code,
                lineid,
            )
            car_no = str(line.get("CarNO") or "") or None

        truck_lat = _safe_float(line.get("LocationLat"))
        truck_lon = _safe_float(line.get("LocationLon"))
        if (
            truck_lat is not None
            and truck_lon is not None
            and point_latitude
            and point_longitude
        ):
            distance = _haversine_distance(
                point_latitude, point_longitude, truck_lat, truck_lon
            )
            if nearest_distance is None or distance < nearest_distance:
                nearest_distance = distance
                nearest_location = line.get("Location")
                nearest_truck_lat = truck_lat
                nearest_truck_lon = truck_lon

        arrival_rank = int(line.get("ArrivalRank") or 0)
        raw_diff = line.get("Diff")
        try:
            diff_minutes = int(raw_diff) if raw_diff not in (None, "") else 65535
        except (ValueError, TypeError):
            diff_minutes = 65535
        barcode = str(line.get("BarCode") or "")
        for point in line.get("Point", []) or []:
            rank = str(point.get("PointRank", ""))
            if (lineid, rank) not in route_index:
                continue
            actual_arrival_dt = _parse_hhmm_datetime(point.get("Arrival"), now)
            if actual_arrival_dt is not None:
                departure_candidates.append(actual_arrival_dt)
            elif arrival_rank > int(point.get("PointRank") or 0):
                fallback_departed_dt = _parse_hhmm_datetime(point.get("PointTime"), now)
                if fallback_departed_dt is not None:
                    departure_candidates.append(fallback_departed_dt)

            arrival_dt = actual_arrival_dt
            if arrival_dt is None:
                try:
                    point_rank = int(point.get("PointRank") or 0)
                except (ValueError, TypeError):
                    point_rank = 0
                arrival_dt = _estimate_official_arrival_dt(
                    arrival_rank=arrival_rank,
                    diff_minutes=diff_minutes,
                    point_rank=point_rank,
                    point_time=point.get("PointTime"),
                    barcode=barcode,
                    now=now,
                )
            if arrival_dt is not None:
                arrival_candidates.append(arrival_dt)

    return {
        "nearest_truck_distance": nearest_distance,
        "nearest_truck_location": nearest_location,
        "nearest_truck_lat": nearest_truck_lat,
        "nearest_truck_lon": nearest_truck_lon,
        "estimated_arrival_time": min(arrival_candidates) if arrival_candidates else None,
        "last_vehicle_update": _parse_official_timestamp(eta_payload.get("TimeStamp")),
        "collection_status": collection_status,
        "collection_status_code": collection_status_code,
        "car_no": car_no,
        "truck_departed": bool(departure_candidates),
        "truck_departed_at": max(departure_candidates) if departure_candidates else None,
    }



class NtpcRubbishCoordinator(DataUpdateCoordinator[CollectionPointData]):
    """Coordinator that polls vehicle location and computes collection status."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: NtpcRubbishApiClient,
    ) -> None:
        self._entry = entry
        self._client = client
        self._route_data: dict[str, Any] | None = None
        self._route_last_updated: datetime | None = None
        self._last_vehicle_update: datetime | None = None

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )

    def _get_routes(self) -> list[dict[str, Any]]:
        """Return the list of routes for this entry."""
        return get_active_routes(self._entry)

    async def _ensure_route_data(self) -> dict[str, Any]:
        """Load route data for the first route, using a hass.data cache."""
        return (await self._ensure_route_data_list())[0]

    async def _ensure_route_data_list(self) -> list[dict[str, Any]]:
        """Load route data for all configured routes, using a hass.data cache."""
        now = dt_util.utcnow()
        route_cache: dict[str, Any] = self.hass.data.setdefault(_ROUTE_CACHE_KEY, {})
        route_items: list[dict[str, Any]] = []

        for route_ref in self._get_routes():
            lineid = route_ref["lineid"]
            rank = route_ref["rank"]
            cache_key = f"{lineid}_{rank}"
            cached = route_cache.get(cache_key)

            if cached is None or (now - cached["updated_at"]).total_seconds() > ROUTE_CACHE_TTL:
                _LOGGER.debug("Fetching route data for lineid=%s rank=%s", lineid, rank)
                route = await self._client.get_route_point(lineid, rank)
                if route is None:
                    raise UpdateFailed(
                        f"Collection point lineid={lineid} rank={rank} not found in route data"
                    )
                route_cache[cache_key] = {"data": route, "updated_at": now}

            route_items.append(route_cache[cache_key]["data"])

        return route_items

    async def _get_official_line_arrival_payload(
        self, line_ids: list[str]
    ) -> dict[str, Any]:
        """Fetch official line-arrival data with a shared cache."""
        cache_key = ",".join(sorted(line_ids))
        arrival_cache: dict[str, Any] = self.hass.data.setdefault(
            _OFFICIAL_LINE_ARRIVAL_CACHE_KEY, {}
        )
        cached = arrival_cache.get(cache_key)
        utc_now = dt_util.utcnow()

        if (
            cached is None
            or (utc_now - cached["updated_at"]).total_seconds()
            > _OFFICIAL_LINE_ARRIVAL_CACHE_TTL
        ):
            _LOGGER.debug("Fetching official line arrivals for %s", cache_key)
            payload = await self._client.get_official_line_arrivals(line_ids)
            arrival_cache[cache_key] = {"data": payload, "updated_at": utc_now}

        return arrival_cache[cache_key]["data"]

    async def _get_official_around_points_payload(
        self,
        *,
        latitude: float,
        longitude: float,
        now: datetime,
    ) -> dict[str, Any]:
        """Fetch official map payload around this collection point."""
        cache_key = (
            f"{latitude:.6f},{longitude:.6f},"
            f"{_official_site_weekday(now)},{_official_site_time_interval(now)}"
        )
        around_cache: dict[str, Any] = self.hass.data.setdefault(
            _OFFICIAL_AROUND_POINTS_CACHE_KEY, {}
        )
        cached = around_cache.get(cache_key)
        utc_now = dt_util.utcnow()

        if (
            cached is None
            or (utc_now - cached["updated_at"]).total_seconds()
            > _OFFICIAL_LINE_ARRIVAL_CACHE_TTL
        ):
            _LOGGER.debug("Fetching official around points for %s", cache_key)
            payload = await self._client.get_official_around_points(
                latitude=latitude,
                longitude=longitude,
                week=_official_site_weekday(now),
                time_interval=_official_site_time_interval(now),
            )
            around_cache[cache_key] = {"data": payload, "updated_at": utc_now}

        return around_cache[cache_key]["data"]

    async def _async_update_data(self) -> CollectionPointData:
        """Fetch latest vehicle data and compute collection point state."""
        try:
            route_items = await self._ensure_route_data_list()
        except UpdateFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Error communicating with NTPC API: {err}") from err

        route = route_items[0]
        now = dt_util.now()
        weekday = now.weekday()

        try:
            lat = float(route.get("latitude") or 0)
            lon = float(route.get("longitude") or 0)
        except (ValueError, TypeError):
            lat, lon = 0.0, 0.0

        garbage_today = any(_is_collected(item, "garbage", weekday) for item in route_items)
        recycling_today = any(_is_collected(item, "recycling", weekday) for item in route_items)
        food_scraps_today = any(_is_collected(item, "foodscraps", weekday) for item in route_items)

        nearest_distance: float | None = None
        nearest_location: str | None = None
        nearest_truck_lat: float | None = None
        nearest_truck_lon: float | None = None
        last_vehicle_update: datetime | None = None
        official_arrival_time: datetime | None = None
        collection_status: str | None = "非收運時間"
        collection_status_code: str | None = None
        car_no: str | None = None
        display_route_items = route_items
        line_ids = sorted({str(item.get("lineid", "")) for item in route_items})
        official_eta_payload: dict[str, Any] | None = None
        if line_ids:
            try:
                official_eta_payload = await self._get_official_around_points_payload(
                    latitude=lat,
                    longitude=lon,
                    now=now,
                )
            except Exception as err:
                _LOGGER.debug("Failed to fetch official around points: %s", err)

            if not any(
                str(line.get("LineID", "")) in line_ids
                for line in (official_eta_payload or {}).get("Line", [])
            ):
                try:
                    official_eta_payload = await self._get_official_line_arrival_payload(
                        line_ids
                    )
                except Exception as err:
                    _LOGGER.debug("Failed to fetch official line arrivals: %s", err)

            if official_eta_payload is not None:
                display_route_items = _select_display_route_items(
                    route_items,
                    official_eta_payload,
                    now,
                )
                official_live = _extract_official_live_data(
                    official_eta_payload,
                    display_route_items,
                    lat,
                    lon,
                    now,
                )
                nearest_distance = official_live["nearest_truck_distance"]
                nearest_location = official_live["nearest_truck_location"]
                nearest_truck_lat = official_live["nearest_truck_lat"]
                nearest_truck_lon = official_live["nearest_truck_lon"]
                last_vehicle_update = official_live["last_vehicle_update"]
                official_arrival_time = official_live["estimated_arrival_time"]
                collection_status = official_live["collection_status"]
                collection_status_code = official_live["collection_status_code"]
                car_no = official_live["car_no"]
                if last_vehicle_update is not None:
                    self._last_vehicle_update = last_vehicle_update

        if line_ids and display_route_items is route_items:
            display_route_items = _select_live_route_items(route_items, now)
        scheduled_collection_time = _scheduled_collection_time_for_routes(
            display_route_items,
            official_eta_payload,
            now,
        )

        effective_last_vehicle_update = last_vehicle_update or self._last_vehicle_update

        estimated_arrival_time = official_arrival_time
        data_staleness_seconds = (
            max(0, int((dt_util.now() - effective_last_vehicle_update).total_seconds()))
            if effective_last_vehicle_update is not None
            else None
        )

        from .const import CONF_POINT_NAME, CONF_DISTRICT
        scheduled_time_str = format_scheduled_times(self._get_routes()) or route.get("time", "")
        display_route = display_route_items[0] if display_route_items else route
        first_lineid = display_route.get("lineid", self._get_routes()[0]["lineid"])
        return CollectionPointData(
            point_name=self._entry.data.get(CONF_POINT_NAME, route.get("name", "")),
            district=self._entry.data.get(CONF_DISTRICT, route.get("city", "")),
            route_line_name=display_route.get("linename", first_lineid),
            latitude=lat,
            longitude=lon,
            scheduled_time=scheduled_time_str,
            garbage_today=garbage_today,
            recycling_today=recycling_today,
            food_scraps_today=food_scraps_today,
            scheduled_collection_time=scheduled_collection_time,
            next_collection_type="garbage" if scheduled_collection_time is not None else None,
            collection_status=collection_status,
            collection_status_code=collection_status_code,
            car_no=car_no,
            nearest_truck_distance=(
                round(nearest_distance, 1) if nearest_distance is not None else None
            ),
            nearest_truck_location=nearest_location,
            nearest_truck_lat=nearest_truck_lat,
            nearest_truck_lon=nearest_truck_lon,
            estimated_arrival_time=estimated_arrival_time,
            last_vehicle_update=effective_last_vehicle_update,
            data_staleness_seconds=data_staleness_seconds,
            truck_departed=official_live["truck_departed"] if official_eta_payload is not None else False,
            truck_departed_at=official_live["truck_departed_at"] if official_eta_payload is not None else None,
        )
