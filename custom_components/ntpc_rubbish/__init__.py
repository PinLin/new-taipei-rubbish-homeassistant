"""New Taipei City Garbage Truck integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import NtpcRubbishApiClient
from .const import DOMAIN
from .coordinator import NtpcRubbishCoordinator

PLATFORMS = ["sensor", "binary_sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up NTPC Rubbish from a config entry."""
    session = async_get_clientsession(hass)
    client = NtpcRubbishApiClient(session)
    coordinator = NtpcRubbishCoordinator(hass, entry, client)

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

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
