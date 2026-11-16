"""Conservative, local extraction for supported transactional email families."""

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from .mail import Mail

SENDERS = {
    "amazon.es": "Amazon",
    "mercadona.es": "Mercadona",
    "mail.mercadona.com": "Mercadona",
    "orders.temu.com": "Temu",
    "leroymerlin.es": "Leroy Merlin",
    "jysk.com": "JYSK",
    "thomann.de": "Thomann",
    "druni.es": "DRUNI",
    "lillydoo.com": "LILLYDOO",
    "s.rituals.com": "Rituals",
    "info.tous.com": "TOUS",
    "dami3c.com": "Dami3C",
    "moisland.com": "moisland",
    "cttexpress.org": "CTT Express",
    "dhl.com": "DHL",
    "ups.com": "UPS",
    "mail.seur.info": "SEUR",
    "network1.pickup-services.com": "SEUR",
    "tip-sa.com": "TIPSA",
    "service.ecoscooting.com": "Ecoscooting",
    "correos.com": "Correos",
}
SHOPIFY = {"store+27536556093": "Dami3C", "store+65085210875": "Lonely Planet"}
CARRIERS = {"CTT Express", "DHL", "UPS", "SEUR", "TIPSA", "Ecoscooting", "Correos"}
MONTHS = {
    "january": 1,
    "enero": 1,
    "jan": 1,
    "february": 2,
    "febrero": 2,
    "feb": 2,
    "march": 3,
    "marzo": 3,
    "mar": 3,
    "april": 4,
    "abril": 4,
    "apr": 4,
    "abr": 4,
    "may": 5,
    "mayo": 5,
    "june": 6,
    "junio": 6,
    "jun": 6,
    "july": 7,
    "julio": 7,
    "jul": 7,
    "august": 8,
    "agosto": 8,
    "aug": 8,
    "ago": 8,
    "september": 9,
    "septiembre": 9,
    "sept": 9,
    "sep": 9,
    "october": 10,
    "octubre": 10,
    "oct": 10,
    "november": 11,
    "noviembre": 11,
    "nov": 11,
    "december": 12,
    "diciembre": 12,
    "dec": 12,
    "dic": 12,
}
WEEKDAYS = "monday|tuesday|wednesday|thursday|friday|saturday|sunday|lunes|martes|miercoles|jueves|viernes|sabado|domingo"


def fold(value: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", value.lower()) if not unicodedata.combining(c)
    )


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


@dataclass
class DeliveryEvent:
    message_id: str
    at: str
    source: str
    retailer: str | None = None
    carrier: str | None = None
    orders: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    status: str | None = None
    expected_date: str | None = None
    expected_end: str | None = None
    window: list[str] | None = None
    confidence: str = "unknown"
    parsing_certainty: str = "high"
    destination_type: str | None = None
    pickup_deadline: str | None = None
    pickup_location: str | None = None
    description: str | None = None
    tracking_url: str | None = None
    source_url: str | None = None
    review_reason: str | None = None
    scheduled: bool = False

    def to_dict(self):
        return asdict(self)


