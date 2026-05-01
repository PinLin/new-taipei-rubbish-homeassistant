"""Binary sensor entities for NTPC Rubbish integration."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ENABLED_ROUTE_KEYS,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_POINT_NAME,
    CONF_ROUTES,
    CONF_SCHEDULED_TIME,
    DOMAIN,
)
from .coordinator import CollectionPointData, NtpcRubbishCoordinator
from .entity import (
    build_device_info,
    format_scheduled_times,
    get_active_routes,
    point_device_id,
    point_entity_id,
    point_object_id,
    route_key,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: NtpcRubbishCoordinator = entry.runtime_data
    point_name: str = entry.data[CONF_POINT_NAME]
    lat: float = entry.data.get(CONF_LATITUDE, 0)
    lon: float = entry.data.get(CONF_LONGITUDE, 0)
    scheduled_times: str = format_scheduled_times(get_active_routes(entry)) or entry.data.get(
        CONF_SCHEDULED_TIME, ""
    )
    device_id = point_device_id(lat, lon)
    routes = entry.data.get(CONF_ROUTES, [])

    async_add_entities(
        [
            GarbageTodaySensor(coordinator, entry, device_id, point_name, scheduled_times),
            RecyclingTodaySensor(coordinator, entry, device_id, point_name, scheduled_times),
            FoodScrapsTodaySensor(coordinator, entry, device_id, point_name, scheduled_times),
            TruckDepartedSensor(coordinator, entry, device_id, point_name, scheduled_times),
            *[
                RouteEnabledSensor(
                    coordinator,
                    entry,
                    device_id,
                    point_name,
                    scheduled_times,
                    route,
                )
                for route in routes
            ],
        ]
    )


class _NtpcRubbishBaseBinarySensor(
    CoordinatorEntity[NtpcRubbishCoordinator], BinarySensorEntity
):
    """Shared base for all NTPC Rubbish binary sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NtpcRubbishCoordinator,
        entry: ConfigEntry,
        device_id: str,
        point_name: str,
        scheduled_times: str,
        attribute: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{device_id}_{attribute}"
        self._attr_translation_key = attribute
        self._attr_suggested_object_id = point_object_id(device_id, attribute)
        self.entity_id = point_entity_id("binary_sensor", device_id, attribute)
        self._attr_device_info = build_device_info(
            entry, device_id, point_name, scheduled_times
        )

    @property
    def available(self) -> bool:
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
        )

    @property
    def _data(self) -> CollectionPointData | None:
        return self.coordinator.data

    @property
    def extra_state_attributes(self) -> dict[str, float]:
        d = self._data
        if d is None:
            return {}
        return {
            "point_id": point_device_id(d.latitude, d.longitude),
            "latitude": d.latitude,
            "longitude": d.longitude,
        }


class GarbageTodaySensor(_NtpcRubbishBaseBinarySensor):
    """On when general garbage is collected today."""

    _attr_icon = "mdi:trash-can"

    def __init__(self, coordinator, entry, device_id, point_name, scheduled_times) -> None:
        super().__init__(coordinator, entry, device_id, point_name, scheduled_times, "garbage_today")

    @property
    def is_on(self) -> bool | None:
        if self._data is None:
            return None
        return self._data.garbage_today


class RecyclingTodaySensor(_NtpcRubbishBaseBinarySensor):
    """On when recycling is collected today."""

    _attr_icon = "mdi:recycle"

    def __init__(self, coordinator, entry, device_id, point_name, scheduled_times) -> None:
        super().__init__(coordinator, entry, device_id, point_name, scheduled_times, "recycling_today")

    @property
    def is_on(self) -> bool | None:
        if self._data is None:
            return None
        return self._data.recycling_today


class FoodScrapsTodaySensor(_NtpcRubbishBaseBinarySensor):
    """On when food scraps (kitchen waste) are collected today."""

    _attr_icon = "mdi:food-apple-outline"

    def __init__(self, coordinator, entry, device_id, point_name, scheduled_times) -> None:
        super().__init__(coordinator, entry, device_id, point_name, scheduled_times, "food_scraps_today")

    @property
    def is_on(self) -> bool | None:
        if self._data is None:
            return None
        return self._data.food_scraps_today


class TruckDepartedSensor(_NtpcRubbishBaseBinarySensor):
    """On when the official live data shows the truck already passed this point."""

    _attr_icon = "mdi:truck-check-outline"

    def __init__(self, coordinator, entry, device_id, point_name, scheduled_times) -> None:
        super().__init__(coordinator, entry, device_id, point_name, scheduled_times, "truck_departed")

    @property
    def is_on(self) -> bool | None:
        if self._data is None:
            return None
        return self._data.truck_departed

    @property
    def extra_state_attributes(self) -> dict[str, str | None]:
        attrs = super().extra_state_attributes
        if self._data is None:
            return attrs
        attrs["departed_at"] = (
            self._data.truck_departed_at.isoformat()
            if self._data.truck_departed_at
            else None
        )
        return attrs


class RouteEnabledSensor(
    CoordinatorEntity[NtpcRubbishCoordinator], BinarySensorEntity
):
    """Diagnostic entity showing whether a configured route is enabled."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:routes"

    def __init__(
        self,
        coordinator: NtpcRubbishCoordinator,
        entry: ConfigEntry,
        device_id: str,
        point_name: str,
        scheduled_times: str,
        route: dict[str, str],
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._device_id = device_id
        self._route = route
        self._route_key = route_key(route)
        route_label = "｜".join(
            part
            for part in (
                route.get("scheduled_time") or route.get("time") or "",
                route.get("linename", ""),
                f"#{route['rank']}" if route.get("rank") else "",
                route.get("lineid", ""),
            )
            if part
        )
        self._attr_name = route_label or self._route_key
        self._attr_unique_id = f"{DOMAIN}_{device_id}_route_{self._route_key}_enabled"
        self._attr_suggested_object_id = point_object_id(
            device_id, f"route_{self._route_key}_enabled"
        )
        self.entity_id = point_entity_id(
            "binary_sensor", device_id, f"route_{self._route_key}_enabled"
        )
        self._attr_device_info = build_device_info(
            entry, device_id, point_name, scheduled_times
        )

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        enabled_route_keys = (
            self._entry.options.get(CONF_ENABLED_ROUTE_KEYS)
            or self._entry.data.get(CONF_ENABLED_ROUTE_KEYS)
            or []
        )
        return not enabled_route_keys or self._route_key in enabled_route_keys

    @property
    def extra_state_attributes(self) -> dict[str, str | bool | None]:
        return {
            "point_id": self._device_id,
            "route_key": self._route_key,
            "scheduled_time": self._route.get("scheduled_time")
            or self._route.get("time"),
            "line_name": self._route.get("linename"),
            "line_id": self._route.get("lineid"),
            "rank": self._route.get("rank"),
        }
