# HA Packages España

Home Assistant delivery and pickup tracking from Gmail. Local parsers combine retailer and courier emails into parcel records, with confidence-aware summaries for today, tomorrow and collection deadlines.

**Example:** “Mercadona: scheduled today 08:00–10:00. Amazon: expected today. Leroy Merlin: ready to collect; collect by 2026-11-18.”

## Install

Requires **Home Assistant 2025.5.2 or newer**. This is a custom integration.

1. In HACS, add `https://github.com/dmitry-helios/HA-packages-Esp` as a custom repository of type **Integration**. Download **HA Packages España** and restart Home Assistant. During development, use the implementation branch's files until the PR is merged.
2. Alternatively, copy `custom_components/packages_esp` into `/config/custom_components/packages_esp`, then restart.
3. Open **Settings → Devices & services → Add integration → Packages España**.
4. Choose **Gmail IMAP app password** or **Gmail API (Google OAuth)**. Both provide the same tracking features. Each account can be configured once.
5. The initial import reads the last 90 days in batches. The dashboard indicates when it is still importing. New mail is checked every five minutes; incomplete initial imports continue every minute.

Nothing is sent, deleted, labelled or marked read. Archived mail and plus-addressed recipients are supported. Spam and Trash are excluded.

### Gmail IMAP setup

Enable Google 2-Step Verification and create an **app password** in your Google account. App passwords may be unavailable for some managed accounts or accounts using Advanced Protection; use OAuth instead in that case.

Enter your Gmail address and app password in the integration setup. The connection uses `imap.gmail.com:993` with TLS, discovers the Gmail **All Mail** special folder, opens it read-only and fetches using `BODY.PEEK[]`. If setup cannot find All Mail, check Gmail's IMAP/folder visibility settings and your organisation's mail policy.

An app password itself grants broader mailbox access than the integration uses. It remains in Home Assistant's config-entry storage; protect your HA backups accordingly.

### Gmail API OAuth setup

1. Create a Google Cloud project and enable the **Gmail API**.
2. Configure the OAuth consent screen. For a personal external app in Testing, add your Gmail account as a test user. Google may expire testing-mode refresh tokens; ongoing use may require changing the app's publishing status. Follow Google's current consent-screen guidance.
3. Create an OAuth client of type **Web application**. Register `https://my.home-assistant.io/redirect/oauth` as the authorised redirect URI when using My Home Assistant. Otherwise use the callback URL shown by HA's local OAuth setup.
4. In HA, open **Settings → Devices & services → three-dot menu → Application credentials** and add the client ID/secret for **Packages España**.
5. Add the integration, choose Gmail API, select the application credentials and authorise Google access. The requested scope is only `https://www.googleapis.com/auth/gmail.readonly`.

OAuth credentials are your own Google application credentials, not this chat's Gmail connection. Tokens are refreshed by Home Assistant. If access is revoked, HA requests reauthentication. No webhook or externally reachable mail backend is required.

