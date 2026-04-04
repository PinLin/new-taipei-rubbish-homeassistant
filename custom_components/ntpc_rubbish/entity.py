"""Shared entity helpers for NTPC Rubbish integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry

from .const import CONF_ENABLED_ROUTE_KEYS, CONF_ROUTES, DOMAIN


def route_key(route: dict[str, str]) -> str:
    """Return a stable route key used in selectors and options."""
    return f"{route.get('lineid', '')}_{route.get('rank', '')}"


def get_active_routes(entry: ConfigEntry) -> list[dict[str, str]]:
    """Return the enabled routes for this config entry."""
    routes: list[dict[str, str]] = entry.data.get(CONF_ROUTES, [])
    enabled_route_keys: list[str] = (
        entry.options.get(CONF_ENABLED_ROUTE_KEYS)
        or entry.data.get(CONF_ENABLED_ROUTE_KEYS)
        or []
    )
    if not enabled_route_keys:
        return routes

    enabled_keys = set(enabled_route_keys)
    active_routes = [route for route in routes if route_key(route) in enabled_keys]
    return active_routes or routes


def format_scheduled_times(routes: list[dict[str, str]]) -> str:
    """Format route times for UI and device info."""
    return ", ".join(
        sorted({route.get("scheduled_time", "") for route in routes if route.get("scheduled_time")})
    )


def point_device_id(latitude: float, longitude: float) -> str:
    """Return the stable point identifier used across entities and devices."""
    return f"{latitude:.5f}_{longitude:.5f}"


def point_object_id(device_id: str, attribute: str) -> str:
    """Return a Home Assistant-safe object id that avoids name-derived pinyin."""
    return f"{DOMAIN}_{device_id.replace('.', '_')}_{attribute}"


def point_entity_id(platform: str, device_id: str, attribute: str) -> str:
    """Return a stable entity_id for the given platform and point attribute."""
    return f"{platform}.{point_object_id(device_id, attribute)}"


def build_device_info(
    entry: ConfigEntry,
    device_id: str,
    point_name: str,
    scheduled_times: str,
) -> dict[str, object]:
    """Build Home Assistant device info with useful diagnostic identifiers."""
    routes = get_active_routes(entry)
    route_summaries = "、".join(
        "｜".join(
            part
            for part in (
                route.get("scheduled_time", ""),
                route.get("linename", ""),
                f"#{route['rank']}" if route.get("rank") else "",
                route.get("lineid", ""),
            )
            if part
        )
        for route in routes
    )
    current_times = scheduled_times or format_scheduled_times(routes)
    model = route_summaries or current_times or "垃圾清運收運點"

    return {
        "identifiers": {(DOMAIN, device_id)},
        "name": point_name,
        "manufacturer": "新北市政府環境保護局",
        "model": model,
    }
