from datetime import UTC, datetime
from unittest.mock import patch

from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.packages_esp.const import DOMAIN
from custom_components.packages_esp.mail import Mail


async def test_install_sync_persist_reload_and_unload(hass, hass_storage):
    """Real HA lifecycle; only the remote IMAP server is replaced."""
    account = MockConfigEntry(
        domain=DOMAIN,
        title="Synthetic",
        unique_id="synthetic@example.com",
        data={
            "transport": "imap",
            "username": "synthetic@example.com",
            "password": "synthetic-password",
        },
    )
    account.add_to_hass(hass)
    now = datetime.now(UTC)
    mail = Mail(
        "gmail:aabb",
        "confirmar-envio@amazon.es",
        "Dispatched: ‘Test order’",
        "Order #123-1234567-1234567 Arriving today",
        now,
    )
    with patch(
        "custom_components.packages_esp.transports.ImapTransport.fetch",
        return_value=([mail], {"validity": "1", "uid": 1}, True),
    ):
        assert await async_setup_component(hass, DOMAIN, {})
        await hass.async_block_till_done()
        assert account.runtime_data.connected
        assert len(account.runtime_data.ledger.records()) == 1
        parcel_id = account.runtime_data.ledger.records()[0]["id"]
        await hass.services.async_call(
            DOMAIN,
            "set_expected_date",
            {"parcel_id": parcel_id, "date": "2026-12-01"},
            blocking=True,
        )
        assert await hass.config_entries.async_reload(account.entry_id)
        await hass.async_block_till_done()
        assert account.runtime_data.ledger.records()[0]["id"] == parcel_id
        assert account.runtime_data.ledger.records()[0]["expected_date"] == "2026-12-01"
        assert len(account.runtime_data.ledger.data["processed"]) == 1
        assert await hass.config_entries.async_unload(account.entry_id)


async def test_imap_reauthentication(hass):
    account = MockConfigEntry(
        domain=DOMAIN,
        title="Synthetic",
        unique_id="synthetic@example.com",
        data={"transport": "imap", "username": "synthetic@example.com", "password": "old-password"},
    )
    account.add_to_hass(hass)
    flow = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "reauth", "entry_id": account.entry_id}, data=account.data
    )
    flow = await hass.config_entries.flow.async_configure(flow["flow_id"], {})
    assert flow["step_id"] == "imap"
    with (
        patch("custom_components.packages_esp.transports.ImapTransport.validate"),
        patch("custom_components.packages_esp.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            flow["flow_id"], {"username": "synthetic@example.com", "password": "new-password"}
        )
        await hass.async_block_till_done()
    assert result["type"] == "abort" and result["reason"] == "reauth_successful"
    assert account.data["password"] == "new-password"
