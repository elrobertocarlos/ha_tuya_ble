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

from habluetooth import BluetoothScanningMode
from homeassistant.components.bluetooth.passive_update_coordinator import (
    PassiveBluetoothCoordinatorEntity,
    PassiveBluetoothDataUpdateCoordinator,
)
from homeassistant.const import CONF_ADDRESS, CONF_DEVICE_ID
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import (
    EntityDescription,
    generate_entity_id,
)
from homeassistant.helpers.event import async_call_later

from .const import (
    DEVICE_DEF_MANUFACTURER,
    DOMAIN,
    FINGERBOT_BUTTON_EVENT,
    SET_DISCONNECTED_DELAY,
)

if TYPE_CHECKING:
    import datetime

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
class TuyaBLELockInfo:
    """
    Lock device configuration information.

    Attributes
    ----------
    alarm_lock : int
        The alarm lock data point ID.
    unlock_ble : int
        The BLE unlock data point ID.
    unlock_fingerprint : int
        The fingerprint unlock data point ID.
    unlock_password : int
        The password unlock data point ID.

    """

    alarm_lock: int
    unlock_ble: int
    unlock_fingerprint: int
    unlock_password: int


@dataclass
class TuyaBLEProductInfo:
    """
    Product information for Tuya BLE devices.

    Attributes
    ----------
    name : str
        The product name.
    manufacturer : str
        The manufacturer name. Defaults to DEVICE_DEF_MANUFACTURER.
    fingerbot : TuyaBLEFingerbotInfo | None
        Fingerbot configuration information, if applicable.
    lock : TuyaBLELockInfo | None
        Lock configuration information, if applicable.

    """

    name: str
    manufacturer: str = DEVICE_DEF_MANUFACTURER
    fingerbot: TuyaBLEFingerbotInfo | None = None
    lock: TuyaBLELockInfo | None = None


