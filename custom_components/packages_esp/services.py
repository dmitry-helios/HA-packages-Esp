"""Validated actions and authenticated query responses."""

from datetime import date

import voluptuous as vol
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from .const import DOMAIN


def async_register_services(hass):
    def coordinator_for(data):
        entries = hass.data.get(DOMAIN, {})
        entry_id = data.get("entry_id")
        if entry_id:
            if entry_id not in entries:
                raise ServiceValidationError("Packages account is not loaded")
            return entries[entry_id]
        if len(entries) != 1:
            raise ServiceValidationError("Specify entry_id when multiple accounts are configured")
        return next(iter(entries.values()))

    async def query(call):
        coordinator = coordinator_for(call.data)
        ledger = coordinator.ledger
        now = dt_util.utcnow()
        if call.service == "get_summary":
            return {
                "summary": ledger.summary(
                    now,
                    coordinator.timezone,
                    call.data.get("language", coordinator.entry.options.get("language", "en")),
                    call.data.get("day", "today"),
                    call.data.get("hide_items", coordinator.entry.options.get("hide_items", False)),
                ),
                "stale": ledger.stale(now),
                "last_sync": ledger.data.get("last_sync"),
            }
        parcel_id = call.data.get("parcel_id")
        if parcel_id:
            if parcel_id not in ledger.data["parcels"]:
                raise ServiceValidationError("Unknown parcel")
            parcel = ledger.data["parcels"][parcel_id]
            return {"parcel": ledger.view(parcel), "history": parcel["history"]}
        return {
            "entry_id": coordinator.entry.entry_id,
            "groups": ledger.groups(now, coordinator.timezone),
            "deliveries": ledger.records(),
            "stale": ledger.stale(now),
            "initial_import": not ledger.data.get("initial_complete"),
            "last_sync": ledger.data.get("last_sync"),
        }

    async def mutate(call):
        coordinator = coordinator_for(call.data)
        if call.service == "refresh":
            coordinator.next_attempt = None
            await coordinator.async_request_refresh()
            return
        parcel_id = call.data["parcel_id"]
        if parcel_id not in coordinator.ledger.data["parcels"]:
            raise ServiceValidationError("Unknown parcel")
        values = {}
        status_actions = {
            "mark_delivered": "delivered",
            "mark_collected": "collected",
            "ignore": "ignored",
        }
        if call.service in status_actions:
            values = {"status": status_actions[call.service]}
        elif call.service == "set_expected_date":
            try:
                expected = date.fromisoformat(call.data["date"])
            except ValueError as error:
                raise ServiceValidationError("Use an ISO date: YYYY-MM-DD") from error
            values = {
                "expected_date": expected.isoformat(),
                "expected_end": None,
                "window": None,
                "confidence": "high",
                "scheduled": False,
            }
        elif call.service == "snooze":
            until = dt_util.parse_datetime(call.data["until"])
            if until is None or until.tzinfo is None or until <= dt_util.utcnow():
                raise ServiceValidationError("Snooze requires a future timestamp with timezone")
            values = {"snoozed_until": until.isoformat()}
        await coordinator.mutate(parcel_id, call.service, values)

    account = {vol.Optional("entry_id"): str}
    hass.services.async_register(
        DOMAIN,
        "get_deliveries",
        query,
        schema=vol.Schema({**account, vol.Optional("parcel_id"): str}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "get_summary",
        query,
        schema=vol.Schema(
            {
                **account,
                vol.Optional("day", default="today"): vol.In(["today", "tomorrow"]),
                vol.Optional("language"): vol.In(["en", "es"]),
                vol.Optional("hide_items"): bool,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
    for action in (
        "refresh",
        "mark_delivered",
        "mark_collected",
        "set_expected_date",
        "ignore",
        "snooze",
        "clear_override",
    ):
        fields = dict(account)
        if action != "refresh":
            fields[vol.Required("parcel_id")] = str
        if action == "set_expected_date":
            fields[vol.Required("date")] = str
        if action == "snooze":
            fields[vol.Required("until")] = str
        hass.services.async_register(DOMAIN, action, mutate, schema=vol.Schema(fields))
