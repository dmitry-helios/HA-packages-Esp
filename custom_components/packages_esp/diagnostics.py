"""Counts only: no email, address, reference, tracking URL or credentials."""


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    ledger = coordinator.ledger
    return {
        "transport": entry.data["transport"],
        "connected": coordinator.connected,
        "initial_import_complete": ledger.data.get("initial_complete", False),
        "active_parcels": len(ledger.records()),
        "processed_messages": len(ledger.data["processed"]),
        "review_items": sum(bool(p.get("review_reason")) for p in ledger.records()),
    }
