from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.packages_esp.calendar import PackagesCalendar
from custom_components.packages_esp.coordinator import PackagesCoordinator
from custom_components.packages_esp.engine import Ledger
from custom_components.packages_esp.mail import Mail
from custom_components.packages_esp.parsers import DeliveryEvent, parse


def test_same_day_courier_update_preserves_booked_window():
    ledger = Ledger()
    ledger.apply(
        DeliveryEvent(
            "1",
            "2026-11-16T09:00:00+00:00",
            "Amazon",
            retailer="Amazon",
            orders=["1"],
            expected_date="2026-11-17",
            window=["08:00", "10:00"],
            confidence="high",
            scheduled=True,
        )
    )
    ledger.apply(
        DeliveryEvent(
            "2",
            "2026-11-17T07:00:00+00:00",
            "Amazon",
            retailer="Amazon",
            orders=["1"],
            expected_date="2026-11-17",
            status="out_for_delivery",
            confidence="high",
        )
    )
    assert ledger.records()[0]["window"] == ["08:00", "10:00"]
    ledger.apply(
        DeliveryEvent(
            "3",
            "2026-11-17T08:00:00+00:00",
            "Amazon",
            retailer="Amazon",
            orders=["1"],
            expected_date="2026-11-18",
            confidence="medium",
        )
    )
    assert ledger.records()[0]["window"] is None


def test_retailer_references_in_table_layouts():
    for sender, subject, body, reference in [
        (
            "service@s.rituals.com",
            "Confirmación del pedido",
            "Resumen del pedido (¡has elegido bien!) 1 producto #euw15656000000",
            "EUW15656000000",
        ),
        (
            "spain@thomann.de",
            "Shipping confirmation and invoice",
            "Order number Order type Order date 202646.000001 Order 13.11.2026",
            "202646.000001",
        ),
    ]:
        event = parse(Mail("1", sender, subject, body, datetime.now(UTC)), "Europe/Madrid")[0]
        assert reference in event.orders


def test_shared_parcel_absorbs_second_order_placeholder():
    ledger = Ledger()
    for n in (1, 2):
        ledger.apply(
            DeliveryEvent(
                str(n),
                "2026-11-16T09:00:00+00:00",
                "Temu",
                retailer="Temu",
                orders=[f"ORDER{n}"],
                status="ordered",
            )
        )
    for n in (1, 2):
        ledger.apply(
            DeliveryEvent(
                str(n + 2),
                "2026-11-16T10:00:00+00:00",
                "Temu",
                retailer="Temu",
                orders=[f"ORDER{n}"],
                aliases=["tracking:SHARED"],
                status="in_transit",
            )
        )
    assert len(ledger.records()) == 1
    assert ledger.records()[0]["orders"] == ["ORDER1", "ORDER2"]


def test_receipt_does_not_create_delivery_and_partial_cancellation_does_not_close_it():
    receipt = Mail(
        "1",
        "no-reply-online@mercadona.es",
        "Your Mercadona receipt",
        "Order #12345678 Payment fulfilled",
        datetime.now(UTC),
    )
    assert parse(receipt, "Europe/Madrid") == []
    cancel = Mail(
        "2",
        "order-update@amazon.es",
        "Item cancelled successfully: Test",
        "Order #123-1234567-1234567",
        datetime.now(UTC),
    )
    result = parse(cancel, "Europe/Madrid")[0]
    assert result.status is None and result.review_reason == "item_change"


def test_sending_tracking_and_compact_range():
    mail = Mail(
        "1",
        "temu@orders.temu.com",
        "Order shipped",
        "Order ID: PO-186-12345678901234567 The Sending tracking number is 957140000001. Estimated delivery: November 17–20",
        datetime(2026, 11, 16, tzinfo=UTC),
    )
    result = parse(mail, "Europe/Madrid")[0]
    assert result.aliases == ["tracking:957140000001"]
    assert (result.expected_date, result.expected_end) == ("2026-11-17", "2026-11-20")


async def test_calendar_window_dst_and_rescheduling(hass):
    account = MockConfigEntry(domain="packages_esp", data={})
    c = PackagesCoordinator(hass, account)
    await hass.config.async_set_time_zone("Europe/Madrid")
    c.ledger.apply(
        DeliveryEvent(
            "1",
            "2026-10-24T09:00:00+00:00",
            "Mercadona",
            retailer="Mercadona",
            orders=["12345678"],
            status="ordered",
            expected_date="2026-10-25",
            confidence="high",
            window=["08:00", "10:00"],
            scheduled=True,
        )
    )
    entity = PackagesCalendar(c, "expected_deliveries", "Expected deliveries")
    events = await entity.async_get_events(
        hass, datetime(2026, 10, 25, tzinfo=UTC), datetime(2026, 10, 26, tzinfo=UTC)
    )
    assert len(events) == 1
    assert events[0].start.utcoffset() == timedelta(hours=1)
    assert events[0].end.hour == 10
    assert not await entity.async_get_events(
        hass, datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 11, 2, tzinfo=UTC)
    )


async def test_derived_events_are_deduplicated_and_suppressed_when_stale(hass):
    account = MockConfigEntry(domain="packages_esp", data={})
    c = PackagesCoordinator(hass, account)
    now = datetime.now(UTC)
    c.ledger.apply(
        DeliveryEvent(
            "1",
            now.isoformat(),
            "Amazon",
            retailer="Amazon",
            orders=["123"],
            status="in_transit",
            expected_date=now.date().isoformat(),
            confidence="medium",
        )
    )
    c.ledger.data.update(initial_complete=True, last_sync=now.isoformat())
    c.store.async_save = AsyncMock()
    events = []
    unsub = hass.bus.async_listen("packages_esp_delivery_changed", lambda e: events.append(e.data))
    await c._derived_events(now)
    await c._derived_events(now)
    await hass.async_block_till_done()
    assert len(events) == 1 and events[0]["change_type"] == "expected_today"
    c.ledger.data["notified"] = {}
    await c._derived_events(now + timedelta(hours=1))
    await hass.async_block_till_done()
    assert len(events) == 1
    unsub()
