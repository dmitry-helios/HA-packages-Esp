"""Packages España integration."""

from pathlib import Path

from homeassistant.components.http import StaticPathConfig

from .const import DOMAIN, PLATFORMS
from .coordinator import PackagesCoordinator
from .services import async_register_services


async def async_setup(hass, config):
    hass.data.setdefault(DOMAIN, {})
    async_register_services(hass)
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                "/packages_esp/packages-esp-card.js",
                str(Path(__file__).parent / "www" / "packages-esp-card.js"),
                False,
            )
        ]
    )
    return True


async def async_setup_entry(hass, entry):
    coordinator = PackagesCoordinator(hass, entry)
    entry.runtime_data = coordinator
    await coordinator.initialize()
    hass.data[DOMAIN][entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id, None)
        return True
    return False


async def async_reload_entry(hass, entry):
    if dict(entry.options) != entry.runtime_data.options:
        await hass.config_entries.async_reload(entry.entry_id)