References: [HA Application Credentials](https://developers.home-assistant.io/docs/core/platform/application_credentials/), [Google Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes), [Google app passwords](https://support.google.com/accounts/answer/185833).

## Dashboard

Add a dashboard resource under **Settings → Dashboards → Resources** (Advanced Mode may be needed):

```yaml
url: /packages_esp/packages-esp-card.js?v=0.1.0
type: module
```

Then add a Manual card:

```yaml
type: custom:packages-esp-card
title: Deliveries
language: en # or es; defaults to HA frontend language
hide_items: false
# entry_id: YOUR_CONFIG_ENTRY_ID # required only with multiple accounts
```

The card shows today, tomorrow, ready pickups, upcoming deliveries, attention items and unknown dates. Details include source and tracking links, pickup location, manual completion, date correction, snooze and clearing corrections. Refreshing the browser after an update may be necessary.

The card uses authenticated HA actions. No mail content is exposed by the static JavaScript URL. Email-derived text is inserted as text, never as executable HTML. Collection codes are not extracted or displayed; open the original email for those instructions.

## Entities and actions

Each account creates nine stable entities, grouped under its Packages España device:

| Entity type | Function |
|---|---|
| Five count sensors | Today, tomorrow, ready pickups, attention, unknown dates |
| Timestamp sensor | Last completed successful synchronisation |
| Connectivity binary sensor | Connection healthy and information less than 30 minutes old |
| Two calendars | Expected deliveries and pickup deadlines |

Count attributes contain up to 50 compact relevant parcel summaries, an account `entry_id`, freshness and import status. Use `get_deliveries` for the full active list. Entity names vary with account count, language and user renaming. No per-parcel or per-sender entities are created.

Actions are available in **Developer tools → Actions**:

| Action | Inputs / response |
|---|---|
| `packages_esp.get_deliveries` | Optional `entry_id`, `parcel_id`; returns groups and active records, or one parcel with extracted event history |
| `packages_esp.get_summary` | Optional `entry_id`, `day: today/tomorrow`, `language: en/es`, `hide_items`; returns `summary`, `stale`, `last_sync` |
| `packages_esp.refresh` | Optional `entry_id`; requests another sync batch |
| `packages_esp.mark_delivered` / `mark_collected` / `ignore` | `parcel_id`, optional `entry_id` |
| `packages_esp.set_expected_date` | `parcel_id`, `date: YYYY-MM-DD`, optional `entry_id` |
| `packages_esp.snooze` | `parcel_id`, `until`: future ISO timestamp including timezone, optional `entry_id` |
| `packages_esp.clear_override` | `parcel_id`, optional `entry_id`; restores the email-derived record |

`entry_id` is required when multiple accounts are loaded. Manual corrections survive restarts and resynchronisation. Snoozing suppresses notifications and spoken mentions while keeping the parcel visible. New conflicting mail is flagged rather than silently overriding a manual correction.

## Automations and Assist

See [examples/automations.yaml](examples/automations.yaml) for opt-in daily summaries, next-day previews, exception notifications and Assist conversation triggers. Replace example notification actions with your devices and configure quiet hours there. The integration does not choose a speaker or send unsolicited notifications.

The event `packages_esp_delivery_changed` contains `entry_id`, `parcel_id`, `change_type` and a compact `parcel` object. Change types include `status_changed`, `date_changed`, `updated`, `expected_today` and `collection_deadline`. Inspect `parcel.status` to distinguish out-for-delivery, ready-for-pickup and failed attempts. Initial import does not emit notifications, repeated mail is deduplicated, and derived daily notifications are suppressed while data is stale.

## What the dates mean

- **High:** explicit scheduled window or current out-for-delivery notice.
- **Medium:** explicit retailer/carrier estimate. Summaries say “expected”.
- **Low/unknown:** ambiguous extraction, conflicting information or no usable date. Excluded from confident arrival announcements.
- “Ready for pickup” requires an availability message. An ETA at a collection point is not collection readiness.
- Passed delivery windows and pickup deadlines remain unconfirmed and need attention; time alone never proves delivery, collection or return.
- Ranges remain ranges. Relative dates use the email timestamp and HA's timezone, including daylight-saving changes.
- Refunds and partial cancellations raise item-change reviews; they do not close the whole parcel.

Email-only tracking cannot see updates that the retailer never emails. Business-day-only promises remain date-unknown. Exact matching uses order and tracking references; notices without enough matching evidence remain separate review items.

## Supported formats

See [docs/supported-formats.md](docs/supported-formats.md). Support is template-based, not a claim that every email ever sent by a brand is understood. Review items are surfaced for recognised delivery senders whose transactional format cannot be resolved confidently. Unknown senders are ignored until an adapter is added.

## Storage and troubleshooting

The ledger is stored in HA's `.storage/packages_esp.<entry_id>` using versioned storage. It contains extracted order/parcel references, event facts, pickup locations, tracking links, checkpoints, deduplication IDs and overrides. Raw email bodies and attachments are not retained. Completed/ignored parcels are retained 90 days; unresolved parcels are kept. Deduplication IDs are retained 180 days. Diagnostics contain counts only.

Transient failures retry after 5, 10, 20, 40, then at most 60 minutes. Saved deliveries stay visible. An expired Gmail history cursor or changed IMAP UID validity triggers a deduplicated rescan. Failed saves do not advance processing checkpoints. Increasing import-days affects the next full import/rescan; it does not reset an existing incremental checkpoint.

To report unsupported formats, provide a **redacted** subject/body preserving date labels and reference shapes. Remove names, addresses, codes, credentials, personal order/tracking numbers and token-bearing URLs. Do not post original mail to public issues.

## Development

```sh
python3.13 -m venv .venv
. .venv/bin/activate
pip install -r requirements-test.txt
ruff check .
ruff format --check .
pytest -q
npm ci
npx playwright install chromium
npm test
```

Integration tests use a disposable Home Assistant 2025.5.2 runtime and synthetic mail. Browser tests exercise the card at desktop and mobile sizes. CI also runs hassfest and HACS validation. Live Gmail authentication and installation into your HA instance are separate deployment steps.

MIT licensed; see [LICENSE](LICENSE).
