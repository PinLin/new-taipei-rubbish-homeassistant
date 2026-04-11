"""Config flow for New Taipei City Garbage Truck integration."""
from __future__ import annotations

import logging
import math
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    LocationSelector,
    LocationSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import NtpcRubbishApiClient
from .const import (
    CONF_DISTRICT,
    CONF_ENABLED_ROUTE_KEYS,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_POINT_NAME,
    CONF_ROUTES,
    CONF_SCHEDULED_TIME,
    CONF_UPDATE_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .entity import format_scheduled_times, route_key

_LOGGER = logging.getLogger(__name__)

# Full route dataset cache key (shared across config flow instances)
_ALL_ROUTES_CACHE_KEY = f"{DOMAIN}_all_routes_cache"
# Max nearest results to display
_MAX_RESULTS = 20


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in metres."""
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin(math.radians(lat2 - lat1) / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def _collection_point_key(route: dict[str, Any]) -> str:
    """Return a stable grouping key for the same physical collection point."""
    try:
        lat = round(float(route.get("latitude") or 0), 4)
        lon = round(float(route.get("longitude") or 0), 4)
    except (ValueError, TypeError):
        lat, lon = 0.0, 0.0
    return f"{route.get('name', '')}|{lat:.4f}|{lon:.4f}"


def _route_sort_key(route: dict[str, Any]) -> tuple[str, str, str]:
    """Sort sibling routes by time, then line id and rank."""
    return (
        str(route.get("time") or ""),
        str(route.get("lineid") or ""),
        str(route.get("rank") or ""),
    )


def _route_selector_label(route: dict[str, Any]) -> str:
    """Build a readable route label for multi-select fields."""
    return "｜".join(
        part
        for part in (
            route.get("scheduled_time") or route.get("time") or "--:--",
            route.get("linename") or route.get("lineid") or "",
            f"#{route.get('rank')}" if route.get("rank") else "",
            route.get("lineid") or "",
        )
        if part
    )


def _distance_to_route(route: dict[str, Any], lat: float, lon: float) -> float:
    """Return the route distance from the user location."""
    try:
        return _haversine_m(
            lat,
            lon,
            float(route.get("latitude") or 0),
            float(route.get("longitude") or 0),
        )
    except (ValueError, TypeError):
        return float("inf")


def _group_routes(
    all_routes: list[dict[str, Any]], user_lat: float, user_lon: float
) -> dict[str, dict[str, Any]]:
    """Group route rows into physical collection points."""
    grouped_points: dict[str, dict[str, Any]] = {}
    for route in all_routes:
        distance = _distance_to_route(route, user_lat, user_lon)
        if math.isinf(distance):
            continue

        key = _collection_point_key(route)
        group = grouped_points.setdefault(
            key,
            {
                "key": key,
                "point": route,
                "routes": [],
                "_dist_raw": distance,
            },
        )
        if distance < group["_dist_raw"]:
            group["_dist_raw"] = distance
            group["point"] = route
        group["routes"].append(route)

    return grouped_points


def _prepare_point_result(point: dict[str, Any]) -> dict[str, Any]:
    """Normalize grouped point data for selectors."""
    point["routes"] = sorted(point["routes"], key=_route_sort_key)
    point["_dist_m"] = round(point["_dist_raw"])
    point["selection_key"] = f"{point['routes'][0]['lineid']}_{point['routes'][0]['rank']}"
    point["scheduled_times"] = ", ".join(
        sorted({str(route.get("time")) for route in point["routes"] if route.get("time")})
    )
    return point


class NtpcRubbishConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for NTPC Rubbish."""

    VERSION = 1

    def __init__(self) -> None:
        self._user_lat: float = 0.0
        self._user_lon: float = 0.0
        self._filtered_points: list[dict[str, Any]] = []
        self._selected_point: dict[str, Any] | None = None
        self._selected_routes: list[dict[str, Any]] = []
        self._enabled_routes: list[dict[str, Any]] = []
        self._update_interval: int = DEFAULT_SCAN_INTERVAL

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            loc = user_input["location"]
            self._user_lat = float(loc["latitude"])
            self._user_lon = float(loc["longitude"])
            try:
                all_routes = await self._get_all_routes()
                grouped_points = _group_routes(all_routes, self._user_lat, self._user_lon)
                self._filtered_points = await self._nearest_points(grouped_points)
            except Exception:
                _LOGGER.exception("Failed to fetch route data")
                errors["base"] = "cannot_connect"
            else:
                if not self._filtered_points:
                    errors["base"] = "no_results"
                else:
                    return await self.async_step_results()

        home_lat = self.hass.config.latitude or 25.05
        home_lon = self.hass.config.longitude or 121.52

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "location",
                        default={"latitude": home_lat, "longitude": home_lon},
                    ): LocationSelector(LocationSelectorConfig())
                }
            ),
            errors=errors,
        )

    async def async_step_results(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            selected_key = user_input.get("point", "")
            for point in self._filtered_points:
                if point["selection_key"] == selected_key:
                    self._selected_point = point["point"]
                    self._selected_routes = point["routes"]
                    self._enabled_routes = point["routes"]
                    if len(self._selected_routes) == 1:
                        return await self.async_step_interval()
                    return await self.async_step_settings()

        options = [
            {
                "value": p["selection_key"],
                "label": "".join(
                    (
                        f"{p.get('_dist_m', '?')}m｜",
                        f"{p['point'].get('name', '')}",
                        f"（{p['point'].get('city', '')} {p['point'].get('village', '')}）｜",
                        f"{p.get('scheduled_times', '--:--')}",
                    )
                ),
            }
            for p in self._filtered_points
        ]

        return self.async_show_form(
            step_id="results",
            data_schema=vol.Schema(
                {
                    vol.Required("point"): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def _nearest_points(
        self, grouped_points: dict[str, dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Return the nearest grouped points without official-site filters."""
        nearby = sorted(grouped_points.values(), key=lambda item: item["_dist_raw"])[:_MAX_RESULTS]
        return [_prepare_point_result(point) for point in nearby]

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            point = self._selected_point
            assert point is not None
            selected_route_keys = user_input.get(CONF_ENABLED_ROUTE_KEYS, [])
            if isinstance(selected_route_keys, str):
                selected_route_keys = [selected_route_keys]
            if not selected_route_keys:
                errors["base"] = "select_at_least_one_route"
            else:
                enabled_keys = set(selected_route_keys)
                enabled_routes = [
                    route for route in self._selected_routes if route_key(route) in enabled_keys
                ]
                if not enabled_routes:
                    errors["base"] = "select_at_least_one_route"
                else:
                    self._enabled_routes = enabled_routes
                    return await self.async_step_interval()

        route_options = [
            {"value": route_key(route), "label": _route_selector_label(route)}
            for route in self._selected_routes
        ]
        default_route_keys = [route_key(route) for route in self._selected_routes]

        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ENABLED_ROUTE_KEYS, default=default_route_keys
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=route_options,
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_interval(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        if user_input is not None:
            self._update_interval = int(user_input[CONF_UPDATE_INTERVAL])
            return await self._async_create_config_entry()

        return self.async_show_form(
            step_id="interval",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_UPDATE_INTERVAL, default=DEFAULT_SCAN_INTERVAL): NumberSelector(
                        NumberSelectorConfig(min=30, step=1, mode=NumberSelectorMode.BOX)
                    )
                }
            ),
        )

    # ------------------------------------------------------------------ #
    # Options flow entry point
    # ------------------------------------------------------------------ #
    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> NtpcRubbishOptionsFlow:
        return NtpcRubbishOptionsFlow(config_entry)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    async def _get_all_routes(self) -> list[dict[str, Any]]:
        """Fetch and cache the full route dataset in hass.data."""
        cache: dict[str, Any] = self.hass.data.setdefault(_ALL_ROUTES_CACHE_KEY, {})
        if "data" not in cache:
            session = async_get_clientsession(self.hass)
            client = NtpcRubbishApiClient(session)
            cache["data"] = await client.get_all_routes()
        return cache["data"]

    async def _async_create_config_entry(self) -> config_entries.FlowResult:
        """Create the config entry for the selected collection point."""
        point = self._selected_point
        assert point is not None

        try:
            lat = float(point.get("latitude") or 0)
            lon = float(point.get("longitude") or 0)
        except (ValueError, TypeError):
            lat, lon = 0.0, 0.0

        all_routes = [
            {
                "lineid": route["lineid"],
                "rank": route["rank"],
                "scheduled_time": route.get("time", ""),
                "linename": route.get("linename", ""),
            }
            for route in self._selected_routes
        ]
        data = {
            CONF_ROUTES: all_routes,
            CONF_ENABLED_ROUTE_KEYS: [route_key(route) for route in self._enabled_routes],
            CONF_POINT_NAME: point.get("name", ""),
            CONF_DISTRICT: point.get("city", ""),
            CONF_LATITUDE: lat,
            CONF_LONGITUDE: lon,
            CONF_SCHEDULED_TIME: format_scheduled_times(all_routes),
        }

        await self.async_set_unique_id(f"{DOMAIN}_{lat:.5f}_{lon:.5f}")
        self._abort_if_unique_id_configured()

        village = point.get("village", "")
        title = f"{data[CONF_POINT_NAME]}（{data[CONF_DISTRICT]} {village}）"
        return self.async_create_entry(
            title=title,
            data=data,
            options={CONF_UPDATE_INTERVAL: self._update_interval},
        )


class NtpcRubbishOptionsFlow(config_entries.OptionsFlow):
    """Handle options for an existing NTPC Rubbish entry."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.FlowResult:
        errors: dict[str, str] = {}
        routes: list[dict[str, Any]] = self._entry.data.get(CONF_ROUTES, [])
        default_route_keys = (
            self._entry.options.get(CONF_ENABLED_ROUTE_KEYS)
            or self._entry.data.get(CONF_ENABLED_ROUTE_KEYS)
            or [route_key(route) for route in routes]
        )

        update_interval = self._entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_SCAN_INTERVAL)

        if user_input is not None:
            selected_route_keys = user_input.get(CONF_ENABLED_ROUTE_KEYS, [])
            if isinstance(selected_route_keys, str):
                selected_route_keys = [selected_route_keys]
            if not selected_route_keys:
                errors["base"] = "select_at_least_one_route"
            else:
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_ENABLED_ROUTE_KEYS: selected_route_keys,
                        CONF_UPDATE_INTERVAL: int(user_input[CONF_UPDATE_INTERVAL]),
                    },
                )

        route_options = [
            {"value": route_key(route), "label": _route_selector_label(route)}
            for route in routes
        ]

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ENABLED_ROUTE_KEYS, default=default_route_keys
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=route_options,
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                    vol.Required(CONF_UPDATE_INTERVAL, default=update_interval): NumberSelector(
                        NumberSelectorConfig(min=30, step=1, mode=NumberSelectorMode.BOX)
                    ),
                }
            ),
            errors=errors,
        )
