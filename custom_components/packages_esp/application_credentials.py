"""Google OAuth application credentials."""

from homeassistant.components.application_credentials import AuthorizationServer


async def async_get_authorization_server(hass):
    return AuthorizationServer(
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
    )
