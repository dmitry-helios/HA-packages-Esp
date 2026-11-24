# Supported email formats

Sender matching checks exact domains and their subdomains. Promotional and review-request subjects are excluded before parsing.

| Family | Sender domain | Extracted evidence |
|---|---|---|
| Amazon.es | `amazon.es` | Order IDs, shipment IDs in progress-tracker links, quoted item descriptions, arrival dates/ranges, delivery states, pickup deadlines |
| Mercadona | `mercadona.es`, `mail.mercadona.com` | Order reference, delivery day/time window, same-day reminders; plain receipts do not create deliveries |
| Temu | `orders.temu.com` | PO order references, tracking, Sending/InPost handoffs, delivery and forwarded pickup notices; compensation dates are not arrival estimates |
| Leroy Merlin | `leroymerlin.es`, `mailing.leroymerlin.es` | Order references, explicit pickup arrival date, destination type; standalone invoices ignored |
| CTT Express | `cttexpress.org` | Parcel number plus original shipment reference, transit and completion |
| DHL | `dhl.com` | JJD reference and expected delivery date |
| UPS | `ups.com` | 1Z reference and scheduled/estimated delivery date |
| SEUR | `mail.seur.info`, `network1.pickup-services.com` | Reference, failed attempt, out-for-delivery, pickup availability/deadline |
| TIPSA | `tip-sa.com` | Tracking, estimated date and transit/delivery states |
| Ecoscooting | `service.ecoscooting.com` | Parcel references, transit/delivery and pickup-related notices |
| Correos | `correos.com` | References, date notices and completion |
| JYSK, Thomann, DRUNI | `jysk.com`, `thomann.de`, `druni.es` | Order/shipping references, explicit dates, status; broad business-day promises remain unknown |
| LILLYDOO, Rituals, TOUS | `lillydoo.com`, `s.rituals.com`, `info.tous.com` | Confirmation/dispatch states and references; German LILLYDOO dispatch subject supported |
| Shopify-style stores | `t.shopifyemail.com`, `dami3c.com`, `moisland.com` | Order/tracking references and shipment states; known store addresses identify Dami3C and Lonely Planet |

GLS is not yet a validated email adapter. A GLS pickup location mentioned by Leroy Merlin is retained as pickup information.

English/Spanish dates include ISO dates, day/month/year, written months, today/tomorrow and Mercadona's weekday-plus-day format. Unresolved references or dates remain review items/unknown dates. Forwarded pickup messages with only a collection code are deliberately not matched using that code.

There is no scraping, PDF OCR, tracking-link fetch, AI fallback or attachment parsing. Add adapters with narrowly scoped extraction and sanitised regression tests.
