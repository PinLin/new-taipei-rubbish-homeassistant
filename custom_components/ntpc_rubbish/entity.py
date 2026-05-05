"""Shared entity helpers for NTPC Rubbish integration."""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo

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
) -> DeviceInfo:
    """Build Home Assistant device info with useful diagnostic identifiers."""
    return DeviceInfo(
        identifiers={(DOMAIN, device_id)},
        name=point_name,
        manufacturer="新北市政府環境保護局",
        model=device_id,
    )


class StateBroadcastDedupMixin:
    """Skip async_write_ha_state when tracked properties haven't changed.

    Each coordinator refresh fans out to every entity's
    _handle_coordinator_update; for a 30 s polling integration with
    ten-plus entities per point that's a lot of HA state writes for
    payloads that are mostly identical between cycles. Subclasses
    declare which properties drive their visible state via
    ``_state_attrs`` and inherit this mixin alongside
    ``CoordinatorEntity``; an empty tuple keeps the default behaviour.
    """

    _state_attrs: tuple[str, ...] = ()
    _last_broadcast_state: tuple[Any, ...] | None = None

    async def async_added_to_hass(self) -> None:
        """Seed the last-broadcast snapshot so the first real update is honest."""
        await super().async_added_to_hass()  # type: ignore[misc]
        self._refresh_last_broadcast()

    def _refresh_last_broadcast(self) -> bool:
        """Recompute the snapshot. Return True if it differs from the prior one."""
        if not self._state_attrs:
            return True
        snapshot = tuple(getattr(self, attr, None) for attr in self._state_attrs)
        if snapshot != self._last_broadcast_state:
            self._last_broadcast_state = snapshot
            return True
        return False

    @callback
    def _handle_coordinator_update(self) -> None:
        """Only broadcast when the entity's tracked state actually changed."""
        if self._refresh_last_broadcast():
            self.async_write_ha_state()  # type: ignore[attr-defined]
