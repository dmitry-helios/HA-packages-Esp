"""Account summary counts, never a sensor per sender or parcel."""

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.util import dt as dt_util

from .entity import PackagesEntity

NAMES = {
    "today": "Deliveries today",
    "tomorrow": "Deliveries tomorrow",
    "pickups_ready": "Pickups ready",
    "attention": "Deliveries needing attention",
    "unknown": "Deliveries with unknown dates",
}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(
        [CountSensor(coordinator, key, name) for key, name in NAMES.items()]
        + [LastSync(coordinator)]
    )


class CountSensor(PackagesEntity, SensorEntity):
    _attr_icon = "mdi:package-variant"

    def __init__(self, coordinator, key, name):
        super().__init__(coordinator, key, name)
        self.key = key

    @property
    def native_value(self):
        return len(
            self.coordinator.ledger.groups(dt_util.utcnow(), self.coordinator.timezone)[self.key]
        )

    @property
    def extra_state_attributes(self):
        ledger = self.coordinator.ledger
        records = ledger.groups(dt_util.utcnow(), self.coordinator.timezone)[self.key]
        return {
            "entry_id": self.coordinator.entry.entry_id,
            "deliveries": [ledger.compact(p) for p in records[:50]],
            "truncated": len(records) > 50,
            "stale": ledger.stale(dt_util.utcnow()),
            "initial_import": not ledger.data.get("initial_complete"),
        }


class LastSync(PackagesEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator, "last_sync", "Last successful sync")

    @property
    def native_value(self):
        value = self.coordinator.ledger.data.get("last_sync")
        return datetime.fromisoformat(value) if value else None
