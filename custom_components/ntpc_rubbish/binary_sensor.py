"""Binary sensor entities for NTPC Rubbish integration."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_LATITUDE, CONF_LONGITUDE, CONF_POINT_NAME, CONF_SCHEDULED_TIME, DOMAIN
from .coordinator import CollectionPointData, NtpcRubbishCoordinator
from .entity import (
    build_device_info,
    format_scheduled_times,
    get_active_routes,
    point_device_id,
    point_entity_id,
    point_object_id,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: NtpcRubbishCoordinator = hass.data[DOMAIN][entry.entry_id]
    point_name: str = entry.data[CONF_POINT_NAME]
    lat: float = entry.data.get(CONF_LATITUDE, 0)
    lon: float = entry.data.get(CONF_LONGITUDE, 0)
    scheduled_times: str = format_scheduled_times(get_active_routes(entry)) or entry.data.get(
        CONF_SCHEDULED_TIME, ""
    )
    device_id = point_device_id(lat, lon)

    async_add_entities(
        [
            GarbageTodaySensor(coordinator, entry, device_id, point_name, scheduled_times),
            RecyclingTodaySensor(coordinator, entry, device_id, point_name, scheduled_times),
            FoodScrapsTodaySensor(coordinator, entry, device_id, point_name, scheduled_times),
            TruckDepartedSensor(coordinator, entry, device_id, point_name, scheduled_times),
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
        if self._data is None:
            return {}
        return {
            "departed_at": (
                self._data.truck_departed_at.isoformat()
                if self._data.truck_departed_at
                else None
            )
        }
