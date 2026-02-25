"""Config flow for Tuya BLE integration."""

from __future__ import annotations

import logging
from typing import Any

import pycountry
import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.components.tuya.const import (
    CONF_ENDPOINT,
    TUYA_RESPONSE_CODE,
    TUYA_RESPONSE_MSG,
    TUYA_RESPONSE_SUCCESS,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithConfigEntry,
)
from homeassistant.const import (
    CONF_ADDRESS,
    CONF_COUNTRY_CODE,
    CONF_DEVICE_ID,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from homeassistant.core import callback

from .cloud import HASSTuyaBLEDeviceManager
from .const import (
    CONF_ACCESS_ID,
    CONF_ACCESS_SECRET,
    CONF_CATEGORY,
    CONF_DEVICE_NAME,
    CONF_LOCAL_KEY,
    CONF_PRODUCT_ID,
    CONF_PRODUCT_MODEL,
    CONF_PRODUCT_NAME,
    CONF_UUID,
    DOMAIN,
    TUYA_COUNTRIES,
)
from .devices import TuyaBLEData, get_device_readable_name
from .tuya_ble import SERVICE_UUID, TuyaBLEDeviceCredentials

_LOGGER = logging.getLogger(__name__)


async def _try_login(
    manager: HASSTuyaBLEDeviceManager,
    user_input: dict[str, Any],
    errors: dict[str, str],
    placeholders: dict[str, Any],
) -> dict[str, Any] | None:
    response: dict[Any, Any] | None
    data: dict[str, Any]

    country = next(
        country
        for country in TUYA_COUNTRIES
        if country.name == user_input[CONF_COUNTRY_CODE]
    )

    data = {
        CONF_ENDPOINT: country.endpoint,
        CONF_ACCESS_ID: user_input[CONF_ACCESS_ID],
        CONF_ACCESS_SECRET: user_input[CONF_ACCESS_SECRET],
        CONF_USERNAME: user_input[CONF_USERNAME],
        CONF_PASSWORD: user_input[CONF_PASSWORD],
        CONF_COUNTRY_CODE: country.country_code,
    }

    _LOGGER.debug(
        "Attempting Tuya login with endpoint: %s, username: %s, country_code: %s",
        country.endpoint,
        user_input[CONF_USERNAME],
        country.country_code,
    )

    manager.data.update(data)
    response = await manager.login()

    if response and response.get(TUYA_RESPONSE_SUCCESS, False):
        _LOGGER.debug("Tuya login successful")
        return data

    _LOGGER.error(
        "Tuya login failed with response: %s",
        response,
    )
    errors["base"] = "login_error"
    if response:
        placeholders.update(
            {
                TUYA_RESPONSE_CODE: response.get(TUYA_RESPONSE_CODE),
                TUYA_RESPONSE_MSG: response.get(TUYA_RESPONSE_MSG),
            }
        )

    return None


def _show_login_form(
    flow: TuyaBLEConfigFlow | TuyaBLEOptionsFlow,
    user_input: dict[str, Any],
    errors: dict[str, str],
    placeholders: dict[str, Any],
) -> ConfigFlowResult:
    """Show the Tuya IOT platform login form."""
    if user_input is not None and user_input.get(CONF_COUNTRY_CODE) is not None:
        for country in TUYA_COUNTRIES:
            if country.country_code == user_input[CONF_COUNTRY_CODE]:
                user_input[CONF_COUNTRY_CODE] = country.name
                break

    def get_country_name(alpha_2: str) -> str | None:
        try:
            country = pycountry.countries.get(alpha_2=alpha_2)
            if country:
                return country.name
        except LookupError:
            _LOGGER.exception(
                "Failed to get country name for alpha_2 code '%s'", alpha_2
            )
        return None

    def_country_name: str | None = None

    return flow.async_show_form(
        step_id="login",
        data_schema=vol.Schema(
            {
                vol.Required(
                    CONF_COUNTRY_CODE,
                    default=user_input.get(CONF_COUNTRY_CODE, def_country_name),
                ): vol.In(
                    # We don't pass a dict {code:name} because country
                    # codes can be duplicate.
                    [country.name for country in TUYA_COUNTRIES]
                ),
                vol.Required(
                    CONF_ACCESS_ID, default=user_input.get(CONF_ACCESS_ID, "")
                ): str,
                vol.Required(
                    CONF_ACCESS_SECRET,
                    default=user_input.get(CONF_ACCESS_SECRET, ""),
                ): str,
                vol.Required(
                    CONF_USERNAME, default=user_input.get(CONF_USERNAME, "")
                ): str,
                vol.Required(
                    CONF_PASSWORD, default=user_input.get(CONF_PASSWORD, "")
                ): str,
            }
        ),
        errors=errors,
        description_placeholders=placeholders,
    )


class TuyaBLEOptionsFlow(OptionsFlowWithConfigEntry):
    """Handle a Tuya BLE options flow."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        super().__init__(config_entry)

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> ConfigFlowResult:
        """Manage the options."""
        return await self.async_step_login()

    async def async_step_login(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the Tuya IOT platform login step and allow updating device credentials."""
        errors: dict[str, str] = {}
        placeholders: dict[str, Any] = {}
        address: str | None = self.config_entry.data.get(CONF_ADDRESS)

        if user_input is not None:
            # Update cloud credentials as before
            entry: TuyaBLEData | None = None
            domain_data = self.hass.data.get(DOMAIN)
            if domain_data:
                entry = domain_data.get(self.config_entry.entry_id)
            if entry and address:
                login_data = await _try_login(
                    entry.manager,
                    user_input,
                    errors,
                    placeholders,
                )
                if login_data:
                    credentials = await entry.manager.get_device_credentials(address)
                    if credentials:
                        self.hass.config_entries.async_update_entry(
                            self.config_entry,
                            options=entry.manager.data,
                        )
                        return self.async_create_entry(data={})
                    errors["base"] = "device_not_registered"
            elif not address:
                errors["base"] = "device_not_registered"

            # Update device credentials (ID, key, etc.)
            # These fields are optional, so update if present
            updated = False
            # Make a mutable copy of options
            options = dict(self.config_entry.options)
            for field in [
                CONF_UUID,
                CONF_LOCAL_KEY,
                CONF_DEVICE_ID,
                CONF_CATEGORY,
                CONF_PRODUCT_ID,
                CONF_DEVICE_NAME,
                CONF_PRODUCT_MODEL,
                CONF_PRODUCT_NAME,
            ]:
                if user_input.get(field) is not None:
                    options[field] = user_input[field]
                    updated = True
            if updated:
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    options=options,
                )
                return self.async_create_entry(data={})

        if user_input is None:
            user_input = {}
            user_input.update(self.config_entry.options)

        # Show a combined form for both cloud and device credentials
        return self.async_show_form(
            step_id="login",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_COUNTRY_CODE,
                        default=user_input.get(CONF_COUNTRY_CODE, ""),
                    ): str,
                    vol.Optional(
                        CONF_ACCESS_ID, default=user_input.get(CONF_ACCESS_ID, "")
                    ): str,
                    vol.Optional(
                        CONF_ACCESS_SECRET,
                        default=user_input.get(CONF_ACCESS_SECRET, ""),
                    ): str,
                    vol.Optional(
                        CONF_USERNAME, default=user_input.get(CONF_USERNAME, "")
                    ): str,
                    vol.Optional(
                        CONF_PASSWORD, default=user_input.get(CONF_PASSWORD, "")
                    ): str,
                    vol.Optional(CONF_UUID, default=user_input.get(CONF_UUID, "")): str,
                    vol.Optional(
                        CONF_LOCAL_KEY, default=user_input.get(CONF_LOCAL_KEY, "")
                    ): str,
                    vol.Optional(
                        CONF_DEVICE_ID, default=user_input.get(CONF_DEVICE_ID, "")
                    ): str,
                    vol.Optional(
                        CONF_CATEGORY, default=user_input.get(CONF_CATEGORY, "")
                    ): str,
                    vol.Optional(
                        CONF_PRODUCT_ID, default=user_input.get(CONF_PRODUCT_ID, "")
                    ): str,
                    vol.Optional(
                        CONF_DEVICE_NAME, default=user_input.get(CONF_DEVICE_NAME, "")
                    ): str,
                    vol.Optional(
                        CONF_PRODUCT_MODEL,
                        default=user_input.get(CONF_PRODUCT_MODEL, ""),
                    ): str,
                    vol.Optional(
                        CONF_PRODUCT_NAME, default=user_input.get(CONF_PRODUCT_NAME, "")
                    ): str,
                }
            ),
            errors=errors,
            description_placeholders=placeholders,
        )


class TuyaBLEConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tuya BLE."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        super().__init__()
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}
        self._data: dict[str, Any] = {}
        self._manager: HASSTuyaBLEDeviceManager | None = None
        self._get_device_info_error = False

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle the bluetooth discovery step."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery_info = discovery_info
        if self._manager is None:
            self._manager = HASSTuyaBLEDeviceManager(self.hass, self._data)
        await self._manager.build_cache()
        self.context["title_placeholders"] = {
            "name": await get_device_readable_name(
                discovery_info,
                self._manager,
            )
        }
        return await self.async_step_login()

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> ConfigFlowResult:
        """Handle the user step."""
        if self._manager is None:
            self._manager = HASSTuyaBLEDeviceManager(self.hass, self._data)
        await self._manager.build_cache()
        return await self.async_step_login()

    async def async_step_login(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the Tuya IOT platform login step."""
        data: dict[str, Any] | None = None
        errors: dict[str, str] = {}
        placeholders: dict[str, Any] = {}

        if user_input is not None:
            if self._manager is None:
                self._manager = HASSTuyaBLEDeviceManager(self.hass, self._data)
            data = await _try_login(
                self._manager,
                user_input,
                errors,
                placeholders,
            )
            if data:
                self._data.update(data)
                return await self.async_step_device()
            # Login failed - go to step that offers alternative
            return await self.async_step_login_failed()

        if user_input is None:
            user_input = {}
            if self._discovery_info:
                if self._manager is None:
                    self._manager = HASSTuyaBLEDeviceManager(self.hass, self._data)
                await self._manager.get_device_credentials(self._discovery_info.address)
            if self._data is None or len(self._data) == 0:
                if self._manager is None:
                    self._manager = HASSTuyaBLEDeviceManager(self.hass, self._data)
                self._manager.get_login_from_cache()
            if self._data is not None and len(self._data) > 0:
                user_input.update(self._data)

        return _show_login_form(self, user_input, errors, placeholders)

    async def async_step_login_failed(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle login failure - offer alternatives."""
        if user_input is not None:
            if user_input.get("choice") == "manual":
                return await self.async_step_manual_credentials()
            # retry
            return await self.async_step_login()

        return self.async_show_form(
            step_id="login_failed",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "choice",
                        default="manual",
                    ): vol.In(
                        {
                            "retry": "Try again with different credentials",
                            "manual": "Use manual device credentials instead",
                        }
                    ),
                }
            ),
            description_placeholders={
                "error": (
                    "Cloud login failed. Cloud login can fail due to IP "
                    "restrictions, account permissions, or incorrect "
                    "credentials. Please choose an option:"
                )
            },
        )

    async def _get_device_credentials(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> TuyaBLEDeviceCredentials | None:
        """Get device credentials from manual entry or cloud."""
        if self._data.get(CONF_UUID) and self._data.get(CONF_LOCAL_KEY):
            # Use manual credentials
            uuid = self._data.get(CONF_UUID)
            local_key = self._data.get(CONF_LOCAL_KEY)
            device_id = self._data.get(CONF_DEVICE_ID)
            category = self._data.get(CONF_CATEGORY)
            product_id = self._data.get(CONF_PRODUCT_ID)

            if uuid and local_key and device_id and category and product_id:
                return TuyaBLEDeviceCredentials.create(
                    uuid,
                    local_key,
                    device_id,
                    category,
                    product_id,
                    self._data.get(CONF_DEVICE_NAME),
                    self._data.get(CONF_PRODUCT_MODEL),
                    self._data.get(CONF_PRODUCT_NAME),
                )
        # Try to get credentials from cloud
        if self._manager is None:
            self._manager = HASSTuyaBLEDeviceManager(self.hass, self._data)
        return await self._manager.get_device_credentials(discovery_info.address)

    async def async_step_device(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the user step to pick discovered device."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            discovery_info = self._discovered_devices[address]
            local_name = await get_device_readable_name(discovery_info, self._manager)
            await self.async_set_unique_id(
                discovery_info.address, raise_on_progress=False
            )
            self._abort_if_unique_id_configured()

            credentials = await self._get_device_credentials(discovery_info)
            self._data[CONF_ADDRESS] = discovery_info.address
            if credentials is None:
                self._get_device_info_error = True
                errors["base"] = "device_not_registered"
            else:
                return self.async_create_entry(
                    title=local_name,
                    data={CONF_ADDRESS: discovery_info.address},
                    options=self._data,
                )

        if discovery := self._discovery_info:
            self._discovered_devices[discovery.address] = discovery
        else:
            current_addresses = self._async_current_ids()
            for discovery in async_discovered_service_info(self.hass):
                if (
                    discovery.address in current_addresses
                    or discovery.address in self._discovered_devices
                    or discovery.service_data is None
                    or SERVICE_UUID not in discovery.service_data
                ):
                    continue
                self._discovered_devices[discovery.address] = discovery

        if not self._discovered_devices:
            return self.async_abort(reason="no_unconfigured_devices")

        def_address: str
        if user_input:
            def_address = user_input.get(CONF_ADDRESS) or next(
                iter(self._discovered_devices)
            )
        else:
            def_address = next(iter(self._discovered_devices))

        return self.async_show_form(
            step_id="device",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ADDRESS,
                        default=def_address,
                    ): vol.In(
                        {
                            service_info.address: await get_device_readable_name(
                                service_info,
                                self._manager,
                            )
                            for service_info in self._discovered_devices.values()
                        }
                    ),
                },
            ),
            errors=errors,
        )

    async def async_step_manual_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle manual entry of device credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Store the manual credentials
            self._data[CONF_UUID] = user_input.get(CONF_UUID, "")
            self._data[CONF_LOCAL_KEY] = user_input.get(CONF_LOCAL_KEY, "")
            self._data[CONF_DEVICE_ID] = user_input.get(CONF_DEVICE_ID, "")
            self._data[CONF_CATEGORY] = user_input.get(CONF_CATEGORY, "")
            self._data[CONF_PRODUCT_ID] = user_input.get(CONF_PRODUCT_ID, "")
            self._data[CONF_DEVICE_NAME] = user_input.get(CONF_DEVICE_NAME, "")
            self._data[CONF_PRODUCT_MODEL] = user_input.get(CONF_PRODUCT_MODEL, "")
            self._data[CONF_PRODUCT_NAME] = user_input.get(CONF_PRODUCT_NAME, "")

            return await self.async_step_device()

        return self.async_show_form(
            step_id="manual_credentials",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UUID,
                        default=self._data.get(CONF_UUID, ""),
                    ): str,
                    vol.Required(
                        CONF_LOCAL_KEY,
                        default=self._data.get(CONF_LOCAL_KEY, ""),
                    ): str,
                    vol.Required(
                        CONF_DEVICE_ID,
                        default=self._data.get(CONF_DEVICE_ID, ""),
                    ): str,
                    vol.Required(
                        CONF_CATEGORY,
                        default=self._data.get(CONF_CATEGORY, ""),
                    ): str,
                    vol.Required(
                        CONF_PRODUCT_ID,
                        default=self._data.get(CONF_PRODUCT_ID, ""),
                    ): str,
                    vol.Optional(
                        CONF_DEVICE_NAME,
                        default=self._data.get(CONF_DEVICE_NAME, ""),
                    ): str,
                    vol.Optional(
                        CONF_PRODUCT_MODEL,
                        default=self._data.get(CONF_PRODUCT_MODEL, ""),
                    ): str,
                    vol.Optional(
                        CONF_PRODUCT_NAME,
                        default=self._data.get(CONF_PRODUCT_NAME, ""),
                    ): str,
                }
            ),
            description_placeholders={
                "help": (
                    "Enter the device credentials. These can typically be "
                    "found in tinytuya or extracted from your Tuya app."
                )
            },
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> TuyaBLEOptionsFlow:
        """Get the options flow for this handler."""
        return TuyaBLEOptionsFlow(config_entry)
