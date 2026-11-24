from datetime import UTC, date, datetime

import pytest

from custom_components.packages_esp.mail import Mail, decode_mail
from custom_components.packages_esp.parsers import date_from_text, parse

NOW = datetime(2026, 11, 16, 9, tzinfo=UTC)


def email(sender, subject, body, links=()):
    return Mail("gmail:abc", sender, subject, body, NOW, links)


@pytest.mark.parametrize(
    "sender,subject,body,status,expected",
    [
        (
            "confirmar-envio@amazon.es",
            "Dispatched: ‘Test headphones’",
            "Ordered Dispatched Out for delivery Delivered Arriving today Order # 123-1234567-1234567",
            "in_transit",
            "2026-11-16",
        ),
        (
            "shipment-tracking@amazon.es",
            "Out for delivery: ‘Test item’",
            "Order # 123-1234567-1234567",
            "out_for_delivery",
            "2026-11-16",
        ),
        (
            "order-update@amazon.es",
            "Delivered: ‘Test item’",
            "Order # 123-1234567-1234567",
            "delivered",
            None,
        ),
        (
            "online@mail.mercadona.com",
            "Confirmed order in Mercadona",
            "Order #12345678 Delivery Friday 20 from 08:00 to 10:00",
            "ordered",
            "2026-11-20",
        ),
        (
            "noreply@mailing.leroymerlin.es",
            "Confirmación de tu pedido 26320L0001",
            "Entrega en Punto de Recogida el 18/11/2026",
            "ordered",
            "2026-11-18",
        ),
        (
            "temu@orders.temu.com",
            "Order shipped and Sending tracking number is ready",
            "Order ID: PO-186-12345678901234567 The Sending tracking number is 957140000001. If delivered after Nov 20, you will get a credit",
            "in_transit",
            None,
        ),
        (
            "noreplyclientes@cttexpress.org",
            "Información envío - 0008180008189700000001",
            "Tu envío número 0008180008189700000001 de JYSK está en reparto. Referencia de envío: JJD00026866000000000001",
            "out_for_delivery",
            "2026-11-16",
        ),
        (
            "noreply@dhl.com",
            "DHL-Notif. Entrega JJD00026866000000000001",
            "Pedido de JYSK. Fecha prevista de entrega: Miércoles, 18 de Noviembre de 2026",
            None,
            "2026-11-18",
        ),
        (
            "pkginfo@ups.com",
            "UPS Ship Notification",
            "THOMANN GMBH Tracking Number: 1ZAY26226855000001 Scheduled Delivery Date: Wednesday, 18/11/2026",
            None,
            "2026-11-18",
        ),
        (
            "no-reply@tip-sa.com",
            "INFORMACIÓN SOBRE TU ENVÍO - TIPSA",
            "Tu envío de DRUNI se encuentra EN REPARTO. Nº SEGUIMIENTO: 0460040300008100000001 Fecha estimada de entrega: Lunes, 16 de Noviembre",
            "out_for_delivery",
            "2026-11-16",
        ),
        (
            "infoenvios@mail.seur.info",
            "No hemos podido entregar tu envío de TOUS",
            "Identificador de envío: TF0000000001-0097430000",
            "delivery_attempted",
            None,
        ),
        (
            "noreply@service.ecoscooting.com",
            "¡Bien! Hemos entregado tu paquete - 080250000100000001",
            "Tu paquete 080250000100000001 - LP88056041870000000 ha sido entregado",
            "delivered",
            None,
        ),
        (
            "correos@correos.com",
            "Información sobre su envío",
            "Tu envío PQ1AL89800388350108000Q tiene prevista su entrega hoy 16/11/2026 antes de las 15:00",
            None,
            "2026-11-16",
        ),
        (
            "store+27536556093@t.shopifyemail.com",
            "A shipment from order #8866000 is out for delivery",
            "JCH Express tracking number: ZS22292800000",
            "out_for_delivery",
            "2026-11-16",
        ),
        (
            "noreply_ES@jysk.com",
            "La confirmación del número de pedido 4109000001",
            "La entrega se realizará entre 2 y 5 días laborables con DHL",
            "ordered",
            None,
        ),
        (
            "spain@thomann.de",
            "Shipping confirmation and invoice",
            "Order number 202646.000001 Tracking number 1ZAY26226855000001",
            "in_transit",
            None,
        ),
        (
            "noreply@druni.es",
            "Tu pedido se ha entregado: #1115500000",
            "Pedido #1115500000 ENTREGADO",
            "delivered",
            None,
        ),
        ("service@lillydoo.com", "Dein Paket kommt bald!", "Pedido #12345678", "in_transit", None),
        (
            "service@s.rituals.com",
            "Confirmación del pedido",
            "Resumen del pedido #euw15656000000 Estamos preparando tu pedido",
            "ordered",
            None,
        ),
        (
            "tous@info.tous.com",
            "Tu pedido TF0000000001 ya está en camino",
            "Haz el seguimiento aquí",
            "in_transit",
            None,
        ),
    ],
)
def test_supported_families(sender, subject, body, status, expected):
    result = parse(email(sender, subject, body), "Europe/Madrid")
    assert len(result) == 1
    assert result[0].status == status
    assert result[0].expected_date == expected


