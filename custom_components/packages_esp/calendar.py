"""Read-only calendars with stable per-parcel event IDs."""

from datetime import datetime, time
from zoneinfo import ZoneInfo

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.util import dt as dt_util

from .entity import PackagesEntity


def as_datetime(value, timezone):
    return (
        value
        if isinstance(value, datetime)
        else datetime.combine(value, time.min, ZoneInfo(timezone))
    )


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [
            PackagesCalendar(entry.runtime_data, "expected_deliveries", "Expected deliveries"),
            PackagesCalendar(entry.runtime_data, "pickup_deadlines", "Pickup deadlines"),
        ]
    )


class PackagesCalendar(PackagesEntity, CalendarEntity):
    def __init__(self, coordinator, key, name):
        super().__init__(coordinator, key, name)
        self.key = key

    def _events(self):
        return self.coordinator.ledger.calendar_events(self.key, self.coordinator.timezone)

    @property
    def event(self):
        now = dt_util.utcnow()
        upcoming = sorted(
            (e for e in self._events() if as_datetime(e["end"], self.coordinator.timezone) > now),
            key=lambda e: as_datetime(e["start"], self.coordinator.timezone),
        )
        return CalendarEvent(**upcoming[0]) if upcoming else None

    async def async_get_events(self, hass, start_date, end_date):
        return [
            CalendarEvent(**e)
            for e in self._events()
            if as_datetime(e["start"], self.coordinator.timezone) < end_date
            and as_datetime(e["end"], self.coordinator.timezone) > start_date
        ]
