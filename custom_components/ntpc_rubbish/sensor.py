"""Sensor entities for NTPC Rubbish integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

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


def _format_relative_collection_time(value: datetime | None) -> str | None:
    """Format a collection datetime for display."""
    if value is None:
        return None

    local_dt = dt_util.as_local(value)
    today = dt_util.now().date()
    if local_dt.date() == today:
        return local_dt.strftime("今天 %H:%M")
    if (local_dt.date() - today).days == 1:
        return local_dt.strftime("明天 %H:%M")
    return local_dt.strftime("%Y-%m-%d %H:%M")


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
            NextCollectionSensor(coordinator, entry, device_id, point_name, scheduled_times),
            CollectionStatusSensor(coordinator, entry, device_id, point_name, scheduled_times),
            EtaMinutesSensor(coordinator, entry, device_id, point_name, scheduled_times),
            NearestTruckDistanceSensor(coordinator, entry, device_id, point_name, scheduled_times),
        ]
    )


class _NtpcRubbishBaseSensor(
    CoordinatorEntity[NtpcRubbishCoordinator], SensorEntity
):
    """Shared base for all NTPC Rubbish sensors."""

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
        self.entity_id = point_entity_id("sensor", device_id, attribute)
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
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self._data
        if d is None:
            return {}
        return {
            "district": d.district,
            "route_line_name": d.route_line_name,
            "latitude": d.latitude,
            "longitude": d.longitude,
            "scheduled_time": d.scheduled_time,
            "collection_status": d.collection_status,
            "collection_status_code": d.collection_status_code,
            "car_no": d.car_no,
            "data_staleness_seconds": d.data_staleness_seconds,
            "next_collection_type": d.next_collection_type,
            "last_vehicle_update": (
                d.last_vehicle_update.isoformat() if d.last_vehicle_update else None
            ),
        }


class NearestTruckDistanceSensor(_NtpcRubbishBaseSensor):
    """Shows the straight-line distance to the nearest truck on the same route."""

    _attr_native_unit_of_measurement = "m"
    _attr_icon = "mdi:truck-outline"

    def __init__(self, coordinator, entry, device_id, point_name, scheduled_times) -> None:
        super().__init__(coordinator, entry, device_id, point_name, scheduled_times, "nearest_truck_distance")

    @property
    def native_value(self) -> float | None:
        if self._data is None:
            return None
        return self._data.nearest_truck_distance

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = super().extra_state_attributes
        if self._data:
            if self._data.nearest_truck_lat is not None:
                attrs["latitude"] = self._data.nearest_truck_lat
            if self._data.nearest_truck_lon is not None:
                attrs["longitude"] = self._data.nearest_truck_lon
        return attrs


class NextCollectionSensor(_NtpcRubbishBaseSensor):
    """Shows the scheduled collection time for the current active run."""

    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator, entry, device_id, point_name, scheduled_times) -> None:
        super().__init__(coordinator, entry, device_id, point_name, scheduled_times, "next_collection")

    @property
    def native_value(self) -> str | None:
        if self._data is None:
            return None
        return _format_relative_collection_time(self._data.scheduled_collection_time)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = super().extra_state_attributes
        if self._data:
            attrs["garbage_today"] = self._data.garbage_today
            attrs["recycling_today"] = self._data.recycling_today
            attrs["food_scraps_today"] = self._data.food_scraps_today
            attrs["scheduled_collection_at"] = (
                self._data.scheduled_collection_time.isoformat()
                if self._data.scheduled_collection_time
                else None
            )
        return attrs


class CollectionStatusSensor(_NtpcRubbishBaseSensor):
    """Shows the official NTPC collection status text for the current route."""

    _attr_icon = "mdi:truck-fast-outline"

    def __init__(self, coordinator, entry, device_id, point_name, scheduled_times) -> None:
        super().__init__(coordinator, entry, device_id, point_name, scheduled_times, "collection_status")

    @property
    def native_value(self) -> str | None:
        if self._data is None:
            return None
        return self._data.collection_status


class EtaMinutesSensor(_NtpcRubbishBaseSensor):
    """Shows the estimated arrival time of the nearest truck."""

    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator, entry, device_id, point_name, scheduled_times) -> None:
        super().__init__(coordinator, entry, device_id, point_name, scheduled_times, "eta_minutes")

    @property
    def native_value(self) -> str | None:
        if self._data is None:
            return None
        return _format_relative_collection_time(self._data.estimated_arrival_time)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = super().extra_state_attributes
        if self._data:
            attrs["estimated_arrival_at"] = (
                self._data.estimated_arrival_time.isoformat()
                if self._data.estimated_arrival_time
                else None
            )
        return attrs
