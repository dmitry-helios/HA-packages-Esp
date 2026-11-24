"""Configure either Gmail API OAuth or read-only Gmail IMAP."""

import asyncio
import imaplib
import logging

import voluptuous as vol
from aiohttp import ClientError
from homeassistant import config_entries
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, GMAIL_API, OAUTH_SCOPE
from .transports import AuthenticationError, ImapTransport, TransportError

LOGGER = logging.getLogger(__name__)


class ConfigFlow(config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN):
    VERSION = 1
    DOMAIN = DOMAIN

    @property
    def logger(self):
        return LOGGER

    @property
    def extra_authorize_data(self):
        return {"scope": OAUTH_SCOPE, "access_type": "offline", "prompt": "consent"}

    async def async_step_user(self, user_input=None):
        return self.async_show_menu(step_id="user", menu_options=["imap", "oauth"])

    async def async_step_oauth(self, user_input=None):
        return await super().async_step_user(user_input)

    async def async_step_imap(self, user_input=None):
        errors = {}
        if user_input:
            username = user_input["username"].strip().lower()
            try:
                transport = ImapTransport(username, user_input["password"].replace(" ", ""))
                await self.hass.async_add_executor_job(transport.validate)
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except (OSError, imaplib.IMAP4.error, TransportError) as error:
                # Never include credential-bearing remote exceptions in logs.
                LOGGER.debug("IMAP setup failed: %s", type(error).__name__)
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(username)
                data = {"transport": "imap", "username": username, "password": transport.password}
                if self.source == config_entries.SOURCE_REAUTH:
                    entry = self._get_reauth_entry()
                    if entry.unique_id != username:
                        return self.async_abort(reason="wrong_account")
                    return self.async_update_reload_and_abort(entry, data_updates=data)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=username, data=data)
        return self.async_show_form(
            step_id="imap",
            data_schema=vol.Schema(
                {
                    vol.Required("username"): str,
                    vol.Required("password"): str,
                }
            ),
            errors=errors,
        )

    async def async_oauth_create_entry(self, data):
        session = async_get_clientsession(self.hass)
        try:
            async with asyncio.timeout(30):
                async with session.get(
                    GMAIL_API + "/profile",
                    headers={"Authorization": "Bearer " + data["token"]["access_token"]},
                ) as response:
                    if response.status != 200:
                        return self.async_abort(reason="cannot_connect")
                    profile = await response.json()
        except (ClientError, TimeoutError):
            return self.async_abort(reason="cannot_connect")
        username = profile["emailAddress"].lower()
        await self.async_set_unique_id(username)
        data.update(transport="oauth", username=username)
        if self.source == config_entries.SOURCE_REAUTH:
            entry = self._get_reauth_entry()
            if entry.unique_id != username:
                return self.async_abort(reason="wrong_account")
            return self.async_update_reload_and_abort(entry, data_updates=data)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=username, data=data)

    async def async_step_reauth(self, entry_data):
        self._reauth_transport = entry_data["transport"]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        if user_input is not None:
            if self._reauth_transport == "imap":
                return await self.async_step_imap()
            return await self.async_step_oauth()
        return self.async_show_form(step_id="reauth_confirm", data_schema=vol.Schema({}))

    @staticmethod
    def async_get_options_flow(config_entry):
        return OptionsFlow()


class OptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "import_days", default=self.config_entry.options.get("import_days", 90)
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=180)),
                    vol.Optional(
                        "language", default=self.config_entry.options.get("language", "en")
                    ): vol.In(["en", "es"]),
                    vol.Optional(
                        "hide_items", default=self.config_entry.options.get("hide_items", False)
                    ): bool,
                }
            ),
        )