def date_from_text(text: str, reference: date) -> date | None:
    """Only parse within an already identified delivery-related clause."""
    text = fold(text)
    if re.search(r"\b(today|hoy)\b", text):
        return reference
    if re.search(r"\b(tomorrow|manana)\b", text):
        return reference + timedelta(days=1)
    match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    try:
        if match:
            return date(*map(int, match.groups()))
        match = re.search(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b", text)
        if match:
            day, month, year = map(int, match.groups())
            return date(year, month, day)
        months = "|".join(sorted(MONTHS, key=len, reverse=True))
        match = re.search(
            rf"\b(\d{{1,2}})\s+(?:de\s+)?({months})\b(?:\s*,?\s*(?:de\s+)?(\d{{4}}))?", text
        )
        if match:
            day, month, year = match.groups()
        else:
            match = re.search(
                rf"\b({months})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?:,?\s+(\d{{4}}))?", text
            )
            if match:
                month, day, year = match.groups()
            else:
                # Mercadona omits month/year: Delivery Friday 13 from 08:00 to 10:00.
                match = re.search(rf"\b({WEEKDAYS})\s+(\d{{1,2}})\b", text)
                if not match:
                    return None
                day = int(match[2])
                for offset in range(0, 45):
                    candidate = reference + timedelta(days=offset)
                    if candidate.day == day:
                        return candidate
                return None
        result = date(int(year or reference.year), MONTHS[month], int(day))
        if not year and result < reference - timedelta(days=180):
            result = result.replace(year=result.year + 1)
        return result
    except ValueError:
        return None


def sender_family(sender: str) -> str | None:
    local, _, domain = sender.lower().rpartition("@")
    if domain == "t.shopifyemail.com":
        return SHOPIFY.get(local, "Shopify store")
    for suffix, family in SENDERS.items():
        if domain == suffix or domain.endswith("." + suffix):
            return family
    return None


def parse(mail: Mail, timezone: str) -> list[DeliveryEvent]:
    family = sender_family(mail.sender)
    subject = fold(mail.subject)
    body = clean(mail.text)
    text = fold(body)
    combined = subject + " " + text
    if not family:
        return []
    if re.search(
        r"review|rate your|resena|newsletter|bienvenido|welcome|oferta|offer|descuento|% off",
        subject,
    ):
        return []
    if not re.search(
        r"order|pedido|envio|delivery|delivered|shipment|shipping|parcel|paquete|paket|pick.?up|recog|entrega|receipt|factura",
        combined,
    ):
        return []
    event = DeliveryEvent(
        mail.id,
        mail.sent_at.isoformat(),
        family,
        retailer=None if family in CARRIERS else family,
        carrier=family if family in CARRIERS else None,
        source_url=mail.source_url,
    )
    # Use the subject for status first: Amazon's body includes every progress-bar label.
    status_patterns = [
        ("returned", r"returned to sender|devuelto al remitente|no longer available for pick.up"),
        ("returning", r"returning to sender|devolviendo al remitente"),
        ("collected", r"picked up|collected|has recogido|recogido correctamente"),
        (
            "delivery_attempted",
            r"no hemos podido|could not deliver|delivery attempt|intentado entregar",
        ),
        (
            "ready_for_pickup",
            r"ready for pick.up|waiting for pick.up|listo para recoger|disponible para.*recogida|ha llegado al punto|arrived at the pickup|llego a la ubicacion de recogida|entregado en tu punto",
        ),
        (
            "delivered",
            r"^delivered:|ha sido entregado|hemos entregado|order delivered|pedido.*se ha entregado|aviso de entrega de|your order was delivered|your shipment.*delivered",
        ),
        ("cancelled", r"item cancelled|order.*cancelled|pedido.*cancelado|pedido.*cancelacion"),
        ("delayed", r"delayed|retrasad|demorad"),
        ("out_for_delivery", r"out for delivery|en reparto|sera entregado hoy"),
        (
            "in_transit",
            r"dispatched|shipped|shipping confirmation|on the way|en camino|en transito|ha sido enviado|ya fue enviado|transferred|transferido|paket kommt bald",
        ),
        (
            "ordered",
            r"ordered:|confirmacion.*pedido|order.*confirm|confirmed order|pedido.*confirmado|gracias por tu pedido|your order with",
        ),
    ]
    for candidate in (subject, text):
        for status, pattern in status_patterns:
            if re.search(pattern, candidate):
                event.status = status
                break
        if event.status:
            break
    # Refund and return-request mail must not close a whole incoming order.
    if re.search(
        r"refund|reembols|solicitud de devolucion|solicito la devolucion|item cancelled", subject
    ):
        event.status = None
        event.review_reason = "item_change"
    if re.search(r"receipt|factura", subject) and not re.search(r"shipping confirmation", subject):
        event.status = None
    if family == "Amazon":
        event.orders = sorted(set(re.findall(r"\b\d{3}-\d{7}-\d{7}\b", combined)))
        title = re.search(r"[‘\"](.+?)[’\"]", mail.subject)
        event.description = title[1][:100] if title else None
    else:
        patterns = [
            r"\bPO-\d+-\d+",
            r"(?:order|pedido)(?:\s+(?:number|id|n[uú]mero|n[º°]|n[º°] de pedido|es|#|no\.?|:))*\s*[#:]?\s*([A-Z0-9][A-Z0-9.-]{4,})",
        ]
        found = re.findall(patterns[0], body + " " + mail.subject, re.I)
        found += re.findall(patterns[1], body + " " + mail.subject, re.I)
        event.orders = sorted({v.upper().rstrip(".") for v in found if re.search(r"\d", v)})
    # URLs are evidence only, never fetched by a parser.
    for link in mail.links:
        parsed = urlparse(link)
        query = parse_qs(parsed.query)
        if (
            family == "Amazon"
            and parsed.hostname
            and (parsed.hostname == "amazon.es" or parsed.hostname.endswith(".amazon.es"))
        ):
            event.orders += [v for v in query.get("orderId", []) if v not in event.orders]
            event.aliases += [f"amazon:{v}" for v in query.get("shipmentId", [])]
        if re.search(r"track|seguimiento|progress-tracker|localizador", link, re.I):
            event.tracking_url = event.tracking_url or link
    # Extract explicit tracking references, including DHL references inside CTT notices.
    for match in re.finditer(
        r"(?:tracking (?:number|id)|numero de seguimiento(?: asignado por \w+)?|n[º°o]?\.?\s*seguimiento|numero de envio|referencia de envio|identificador de envio|envio numero|envio seur n[º°]?|tu envio|tu paquete)\s*(?:is|es|:|#)?\s*([a-z0-9][a-z0-9-]{7,})",
        combined,
    ):
        value = match[1].upper()
        if any(c.isdigit() for c in value):
            event.aliases.append(f"tracking:{value}")
    for value in re.findall(
        r"\b(?:1Z[A-Z0-9]{16}|JJD\d{12,}|PQ[A-Z0-9]{15,}|LP\d{12,})\b",
        (body + " " + mail.subject).upper(),
    ):
        event.aliases.append(f"tracking:{value}")
    if family in CARRIERS:
        tail = re.search(r" - ([\dA-Z]{10,})$", mail.subject)
        if tail:
            event.aliases.append(f"tracking:{tail[1]}")
        for merchant in ("JYSK", "Thomann", "DRUNI", "TOUS", "Amazon"):
            if merchant.lower() in text:
                event.retailer = merchant
                break
    if family == "Temu":
        for carrier in ("InPost", "Sending"):
            if carrier.lower() in combined:
                event.carrier = carrier
        # InPost forwarded notification may only carry a pickup code; do not treat it as tracking.
    event.aliases = sorted(set(event.aliases))
    event.destination_type = (
        "pickup"
        if re.search(r"locker|punto de recogida|pickup|pick.up|punto pack", combined)
        else None
    )
    reference = mail.sent_at.astimezone(ZoneInfo(timezone)).date()
    eta = re.search(
        r"(?:arriving|estimated delivery(?: date)?|scheduled delivery(?: date)?|fecha (?:prevista|estimada|de entrega programada)(?: de entrega)?|entrega en punto de recogida|delivery\s+(?="
        + WEEKDAYS
        + r")|will be delivered|sera entregado|prevista su entrega|entrega prevista)\s*[:\-]?\s*(.{0,100})",
        combined,
    )
    if eta:
        expected = date_from_text(eta[1], reference)
        if expected:
            event.expected_date = expected.isoformat()
            event.confidence = "medium"
            event.scheduled = family == "Mercadona"
            if event.scheduled:
                event.confidence = "high"
            # Retain an explicit range if the clause includes two complete dates.
            pieces = re.split(r"\s+(?:to|and|hasta|al|y)\s+|\s+[–-]\s+", eta[1])
            if len(pieces) > 1:
                end = date_from_text(pieces[1], reference)
                if end and end > expected:
                    event.expected_end = end.isoformat()
            compact_range = re.search(r"([a-z]+)\s+(\d{1,2})\s*[-–]\s*(\d{1,2})", eta[1])
            if compact_range and compact_range[1] in MONTHS:
                end = date_from_text(f"{compact_range[1]} {compact_range[3]}", reference)
                if end and end > expected:
                    event.expected_end = end.isoformat()
    window = re.search(
        r"(?:between|from|entre|desde)\s*(\d{1,2}:\d{2})\s*(?:and|to|a|y|hasta)\s*(\d{1,2}:\d{2})",
        combined,
    )
    if window and event.expected_date:
        if all(int(t.split(":")[0]) < 24 and int(t.split(":")[1]) < 60 for t in window.groups()):
            event.window = [t.zfill(5) for t in window.groups()]
    deadline = re.search(
        r"(?:pick up by|collect by|recoger hasta|hasta el proximo)\s+(.{0,80})", combined
    )
    if deadline:
        value = date_from_text(deadline[1], reference)
        event.pickup_deadline = value.isoformat() if value else None
    if event.status == "out_for_delivery":
        event.expected_date = reference.isoformat()
        event.expected_end = None
        event.confidence = "high"
    if event.status == "ready_for_pickup":
        event.destination_type = "pickup"
        event.confidence = "high"
    location = re.search(
        r"(?:punto de recogida|te esta esperando en|tienda seur pickup|amazon (?:locker|counter))\s*[:\-]?\s*([^\n]{3,120})",
        fold(mail.text),
    )
    if location:
        event.pickup_location = clean(location[1])[:120]
    if not event.orders and not event.aliases:
        event.review_reason = event.review_reason or "missing_reference"
        event.parsing_certainty = "low"
    if not event.status and not event.expected_date and not event.review_reason:
        if re.search(r"receipt|factura", subject):
            return []
        event.review_reason = "unsupported_format"
        event.parsing_certainty = "low"
    # An uncertain parse cannot confidently predict an arrival.
    if event.parsing_certainty == "low" and event.expected_date:
        event.confidence = "low"
    return [event]
