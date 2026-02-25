"""The Tuya BLE integration."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

from homeassistant.components.tuya.const import (
    CONF_ENDPOINT,
    TUYA_RESPONSE_RESULT,
    TUYA_RESPONSE_SUCCESS,
)
from homeassistant.components.tuya.const import (
    DOMAIN as TUYA_DOMAIN,
)
from homeassistant.const import (
    CONF_ADDRESS,
    CONF_COUNTRY_CODE,
    CONF_DEVICE_ID,
    CONF_PASSWORD,
    CONF_USERNAME,
)
from tuya_iot import (
    TuyaOpenAPI,
)

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
    TUYA_API_DEVICES_URL,
    TUYA_API_FACTORY_INFO_URL,
    TUYA_FACTORY_INFO_MAC,
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
    Cache item for Tuya Cloud API connection and device credentials.

    Attributes
    ----------
    api : TuyaOpenAPI | None
        The Tuya Open API instance for cloud communication.
    login : dict[str, Any]
        Login credentials and configuration data.
    credentials : dict[str, dict[str, Any]]
        Device credentials indexed by MAC address.

    """

    api: TuyaOpenAPI | None
    login: dict[str, Any]
    credentials: dict[str, dict[str, Any]]


CONF_TUYA_LOGIN_KEYS = [
    CONF_ENDPOINT,
    CONF_ACCESS_ID,
    CONF_ACCESS_SECRET,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_COUNTRY_CODE,
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


class CacheConfiguration(Enum):
    """
    Configuration for cache behavior.

    Attributes
    ----------
    ENABLE : int
        Enable caching of credentials.
    DISABLE : int
        Disable caching of credentials.

    """

    ENABLE = 1
    DISABLE = 2


_cache: dict[str, TuyaCloudCacheItem] = {}


class HASSTuyaBLEDeviceManager(AbstaractTuyaBLEDeviceManager):
    """Cloud connected manager of the Tuya BLE devices credentials."""

    def __init__(self, hass: HomeAssistant, data: dict[str, Any]) -> None:
        """Initialize the manager with a Home Assistant instance and config data."""
        if hass is None:
            msg = "Home Assistant instance cannot be None."
            raise ValueError(msg)
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
    def _has_login(data: dict[Any, Any]) -> bool:
        return all(data.get(key) is not None for key in CONF_TUYA_LOGIN_KEYS)

    @staticmethod
    def _has_credentials(data: dict[Any, Any]) -> bool:
        return all(data.get(key) is not None for key in CONF_TUYA_DEVICE_KEYS)

    async def _login(
        self,
        data: dict[str, Any],
        cache_config: CacheConfiguration = CacheConfiguration.DISABLE,
    ) -> dict[Any, Any]:
        """Login into Tuya cloud using credentials from data dictionary."""
        if len(data) == 0:
            return {}

        access_id = data.get(CONF_ACCESS_ID, "")
        access_secret = data.get(CONF_ACCESS_SECRET, "")
        username = data.get(CONF_USERNAME, "")
        password = data.get(CONF_PASSWORD, "")
        country_code = data.get(CONF_COUNTRY_CODE, "")
        endpoint = data.get(CONF_ENDPOINT, "")

        _LOGGER.debug(
            "Tuya API connection attempt - endpoint: %s, access_id: %s,"
            "access_secret_len: %d, username: %s, country_code: %s",
            endpoint,
            access_id,
            len(access_secret),
            username,
            country_code,
        )

        api = TuyaOpenAPI(
            endpoint=endpoint,
            access_id=access_id,
            access_secret=access_secret,
        )
        api.set_dev_channel("hass")

        response = await self._hass.async_add_executor_job(
            api.connect,
            username,
            password,
            country_code,
        )

        _LOGGER.debug("Tuya API response: %s", response)

        if self._is_login_success(response):
            _LOGGER.debug("Successful login for %s", data[CONF_USERNAME])
            if cache_config == CacheConfiguration.ENABLE:
                cache_key = self._get_cache_key(data)
                cache_item = _cache.get(cache_key)
                if cache_item:
                    cache_item.api = api
                    cache_item.login = data
                else:
                    _cache[cache_key] = TuyaCloudCacheItem(api, data, {})
        else:
            _LOGGER.error(
                "Failed login for %s: %s",
                data[CONF_USERNAME],
                response,
            )

        return response

    def _check_login(self) -> bool:
        cache_key = self._get_cache_key(self._data)
        return _cache.get(cache_key) is not None

    async def login(
        self,
        cache_config: CacheConfiguration = CacheConfiguration.DISABLE,
    ) -> dict[Any, Any]:
        """
        Log in to the Tuya cloud using stored configuration data.

        Parameters
        ----------
        cache_config : CacheConfiguration, optional
            Whether to store the login session in the shared cache,
            by default CacheConfiguration.DISABLE.

        Returns
        -------
        dict[Any, Any]
            The raw response from the Tuya API login request.

        """
        return await self._login(self._data, cache_config)

    async def login_cached(
        self,
        cache_config: CacheConfiguration = CacheConfiguration.DISABLE,
    ) -> dict[Any, Any]:
        """
        Log in to the Tuya cloud using stored configuration data.

        Parameters
        ----------
        cache_config : CacheConfiguration, optional
            Whether to store the login session in the shared cache,
            by default CacheConfiguration.DISABLE.

        Returns
        -------
        dict[Any, Any]
            The raw response from the Tuya API login request.

        """
        return await self._login(self._data, cache_config)

    async def _fill_cache_item(self, item: TuyaCloudCacheItem) -> None:
        if item.api is None:
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
                            item.credentials[mac] = {
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

    async def build_cache(self) -> None:
        """
        Build the cache of device credentials from Tuya cloud.

        Retrieves credentials from all configured Tuya integrations (both regular
        Tuya and Tuya BLE) and populates the shared cache with device information.

        """
        data = {}
        tuya_config_entries = self._hass.config_entries.async_entries(TUYA_DOMAIN)
        for config_entry in tuya_config_entries:
            data.clear()
            data.update(config_entry.data)
            # Only try to login if the data has the required credentials
            if not all(k in data for k in CONF_TUYA_LOGIN_KEYS):
                continue
            key = self._get_cache_key(data)
            item = _cache.get(key)
            if (item is None or len(item.credentials) == 0) and self._is_login_success(
                await self._login(data, cache_config=CacheConfiguration.ENABLE)
            ):
                item = _cache.get(key)
                if item and len(item.credentials) == 0:
                    await self._fill_cache_item(item)

        ble_config_entries = self._hass.config_entries.async_entries(DOMAIN)
        for config_entry in ble_config_entries:
            data.clear()
            data.update(config_entry.options)
            # Only try to login if the data has the required credentials
            if not all(k in data for k in CONF_TUYA_LOGIN_KEYS):
                continue
            key = self._get_cache_key(data)
            item = _cache.get(key)
            if (item is None or len(item.credentials) == 0) and self._is_login_success(
                await self._login(data, cache_config=CacheConfiguration.ENABLE)
            ):
                item = _cache.get(key)
                if item and len(item.credentials) == 0:
                    await self._fill_cache_item(item)

    def get_login_from_cache(self) -> None:
        """
        Retrieve login credentials from the cache.

        Updates the instance data with login credentials from the first
        available cached item.

        """
        for cache_item in _cache.values():
            self._data.update(cache_item.login)
            break

    def _find_cache_key_for_address(self, address: str) -> str | None:
        """Find the cache key that contains credentials for the given address."""
        if self._has_login(self._data):
            return self._get_cache_key(self._data)

        for key, cache_item in _cache.items():
            if cache_item.credentials.get(address) is not None:
                return key
        return None

    async def _ensure_cache_item(
        self, cache_key: str | None
    ) -> TuyaCloudCacheItem | None:
        """Ensure cache item exists and is populated."""
        if not cache_key:
            return None

        item = _cache.get(cache_key)
        if item is None and self._is_login_success(
            await self.login(cache_config=CacheConfiguration.ENABLE)
        ):
            item = _cache.get(cache_key)

        if item:
            await self._fill_cache_item(item)

        return item

    def _create_credentials_from_dict(
        self, credentials: dict[str, Any]
    ) -> TuyaBLEDeviceCredentials | None:
        """Create TuyaBLEDeviceCredentials from a dictionary."""
        uuid = credentials.get(CONF_UUID)
        local_key = credentials.get(CONF_LOCAL_KEY)
        device_id = credentials.get(CONF_DEVICE_ID)
        category = credentials.get(CONF_CATEGORY)
        product_id = credentials.get(CONF_PRODUCT_ID)

        if uuid and local_key and device_id and category and product_id:
            return TuyaBLEDeviceCredentials.create(
                uuid,
                local_key,
                device_id,
                category,
                product_id,
                credentials.get(CONF_DEVICE_NAME),
                credentials.get(CONF_PRODUCT_MODEL),
                credentials.get(CONF_PRODUCT_NAME),
            )
        return None

    async def get_device_credentials(
        self,
        address: str,
        *,
        force_update: bool = False,
        save_data: bool = False,
    ) -> TuyaBLEDeviceCredentials | None:
        """Get credentials of the Tuya BLE device."""
        credentials: dict[str, Any] | None = None
        item: TuyaCloudCacheItem | None = None

        if not force_update and self._has_credentials(self._data):
            credentials = self._data.copy()
        else:
            cache_key = self._find_cache_key_for_address(address)
            item = (
                await self._ensure_cache_item(cache_key)
                if force_update or (cache_key and not _cache.get(cache_key))
                else _cache.get(cache_key)
                if cache_key
                else None
            )
            if item:
                credentials = item.credentials.get(address)

        if not credentials:
            return None

        result = self._create_credentials_from_dict(credentials)
        _LOGGER.debug("Retrieved: %s", result)

        if save_data:
            if item:
                self._data.update(item.login)
            self._data.update(credentials)

        return result

    @property
    def data(self) -> dict[str, Any]:
        """
        Get the configuration data dictionary.

        Returns
        -------
        dict[str, Any]
            The configuration data for this device manager instance.

        """
        return self._data
