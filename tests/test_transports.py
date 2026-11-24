import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.packages_esp.transports import (
    AuthenticationError,
    GmailTransport,
    ImapTransport,
)

RAW = b"From: confirmar-envio@amazon.es\r\nSubject: Dispatched: Test\r\nDate: Mon, 16 Nov 2026 09:00:00 +0000\r\n\r\nOrder #123-1234567-1234567 Arriving today"


async def test_gmail_pagination_history_and_deleted_messages():
    transport = GmailTransport(None)
    transport.request = AsyncMock(
        side_effect=[
            {"historyId": "100"},
            {"messages": [{"id": "a"}], "nextPageToken": "next"},
            {
                "raw": base64.urlsafe_b64encode(RAW).decode(),
                "internalDate": "1794819600000",
                "labelIds": [],
            },
            {"messages": [{"id": "b"}]},
            None,
            {"historyId": "105", "history": [{"messagesAdded": [{"message": {"id": "c"}}]}]},
            {"raw": "", "internalDate": "1794819600000", "labelIds": ["TRASH"]},
        ]
    )
    mails, cp, complete = await transport.fetch({})
    assert len(mails) == 1 and mails[0].id == "gmail:a"
    assert not complete and cp["page"] == "next"
    _, cp, complete = await transport.fetch(cp)
    assert complete and cp["history"] == "100"
    mails, cp, complete = await transport.fetch(cp)
    assert not mails and cp["history"] == "105"


async def test_history_expiry_rescans_without_mutating_input():
    transport = GmailTransport(None)
    transport.request = AsyncMock(side_effect=[None, {"historyId": "200"}, {}])
    original = {"mode": "history", "history": "1"}
    _, cp, complete = await transport.fetch(original)
    assert complete and cp["history"] == "200"
    assert original["history"] == "1"


async def test_gmail_auth_error():
    response = MagicMock(status=401)
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)
    transport = GmailTransport(MagicMock(async_request=AsyncMock(return_value=response)))
    with pytest.raises(AuthenticationError):
        await transport.profile()


def test_imap_readonly_peek_uidvalidity_and_gmail_identity():
    connection = MagicMock()
    connection.list.return_value = ("OK", [b'(\\HasNoChildren \\All) "/" "[Gmail]/All Mail"'])
    connection.select.return_value = ("OK", [b"1"])
    connection.response.return_value = ("UIDVALIDITY", [b"12"])
    connection.uid.side_effect = [
        ("OK", [b"42"]),
        ("OK", [(b'42 (X-GM-MSGID 2748 INTERNALDATE "16-Nov-2026 09:00:00 +0000")', RAW)]),
    ]
    with patch.object(ImapTransport, "_connect", return_value=connection):
        mails, cp, complete = ImapTransport("test@example.com", "secret").fetch(
            {"validity": "old", "uid": 999}
        )
    assert complete and cp == {"validity": "12", "uid": 42}
    assert mails[0].id == "gmail:abc"
    connection.select.assert_called_once_with('"[Gmail]/All Mail"', readonly=True)
    assert "BODY.PEEK[]" in connection.uid.call_args_list[1].args[2]
    assert connection.uid.call_args_list[0].args[-1] == "1:*"
    connection.logout.assert_called_once()
