"""
Tuya BLE Cloud integration for Home Assistant.

This module handles Tuya cloud API authentication, device credential caching,
and retrieval for Tuya BLE devices within Home Assistant.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.const import (
    CONF_ADDRESS,
    CONF_COUNTRY_CODE,
    CONF_DEVICE_ID,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from tuya_iot import (
    AuthType,
    TuyaOpenAPI,
)

from .const import (
    CONF_ACCESS_ID,
    CONF_ACCESS_SECRET,
    CONF_APP_TYPE,
    CONF_AUTH_TYPE,
    CONF_CATEGORY,
    CONF_DEVICE_NAME,
    CONF_ENDPOINT,
    CONF_LOCAL_KEY,
    CONF_PRODUCT_ID,
    CONF_PRODUCT_MODEL,
    CONF_PRODUCT_NAME,
    CONF_UUID,
    DOMAIN,
    TUYA_API_DEVICES_URL,
    TUYA_API_FACTORY_INFO_URL,
    TUYA_DOMAIN,
    TUYA_FACTORY_INFO_MAC,
    TUYA_RESPONSE_RESULT,
    TUYA_RESPONSE_SUCCESS,
)
from .tuya_ble import (
    AbstaractTuyaBLEDeviceManager,
    TuyaBLEDeviceCredentials,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


@dataclass
class TuyaCloudCacheItem:
    """
    Cache item for Tuya cloud API, login data, and device credentials.

    Attributes:
        api: TuyaOpenAPI instance or None.
        login: Dictionary containing login information.
        credentials: Dictionary mapping device MAC addresses to their credentials.

    """

    api: TuyaOpenAPI | None
    login_credentials: dict[str, Any]
    devices_credentials: dict[str, dict[str, Any]]


CONF_TUYA_LOGIN_KEYS = [
    CONF_ENDPOINT,
    CONF_ACCESS_ID,
    CONF_ACCESS_SECRET,
    CONF_AUTH_TYPE,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_COUNTRY_CODE,
    CONF_APP_TYPE,
]

CONF_TUYA_DEVICE_KEYS = [
    CONF_UUID,
    CONF_LOCAL_KEY,
    CONF_DEVICE_ID,
    CONF_CATEGORY,
    CONF_PRODUCT_ID,
    CONF_DEVICE_NAME,
    CONF_PRODUCT_NAME,
    CONF_PRODUCT_MODEL,
]

_cache: dict[str, TuyaCloudCacheItem] = {}


class HASSTuyaBLEDeviceManager(AbstaractTuyaBLEDeviceManager):
    """
    Home Assistant-specific Tuya BLE Device Manager.

    Handles login, credential caching, and device credential retrieval
    for Tuya BLE devices using Home Assistant configuration entries and
    Tuya cloud API.
    """

    def __init__(self, hass: HomeAssistant, data: dict[str, Any]) -> None:
        """
        Initialize the HASSTuyaBLEDeviceManager.

        Args:
            hass: HomeAssistant instance.
            data: Dictionary containing configuration data.

        """
        self._hass = hass
        self._data = data

    @staticmethod
    def _is_login_success(response: dict[Any, Any]) -> bool:
        return bool(response.get(TUYA_RESPONSE_SUCCESS, False))

    @staticmethod
    def _get_cache_key(data: dict[str, Any]) -> str:
        key_dict = {key: data.get(key) for key in CONF_TUYA_LOGIN_KEYS}
        return json.dumps(key_dict)

    @staticmethod
    def _has_login_credentials(data: dict[Any, Any]) -> bool:
        return all(data.get(key) is not None for key in CONF_TUYA_LOGIN_KEYS)

    @staticmethod
    def _has_credentials(data: dict[Any, Any]) -> bool:
        return all(data.get(key) is not None for key in CONF_TUYA_DEVICE_KEYS)

    async def login_with_credentials(
        self, data: dict[str, Any], add_to_cache: bool = False
    ) -> dict[Any, Any]:
        """
        Attempt to log in to the Tuya cloud API using provided credentials.

        Args:
            data: Dictionary containing login credentials and configuration.
            add_to_cache: If True, add the login session to the cache.

        Returns:
            Dictionary containing the response from the Tuya cloud API.

        """
        _LOGGER.debug(
            "Attempting login with data: %s\nadd_to_cache: %s",
            {key: data.get(key) for key in CONF_TUYA_LOGIN_KEYS},
            add_to_cache,
        )
        if len(data) == 0:
            return {}

        _LOGGER.debug(
            "Creating TuyaOpenAPI instance with\nendpoint: %s\n"
            "access_id: %s\naccess_secret: %s\nauth_type: %s",
            data.get(CONF_ENDPOINT),
            data.get(CONF_ACCESS_ID),
            data.get(CONF_ACCESS_SECRET),
            data.get(CONF_AUTH_TYPE),
        )

        api = TuyaOpenAPI(
            endpoint=data.get(CONF_ENDPOINT, ""),
            access_id=data.get(CONF_ACCESS_ID, ""),
            access_secret=data.get(CONF_ACCESS_SECRET, ""),
            auth_type=data.get(CONF_AUTH_TYPE, ""),
        )
        api.set_dev_channel("hass")

        response = await self._hass.async_add_executor_job(
            api.connect,
            data.get(CONF_USERNAME, ""),
            data.get(CONF_PASSWORD, ""),
            data.get(CONF_COUNTRY_CODE, ""),
            data.get(CONF_APP_TYPE, ""),
        )

        if self._is_login_success(response):
            _LOGGER.debug("Successful login for %s", data[CONF_USERNAME])
            if add_to_cache:
                auth_type = data[CONF_AUTH_TYPE]
                if type(auth_type) is AuthType:
                    data[CONF_AUTH_TYPE] = auth_type.value
                cache_key = self._get_cache_key(data)
                cache_item = _cache.get(cache_key)
                if cache_item:
                    cache_item.api = api
                    cache_item.login_credentials = data
                else:
                    _cache[cache_key] = TuyaCloudCacheItem(api, data, {})
                await self._fill_cache_item(_cache[cache_key])

        return response

    def _check_login(self) -> bool:
        cache_key = self._get_cache_key(self._data)
        return _cache.get(cache_key) is not None

    async def login_with_stored_credentials(
        self, add_to_cache: bool = False
    ) -> dict[Any, Any]:
        """
        Log in to the Tuya cloud API using internal data.

        Args:
            add_to_cache: If True, add the login session to the cache.

        Returns:
            Dictionary containing the response from the Tuya cloud API.

        """
        _LOGGER.debug("Initiating login with internal data: %s", self._data)
        return await self.login_with_credentials(self._data, add_to_cache)

    async def _fill_cache_item(self, item: TuyaCloudCacheItem) -> None:
        _LOGGER.debug(
            "Filling cache item for user: %s", item.login_credentials.get(CONF_USERNAME)
        )
        if item.api is None:
            _LOGGER.error("TuyaCloudCacheItem.api is None, cannot fetch devices.")
            return

        devices_response = await self._hass.async_add_executor_job(
            item.api.get,
            TUYA_API_DEVICES_URL % (item.api.token_info.uid),
        )
        if devices_response.get(TUYA_RESPONSE_SUCCESS):
            devices = devices_response.get(TUYA_RESPONSE_RESULT)
            if isinstance(devices, Iterable):
                for device in devices:
                    fi_response = await self._hass.async_add_executor_job(
                        item.api.get,
                        TUYA_API_FACTORY_INFO_URL % (device.get("id")),
                    )
                    fi_response_result = fi_response.get(TUYA_RESPONSE_RESULT)
                    if fi_response_result and len(fi_response_result) > 0:
                        factory_info = fi_response_result[0]
                        if factory_info and (TUYA_FACTORY_INFO_MAC in factory_info):
                            mac = ":".join(
                                factory_info[TUYA_FACTORY_INFO_MAC][i : i + 2]
                                for i in range(0, 12, 2)
                            ).upper()
                            item.devices_credentials[mac] = {
                                CONF_ADDRESS: mac,
                                CONF_UUID: device.get("uuid"),
                                CONF_LOCAL_KEY: device.get("local_key"),
                                CONF_DEVICE_ID: device.get("id"),
                                CONF_CATEGORY: device.get("category"),
                                CONF_PRODUCT_ID: device.get("product_id"),
                                CONF_DEVICE_NAME: device.get("name"),
                                CONF_PRODUCT_MODEL: device.get("model"),
                                CONF_PRODUCT_NAME: device.get("product_name"),
                            }
                    _LOGGER.debug(
                        "Cache item filled for %s: %s",
                        item.login_credentials.get(CONF_USERNAME),
                        list(item.devices_credentials.keys()),
                    )

    async def build_cache(self) -> None:
        """
        Build and populate the cache with Tuya BLE device credentials.

        Iterates through Tuya and BLE config entries, logs in if necessary,
        and fills the cache with device credentials.
        """
        _LOGGER.debug("Building cache with current configuration entries.")
        data = {}
        tuya_config_entries = self._hass.config_entries.async_entries(TUYA_DOMAIN)
        for config_entry in tuya_config_entries:
            _LOGGER.debug(
                "Processing Tuya config entry %s with data: %s",
                config_entry.entry_id,
                {key: config_entry.data.get(key) for key in CONF_TUYA_LOGIN_KEYS},
            )
            data.clear()
            data.update(config_entry.data)
            key = self._get_cache_key(data)
            item = _cache.get(key)
            if (
                item is None or len(item.devices_credentials) == 0
            ) and self._is_login_success(
                await self.login_with_credentials(data, add_to_cache=True)
            ):
                _LOGGER.debug(
                    "Login successful for config entry %s, updating cache for key: %s",
                    config_entry.entry_id,
                    key,
                )
                item = _cache.get(key)
                if item and len(item.devices_credentials) == 0:
                    await self._fill_cache_item(item)

        ble_config_entries = self._hass.config_entries.async_entries(DOMAIN)
        for config_entry in ble_config_entries:
            _LOGGER.debug(
                "Processing BLE config entry %s with options: %s",
                config_entry.entry_id,
                {key: config_entry.options.get(key) for key in CONF_TUYA_LOGIN_KEYS},
            )
            data.clear()
            data.update(config_entry.options)
            key = self._get_cache_key(data)
            item = _cache.get(key)
            if (
                item is None or len(item.devices_credentials) == 0
            ) and self._is_login_success(
                await self.login_with_credentials(data, add_to_cache=True)
            ):
                _LOGGER.debug(
                    "Login successful for BLE config entry %s, updating cache for key: %s",
                    config_entry.entry_id,
                    key,
                )
                item = _cache.get(key)
                if item and len(item.devices_credentials) == 0:
                    await self._fill_cache_item(item)

    def get_login_from_cache(self) -> None:
        """
        Update self._data with login information from the first cache item found.

        This method iterates through the cache and updates the internal data dictionary
        with login information from the first available cache item.
        """
        for cache_item in _cache.values():
            self._data.update(cache_item.login_credentials)
            break

    async def get_device_credentials(
        self,
        address: str,
        force_update: bool = False,  # noqa: FBT001, FBT002
        save_data: bool = False,  # noqa: FBT001, FBT002
    ) -> TuyaBLEDeviceCredentials | None:
        """
        Retrieve Tuya BLE device credentials for a given device address.

        Args:
            address: The MAC address of the device.
            force_update: If True, forces cache update and credential retrieval.
            save_data: If True, updates internal data with retrieved credentials.

        Returns:
            TuyaBLEDeviceCredentials object if credentials are found, otherwise None.

        """
        _LOGGER.debug(
            "Retrieving device credentials for address: %s\nforce_update: %s\nsave_data: %s",
            address,
            force_update,
            save_data,
        )
        credentials: dict[str, Any] | None = None
        item: TuyaCloudCacheItem | None = None

        cache_key = None
        if self._has_credentials(self._data) and not force_update:
            _LOGGER.debug("Credentials found in internal data, using them directly.")
            credentials = self._data.copy()
        else:
            if self._has_login_credentials(self._data):
                _LOGGER.debug(
                    "Login credentials found in internal data, looking for cache key."
                )
                cache_key = self._get_cache_key(self._data)
            else:
                _LOGGER.debug(
                    "No login credentials in internal data, searching cache for address: %s",
                    address,
                )
                cache_key = next(
                    (
                        key
                        for key, cache_item in _cache.items()
                        if cache_item.devices_credentials.get(address)
                    ),
                    None,
                )
            _LOGGER.debug("Cache key determined: %s", cache_key)
            item = _cache.get(cache_key) if cache_key else None
            _LOGGER.debug(
                "Cache item retrieved for key %s: %s",
                cache_key,
                {key: item.login_credentials.get(key) for key in CONF_TUYA_LOGIN_KEYS}
                if item
                else None,
            )

            if (force_update or item is None) and self._is_login_success(
                await self.login_with_stored_credentials(add_to_cache=True)
            ):
                _LOGGER.debug(
                    "Login successful with stored credentials, updating cache for key: %s",
                    cache_key,
                )
                item = _cache.get(cache_key) if cache_key is not None else None
                if not item and cache_key:
                    _cache[cache_key] = TuyaCloudCacheItem(None, self._data.copy(), {})
                    item = _cache[cache_key]
                if item:
                    await self._fill_cache_item(item)

            credentials = item.devices_credentials.get(address) if item else None

        if not credentials:
            return None

        result = TuyaBLEDeviceCredentials(
            credentials.get(CONF_UUID, ""),
            credentials.get(CONF_LOCAL_KEY, ""),
            credentials.get(CONF_DEVICE_ID, ""),
            credentials.get(CONF_CATEGORY, ""),
            credentials.get(CONF_PRODUCT_ID, ""),
            credentials.get(CONF_DEVICE_NAME, ""),
            credentials.get(CONF_PRODUCT_MODEL, ""),
            credentials.get(CONF_PRODUCT_NAME, ""),
        )
        _LOGGER.debug(
            "Device credentials retrieved for address %s: %s",
            address,
            {key: credentials.get(key) for key in CONF_TUYA_DEVICE_KEYS},
        )
        if save_data:
            _LOGGER.debug(
                "Updating internal data with credentials for address: %s", address
            )
            if item:
                self._data.update(item.login_credentials)
            self._data.update(credentials)

        return result

    @property
    def data(self) -> dict[str, Any]:
        """Return the internal data dictionary used for Tuya BLE device management."""
        return self._data
