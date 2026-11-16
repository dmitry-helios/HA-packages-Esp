from copy import deepcopy
from datetime import UTC, datetime, timedelta

from custom_components.packages_esp.engine import Ledger
from custom_components.packages_esp.parsers import DeliveryEvent

NOW = datetime(2026, 11, 16, 9, tzinfo=UTC)


def event(id="1", **kwargs):
    return DeliveryEvent(
        message_id=id, at=NOW.isoformat(), source="Amazon", retailer="Amazon", **kwargs
    )


def test_dedup_split_orders_and_shared_parcels():
    ledger = Ledger()
    initial = event(orders=["ORDER1"], status="ordered")
    ledger.apply(initial)
    assert ledger.apply(initial) == []
    ledger.apply(event("2", orders=["ORDER1"], aliases=["tracking:A"], status="in_transit"))
    ledger.apply(event("3", orders=["ORDER1"], aliases=["tracking:B"], status="in_transit"))
    assert len(ledger.records()) == 2
    ledger.apply(event("4", orders=["ORDER2"], aliases=["tracking:B"], status="in_transit"))
    assert len(ledger.records()) == 2
    assert any(p["orders"] == ["ORDER1", "ORDER2"] for p in ledger.records())


def test_courier_alias_bridge_and_restart():
    ledger = Ledger()
    ledger.apply(event(aliases=["tracking:DHL1"], status="in_transit"))
    ledger = Ledger(deepcopy(ledger.data))
    ledger.apply(event("2", aliases=["tracking:CTT1", "tracking:DHL1"], status="out_for_delivery"))
    assert len(ledger.records()) == 1
    assert len(ledger.records()[0]["aliases"]) == 2


def test_late_messages_do_not_regress_delivered_or_eta():
    ledger = Ledger()
    ledger.apply(
        event(
            orders=["ORDER1"], status="delivered", expected_date="2026-11-18", confidence="medium"
        )
    )
    old = event(
        "2", orders=["ORDER1"], status="in_transit", expected_date="2026-11-17", confidence="medium"
    )
    old.at = (NOW - timedelta(days=1)).isoformat()
    ledger.apply(old)
    p = ledger.records(True)[0]
    assert p["status"] == "delivered"
    assert p["expected_date"] == "2026-11-18"


def test_conflicting_dates_and_manual_corrections():
    ledger = Ledger()
    ledger.apply(event(orders=["ORDER1"], expected_date="2026-11-16", confidence="medium"))
    ledger.apply(event("2", orders=["ORDER1"], expected_date="2026-11-17", confidence="medium"))
    p = ledger.records()[0]
    assert p["review_reason"] == "conflicting_dates"
    ledger.override(p["id"], {"expected_date": "2026-11-20"})
    restored = Ledger(deepcopy(ledger.data))
    assert restored.records()[0]["expected_date"] == "2026-11-20"
    restored.clear_override(p["id"])
    assert restored.records()[0]["expected_date"] == "2026-11-16"


def test_expired_window_is_unconfirmed_not_delivered():
    ledger = Ledger()
    ledger.apply(
        event(
            orders=["ORDER1"],
            status="ordered",
            expected_date="2026-11-16",
            window=["08:00", "09:00"],
            confidence="high",
        )
    )
    groups = ledger.groups(NOW, "Europe/Madrid")
    assert not groups["today"]
    assert groups["attention"][0]["status"] == "ordered"


def test_pickup_arrival_is_not_ready_and_deadline_not_completion():
    ledger = Ledger()
    ledger.apply(
        event(
            orders=["ORDER1"],
            status="in_transit",
            expected_date="2026-11-16",
            confidence="medium",
            destination_type="pickup",
        )
    )
    assert not ledger.groups(NOW, "Europe/Madrid")["pickups_ready"]
    assert "not yet ready" in ledger.summary(NOW, "Europe/Madrid")
    ledger.apply(
        event("2", orders=["ORDER1"], status="ready_for_pickup", pickup_deadline="2026-11-15")
    )
    groups = ledger.groups(NOW, "Europe/Madrid")
    assert groups["attention"] and groups["pickups_ready"]


def test_midnight_dst_low_confidence_and_calendar_ids():
    ledger = Ledger()
    ledger.apply(
        event(
            orders=["ORDER1"], status="in_transit", expected_date="2026-11-17", confidence="medium"
        )
    )
    assert len(ledger.groups(NOW, "Europe/Madrid")["tomorrow"]) == 1
    assert len(ledger.groups(NOW.replace(hour=23), "Europe/Madrid")["today"]) == 1
    before = ledger.calendar_events("expected_deliveries", "Europe/Madrid")[0]
    p = ledger.records()[0]
    ledger.override(p["id"], {"expected_date": "2026-11-18"})
    assert ledger.calendar_events("expected_deliveries", "Europe/Madrid")[0]["uid"] == before["uid"]
    ledger.override(p["id"], {"confidence": "low"})
    assert not ledger.calendar_events("expected_deliveries", "Europe/Madrid")


def test_summary_snooze_staleness_and_prune():
    ledger = Ledger()
    ledger.apply(
        event(
            orders=["ORDER1"],
            status="out_for_delivery",
            expected_date="2026-11-16",
            confidence="high",
        )
    )
    assert "out of date" in ledger.summary(NOW, "Europe/Madrid")
    ledger.data["last_sync"] = NOW.isoformat()
    p = ledger.records()[0]
    ledger.override(p["id"], {"snoozed_until": (NOW + timedelta(hours=1)).isoformat()})
    assert "Amazon" not in ledger.summary(NOW, "Europe/Madrid")
    ledger.prune(NOW + timedelta(days=100))
    assert len(ledger.records()) == 1
    ledger.override(p["id"], {"status": "collected"})
    ledger.prune(NOW + timedelta(days=100))
    assert not ledger.records(True)
