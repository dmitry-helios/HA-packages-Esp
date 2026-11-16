"""Transport-neutral mail decoding. No attachments or remote resources are loaded."""

from dataclasses import dataclass
from datetime import datetime
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser


class HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text = []
        self.links = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "head"}:
            self.skip += 1
        if tag in {"p", "div", "br", "tr", "li"}:
            self.text.append("\n")
        if tag == "a":
            for key, value in attrs:
                if key == "href" and value and value.startswith("https://"):
                    self.links.append(value)

    def handle_endtag(self, tag):
        if tag in {"script", "style", "head"} and self.skip:
            self.skip -= 1
        if tag in {"p", "div", "tr", "td", "li"}:
            self.text.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.text.append(data)


@dataclass(frozen=True)
class Mail:
    id: str
    sender: str
    subject: str
    text: str
    sent_at: datetime
    links: tuple[str, ...] = ()
    source_url: str | None = None


def decode_mail(raw: bytes, message_id: str, received_at: datetime) -> Mail:
    message = BytesParser(policy=policy.default).parsebytes(raw)
    plain, html, links = [], [], []
    for part in message.walk():
        if part.get_content_disposition() == "attachment":
            continue
        if part.get_content_type() not in {"text/plain", "text/html"}:
            continue
        try:
            content = part.get_content()
        except (UnicodeError, LookupError):
            content = (part.get_payload(decode=True) or b"").decode("utf-8", "replace")
        if part.get_content_type() == "text/html":
            parser = HTMLText()
            parser.feed(content)
            html.append(" ".join(parser.text))
            links.extend(parser.links)
        else:
            plain.append(content)
    # Some retailers put only an unsubscribe stub in the plain part.
    text = "\n".join(html if html else plain)
    try:
        sent_at = parsedate_to_datetime(message.get("Date", ""))
        if sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=received_at.tzinfo)
    except (ValueError, TypeError):
        sent_at = received_at
    return Mail(
        id=message_id,
        sender=parseaddr(message.get("From", ""))[1].lower(),
        subject=str(message.get("Subject", "")),
        text=text,
        sent_at=sent_at,
        links=tuple(dict.fromkeys(links)),
        source_url=f"https://mail.google.com/mail/u/0/#all/{message_id.removeprefix('gmail:')}"
        if message_id.startswith("gmail:")
        else None,
    )
