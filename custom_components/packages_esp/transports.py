"""Read-only Gmail API and Gmail IMAP transports with resumable batches."""

import asyncio
import base64
import imaplib
import re
import ssl
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

from aiohttp import ClientResponseError

from .const import GMAIL_API
from .mail import decode_mail


class AuthenticationError(Exception):
    """Credentials need user attention."""


class TransportError(Exception):
    """Temporary or malformed remote response."""


class GmailTransport:
    def __init__(self, session):
        self.session = session

    async def request(self, path, params=None, allow_missing=False):
        async with asyncio.timeout(45):
            try:
                response = await self.session.async_request("GET", GMAIL_API + path, params=params)
            except ClientResponseError as error:
                if error.status in {400, 401, 403}:
                    raise AuthenticationError("Google token refresh rejected") from error
                raise
            async with response:
                if response.status == 401:
                    raise AuthenticationError("Gmail authorization required")
                if response.status == 403:
                    details = await response.json()
                    reasons = {e.get("reason") for e in details.get("error", {}).get("errors", [])}
                    if reasons & {
                        "rateLimitExceeded",
                        "userRateLimitExceeded",
                        "dailyLimitExceeded",
                        "quotaExceeded",
                    }:
                        raise TransportError("Gmail quota temporarily exceeded")
                    raise AuthenticationError("Gmail permission required")
                if response.status == 404 and allow_missing:
                    return None
                if response.status >= 400:
                    raise TransportError(f"Gmail HTTP {response.status}")
                return await response.json()

    async def profile(self):
        return await self.request("/profile")

    async def fetch(self, checkpoint, days=90):
        cp = deepcopy(checkpoint)
        messages = []
        if not cp:
            profile = await self.profile()
            cp = {"mode": "full", "baseline": profile["historyId"], "page": None}
        if cp["mode"] == "full":
            params = {"q": f"newer_than:{days}d -in:spam -in:trash", "maxResults": 50}
            if cp.get("page"):
                params["pageToken"] = cp["page"]
            page = await self.request("/messages", params)
            ids = [m["id"] for m in page.get("messages", [])]
        else:
            params = {
                "startHistoryId": cp["history"],
                "historyTypes": "messageAdded",
                "maxResults": 50,
            }
            if cp.get("page"):
                params["pageToken"] = cp["page"]
            page = await self.request("/history", params, allow_missing=True)
            if page is None:
                return await self.fetch({}, days)
            ids = list(
                dict.fromkeys(
                    m["message"]["id"]
                    for h in page.get("history", [])
                    for m in h.get("messagesAdded", [])
                )
            )
        for message_id in ids:
            result = await self.request(
                f"/messages/{message_id}", {"format": "raw"}, allow_missing=True
            )
            if result is None or {"SPAM", "TRASH"} & set(result.get("labelIds", [])):
                continue
            raw = base64.urlsafe_b64decode(result["raw"] + "===")
            received = datetime.fromtimestamp(int(result["internalDate"]) / 1000, UTC)
            messages.append(decode_mail(raw, "gmail:" + message_id, received))
        complete = not page.get("nextPageToken")
        if complete:
            history = (
                cp["baseline"] if cp["mode"] == "full" else page.get("historyId", cp["history"])
            )
            cp = {"mode": "history", "history": history, "page": None}
        else:
            cp["page"] = page["nextPageToken"]
        return messages, cp, complete


class ImapTransport:
    def __init__(self, username, password, mailbox=None):
        self.username, self.password, self.mailbox = username, password, mailbox

    def _connect(self):
        connection = imaplib.IMAP4_SSL(
            "imap.gmail.com", 993, ssl_context=ssl.create_default_context(), timeout=45
        )
        try:
            connection.login(self.username, self.password)
        except imaplib.IMAP4.error as error:
            connection.logout()
            raise AuthenticationError("Gmail app password rejected") from error
        return connection

    def _select(self, connection):
        mailbox = self.mailbox
        if not mailbox:
            status, lines = connection.list()
            if status != "OK":
                raise TransportError("Cannot list Gmail folders")
            for line in lines or []:
                if line and b"\\All" in line:
                    match = re.search(rb'\) "[^"]*" (.+)$', line)
                    if match:
                        mailbox = match[1].decode("ascii")
                        break
        if not mailbox:
            raise TransportError("Gmail All Mail folder not found; enable IMAP visibility")
        if not mailbox.startswith('"'):
            mailbox = '"' + mailbox.replace('"', '\\"') + '"'
        status, _ = connection.select(mailbox, readonly=True)
        if status != "OK":
            raise TransportError("Cannot open Gmail All Mail folder")

    def validate(self):
        connection = self._connect()
        try:
            self._select(connection)
        finally:
            connection.logout()

    def fetch(self, checkpoint, days=90):
        connection = self._connect()
        try:
            self._select(connection)
            validity = connection.response("UIDVALIDITY")[1][0].decode()
            cp = deepcopy(checkpoint) if checkpoint.get("validity") == validity else {}
            previous = int(cp.get("uid", 0))
            # Gmail raw search includes archived messages in All Mail and excludes spam/trash.
            query = f'"newer_than:{days}d -in:spam -in:trash"'
            status, result = connection.uid(
                "SEARCH", None, "X-GM-RAW", query, "UID", f"{previous + 1}:*"
            )
            if status != "OK":
                raise TransportError("Gmail search failed")
            ids = sorted(int(v) for v in (result[0] or b"").split() if int(v) > previous)
            messages = []
            last = previous
            for uid in ids[:50]:
                status, parts = connection.uid(
                    "FETCH", str(uid), "(BODY.PEEK[] X-GM-MSGID INTERNALDATE)"
                )
                if status != "OK":
                    raise TransportError("Gmail message fetch failed")
                for part in parts:
                    if not isinstance(part, tuple):
                        continue
                    header, raw = part
                    identity = re.search(rb"X-GM-MSGID (\d+)", header)
                    timestamp = re.search(rb'INTERNALDATE "([^"]+)"', header)
                    received = datetime.now(UTC)
                    if timestamp:
                        received = parsedate_to_datetime(timestamp[1].decode())
                    message_id = (
                        "gmail:" + format(int(identity[1]), "x")
                        if identity
                        else f"imap:{validity}:{uid}"
                    )
                    messages.append(decode_mail(raw, message_id, received))
                last = uid
            return messages, {"validity": validity, "uid": last}, len(ids) <= 50
        finally:
            connection.logout()


def retry_delay(failures):
    return timedelta(seconds=min(300 * 2 ** max(0, failures - 1), 3600))
