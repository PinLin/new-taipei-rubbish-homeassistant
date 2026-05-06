"""Diagnostics support for NTPC Rubbish."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntry

from .const import CONF_ENABLED_ROUTE_KEYS, CONF_ROUTES, DOMAIN
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
    last_update_time = coordinator.last_update_success_time
    routes = entry.data.get(CONF_ROUTES, [])
    enabled_route_keys = set(
        entry.options.get(CONF_ENABLED_ROUTE_KEYS)
        or entry.data.get(CONF_ENABLED_ROUTE_KEYS)
        or []
    )

    return {
        "entry": async_redact_data(entry.as_dict(), REDACT_KEYS),
        "coordinator": {
            "last_update_success_time": (
                last_update_time.isoformat() if last_update_time else None
            ),
            "last_update_success": coordinator.last_update_success,
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
        "data": async_redact_data(_serialize(coordinator.data), REDACT_KEYS),
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
    device: DeviceEntry,
) -> dict[str, Any]:
    """Return diagnostics for a single collection point.

    Includes the CollectionPointData snapshot the coordinator stores
    for the device plus a roster of every entity registered for the
    device with its current state and attributes — enough to triage
    "this entity shows wrong value" bug reports without screenshots.
    """
    coordinator = entry.runtime_data
    last_update_time = coordinator.last_update_success_time

    # Resolve point identifier; entity uses identifiers={(DOMAIN, device_id)}.
    point_id: str | None = None
    for ident_domain, identifier in device.identifiers:
        if ident_domain == DOMAIN:
            point_id = identifier
            break

    ent_reg = er.async_get(hass)
    entities: list[dict[str, Any]] = []
    for ent in er.async_entries_for_device(
        ent_reg, device.id, include_disabled_entities=True
    ):
        state = hass.states.get(ent.entity_id)
        entities.append(
            {
                "entity_id": ent.entity_id,
                "unique_id": ent.unique_id,
                "platform": ent.platform,
                "domain": ent.domain,
                "translation_key": ent.translation_key,
                "device_class": ent.device_class or ent.original_device_class,
                "disabled_by": ent.disabled_by,
                "state": state.state if state else None,
                "attributes": dict(state.attributes) if state else None,
            }
        )

    return {
        "device": {
            "id": device.id,
            "name": device.name,
            "name_by_user": device.name_by_user,
            "manufacturer": device.manufacturer,
            "model": device.model,
            "identifiers": [list(i) for i in device.identifiers],
        },
        "coordinator": {
            "last_update_success_time": (
                last_update_time.isoformat() if last_update_time else None
            ),
            "last_update_success": coordinator.last_update_success,
        },
        "point_id": point_id,
        "data": (
            async_redact_data(_serialize(coordinator.data), REDACT_KEYS)
            if coordinator.data is not None
            else None
        ),
        "entities": async_redact_data(entities, REDACT_KEYS),
    }
