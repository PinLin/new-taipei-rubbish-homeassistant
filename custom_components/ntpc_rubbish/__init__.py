"""New Taipei City Garbage Truck integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import entity_registry as er

from .api import NtpcRubbishApiClient
from .const import CONF_LATITUDE, CONF_LONGITUDE, DOMAIN
from .coordinator import NtpcRubbishCoordinator
from .entity import point_device_id, point_entity_id

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "binary_sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up NTPC Rubbish from a config entry."""
    session = async_get_clientsession(hass)
    client = NtpcRubbishApiClient(session)
    coordinator = NtpcRubbishCoordinator(hass, entry, client)

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await _async_migrate_entity_ids(hass, entry)

    # Reload entry when options change so coordinator picks up new settings
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    # Register manual update service once
    if not hass.services.has_service(DOMAIN, "update"):

        async def _handle_update(call: ServiceCall) -> None:
            entry_ids: list[str] = call.data.get("entry_ids", [])
            all_coordinators: dict[str, NtpcRubbishCoordinator] = hass.data.get(
                DOMAIN, {}
            )
            targets = (
                {eid: all_coordinators[eid] for eid in entry_ids if eid in all_coordinators}
                if entry_ids
                else all_coordinators
            )
            # Refresh against a snapshot so concurrent entry adds/removals do not
            # mutate the dictionary during iteration.
            for coord in list(targets.values()):
                await coord.async_request_refresh()

        hass.services.async_register(DOMAIN, "update", _handle_update)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
            hass.services.async_remove(DOMAIN, "update")
    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload entry when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_migrate_entity_ids(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Rename existing entities to stable ID-based names without pinyin."""
    registry = er.async_get(hass)
    device_id = point_device_id(
        float(entry.data.get(CONF_LATITUDE, 0)),
        float(entry.data.get(CONF_LONGITUDE, 0)),
    )
    entity_specs = [
        ("sensor", "next_collection"),
        ("sensor", "collection_status"),
        ("sensor", "eta_minutes"),
        ("sensor", "nearest_truck_distance"),
        ("binary_sensor", "garbage_today"),
        ("binary_sensor", "recycling_today"),
        ("binary_sensor", "food_scraps_today"),
        ("binary_sensor", "truck_departed"),
    ]

    registry_entries = list(registry.entities.values())
    for platform, attribute in entity_specs:
        unique_id = f"{DOMAIN}_{device_id}_{attribute}"
        target_entity_id = point_entity_id(platform, device_id, attribute)
        registry_entry = next(
            (
                entity
                for entity in registry_entries
                if entity.platform == platform
                and entity.config_entry_id == entry.entry_id
                and entity.unique_id == unique_id
            ),
            None,
        )
        if registry_entry is None or registry_entry.entity_id == target_entity_id:
            continue
        try:
            registry.async_update_entity(
                registry_entry.entity_id,
                new_entity_id=target_entity_id,
            )
            _LOGGER.info(
                "Migrated entity_id %s -> %s",
                registry_entry.entity_id,
                target_entity_id,
            )
        except ValueError:
            _LOGGER.warning(
                "Unable to migrate %s to %s because the target entity_id already exists",
                registry_entry.entity_id,
                target_entity_id,
            )
