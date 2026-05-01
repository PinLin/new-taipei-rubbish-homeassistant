"""Diagnostics support for NTPC Rubbish."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_ENABLED_ROUTE_KEYS, CONF_ROUTES
from .entity import route_key

# A user's collection point latitude / longitude is effectively their home
# address, so we redact it from diagnostics shared with third parties.
REDACT_KEYS = {
    "access_token",
    "refresh_token",
    "password",
    "api_key",
    "latitude",
    "longitude",
    "nearest_truck_lat",
    "nearest_truck_lon",
}


def _serialize(obj: Any) -> Any:
    """Convert nested dataclasses to plain dicts so async_redact_data can walk them."""
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(v) for v in obj]
    return obj


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return redacted diagnostic info for one config entry."""
    coordinator = entry.runtime_data
    raw_data = coordinator.data if coordinator is not None else None
    last_update = coordinator.last_update if coordinator is not None else None
    routes = entry.data.get(CONF_ROUTES, [])
    enabled_route_keys = set(
        entry.options.get(CONF_ENABLED_ROUTE_KEYS)
        or entry.data.get(CONF_ENABLED_ROUTE_KEYS)
        or []
    )

    return {
        "entry": async_redact_data(entry.as_dict(), REDACT_KEYS),
        "coordinator": {
            "last_update": last_update.isoformat() if last_update else None,
            "last_update_success": (
                coordinator.last_update_success if coordinator is not None else None
            ),
        },
        "routes": [
            {
                "route_key": route_key(route),
                "enabled": not enabled_route_keys or route_key(route) in enabled_route_keys,
                "scheduled_time": route.get("scheduled_time") or route.get("time"),
                "line_name": route.get("linename"),
                "line_id": route.get("lineid"),
                "rank": route.get("rank"),
            }
            for route in routes
        ],
        "data": async_redact_data(_serialize(raw_data), REDACT_KEYS),
    }
