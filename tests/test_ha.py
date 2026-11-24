from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.exceptions import ServiceValidationError
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.packages_esp.const import DOMAIN
from custom_components.packages_esp.coordinator import PackagesCoordinator
from custom_components.packages_esp.diagnostics import async_get_config_entry_diagnostics
from custom_components.packages_esp.engine import Ledger
from custom_components.packages_esp.mail import Mail
from custom_components.packages_esp.parsers import DeliveryEvent
from custom_components.packages_esp.transports import AuthenticationError, TransportError


def entry():
    return MockConfigEntry(
        domain=DOMAIN,
        title="test@example.com",
        unique_id="test@example.com",
        data={"transport": "imap", "username": "test@example.com", "password": "secret"},
    )


async def test_setup_entities_actions_calendars_and_unload(hass):
    now = datetime.now(UTC)
    account = entry()
    account.add_to_hass(hass)

    async def initialize(coordinator):
        coordinator.ledger = Ledger()
        coordinator.ledger.apply(
            DeliveryEvent(
                "test",
                now.isoformat(),
                "Amazon",
                retailer="Amazon",
                orders=["ORDER1"],
                status="in_transit",
                expected_date=now.date().isoformat(),
                confidence="medium",
            )
        )
        coordinator.ledger.data["last_sync"] = now.isoformat()
        coordinator.ledger.data["initial_complete"] = True
        coordinator.connected = True
        coordinator.async_set_updated_data(coordinator.ledger)

    with patch.object(PackagesCoordinator, "initialize", initialize):
        assert await async_setup_component(hass, DOMAIN, {})
        await hass.async_block_till_done()
    states = [
        s
        for s in hass.states.async_all()
        if "packages_esp" in s.entity_id or "packages_espana" in s.entity_id
    ]
    assert len(states) == 9
    data = await hass.services.async_call(
        DOMAIN, "get_deliveries", {}, blocking=True, return_response=True
    )
    p = data["deliveries"][0]
    assert data["groups"]["today"] and not data["stale"]
    summary = await hass.services.async_call(
        DOMAIN, "get_summary", {"language": "es"}, blocking=True, return_response=True
    )
    assert "previsto" in summary["summary"]
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "set_expected_date", {"parcel_id": p["id"], "date": "invalid"}, blocking=True
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "snooze", {"parcel_id": p["id"], "until": "2020-01-01"}, blocking=True
        )
    await hass.services.async_call(DOMAIN, "mark_collected", {"parcel_id": p["id"]}, blocking=True)
    assert not account.runtime_data.ledger.records()
    diagnostics = await async_get_config_entry_diagnostics(hass, account)
    assert "secret" not in str(diagnostics) and "ORDER1" not in str(diagnostics)
    assert await hass.config_entries.async_unload(account.entry_id)


async def test_imap_flow_valid_invalid_and_duplicate(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] == "menu"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "imap"}
    )
    with patch(
        "custom_components.packages_esp.config_flow.ImapTransport.validate",
        side_effect=AuthenticationError,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": "test@example.com", "password": "bad"}
        )
    assert result["errors"]["base"] == "invalid_auth"
    with (
        patch("custom_components.packages_esp.config_flow.ImapTransport.validate"),
        patch("custom_components.packages_esp.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": "test@example.com", "password": "app password"}
        )
        await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert result["data"]["password"] == "apppassword"


async def test_coordinator_import_replay_failure_and_recovery(hass):
    account = entry()
    account.add_to_hass(hass)
    c = PackagesCoordinator(hass, account)
    c.store.async_save = AsyncMock()
    now = datetime.now(UTC)
    mail = Mail(
        "gmail:1",
        "confirmar-envio@amazon.es",
        "Dispatched: ‘Test’",
        "Order #123-1234567-1234567 Arriving today",
        now,
    )
    c.transport = AsyncMock()
    c.transport.fetch.return_value = ([mail], {"mode": "history", "history": "100"}, True)
    fired = []
    unsubscribe = hass.bus.async_listen(
        "packages_esp_delivery_changed", lambda event: fired.append(event.data)
    )
    await c._async_update_data()
    await hass.async_block_till_done()
    assert not fired and len(c.ledger.records()) == 1
    await c._async_update_data()
    assert len(c.ledger.records()) == 1
    c.transport.fetch.side_effect = TransportError("offline")
    with pytest.raises(Exception, match="retained saved deliveries"):
        await c._async_update_data()
    assert len(c.ledger.records()) == 1 and not c.connected
    c.next_attempt = None
    c.transport.fetch.side_effect = None
    delivered = Mail(
        "gmail:2", mail.sender, "Delivered: ‘Test’", mail.text, now + timedelta(minutes=1)
    )
    c.transport.fetch.return_value = ([delivered], {"mode": "history", "history": "101"}, True)
    await c._async_update_data()
    await hass.async_block_till_done()
    assert not c.ledger.records() and len(fired) == 1
    unsubscribe()


async def test_failed_save_does_not_advance_checkpoint(hass):
    c = PackagesCoordinator(hass, entry())
    c.store.async_save = AsyncMock(side_effect=OSError("disk full"))
    c.transport = AsyncMock()
    c.transport.fetch.return_value = ([], {"history": "100"}, True)
    with pytest.raises(Exception):
        await c._async_update_data()
    assert c.ledger.data["checkpoint"] == {}
