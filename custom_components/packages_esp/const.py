"""Integration constants."""

DOMAIN = "packages_esp"
PLATFORMS = ["sensor", "binary_sensor", "calendar"]
EVENT = f"{DOMAIN}_delivery_changed"
TERMINAL = {"delivered", "collected", "cancelled", "returned", "ignored"}
GROUPS = ("today", "tomorrow", "pickups_ready", "attention", "unknown", "upcoming")
OAUTH_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
POLL_SECONDS = 300
STALE_SECONDS = 1800
RETENTION_DAYS = 90
