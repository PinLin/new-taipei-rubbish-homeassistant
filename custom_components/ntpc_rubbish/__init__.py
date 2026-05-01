"""New Taipei City Garbage Truck integration."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import NtpcRubbishApiClient
from .const import CONF_LATITUDE, CONF_LONGITUDE, DOMAIN, SERVICE_UPDATE
from .coordinator import NtpcRubbishCoordinator
from .entity import point_device_id

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

    if not hass.services.has_service(DOMAIN, SERVICE_UPDATE):

        async def _handle_update(call: ServiceCall) -> None:
            point_ids: list[str] = call.data.get("point_ids", [])
            for config_entry in hass.config_entries.async_entries(DOMAIN):
                point_id = point_device_id(
                    float(config_entry.data.get(CONF_LATITUDE, 0)),
                    float(config_entry.data.get(CONF_LONGITUDE, 0)),
                )
                if point_ids and point_id not in point_ids:
                    continue
                if not hasattr(config_entry, "runtime_data"):
                    continue
                await config_entry.runtime_data.async_request_refresh()

        hass.services.async_register(
            DOMAIN,
            SERVICE_UPDATE,
            _handle_update,
            schema=vol.Schema(
                {vol.Optional("point_ids", default=[]): vol.All(cv.ensure_list, [cv.string])}
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
            hass.services.async_remove(DOMAIN, SERVICE_UPDATE)
    return unload_ok