def test_amazon_shipment_identity_and_description():
    result = parse(
        email(
            "confirmar-envio@amazon.es",
            "Dispatched: ‘Headphones’",
            "Arriving tomorrow Order # 123-1234567-1234567",
            (
                "https://www.amazon.es/progress-tracker/package?orderId=123-1234567-1234567&shipmentId=TEST1",
            ),
        ),
        "Europe/Madrid",
    )[0]
    assert result.aliases == ["amazon:TEST1"]
    assert result.description == "Headphones"
    assert result.expected_date == "2026-11-17"


def test_pickup_deadline_and_forwarded_temu():
    result = parse(
        email(
            "pickup-point@amazon.es",
            "Package ready for pick-up: Amazon Locker - Test; pick up by 20 November",
            "Order # 123-1234567-1234567",
        ),
        "Europe/Madrid",
    )[0]
    assert result.status == "ready_for_pickup"
    assert result.pickup_deadline == "2026-11-20"
    result = parse(
        email(
            "notice@orders.temu.com",
            "Your Temu package has arrived at the pickup location",
            "InPost ¡Ya puedes recoger tu paquete! Te está esperando en: TEST SHOP",
        ),
        "Europe/Madrid",
    )[0]
    assert result.carrier == "InPost"
    assert result.status == "ready_for_pickup"
    assert result.review_reason == "missing_reference"


def test_refund_is_not_order_cancellation():
    result = parse(
        email(
            "temu@orders.temu.com",
            "Tu pedido ha sido reembolsado parcialmente",
            "Order ID: PO-186-12345678901234567",
        ),
        "Europe/Madrid",
    )[0]
    assert result.status is None
    assert result.review_reason == "item_change"


@pytest.mark.parametrize(
    "sender,subject",
    [
        ("x@amazon.es.evil.example", "Ordered: item"),
        ("no-reply@amazon.es", "Review your order"),
        ("temu@eu.temuemail.com", "Delivery tomorrow FREE"),
    ],
)
def test_unrelated_and_marketing_ignored(sender, subject):
    assert parse(email(sender, subject, "Order #12345678"), "Europe/Madrid") == []


def test_dates_invalid_year_rollover_and_relative_timezone():
    assert date_from_text("32/11/2026", date(2026, 11, 16)) is None
    assert date_from_text("January 2", date(2026, 12, 30)) == date(2027, 1, 2)
    mail = Mail(
        "1",
        "confirmar-envio@amazon.es",
        "Dispatched: item",
        "Order # 123-1234567-1234567 Arriving today",
        datetime(2026, 11, 16, 23, 30, tzinfo=UTC),
    )
    assert parse(mail, "Europe/Madrid")[0].expected_date == "2026-11-17"


def test_html_decoding_uses_real_body_not_plain_stub():
    raw = b'From: Shop <confirmar-envio@amazon.es>\r\nSubject: Dispatched: Test\r\nMIME-Version: 1.0\r\nContent-Type: multipart/alternative; boundary="test"\r\n\r\n--test\r\nContent-Type: text/plain\r\n\r\nOpen browser\r\n--test\r\nContent-Type: text/html\r\n\r\n<style>bad</style><p>Arriving today</p><a href="https://example.com/track">Track</a>\r\n--test--'
    mail = decode_mail(raw, "gmail:abc", NOW)
    assert "Arriving today" in mail.text
    assert "bad" not in mail.text
    assert mail.links == ("https://example.com/track",)
