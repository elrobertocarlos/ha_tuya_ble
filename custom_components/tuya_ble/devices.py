"""
Tuya BLE device integration for Home Assistant.

This module provides classes and utilities for managing Tuya BLE devices,
including device coordinators, entities, product information, and device
registry integration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.const import CONF_ADDRESS, CONF_DEVICE_ID
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import (
    EntityDescription,
    generate_entity_id,
)
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import (
    DEVICE_DEF_MANUFACTURER,
    DOMAIN,
    FINGERBOT_BUTTON_EVENT,
    SET_DISCONNECTED_DELAY,
)

if TYPE_CHECKING:
    from home_assistant_bluetooth import BluetoothServiceInfoBleak

    from .cloud import HASSTuyaBLEDeviceManager
    from .tuya_ble import (
        AbstaractTuyaBLEDeviceManager,
        TuyaBLEDataPoint,
        TuyaBLEDevice,
        TuyaBLEDeviceCredentials,
    )

_LOGGER = logging.getLogger(__name__)


@dataclass
class TuyaBLEFingerbotInfo:
    """
    Fingerbot device configuration information.

    Attributes
    ----------
    switch : int
        The switch data point ID.
    mode : int
        The mode data point ID.
    up_position : int
        The up position data point ID.
    down_position : int
        The down position data point ID.
    hold_time : int
        The hold time data point ID.
    reverse_positions : int
        The reverse positions data point ID.
    manual_control : int
        The manual control data point ID. Defaults to 0.
    program : int
        The program data point ID. Defaults to 0.

    """

    switch: int
    mode: int
    up_position: int
    down_position: int
    hold_time: int
    reverse_positions: int
    manual_control: int = 0
    program: int = 0


@dataclass
class TuyaBLEProductInfo:
    """
    Product information for a Tuya BLE device.

    Attributes
    ----------
    name : str
        The product name.
    manufacturer : str
        The manufacturer name. Defaults to DEVICE_DEF_MANUFACTURER.
    fingerbot : TuyaBLEFingerbotInfo | None
        Fingerbot-specific configuration, if applicable. Defaults to None.

    """

    name: str
    manufacturer: str = DEVICE_DEF_MANUFACTURER
    fingerbot: TuyaBLEFingerbotInfo | None = None


class TuyaBLEEntity(CoordinatorEntity):
    """
    Tuya BLE base entity.

    Provides common functionality for all Tuya BLE entities, including device info,
    availability status, and coordinator update handling.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: TuyaBLECoordinator,
        device: TuyaBLEDevice,
        product: TuyaBLEProductInfo,
        description: EntityDescription,
    ) -> None:
        super().__init__(coordinator)
        self._hass = hass
        self._coordinator = coordinator
        self._device = device
        self._product = product
        if description.translation_key is None:
            self._attr_translation_key = description.key
        self.entity_description = description
        self._attr_has_entity_name = True
        self._attr_unique_id = f"{self._device.device_id}-{description.key}"
        self.entity_id = generate_entity_id(
            "sensor.{}", self._attr_unique_id, hass=hass
        )

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device info."""
        return get_device_info(self._device)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._coordinator.connected

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class TuyaBLECoordinator(DataUpdateCoordinator[None]):
    """
    Data coordinator for receiving Tuya BLE updates.

    Manages device connection state, firmware updates, and data updates for Tuya BLE
    devices.
    """

    def __init__(
        self, hass: HomeAssistant, device: TuyaBLEDevice, entry_id: str
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
        )
        self._device = device
        self._entry_id = entry_id
        self._disconnected: bool = True
        self._unsub_disconnect: CALLBACK_TYPE | None = None
        device.register_connected_callback(self._async_handle_connect)
        device.register_callback(self._async_handle_update)
        device.register_disconnected_callback(self._async_handle_disconnect)

        # ...existing code...

    @property
    def connected(self) -> bool:
        """Return True when the device is connected."""
        return not self._disconnected

    @callback
    def _async_handle_connect(self) -> None:
        if self._unsub_disconnect is not None:
            self._unsub_disconnect()
        if self._disconnected:
            self._disconnected = False
            # Update device registry with current device info
            # (including firmware version)
            device_registry = dr.async_get(self.hass)
            device_info = get_device_info(self._device)
            if device_info:
                _LOGGER.debug(
                    "%s: Updating device registry with sw_version: %s",
                    self._device.address,
                    device_info.get("sw_version"),
                )
                # Get existing device entry
                identifiers = device_info.get("identifiers")
                if identifiers:
                    device = device_registry.async_get_device(identifiers=identifiers)
                    if device:
                        # Update existing device with new firmware version
                        device_registry.async_update_device(
                            device.id,
                            sw_version=device_info.get("sw_version"),
                            hw_version=device_info.get("hw_version"),
                        )
            self.async_update_listeners()

    @callback
    def _async_handle_update(self, updates: list[TuyaBLEDataPoint]) -> None:
        """Just trigger the callbacks."""
        self._async_handle_connect()
        self.async_set_updated_data(None)
        info = get_device_product_info(self._device)
        if info and info.fingerbot and info.fingerbot.manual_control != 0:
            for update in updates:
                if update.id == info.fingerbot.switch and update.changed_by_device:
                    self.hass.bus.fire(
                        FINGERBOT_BUTTON_EVENT,
                        {
                            CONF_ADDRESS: self._device.address,
                            CONF_DEVICE_ID: self._device.device_id,
                        },
                    )

    @callback
    def _set_disconnected(self, _: None) -> None:
        """Invoke the idle timeout callback, called when the alarm fires."""
        self._disconnected = True
        self._unsub_disconnect = None
        self.async_update_listeners()

    @callback
    def _async_handle_disconnect(self) -> None:
        """Trigger the callbacks for disconnected."""
        if self._unsub_disconnect is None:
            delay: float = SET_DISCONNECTED_DELAY
            self._unsub_disconnect = async_call_later(
                self.hass, delay, self._set_disconnected
            )


@dataclass
class TuyaBLEData:
    """
    Data for the Tuya BLE integration.

    Attributes
    ----------
    title : str
        The display title for the device.
    device : TuyaBLEDevice
        The Tuya BLE device instance.
    product : TuyaBLEProductInfo
        Product information for the device.
    manager : HASSTuyaBLEDeviceManager
        The device manager instance.
    coordinator : TuyaBLECoordinator
        The data coordinator for the device.

    """

    title: str
    device: TuyaBLEDevice
    product: TuyaBLEProductInfo
    manager: HASSTuyaBLEDeviceManager
    coordinator: TuyaBLECoordinator


@dataclass
class TuyaBLECategoryInfo:
    """
    Category information for Tuya BLE devices.

    Attributes
    ----------
    products : dict[str, TuyaBLEProductInfo]
        Mapping of product IDs to product information.
    info : TuyaBLEProductInfo | None
        Default product information for the category. Defaults to None.

    """

    products: dict[str, TuyaBLEProductInfo]
    info: TuyaBLEProductInfo | None = None


devices_database: dict[str, TuyaBLECategoryInfo] = {
    "cl": TuyaBLECategoryInfo(
        products={
            "kcy0x4pi": TuyaBLEProductInfo(  # Smart curtain robot 4
                name="Smart Curtain Robot",
            ),
        },
    ),
    "co2bj": TuyaBLECategoryInfo(
        products={
            "59s19z5m": TuyaBLEProductInfo(  # device product_id
                name="CO2 Detector",
            ),
        },
    ),
    "ms": TuyaBLECategoryInfo(
        products={
            **dict.fromkeys(
                ["ludzroix", "isk2p555"],
                TuyaBLEProductInfo(  # device product_id
                    name="Smart Lock",
                ),
            ),
        },
    ),
    "jtmspro": TuyaBLECategoryInfo(
        products={
            "ebd5e0uauqx0vfsp": TuyaBLEProductInfo(  # device product_id
                name="CentralAcesso",
            ),
        },
    ),
    "szjqr": TuyaBLECategoryInfo(
        products={
            "3yqdo5yt": TuyaBLEProductInfo(  # device product_id
                name="CUBETOUCH 1s",
                fingerbot=TuyaBLEFingerbotInfo(
                    switch=1,
                    mode=2,
                    up_position=5,
                    down_position=6,
                    hold_time=3,
                    reverse_positions=4,
                ),
            ),
            "xhf790if": TuyaBLEProductInfo(  # device product_id
                name="CubeTouch II",
                fingerbot=TuyaBLEFingerbotInfo(
                    switch=1,
                    mode=2,
                    up_position=5,
                    down_position=6,
                    hold_time=3,
                    reverse_positions=4,
                ),
            ),
            **dict.fromkeys(
                ["blliqpsj", "ndvkgsrm", "yiihr7zh", "neq16kgd"],  # device product_ids
                TuyaBLEProductInfo(
                    name="Fingerbot Plus",
                    fingerbot=TuyaBLEFingerbotInfo(
                        switch=2,
                        mode=8,
                        up_position=15,
                        down_position=9,
                        hold_time=10,
                        reverse_positions=11,
                        manual_control=17,
                        program=121,
                    ),
                ),
            ),
            **dict.fromkeys(
                [
                    "ltak7e1p",
                    "y6kttvd6",
                    "yrnk7mnn",
                    "nvr2rocq",
                    "bnt7wajf",
                    "rvdceqjh",
                    "5xhbk964",
                ],  # device product_ids
                TuyaBLEProductInfo(
                    name="Fingerbot",
                    fingerbot=TuyaBLEFingerbotInfo(
                        switch=2,
                        mode=8,
                        up_position=15,
                        down_position=9,
                        hold_time=10,
                        reverse_positions=11,
                        program=121,
                    ),
                ),
            ),
        },
    ),
    "kg": TuyaBLECategoryInfo(
        products={
            **dict.fromkeys(
                ["mknd4lci", "riecov42"],  # device product_ids
                TuyaBLEProductInfo(
                    name="Fingerbot Plus",
                    fingerbot=TuyaBLEFingerbotInfo(
                        switch=1,
                        mode=101,
                        up_position=106,
                        down_position=102,
                        hold_time=103,
                        reverse_positions=104,
                        manual_control=107,
                        program=109,
                    ),
                ),
            ),
        },
    ),
    "wk": TuyaBLECategoryInfo(
        products={
            **dict.fromkeys(
                [
                    "drlajpqc",
                    "nhj2j7su",
                ],  # device product_id
                TuyaBLEProductInfo(
                    name="Thermostatic Radiator Valve",
                ),
            ),
        },
    ),
    "wsdcg": TuyaBLECategoryInfo(
        products={
            "ojzlzzsw": TuyaBLEProductInfo(  # device product_id
                name="Soil moisture sensor",
            ),
        },
    ),
    "znhsb": TuyaBLECategoryInfo(
        products={
            "cdlandip":  # device product_id
            TuyaBLEProductInfo(
                name="Smart water bottle",
            ),
        },
    ),
    "sfkzq": TuyaBLECategoryInfo(
        products={
            "nxquc5lb": TuyaBLEProductInfo(
                name="Water valve controller",
            ),
        },
    ),
    "ggq": TuyaBLECategoryInfo(
        products={
            **dict.fromkeys(
                [
                    "6pahkcau",
                    "hfgdqhho",
                    "fnlw6npo",
                ],  # device product_id
                TuyaBLEProductInfo(
                    name="Irrigation computer",
                ),
            ),
        },
    ),
}


def get_product_info_by_ids(
    category: str, product_id: str
) -> TuyaBLEProductInfo | None:
    """
    Get product information by category and product ID.

    Parameters
    ----------
    category : str
        The device category.
    product_id : str
        The product ID.

    Returns
    -------
    TuyaBLEProductInfo | None
        Product information if found, otherwise category default info or None.

    """
    category_info = devices_database.get(category)
    if category_info is not None:
        product_info = category_info.products.get(product_id)
        if product_info is not None:
            return product_info
        return category_info.info
    return None


def get_device_product_info(device: TuyaBLEDevice) -> TuyaBLEProductInfo | None:
    """
    Get product information for a Tuya BLE device.

    Parameters
    ----------
    device : TuyaBLEDevice
        The Tuya BLE device.

    Returns
    -------
    TuyaBLEProductInfo | None
        Product information if found, otherwise None.

    """
    return get_product_info_by_ids(device.category, device.product_id)


def get_short_address(address: str) -> str:
    """
    Get the last 6 characters of a formatted Bluetooth address.

    Parameters
    ----------
    address : str
        The Bluetooth address string.

    Returns
    -------
    str
        The last 6 characters of the formatted address.

    """
    results = address.replace("-", ":").upper().split(":")
    return f"{results[-3]}{results[-2]}{results[-1]}"[-6:]


async def get_device_readable_name(
    discovery_info: BluetoothServiceInfoBleak,
    manager: AbstaractTuyaBLEDeviceManager | None,
) -> str:
    """
    Build a readable device name for discovered Tuya BLE devices.

    Parameters
    ----------
    discovery_info : BluetoothServiceInfoBleak
        The BLE discovery information for the device.
    manager : AbstaractTuyaBLEDeviceManager | None
        Manager used to resolve credentials and product details.

    Returns
    -------
    str
        A user-friendly device name including a short address suffix.

    """
    credentials: TuyaBLEDeviceCredentials | None = None
    product_info: TuyaBLEProductInfo | None = None
    if manager:
        credentials = await manager.get_device_credentials(discovery_info.address)
        if credentials:
            product_info = get_product_info_by_ids(
                credentials.category,
                credentials.product_id,
            )
    short_address = get_short_address(discovery_info.address)
    if product_info:
        return f"{product_info.name} {short_address}"
    if credentials:
        return f"{credentials.device_name} {short_address}"
    return f"{discovery_info.device.name} {short_address}"


def get_device_info(device: TuyaBLEDevice) -> DeviceInfo | None:
    """
    Get device information for Home Assistant device registry.

    Parameters
    ----------
    device : TuyaBLEDevice
        The Tuya BLE device.

    Returns
    -------
    DeviceInfo | None
        Device information including connections, identifiers, manufacturer, model, and
        version info.

    """
    product_info = None
    if device.category and device.product_id:
        product_info = get_product_info_by_ids(device.category, device.product_id)
    product_name: str
    product_name = product_info.name if product_info else device.name
    return DeviceInfo(
        connections={(dr.CONNECTION_BLUETOOTH, device.address)},
        hw_version=device.hardware_version,
        identifiers={(DOMAIN, device.address)},
        manufacturer=(
            product_info.manufacturer if product_info else DEVICE_DEF_MANUFACTURER
        ),
        model=(f"{device.product_model or product_name} ({device.product_id})"),
        name=(f"{product_name} {get_short_address(device.address)}"),
        sw_version=(f"{device.device_version} (protocol {device.protocol_version})"),
    )
