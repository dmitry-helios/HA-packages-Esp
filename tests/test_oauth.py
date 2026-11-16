from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.helpers import config_entry_oauth2_flow

from custom_components.packages_esp.const import DOMAIN, GMAIL_API, OAUTH_SCOPE


class FakeOAuth(config_entry_oauth2_flow.AbstractOAuth2Implementation):
    @property
    def name(self):
        return "Test Google"

    @property
    def domain(self):
        return "test_google"

    async def async_generate_authorize_url(self, flow_id):
        return "https://accounts.google.com/o/oauth2/v2/auth?state=test"

    async def async_resolve_external_data(self, external_data):
        return {"access_token": "test-access", "refresh_token": "test-refresh", "expires_in": 3600}

    async def _async_refresh_token(self, token):
        return token


async def test_google_oauth_authorize_scopes_and_profile(hass, aioclient_mock):
    config_entry_oauth2_flow.async_register_implementation(hass, DOMAIN, FakeOAuth())
    aioclient_mock.get(
        GMAIL_API + "/profile", json={"emailAddress": "test@example.com", "historyId": "100"}
    )
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "oauth"}
    )
    assert result["step_id"] == "pick_implementation"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"implementation": "test_google"}
    )
    assert result["type"] == "external"
    assert "access_type=offline" in result["url"]
    assert "gmail.readonly" in result["url"]
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "test"})
    with patch("custom_components.packages_esp.async_setup_entry", AsyncMock(return_value=True)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
        await hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert result["data"]["transport"] == "oauth"
    assert result["data"]["token"]["refresh_token"] == "test-refresh"
    assert OAUTH_SCOPE.endswith("gmail.readonly")
