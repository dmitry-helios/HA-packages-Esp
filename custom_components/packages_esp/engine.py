"""Persistent delivery ledger, independent of Home Assistant and network access."""

from copy import deepcopy
from datetime import date, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from .const import GROUPS, RETENTION_DAYS, STALE_SECONDS, TERMINAL
from .parsers import DeliveryEvent


class Ledger:
    def __init__(self, data=None):
        self.data = data or {"parcels": {}, "processed": {}, "checkpoint": {}, "last_sync": None}
        self.data.setdefault("initial_complete", False)

    def apply(self, event: DeliveryEvent) -> list[dict]:
        if event.message_id in self.data["processed"]:
            return []
        changes = []
        parcels = self.data["parcels"]
        exact = [p for p in parcels.values() if set(p["aliases"]) & set(event.aliases)]
        order_matches = [
            p
            for p in parcels.values()
            if p["retailer"] == event.retailer and set(p["orders"]) & set(event.orders)
        ]
        if exact:
            targets = exact[:1]
            # Explicit alias bridges can safely merge records (e.g. DHL -> CTT).
            duplicates = exact[1:] + [
                p for p in order_matches if not p["aliases"] and p not in exact
            ]
            for duplicate in duplicates:
                target = targets[0]
                if duplicate.get("overrides") and target.get("overrides") != duplicate["overrides"]:
                    target["review_reason"] = "conflicting_manual_records"
                    continue
                target["orders"] = sorted(set(target["orders"] + duplicate["orders"]))
                target["aliases"] = sorted(set(target["aliases"] + duplicate["aliases"]))
                target["history"] += duplicate["history"]
                target["overrides"].update(duplicate.get("overrides", {}))
                for key, timestamp in duplicate["field_times"].items():
                    previous = target["field_times"].get(key)
                    if previous is None or datetime.fromisoformat(
                        timestamp
                    ) > datetime.fromisoformat(previous):
                        target[key] = duplicate[key]
                        target["field_times"][key] = timestamp
                        if key == "expected_date":
                            for related in ("expected_end", "window", "confidence", "scheduled"):
                                target[related] = duplicate[related]
                del parcels[duplicate["id"]]
        elif event.aliases:
            provisional = [
                p
                for p in order_matches
                if not p["aliases"] and self.view(p)["status"] not in TERMINAL
            ]
            targets = provisional[:1]
        elif len(order_matches) == 1:
            targets = order_matches
        elif len(order_matches) > 1:
            # An order-only notification cannot identify which split parcel changed.
            if event.status in {"ordered", None} and not event.review_reason:
                self.data["processed"][event.message_id] = event.at
                return []
            event.review_reason = "ambiguous_split_order"
            event.parsing_certainty = "low"
            event.status = None
            targets = []
        else:
            targets = []
        if not targets:
            parcel_id = uuid4().hex
            parcel = {
                "id": parcel_id,
                "orders": [],
                "aliases": [],
                "history": [],
                "overrides": {},
                "retailer": event.retailer or event.source,
                "carrier": event.carrier,
                "description": None,
                "status": "unknown",
                "expected_date": None,
                "expected_end": None,
                "window": None,
                "confidence": "unknown",
                "parsing_certainty": "high",
                "destination_type": "home",
                "pickup_deadline": None,
                "pickup_location": None,
                "tracking_url": None,
                "source_url": None,
                "review_reason": None,
                "scheduled": False,
                "updated_at": event.at,
                "field_times": {},
            }
            parcels[parcel_id] = parcel
            targets = [parcel]
        for parcel in targets:
            before = self.view(parcel)
            parcel["orders"] = sorted(set(parcel["orders"] + event.orders))
            parcel["aliases"] = sorted(set(parcel["aliases"] + event.aliases))
            # Keep extracted facts only, not raw mail.
            parcel["history"].append(event.to_dict())
            parcel["history"] = sorted(
                parcel["history"], key=lambda e: datetime.fromisoformat(e["at"])
            )[-100:]
            for key in (
                "status",
                "expected_date",
                "pickup_deadline",
                "pickup_location",
                "description",
                "carrier",
                "destination_type",
                "tracking_url",
                "source_url",
                "review_reason",
            ):
                value = getattr(event, key)
                if value is None:
                    continue
                old_time = parcel["field_times"].get(key)
                if old_time and datetime.fromisoformat(event.at) < datetime.fromisoformat(old_time):
                    continue
                if key == "status" and parcel["status"] in TERMINAL and value not in TERMINAL:
                    continue
                if key == "status" and value == "ordered" and parcel["status"] != "unknown":
                    continue
                if key == "expected_date" and old_time == event.at and parcel[key] != value:
                    parcel["review_reason"] = "conflicting_dates"
                    parcel["confidence"] = "low"
                    continue
                if key in parcel["overrides"] and parcel["overrides"][key] != value:
                    parcel["review_reason"] = "manual_conflict"
                parcel[key] = value
                parcel["field_times"][key] = event.at
                if key == "expected_date":
                    parcel.update(
                        expected_end=event.expected_end,
                        window=event.window,
                        confidence=event.confidence,
                        scheduled=event.scheduled,
                    )
            if datetime.fromisoformat(event.at) >= datetime.fromisoformat(parcel["updated_at"]):
                parcel["updated_at"] = event.at
                parcel["parsing_certainty"] = event.parsing_certainty
            after = self.view(parcel)
            if before != after:
                change = "status_changed" if before["status"] != after["status"] else "updated"
                if before["expected_date"] != after["expected_date"]:
                    change = "date_changed"
                changes.append(
                    {
                        "parcel_id": parcel["id"],
                        "change_type": change,
                        "parcel": self.compact(after),
                    }
                )
        self.data["processed"][event.message_id] = event.at
        return changes

    @staticmethod
    def view(parcel):
        result = {
            k: deepcopy(v)
            for k, v in parcel.items()
            if k not in {"history", "overrides", "field_times"}
        }
        result.update(parcel.get("overrides", {}))
        return result

    @staticmethod
    def compact(parcel):
        keys = (
            "id",
            "retailer",
            "description",
            "carrier",
            "status",
            "expected_date",
            "expected_end",
            "window",
            "confidence",
            "destination_type",
            "pickup_deadline",
            "updated_at",
            "scheduled",
            "review_reason",
        )
        return {k: parcel.get(k) for k in keys}

    def records(self, include_completed=False):
        records = [self.view(p) for p in self.data["parcels"].values()]
        return sorted(
            (p for p in records if include_completed or p["status"] not in TERMINAL),
            key=lambda p: (p["expected_date"] or "9999", p["id"]),
        )

    def groups(self, now: datetime, timezone: str):
        local = now.astimezone(ZoneInfo(timezone))
        today = local.date().isoformat()
        tomorrow = (local.date() + timedelta(days=1)).isoformat()
        groups = {key: [] for key in GROUPS}
        for p in self.records():
            deadline = p.get("pickup_deadline")
            expected = p.get("expected_date")
            end = p.get("expected_end") or expected
            overdue = bool(end and end < today)
            if end == today and p.get("window"):
                overdue = p["window"][1] < local.strftime("%H:%M")
            attention = p.get("review_reason") or p["status"] in {
                "delayed",
                "delivery_attempted",
                "returning",
            }
            if p["status"] == "ready_for_pickup":
                groups["pickups_ready"].append(p)
                attention = attention or (deadline and deadline <= tomorrow)
            else:
                attention = attention or overdue
                if not expected:
                    groups["unknown"].append(p)
                elif p["confidence"] in {"high", "medium"} and not p.get("review_reason"):
                    if expected <= today <= end and not overdue and not attention:
                        groups["today"].append(p)
                    if expected <= tomorrow <= end and not attention:
                        groups["tomorrow"].append(p)
                    if expected > tomorrow:
                        groups["upcoming"].append(p)
                else:
                    groups["upcoming"].append(p)
            if attention:
                groups["attention"].append(p)
        return groups

    def stale(self, now):
        last = self.data.get("last_sync")
        return not last or (now - datetime.fromisoformat(last)).total_seconds() > STALE_SECONDS

    def override(self, parcel_id, values):
        parcel = self.data["parcels"][parcel_id]
        parcel["overrides"].update(values)

    def clear_override(self, parcel_id):
        parcel = self.data["parcels"][parcel_id]
        parcel["overrides"] = {}
        if parcel.get("review_reason") == "manual_conflict":
            parcel["review_reason"] = None

    def prune(self, now):
        cutoff = now - timedelta(days=RETENTION_DAYS)
        self.data["parcels"] = {
            k: p
            for k, p in self.data["parcels"].items()
            if self.view(p)["status"] not in TERMINAL
            or datetime.fromisoformat(p["updated_at"]) >= cutoff
        }
        # Longer than import window, so recovery rescans do not resurrect old completions.
        self.data["processed"] = {
            k: v
            for k, v in self.data["processed"].items()
            if datetime.fromisoformat(v) >= now - timedelta(days=180)
        }

    def summary(self, now, timezone, language="en", day="today", hide_items=False):
        groups = self.groups(now, timezone)
        spanish = language == "es"
        sentences = []
        for p in groups[day] + groups["pickups_ready"]:
            if p.get("snoozed_until") and datetime.fromisoformat(p["snoozed_until"]) > now:
                continue
            name = p["retailer"]
            if p.get("description") and not hide_items:
                name += f" ({p['description']})"
            if p["status"] == "ready_for_pickup":
                text = f"{name}: listo para recoger" if spanish else f"{name}: ready to collect"
                if p.get("pickup_deadline"):
                    text += ("; recoger antes del " if spanish else "; collect by ") + p[
                        "pickup_deadline"
                    ]
            else:
                when = ("hoy" if day == "today" else "mañana") if spanish else day
                verb = (
                    ("programado" if p.get("scheduled") else "previsto")
                    if spanish
                    else ("scheduled" if p.get("scheduled") else "expected")
                )
                text = f"{name}: {verb} {when}"
                if p["destination_type"] == "pickup":
                    text += (
                        "; llegada al punto de recogida, aún no disponible"
                        if spanish
                        else "; arrival at pickup point, not yet ready"
                    )
                if p.get("window"):
                    text += " " + "–".join(p["window"])
                if p.get("expected_end"):
                    text += (
                        (" (intervalo " if spanish else " (range ")
                        + p["expected_date"]
                        + "–"
                        + p["expected_end"]
                        + ")"
                    )
            sentences.append(text + ".")
        if not sentences:
            sentences.append(
                "No hay entregas previstas ni recogidas pendientes."
                if spanish
                else "No expected deliveries or ready pickups."
            )
        if groups["attention"]:
            sentences.append(
                f"{len(groups['attention'])} "
                + ("envíos requieren atención." if spanish else "deliveries need attention.")
            )
        if self.stale(now):
            sentences.insert(
                0,
                "La información puede estar desactualizada."
                if spanish
                else "Delivery information may be out of date.",
            )
        return " ".join(sentences)

    def calendar_events(self, kind, timezone):
        result = []
        tz = ZoneInfo(timezone)
        for p in self.records():
            value = (
                p.get("pickup_deadline") if kind == "pickup_deadlines" else p.get("expected_date")
            )
            if not value or (
                kind != "pickup_deadlines"
                and (
                    p["status"] == "ready_for_pickup"
                    or p["confidence"] not in {"high", "medium"}
                    or p.get("review_reason")
                )
            ):
                continue
            start = date.fromisoformat(value)
            end = start + timedelta(days=1)
            if kind != "pickup_deadlines":
                if p.get("expected_end"):
                    end = date.fromisoformat(p["expected_end"]) + timedelta(days=1)
                elif p.get("window"):
                    start = datetime.combine(start, time.fromisoformat(p["window"][0]), tz)
                    end = datetime.combine(start.date(), time.fromisoformat(p["window"][1]), tz)
                    if end <= start:
                        end += timedelta(days=1)
            label = (
                "Collect by"
                if kind == "pickup_deadlines"
                else "Scheduled"
                if p.get("scheduled")
                else "Expected"
            )
            result.append(
                {
                    "uid": f"{p['id']}:{kind}",
                    "start": start,
                    "end": end,
                    "summary": f"{label}: {p['retailer']}",
                    "description": p.get("description") or p["status"],
                }
            )
        return result
