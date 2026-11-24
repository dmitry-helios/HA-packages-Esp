"""Connection and freshness diagnostics."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.util import dt as dt_util

from .entity import PackagesEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([Connection(entry.runtime_data)])


class Connection(PackagesEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator, "connected", "Connected")

    @property
    def is_on(self):
        return self.coordinator.connected and not self.coordinator.ledger.stale(dt_util.utcnow())