class TuyaBLEEntity(PassiveBluetoothCoordinatorEntity):
    """
    Tuya BLE base entity.

    Provides common functionality for all Tuya BLE entities, including device info,
    availability status, and coordinator update handling.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: TuyaBLEPassiveCoordinator,
        device: TuyaBLEDevice,
        product: TuyaBLEProductInfo,
        description: EntityDescription,
    ) -> None:
        """
        Initialize a TuyaBLEEntity.

        Parameters
        ----------
        hass : HomeAssistant
            The Home Assistant instance.
        coordinator : TuyaBLEPassiveCoordinator
            The data update coordinator.
        device : TuyaBLEDevice
            The Tuya BLE device instance.
        product : TuyaBLEProductInfo
            Product information for the device.
        description : EntityDescription
            Entity description for Home Assistant.

        """
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


class TuyaBLEPassiveCoordinator(PassiveBluetoothDataUpdateCoordinator):
    """
    Passive coordinator for Tuya BLE devices.

    Manages passive Bluetooth updates, device connection state,
    and event firing for Tuya BLE devices.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        logger: logging.Logger,
        address: str,
        device: TuyaBLEDevice,
    ) -> None:
        """
        Initialize the TuyaBLEPassiveCoordinator.

        Parameters
        ----------
        hass : HomeAssistant
            The Home Assistant instance.
        logger : logging.Logger
            Logger instance.
        address : str
            Bluetooth address of the device.
        device : TuyaBLEDevice
            The Tuya BLE device instance.

        """
        super().__init__(
            hass, logger, address, BluetoothScanningMode.ACTIVE, connectable=True
        )
        self._device = device
        self._disconnected: bool = True
        self._unsub_disconnect: CALLBACK_TYPE | None = None
        self._unsub_refresh_requests: list[CALLBACK_TYPE] = []
        device.register_connected_callback(self._async_handle_connect)
        device.register_callback(self._async_handle_update)
        device.register_disconnected_callback(self._async_handle_disconnect)

    @property
    def connected(self) -> bool:
        """Return True if the device is currently connected."""
        return not self._disconnected

    @callback
    def _async_update_device_registry_versions(self) -> None:
        """Update device registry with latest firmware/protocol/hardware versions."""
        if not (
            self._device.device_version
            or self._device.protocol_version
            or self._device.hardware_version
        ):
            return

        device_registry = dr.async_get(self.hass)
        device_entry = device_registry.async_get_device(
            identifiers={(DOMAIN, self._device.address)}
        )
        if device_entry is None:
            return

        device_registry.async_update_device(
            device_entry.id,
            hw_version=self._device.hardware_version or None,
            sw_version=(
                f"{self._device.device_version} "
                f"(protocol {self._device.protocol_version})"
                if self._device.device_version or self._device.protocol_version
                else None
            ),
        )

    @callback
    def _async_handle_connect(self) -> None:
        if self._unsub_disconnect is not None:
            self._unsub_disconnect()
        if self._disconnected:
            self._disconnected = False
            self._schedule_refresh_requests()
            self.async_update_listeners()
        self._async_update_device_registry_versions()

    @callback
    def _cancel_refresh_requests(self) -> None:
        while self._unsub_refresh_requests:
            self._unsub_refresh_requests.pop()()

    @callback
    def _request_datapoints_refresh(self, _: datetime.datetime | None = None) -> None:
        self.hass.async_create_task(self._device.update_all_datapoints())

    @callback
    def _schedule_refresh_requests(self) -> None:
        # Some devices send partial DP snapshots immediately after connect.
        # Trigger a few staged refreshes to pick up late-arriving values.
        self._cancel_refresh_requests()
        self._request_datapoints_refresh()
        for delay in (1.0, 3.0):
            self._unsub_refresh_requests.append(
                async_call_later(self.hass, delay, self._request_datapoints_refresh)
            )

    @callback
    def _async_handle_update(self, updates: list[TuyaBLEDataPoint]) -> None:
        self._async_handle_connect()
        self.async_update_listeners()
        self._async_update_device_registry_versions()
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
        if info and info.lock:
            for update in updates:
                if update.changed_by_device:
                    if update.id == info.lock.alarm_lock:
                        self.hass.bus.fire(
                            f"{DOMAIN}_lock_alarm_event",
                            {
                                CONF_ADDRESS: self._device.address,
                                CONF_DEVICE_ID: self._device.device_id,
                                "event": "alarm_lock",
                                "value": update.value,
                            },
                        )
                    elif update.id == info.lock.unlock_ble:
                        self.hass.bus.fire(
                            f"{DOMAIN}_lock_unlock_ble_event",
                            {
                                CONF_ADDRESS: self._device.address,
                                CONF_DEVICE_ID: self._device.device_id,
                                "event": "unlock_ble",
                                "value": update.value,
                            },
                        )
                    elif update.id == info.lock.unlock_fingerprint:
                        self.hass.bus.fire(
                            f"{DOMAIN}_lock_unlock_fingerprint_event",
                            {
                                CONF_ADDRESS: self._device.address,
                                CONF_DEVICE_ID: self._device.device_id,
                                "event": "unlock_fingerprint",
                                "value": update.value,
                            },
                        )
                    elif update.id == info.lock.unlock_password:
                        self.hass.bus.fire(
                            f"{DOMAIN}_lock_unlock_password_event",
                            {
                                CONF_ADDRESS: self._device.address,
                                CONF_DEVICE_ID: self._device.device_id,
                                "event": "unlock_password",
                                "value": update.value,
                            },
                        )

    @callback
    def _set_disconnected(self, _: datetime.datetime) -> None:
        self._disconnected = True
        self._unsub_disconnect = None
        self._cancel_refresh_requests()
        self.async_update_listeners()

    @callback
    def _async_handle_disconnect(self) -> None:
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
    coordinator : TuyaBLEPassiveCoordinator
        The data coordinator for the device.

    """

    title: str
    device: TuyaBLEDevice
    product: TuyaBLEProductInfo
    manager: HASSTuyaBLEDeviceManager
    coordinator: TuyaBLEPassiveCoordinator


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
