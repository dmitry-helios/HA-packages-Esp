"""Polling, durable batches and derived delivery events."""

import asyncio
import imaplib
import logging
from copy import deepcopy
from datetime import timedelta

from aiohttp import ClientError
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DOMAIN, EVENT, POLL_SECONDS
from .engine import Ledger
from .parsers import parse
from .transports import (
    AuthenticationError,
    GmailTransport,
    ImapTransport,
    TransportError,
    retry_delay,
)

LOGGER = logging.getLogger(__name__)


class PackagesCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(hass, LOGGER, name=DOMAIN, update_interval=timedelta(seconds=POLL_SECONDS))
        self.entry = entry
        self.options = dict(entry.options)
        self.store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        self.ledger = Ledger()
        self.transport = None
        self.lock = asyncio.Lock()
        self.failures = 0
        self.next_attempt = None
        self.connected = False

    @property
    def timezone(self):
        return self.hass.config.time_zone

    async def initialize(self):
        saved = await self.store.async_load()
        self.ledger = Ledger(saved)
        if self.entry.data["transport"] == "oauth":
            implementation = await config_entry_oauth2_flow.async_get_config_entry_implementation(
                self.hass, self.entry
            )
            session = config_entry_oauth2_flow.OAuth2Session(self.hass, self.entry, implementation)
            self.transport = GmailTransport(session)
        else:
            self.transport = ImapTransport(self.entry.data["username"], self.entry.data["password"])
        await self.async_refresh()
        # Keep restored records available even during outages.
        if self.data is None:
            self.async_set_updated_data(self.ledger)
        self.entry.async_on_unload(
            async_track_time_interval(self.hass, self._tick, timedelta(minutes=1))
        )

    async def _tick(self, now):
        async with self.lock:
            await self._derived_events(now)
            self.async_update_listeners()
        if self.connected and not self.ledger.data.get("initial_complete"):
            await self.async_request_refresh()

    async def _derived_events(self, now):
        if not self.ledger.data.get("initial_complete") or self.ledger.stale(now):
            return
        notified = self.ledger.data.setdefault("notified", {})
        groups = self.ledger.groups(now, self.timezone)
        local_day = dt_util.as_local(now).date().isoformat()
        dirty = False
        for kind, records in (
            ("expected_today", groups["today"]),
            ("collection_deadline", groups["pickups_ready"]),
        ):
            for parcel in records:
                if kind == "collection_deadline" and (
                    not parcel.get("pickup_deadline")
                    or parcel["pickup_deadline"]
                    > (dt_util.as_local(now).date() + timedelta(days=1)).isoformat()
                ):
                    continue
                key = f"{kind}:{parcel['id']}:{local_day}"
                if key not in notified:
                    notified[key] = now.isoformat()
                    dirty = True
                    self.emit(
                        {
                            "parcel_id": parcel["id"],
                            "change_type": kind,
                            "parcel": self.ledger.compact(parcel),
                        },
                        now,
                    )
        cutoff = (now - timedelta(days=7)).isoformat()
        self.ledger.data["notified"] = {k: v for k, v in notified.items() if v >= cutoff}
        if dirty:
            await self.store.async_save(self.ledger.data)

    def emit(self, change, now):
        parcel = self.ledger.view(self.ledger.data["parcels"][change["parcel_id"]])
        if parcel.get("snoozed_until") and dt_util.parse_datetime(parcel["snoozed_until"]) > now:
            return
        self.hass.bus.async_fire(EVENT, {"entry_id": self.entry.entry_id, **change})

    async def _async_update_data(self):
        now = dt_util.utcnow()
        if self.next_attempt and now < self.next_attempt:
            return self.ledger
        async with self.lock:
            try:
                checkpoint = self.ledger.data["checkpoint"]
                days = self.entry.options.get("import_days", 90)
                if isinstance(self.transport, ImapTransport):
                    batch, checkpoint, complete = await self.hass.async_add_executor_job(
                        self.transport.fetch, checkpoint, days
                    )
                else:
                    batch, checkpoint, complete = await self.transport.fetch(checkpoint, days)
                pending = Ledger(deepcopy(self.ledger.data))
                notify = pending.data.get("initial_complete", False)
                changes = []
                for mail in sorted(batch, key=lambda m: m.sent_at):
                    if mail.id in pending.data["processed"]:
                        continue
                    for event in parse(mail, self.timezone):
                        changes.extend(pending.apply(event))
                    pending.data["processed"][mail.id] = mail.sent_at.isoformat()
                pending.data["checkpoint"] = checkpoint
                if complete:
                    pending.data["initial_complete"] = True
                    pending.data["last_sync"] = now.isoformat()
                pending.prune(now)
                # Persist before publishing events or advancing the in-memory checkpoint.
                await self.store.async_save(pending.data)
                self.ledger = pending
                self.connected, self.failures, self.next_attempt = True, 0, None
                if notify:
                    for change in changes:
                        self.emit(change, now)
                elif complete:
                    # Seed derived notifications without announcing the historical import.
                    day = dt_util.as_local(now).date().isoformat()
                    pending.data["notified"] = {
                        f"{kind}:{p['id']}:{day}": now.isoformat()
                        for kind in ("expected_today", "collection_deadline")
                        for p in pending.records()
                    }
                    await self.store.async_save(pending.data)
                return self.ledger
            except AuthenticationError as error:
                self.connected = False
                raise ConfigEntryAuthFailed("Gmail authorization required") from error
            except (
                ClientError,
                OSError,
                TimeoutError,
                TransportError,
                imaplib.IMAP4.error,
            ) as error:
                self.connected = False
                self.failures += 1
                self.next_attempt = now + retry_delay(self.failures)
                raise UpdateFailed(
                    f"Email sync failed ({type(error).__name__}); retained saved deliveries"
                ) from error

    async def mutate(self, parcel_id, action, values):
        async with self.lock:
            if action == "clear_override":
                self.ledger.clear_override(parcel_id)
            else:
                self.ledger.override(parcel_id, values)
            await self.store.async_save(self.ledger.data)
            self.async_set_updated_data(self.ledger)
