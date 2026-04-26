"""New Taipei City Garbage Truck integration."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
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

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        raise ConfigEntryNotReady(f"First refresh failed: {err}") from err

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload entry when options change so coordinator picks up new settings
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    # Register manual update service once
    if not hass.services.has_service(DOMAIN, "update"):

        async def _handle_update(call: ServiceCall) -> None:
            entry_ids: list[str] = call.data.get("entry_ids", [])
            for cfg in hass.config_entries.async_entries(DOMAIN):
                if entry_ids and cfg.entry_id not in entry_ids:
                    continue
                if not hasattr(cfg, "runtime_data"):
                    continue
                await cfg.runtime_data.async_request_refresh()

        hass.services.async_register(
            DOMAIN,
            "update",
            _handle_update,
            schema=vol.Schema(
                {vol.Optional("entry_ids", default=[]): vol.All(cv.ensure_list, [cv.string])}
            ),
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        remaining = [
            e for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id != entry.entry_id
        ]
        if not remaining:
            hass.services.async_remove(DOMAIN, "update")
    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload entry when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)
