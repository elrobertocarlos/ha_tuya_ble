"""
Tuya BLE device communication module.

This module provides classes and utilities for communicating with Tuya BLE devices:
- TuyaBLEDevice: main class for device connection and communication
- TuyaBLEDataPoint: represents a single data point on the device
- TuyaBLEDataPoints: collection of data points
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import time
from struct import pack, unpack
from typing import TYPE_CHECKING

from bleak.exc import BleakDBusError, BleakError
from bleak_retry_connector import (
    BLEAK_BACKOFF_TIME,
    BLEAK_RETRY_EXCEPTIONS,
    BleakClientWithServiceCache,
    BleakNotFoundError,
    establish_connection,
)
from Crypto.Cipher import AES

from .const import (
    CHARACTERISTIC_NOTIFY,
    CHARACTERISTIC_WRITE,
    GATT_MTU,
    MANUFACTURER_DATA_ID,
    RESPONSE_WAIT_TIMEOUT,
    SERVICE_UUID,
    TuyaBLECode,
    TuyaBLEDataPointType,
)
from .exceptions import (
    TuyaBLEDataCRCError,
    TuyaBLEDataFormatError,
    TuyaBLEDataLengthError,
    TuyaBLEDeviceError,
    TuyaBLEEnumValueError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from bleak.backends.device import BLEDevice
    from bleak.backends.scanner import AdvertisementData

    from .manager import AbstaractTuyaBLEDeviceManager, TuyaBLEDeviceCredentials

_LOGGER = logging.getLogger(__name__)


BLEAK_EXCEPTIONS = (*BLEAK_RETRY_EXCEPTIONS, OSError)
TUYA_BLE_PROTOCOL_VERSION_3 = 3
TUYA_BLE_ENUM_MAX_UINT8 = 0xFF
TUYA_BLE_ENUM_MAX_UINT16 = 0xFFFF


class TuyaBLEDataPoint:
    """
    Represents a single data point on a Tuya BLE device.

    Attributes
    ----------
    id : int
        The unique identifier of the data point.
    value : bytes | bool | int | str
        The current value of the data point.
    timestamp : float
        The timestamp when the data point was last updated.
    type : TuyaBLEDataPointType
        The data type of the value.

    """

    def __init__(  # noqa: PLR0913
        self,
        owner: TuyaBLEDataPoints,
        dp_id: int,
        timestamp: float,
        flags: int,
        dp_type: TuyaBLEDataPointType,
        value: bytes | bool | int | str,
    ) -> None:
        """
        Initialize a TuyaBLE data point.

        With owner, id, timestamp, flags, type and value.
        """
        self._owner = owner
        self._id = dp_id
        self._value = value
        self._changed_by_device = False
        self._update_from_device(timestamp, flags, dp_type, value)

    def _update_from_device(
        self,
        timestamp: float,
        flags: int,
        dp_type: TuyaBLEDataPointType,
        value: bytes | bool | int | str,
    ) -> None:
        self._timestamp = timestamp
        self._flags = flags
        self._type = dp_type
        self._changed_by_device = self._value != value
        self._value = value

    def _get_value(self) -> bytes:  # noqa: PLR0911
        match self._type:
            case TuyaBLEDataPointType.DT_RAW | TuyaBLEDataPointType.DT_BITMAP:
                if not isinstance(self._value, bytes):
                    msg = "RAW/BITMAP datapoint value must be bytes"
                    raise TypeError(msg)
                return self._value
            case TuyaBLEDataPointType.DT_BOOL:
                return pack(">B", 1 if self._value else 0)
            case TuyaBLEDataPointType.DT_VALUE:
                return pack(">i", self._value)
            case TuyaBLEDataPointType.DT_ENUM:
                if not isinstance(self._value, int):
                    msg = "ENUM datapoint value must be int"
                    raise TypeError(msg)
                enum_value = self._value
                if enum_value > TUYA_BLE_ENUM_MAX_UINT16:
                    return pack(">I", enum_value)
                if enum_value > TUYA_BLE_ENUM_MAX_UINT8:
                    return pack(">H", enum_value)
                return pack(">B", enum_value)
            case TuyaBLEDataPointType.DT_STRING:
                if not isinstance(self._value, (str, bytes)):
                    msg = "STRING datapoint value must be str or bytes"
                    raise TypeError(msg)
                if isinstance(self._value, str):
                    return self._value.encode()
                return bytes(self._value)

    def get_value(self) -> bytes:
        """Return the datapoint value encoded for transmission."""
        return self._get_value()

    @property
    def id(self) -> int:
        """Return the unique identifier of the data point."""
        return self._id

    @property
    def timestamp(self) -> float:
        """Return the timestamp when the data point was last updated."""
        return self._timestamp

    @property
    def flags(self) -> int:
        """Return the flags of the data point."""
        return self._flags

    @property
    def type(self) -> TuyaBLEDataPointType:
        """Return the data type of the value."""
        return self._type

    @property
    def value(self) -> bytes | bool | int | str:
        """Return the current value of the data point."""
        return self._value

    @property
    def changed_by_device(self) -> bool:
        """Return whether the data point was changed by the device."""
        return self._changed_by_device

    async def set_value(self, value: bytes | bool | int | str) -> None:
        match self._type:
            case TuyaBLEDataPointType.DT_RAW | TuyaBLEDataPointType.DT_BITMAP:
                self._value = bytes(value)
            case TuyaBLEDataPointType.DT_BOOL:
                self._value = bool(value)
            case TuyaBLEDataPointType.DT_VALUE:
                self._value = int(value)
            case TuyaBLEDataPointType.DT_ENUM:
                value = int(value)
                if value >= 0:
                    self._value = value
                else:
                    raise TuyaBLEEnumValueError()

            case TuyaBLEDataPointType.DT_STRING:
                self._value = str(value)

        self._changed_by_device = False
        await self._owner._update_from_user(self._id)


class TuyaBLEDataPoints:
    """Container for Tuya BLE data points managed by a device."""

    def __init__(self, owner: TuyaBLEDevice) -> None:
        """Initialize the data point container for a device."""
        self._owner = owner
        self._datapoints: dict[int, TuyaBLEDataPoint] = {}
        self._update_started: int = 0
        self._updated_datapoints: list[int] = []

    def __len__(self) -> int:
        """Return the number of managed data points."""
        return len(self._datapoints)

    def __getitem__(self, key: int) -> TuyaBLEDataPoint | None:
        """Return the data point for the given ID, if present."""
        return self._datapoints.get(key)

    def has_id(self, dp_id: int, type: TuyaBLEDataPointType | None = None) -> bool:
        """Return True if the given data point ID exists and matches type if provided."""
        return (dp_id in self._datapoints) and (
            (type is None) or (self._datapoints[dp_id].type == type)
        )

    def get_or_create(
        self,
        dp_id: int,
        type: TuyaBLEDataPointType,
        value: bytes | bool | int | str | None = None,
    ) -> TuyaBLEDataPoint:
        """Return an existing data point by ID or create a new one."""
        datapoint = self._datapoints.get(dp_id)
        if datapoint:
            return datapoint
        datapoint = TuyaBLEDataPoint(self, dp_id, time.time(), 0, type, value)
        self._datapoints[dp_id] = datapoint
        return datapoint

    def begin_update(self) -> None:
        """Start a batched datapoint update operation."""
        self._update_started += 1

    async def end_update(self) -> None:
        """End a batched datapoint update operation and send any pending updates."""
        if self._update_started > 0:
            self._update_started -= 1
            if self._update_started == 0 and len(self._updated_datapoints) > 0:
                await self._owner._send_datapoints(self._updated_datapoints)
                self._updated_datapoints = []

    def _update_from_device(
        self,
        dp_id: int,
        timestamp: float,
        flags: int,
        dp_type: TuyaBLEDataPointType,
        value: bytes | bool | int | str,
    ) -> None:
        dp = self._datapoints.get(dp_id)
        if dp:
            dp._update_from_device(timestamp, flags, dp_type, value)
        else:
            self._datapoints[dp_id] = TuyaBLEDataPoint(
                self, dp_id, timestamp, flags, dp_type, value
            )

    async def _update_from_user(self, dp_id: int) -> None:
        if self._update_started > 0:
            if dp_id in self._updated_datapoints:
                self._updated_datapoints.remove(dp_id)
            self._updated_datapoints.append(dp_id)
        else:
            await self._owner._send_datapoints([dp_id])


global_connect_lock = asyncio.Lock()


class TuyaBLEDevice:
    """
    Main class for Tuya BLE device connection and communication.

    Handles device initialization, pairing, connection management, data point updates,
    and communication with Tuya BLE devices.

    Attributes
    ----------
    _device_manager : AbstaractTuyaBLEDeviceManager
        Manager for device credentials and BLE operations.
    _ble_device : BLEDevice
        The BLE device instance.
    _advertisement_data : AdvertisementData | None
        BLE advertisement data.
    _client : BleakClientWithServiceCache | None
        BLE client for communication.
    _datapoints : TuyaBLEDataPoints
        Collection of data points for the device.
    _is_paired : bool
        Indicates if the device is paired.
    _expected_disconnect : bool
        Indicates if a disconnect is expected.
    _operation_lock : asyncio.Lock
        Lock for BLE operations.
    _connect_lock : asyncio.Lock
        Lock for BLE connection.
    _current_seq_num : int
        Current sequence number for packets.
    _seq_num_lock : asyncio.Lock
        Lock for sequence number updates.
    _device_version : str
        Device firmware version.
    _protocol_version_str : str
        Protocol version as string.
    _hardware_version : str
        Hardware version.
    _auth_key : bytes | None
        Authentication key.
    _local_key : bytes | None
        Local key.
    _login_key : bytes | None
        Login key.
    _session_key : bytes | None
        Session key.

    Methods
    -------
    initialize()
        Initialize the Tuya BLE device.
    pair()
        Send pairing request to device.
    update()
        Request device status update.
    start()
        Start the TuyaBLE device.
    stop()
        Stop the TuyaBLE device.
    register_callback(callback)
        Register a callback for state changes.
    register_connected_callback(callback)
        Register a callback for connection events.
    register_disconnected_callback(callback)
        Register a callback for disconnection events.

    """

    def __init__(
        self,
        device_manager: AbstaractTuyaBLEDeviceManager,
        ble_device: BLEDevice,
        advertisement_data: AdvertisementData | None = None,
    ) -> None:
        """Init the TuyaBLE."""
        self._device_manager = device_manager
        self._device_info: TuyaBLEDeviceCredentials | None = None
        self._ble_device = ble_device
        self._advertisement_data = advertisement_data
        self._operation_lock = asyncio.Lock()
        self._connect_lock = asyncio.Lock()
        self._client: BleakClientWithServiceCache | None = None
        self._expected_disconnect = False
        self._connected_callbacks: list[Callable[[], None]] = []
        self._callbacks: list[Callable[[list[TuyaBLEDataPoint]], None]] = []
        self._disconnected_callbacks: list[Callable[[], None]] = []
        self._current_seq_num = 1
        self._seq_num_lock = asyncio.Lock()

        self._is_bound = False
        self._flags = 0
        self._protocol_version = 2

        self._device_version: str = ""
        self._protocol_version_str: str = ""
        self._hardware_version: str = ""

        self._device_info: TuyaBLEDeviceCredentials | None = None

        self._auth_key: bytes | None = None
        self._local_key: bytes | None = None
        self._login_key: bytes | None = None
        self._session_key: bytes | None = None

        self._is_paired = False

        self._input_buffer: bytearray | None = None
        self._input_expected_packet_num = 0
        self._input_expected_length = 0
        self._input_expected_responses: dict[int, asyncio.Future[int] | None] = {}

        self._datapoints = TuyaBLEDataPoints(self)

    def set_ble_device_and_advertisement_data(
        self, ble_device: BLEDevice, advertisement_data: AdvertisementData
    ) -> None:
        """Set the ble device."""
        self._ble_device = ble_device
        self._advertisement_data = advertisement_data
        # Keep protocol/binding metadata in sync with the latest advertisements.
        # Some devices require protocol v3 during the initial device-info handshake.
        self._decode_advertisement_data()

    async def initialize(self) -> None:
        """
        Initialize the Tuya BLE device.

        Updates device information and decodes advertisement data if available.
        This should be called after creating a TuyaBLEDevice instance.
        """
        _LOGGER.debug("%s: Initializing", self.address)
        if await self._update_device_info():
            self._decode_advertisement_data()

    def _build_pairing_request(self) -> bytes:
        if self._device_info is None or self._local_key is None:
            msg = "Device credentials are not initialized"
            raise RuntimeError(msg)

        result = bytearray()

        result += self._device_info.uuid.encode()
        result += self._local_key
        result += self._device_info.device_id.encode()
        for _ in range(44 - len(result)):
            result += b"\x00"

        return result

    async def pair(self) -> None:
        """Send pairing request to device."""
        await self._send_packet(
            TuyaBLECode.FUN_SENDER_PAIR, self._build_pairing_request()
        )

    async def update(self) -> None:
        """Request device status update from the Tuya BLE device."""
        _LOGGER.debug("%s: Updating", self.address)
        await self.update_all_datapoints()

    async def update_all_datapoints(self) -> None:
        """
        Request complete refresh of all device datapoints.

        This method forces the device to send all datapoint values, not just changes.
        Useful for initial sync or recovering from missed updates. Sends multiple
        status requests with a small delay to ensure device captures and responds
        with full state.
        """
        _LOGGER.debug("%s: Requesting complete datapoint refresh", self.address)
        # Send multiple status requests to force device to dump all state
        for attempt in range(3):
            await self._send_packet(
                TuyaBLECode.FUN_SENDER_DEVICE_STATUS,
                b"",
                wait_for_response=False,
            )
            if attempt < 2:
                # Small delay between requests to allow device to respond
                await asyncio.sleep(0.2)
        _LOGGER.debug("%s: Complete datapoint refresh requested", self.address)

    async def _update_device_info(self) -> bool:
        if self._device_info is None:
            if self._device_manager:
                self._device_info = await self._device_manager.get_device_credentials(
                    self._ble_device.address, force_update=False
                )
            if self._device_info:
                self._local_key = self._device_info.local_key[:6].encode()
                self._login_key = hashlib.md5(self._local_key).digest()

        return self._device_info is not None

    def _decode_advertisement_data(self) -> None:
        raw_product_id: bytes | None = None
        # raw_product_key: bytes | None = None
        raw_uuid: bytes | None = None
        if self._advertisement_data:
            if self._advertisement_data.service_data:
                service_data = self._advertisement_data.service_data.get(SERVICE_UUID)
                if service_data and len(service_data) > 1:
                    match service_data[0]:
                        case 0:
                            raw_product_id = service_data[1:]
                        # case 1:
                        #    raw_product_key = service_data[1:]

            if self._advertisement_data.manufacturer_data:
                manufacturer_data = self._advertisement_data.manufacturer_data.get(
                    MANUFACTURER_DATA_ID
                )
                if manufacturer_data and len(manufacturer_data) > 6:
                    self._is_bound = (manufacturer_data[0] & 0x80) != 0
                    self._protocol_version = manufacturer_data[1]
                    raw_uuid = manufacturer_data[6:]
                    if raw_product_id:
                        key = hashlib.md5(
                            raw_product_id, usedforsecurity=False
                        ).digest()
                        cipher = AES.new(key, AES.MODE_CBC, key)
                        raw_uuid = cipher.decrypt(raw_uuid)
                        self._uuid = raw_uuid.decode("utf-8")

    @property
    def address(self) -> str:
        """Return the address."""
        return self._ble_device.address

    @property
    def name(self) -> str:
        """Get the name of the device."""
        if self._device_info:
            return (
                self._device_info.device_name
                or self._ble_device.name
                or self._ble_device.address
            )
        return self._ble_device.name or self._ble_device.address

    @property
    def rssi(self) -> int | None:
        """Get the rssi of the device."""
        if self._advertisement_data:
            return self._advertisement_data.rssi
        return None

    @property
    def uuid(self) -> str:
        """Return the UUID of the device."""
        if self._device_info is not None:
            return self._device_info.uuid
        return ""

    @property
    def local_key(self) -> str:
        """Return the local key of the device."""
        if self._device_info is not None:
            return self._device_info.local_key
        return ""

    @property
    def category(self) -> str:
        """Return the category of the device."""
        if self._device_info is not None:
            return self._device_info.category
        return ""

    @property
    def device_id(self) -> str:
        """Return the device ID."""
        if self._device_info is not None:
            return self._device_info.device_id
        return ""

    @property
    def product_id(self) -> str:
        """Return the product ID."""
        if self._device_info is not None:
            return self._device_info.product_id
        return ""

    @property
    def product_model(self) -> str:
        """Return the product model."""
        if self._device_info is not None:
            return self._device_info.product_model or ""
        return ""

    @property
    def product_name(self) -> str:
        """Return the product name."""
        if self._device_info is not None:
            return self._device_info.product_name or ""
        return ""

    @property
    def device_version(self) -> str:
        """Return the device firmware version."""
        return self._device_version

    @property
    def hardware_version(self) -> str:
        """Return the hardware version."""
        return self._hardware_version

    @property
    def protocol_version(self) -> str:
        """Return the protocol version."""
        return self._protocol_version_str

    @property
    def datapoints(self) -> TuyaBLEDataPoints:
        """Get datapoints exposed by device."""
        return self._datapoints

    def get_or_create_datapoint(
        self,
        dp_id: int,
        dp_type: TuyaBLEDataPointType,
        value: bytes | bool | int | str | None = None,
    ) -> TuyaBLEDataPoint:
        """
        Get or create a datapoint exposed by device.

        Parameters
        ----------
        dp_id : int
            The unique identifier of the data point.
        dp_type : TuyaBLEDataPointType
            The data type of the value.
        value : bytes | bool | int | str | None, optional
            The initial value of the data point.

        Returns
        -------
        TuyaBLEDataPoint
            The data point object.

        """
        return self._datapoints.get_or_create(dp_id, dp_type, value)

    def _fire_connected_callbacks(self) -> None:
        """Fire the callbacks."""
        for callback in self._connected_callbacks:
            callback()

    def register_connected_callback(
        self, callback: Callable[[], None]
    ) -> Callable[[], None]:
        """Register a callback to be called when device disconnected."""

        def unregister_callback() -> None:
            self._connected_callbacks.remove(callback)

        self._connected_callbacks.append(callback)
        return unregister_callback

    def _fire_callbacks(self, datapoints: list[TuyaBLEDataPoint]) -> None:
        """Fire the callbacks."""
        for callback in self._callbacks:
            callback(datapoints)

    def register_callback(
        self,
        callback: Callable[[list[TuyaBLEDataPoint]], None],
    ) -> Callable[[], None]:
        """Register a callback to be called when the state changes."""

        def unregister_callback() -> None:
            self._callbacks.remove(callback)

        self._callbacks.append(callback)
        return unregister_callback

    def _fire_disconnected_callbacks(self) -> None:
        """Fire the callbacks."""
        for callback in self._disconnected_callbacks:
            callback()

    def register_disconnected_callback(
        self, callback: Callable[[], None]
    ) -> Callable[[], None]:
        """Register a callback to be called when device disconnected."""

        def unregister_callback() -> None:
            self._disconnected_callbacks.remove(callback)

        self._disconnected_callbacks.append(callback)
        return unregister_callback

    async def start(self):
        """Start the TuyaBLE."""
        _LOGGER.debug("%s: Starting...", self.address)
        # await self._send_packet()

    async def stop(self) -> None:
        """Stop the TuyaBLE."""
        _LOGGER.debug("%s: Stop", self.address)
        await self._execute_disconnect()

    def request_reconnect(self) -> None:
        """Request reconnect of the active BLE session."""
        asyncio.create_task(self._request_reconnect())

    async def _request_reconnect(self) -> None:
        """Reconnect by dropping the current session or ensuring a new one."""
        client = self._client
        if client and client.is_connected:
            _LOGGER.debug(
                "%s: Requested reconnect; disconnecting current session", self.address
            )
            try:
                await client.disconnect()
            except BLEAK_EXCEPTIONS:
                _LOGGER.debug(
                    "%s: Requested reconnect could not disconnect cleanly",
                    self.address,
                    exc_info=True,
                )
                asyncio.create_task(self._reconnect())
        else:
            asyncio.create_task(self._reconnect())

    def _disconnected(self, client: BleakClientWithServiceCache) -> None:
        """Disconnected callback."""
        was_paired = self._is_paired
        self._is_paired = False
        self._fail_pending_responses()
        self._fire_disconnected_callbacks()
        if self._expected_disconnect:
            _LOGGER.debug(
                "%s: Disconnected from device; RSSI: %s",
                self.address,
                self.rssi,
            )
            return
        self._client = None
        _LOGGER.warning(
            "%s: Device unexpectedly disconnected; RSSI: %s",
            self.address,
            self.rssi,
        )
        if was_paired:
            _LOGGER.debug(
                "%s: Scheduling reconnect; RSSI: %s",
                self.address,
                self.rssi,
            )
            asyncio.create_task(self._reconnect())

    def _fail_pending_responses(self) -> None:
        """Fail and clear pending request futures after connection loss."""
        for future in self._input_expected_responses.values():
            if future and not future.done():
                future.set_exception(BleakError("Disconnected while waiting for response"))
        self._input_expected_responses.clear()

    def _disconnect(self) -> None:
        """Disconnect from device."""
        asyncio.create_task(self._execute_timed_disconnect())

    async def _execute_timed_disconnect(self) -> None:
        """Execute timed disconnection."""
        _LOGGER.debug(
            "%s: Disconnecting",
            self.address,
        )
        await self._execute_disconnect()

    async def _execute_disconnect(self) -> None:
        """Execute disconnection."""
        async with self._connect_lock:
            client = self._client
            self._expected_disconnect = True
            self._client = None
            if client and client.is_connected:
                await client.stop_notify(CHARACTERISTIC_NOTIFY)
                await client.disconnect()
        async with self._seq_num_lock:
            self._current_seq_num = 1

    async def _ensure_connected(self) -> None:
        """Ensure connection to device is established."""
        global global_connect_lock
        if self._expected_disconnect:
            return
        if self._connect_lock.locked():
            _LOGGER.debug(
                "%s: Connection already in progress,"
                " waiting for it to complete; RSSI: %s",
                self.address,
                self.rssi,
            )
        if self._client and self._client.is_connected and self._is_paired:
            return
        async with self._connect_lock:
            # Check again while holding the lock
            await asyncio.sleep(0.01)
            if self._client and self._client.is_connected and self._is_paired:
                return
            attempts_count = 100
            while attempts_count > 0:
                attempts_count -= 1
                if attempts_count == 0:
                    _LOGGER.error(
                        "%s: Connecting, all attempts failed; RSSI: %s",
                        self.address,
                        self.rssi,
                    )
                    raise BleakNotFoundError()
                try:
                    async with global_connect_lock:
                        _LOGGER.debug(
                            "%s: Connecting; RSSI: %s", self.address, self.rssi
                        )
                        client = await establish_connection(
                            BleakClientWithServiceCache,
                            self._ble_device,
                            self.address,
                            self._disconnected,
                            use_services_cache=True,
                            ble_device_callback=lambda: self._ble_device,
                        )
                except BleakNotFoundError:
                    _LOGGER.error(
                        "%s: device not found, not in range, or poor RSSI: %s",
                        self.address,
                        self.rssi,
                        exc_info=True,
                    )
                    continue
                except BLEAK_EXCEPTIONS:
                    _LOGGER.debug(
                        "%s: communication failed", self.address, exc_info=True
                    )
                    continue
                except Exception:
                    _LOGGER.debug("%s: unexpected error", self.address, exc_info=True)
                    continue

                if client and client.is_connected:
                    _LOGGER.debug("%s: Connected; RSSI: %s", self.address, self.rssi)
                    self._client = client
                    try:
                        await self._client.start_notify(
                            CHARACTERISTIC_NOTIFY, self._notification_handler
                        )
                    except Exception:  # [BLEAK_EXCEPTIONS, BleakNotFoundError]:
                        self._client = None
                        _LOGGER.error(
                            "%s: starting notifications failed",
                            self.address,
                            exc_info=True,
                        )
                        continue
                else:
                    continue

                paired_via_fallback = False

                if self._client and self._client.is_connected:
                    _LOGGER.debug(
                        "%s: Sending device info request (protocol v%s)",
                        self.address,
                        self._protocol_version,
                    )
                    try:
                        if not await self._send_packet_while_connected(
                            TuyaBLECode.FUN_SENDER_DEVICE_INFO,
                            bytes(0),
                            0,
                            True,
                        ):
                            if not (self._client and self._client.is_connected):
                                self._client = None
                                _LOGGER.debug(
                                    "%s: Device disconnected before compatibility"
                                    " pairing fallback",
                                    self.address,
                                )
                                continue
                            _LOGGER.warning(
                                "%s: Device info request failed; attempting"
                                " compatibility pairing fallback",
                                self.address,
                            )
                            try:
                                if not await self._send_packet_while_connected(
                                    TuyaBLECode.FUN_SENDER_PAIR,
                                    self._build_pairing_request(),
                                    0,
                                    True,
                                ):
                                    self._client = None
                                    _LOGGER.error(
                                        "%s: Compatibility pairing fallback failed",
                                        self.address,
                                    )
                                    continue
                                paired_via_fallback = True
                            except Exception:
                                self._client = None
                                _LOGGER.error(
                                    "%s: Compatibility pairing fallback failed",
                                    self.address,
                                    exc_info=True,
                                )
                                continue
                    except Exception:  # [BLEAK_EXCEPTIONS, BleakNotFoundError]:
                        self._client = None
                        _LOGGER.error(
                            "%s: Sending device info request failed",
                            self.address,
                            exc_info=True,
                        )
                        continue
                else:
                    continue

                if (
                    self._client
                    and self._client.is_connected
                    and not paired_via_fallback
                ):
                    _LOGGER.debug("%s: Sending pairing request", self.address)
                    try:
                        if not await self._send_packet_while_connected(
                            TuyaBLECode.FUN_SENDER_PAIR,
                            self._build_pairing_request(),
                            0,
                            True,
                        ):
                            self._client = None
                            _LOGGER.error(
                                "%s: Sending pairing request failed",
                                self.address,
                            )
                            continue
                    except Exception:  # [BLEAK_EXCEPTIONS, BleakNotFoundError]:
                        self._client = None
                        _LOGGER.error(
                            "%s: Sending pairing request failed",
                            self.address,
                            exc_info=True,
                        )
                        continue
                else:
                    continue

                break

        if self._client:
            if self._client.is_connected:
                if self._is_paired:
                    _LOGGER.debug("%s: Successfully connected", self.address)
                    self._fire_connected_callbacks()
                else:
                    _LOGGER.error("%s: Connected but not paired", self.address)
            else:
                _LOGGER.error("%s: Not connected", self.address)
        else:
            _LOGGER.error("%s: No client device", self.address)

    async def _reconnect(self) -> None:
        """Attempt a reconnect."""
        _LOGGER.debug("%s: Reconnect, ensuring connection", self.address)
        async with self._seq_num_lock:
            self._current_seq_num = 1
        try:
            if self._expected_disconnect:
                return
            await self._ensure_connected()
            if self._expected_disconnect:
                return
            _LOGGER.debug("%s: Reconnect, connection ensured", self.address)
        except BLEAK_EXCEPTIONS:  # BleakNotFoundError:
            _LOGGER.debug(
                "%s: Reconnect, failed to ensure connection - backing off",
                self.address,
                exc_info=True,
            )
            await asyncio.sleep(BLEAK_BACKOFF_TIME)
            _LOGGER.debug("%s: Reconnecting again", self.address)
            asyncio.create_task(self._reconnect())

    @staticmethod
    def _calc_crc16(data: bytes) -> int:
        crc = 0xFFFF
        for byte in data:
            crc ^= byte & 255
            for _ in range(8):
                tmp = crc & 1
                crc >>= 1
                if tmp != 0:
                    crc ^= 0xA001
        return crc

    @staticmethod
    def _pack_int(value: int) -> bytearray:
        curr_byte: int
        result = bytearray()
        while True:
            curr_byte = value & 0x7F
            value >>= 7
            if value != 0:
                curr_byte |= 0x80
            result += pack(">B", curr_byte)
            if value == 0:
                break
        return result

    @staticmethod
    def _unpack_int(data: bytes, start_pos: int) -> tuple(int, int):
        result: int = 0
        offset: int = 0
        while offset < 5:
            pos: int = start_pos + offset
            if pos >= len(data):
                raise TuyaBLEDataFormatError()
            curr_byte: int = data[pos]
            result |= (curr_byte & 0x7F) << (offset * 7)
            offset += 1
            if (curr_byte & 0x80) == 0:
                break
        if offset > 4:
            raise TuyaBLEDataFormatError()
        return (result, start_pos + offset)

    def _build_packets(
        self,
        seq_num: int,
        code: TuyaBLECode,
        data: bytes,
        response_to: int = 0,
    ) -> list[bytes]:
        key: bytes
        iv = secrets.token_bytes(16)
        security_flag: bytes
        if code == TuyaBLECode.FUN_SENDER_DEVICE_INFO:
            if self._login_key is None:
                msg = "Login key is not initialized"
                raise RuntimeError(msg)
            key = self._login_key
            security_flag = b"\x04"
        else:
            # Some devices never answer FUN_SENDER_DEVICE_INFO but still accept
            # pairing requests encrypted with login key (flag 0x04).
            if code == TuyaBLECode.FUN_SENDER_PAIR and self._session_key is None:
                if self._login_key is None:
                    msg = "Login key is not initialized"
                    raise RuntimeError(msg)
                key = self._login_key
                security_flag = b"\x04"
            else:
                if self._session_key is None:
                    msg = "Session key is not initialized"
                    raise RuntimeError(msg)
                key = self._session_key
                security_flag = b"\x05"

        raw = bytearray()
        raw += pack(">IIHH", seq_num, response_to, code.value, len(data))
        raw += data
        crc = self._calc_crc16(raw)
        raw += pack(">H", crc)
        while len(raw) % 16 != 0:
            raw += b"\x00"

        cipher = AES.new(key, AES.MODE_CBC, iv)
        encrypted = security_flag + iv + cipher.encrypt(raw)

        command = []
        packet_num = 0
        pos = 0
        length = len(encrypted)
        while pos < length:
            packet = bytearray()
            packet += self._pack_int(packet_num)

            if packet_num == 0:
                packet += self._pack_int(length)
                packet += pack(">B", self._protocol_version << 4)

            data_part = encrypted[
                pos : pos
                + GATT_MTU
                - len(
                    packet
                )  # fmt: skip
            ]
            packet += data_part
            command.append(packet)

            pos += len(data_part)
            packet_num += 1

        return command

    async def _get_seq_num(self) -> int:
        async with self._seq_num_lock:
            result = self._current_seq_num
            self._current_seq_num += 1
        return result

    async def _send_packet(
        self,
        code: TuyaBLECode,
        data: bytes,
        wait_for_response: bool = True,
        # retry: int | None = None,
    ) -> None:
        """Send packet to device and optional read response."""
        if self._expected_disconnect:
            return
        await self._ensure_connected()
        if self._expected_disconnect:
            return
        await self._send_packet_while_connected(code, data, 0, wait_for_response)

    async def _send_response(
        self,
        code: TuyaBLECode,
        data: bytes,
        response_to: int,
    ) -> None:
        """Send response to received packet."""
        if self._client and self._client.is_connected:
            await self._send_packet_while_connected(code, data, response_to, False)

    async def _send_packet_while_connected(
        self,
        code: TuyaBLECode,
        data: bytes,
        response_to: int,
        wait_for_response: bool,
        # retry: int | None = None
    ) -> bool:
        """Send packet to device and optional read response."""
        result = True
        future: asyncio.Future | None = None
        seq_num = await self._get_seq_num()
        if wait_for_response:
            future = asyncio.Future()
            self._input_expected_responses[seq_num] = future

        packets: list[bytes] = self._build_packets(seq_num, code, data, response_to)
        await self._int_send_packet_while_connected(packets)
        if future:
            try:
                await asyncio.wait_for(future, RESPONSE_WAIT_TIMEOUT)
            except TimeoutError:
                _LOGGER.error(
                    "%s: timeout receiving response, RSSI: %s",
                    self.address,
                    self.rssi,
                )
                result = False
            except BleakError:
                _LOGGER.debug(
                    "%s: connection lost while waiting for response, RSSI: %s",
                    self.address,
                    self.rssi,
                )
                result = False
            self._input_expected_responses.pop(seq_num, None)

        return result

    async def _int_send_packet_while_connected(
        self,
        packets: list[bytes],
    ) -> None:
        if self._operation_lock.locked():
            _LOGGER.debug(
                "%s: Operation already in progress, "
                "waiting for it to complete; RSSI: %s",
                self.address,
                self.rssi,
            )
        async with self._operation_lock:
            try:
                await self._send_packets_locked(packets)
            except BleakNotFoundError:
                _LOGGER.error(
                    "%s: device not found, no longer in range, or poor RSSI: %s",
                    self.address,
                    self.rssi,
                    exc_info=True,
                )
                raise
            except BLEAK_EXCEPTIONS:
                _LOGGER.error(
                    "%s: communication failed",
                    self.address,
                    exc_info=True,
                )
                raise

    async def _resend_packets(self, packets: list[bytes]) -> None:
        if self._expected_disconnect:
            return
        await self._ensure_connected()
        if self._expected_disconnect:
            return
        await self._int_send_packet_while_connected(packets)

    async def _send_packets_locked(self, packets: list[bytes]) -> None:
        """Send command to device and read response."""
        try:
            await self._int_send_packets_locked(packets)
        except BleakDBusError as ex:
            # Disconnect so we can reset state and try again
            await asyncio.sleep(BLEAK_BACKOFF_TIME)
            _LOGGER.debug(
                "%s: RSSI: %s; Backing off %ss; Disconnecting due to error: %s",
                self.address,
                self.rssi,
                BLEAK_BACKOFF_TIME,
                ex,
            )
            if self._is_paired:
                asyncio.create_task(self._resend_packets(packets))
            else:
                asyncio.create_task(self._reconnect())
            raise BleakError from ex
        except BleakError as ex:
            # Disconnect so we can reset state and try again
            _LOGGER.debug(
                "%s: RSSI: %s; Disconnecting due to error: %s",
                self.address,
                self.rssi,
                ex,
            )
            if self._is_paired:
                asyncio.create_task(self._resend_packets(packets))
            else:
                asyncio.create_task(self._reconnect())
            raise

    async def _int_send_packets_locked(self, packets: list[bytes]) -> None:
        """Execute command and read response."""
        for packet in packets:
            if self._client:
                try:
                    # _LOGGER.debug("%s: Sending packet: %s", self.address, packet.hex())
                    await self._client.write_gatt_char(
                        CHARACTERISTIC_WRITE,
                        packet,
                        False,
                    )
                except:
                    _LOGGER.error(
                        "%s: Error during sending packet",
                        self.address,
                        exc_info=True,
                    )
                    if self._client and self._client.is_connected:
                        self._disconnected(self._client)
                    raise BleakError()
            else:
                _LOGGER.error(
                    "%s: Client disconnected during sending packet",
                    self.address,
                    exc_info=True,
                )
                raise BleakError()

    def _get_key(self, security_flag: int) -> bytes:
        if security_flag == 1:
            if self._auth_key is None:
                msg = "Auth key is not initialized"
                raise RuntimeError(msg)
            return self._auth_key
        if security_flag == 4:
            if self._login_key is None:
                msg = "Login key is not initialized"
                raise RuntimeError(msg)
            return self._login_key
        if security_flag == 5:
            if self._session_key is None:
                msg = "Session key is not initialized"
                raise RuntimeError(msg)
            return self._session_key
        msg = "Unsupported security flag"
        raise RuntimeError(msg)

    def _parse_timestamp(self, data: bytes, start_pos: int) -> tuple(float, int):
        timestamp: float
        pos = start_pos
        if pos >= len(data):
            raise TuyaBLEDataLengthError()
        time_type = data[pos]
        pos += 1
        end_pos = pos
        match time_type:
            case 0:
                end_pos += 13
                if end_pos > len(data):
                    raise TuyaBLEDataLengthError()
                timestamp = int(data[pos:end_pos].decode()) / 1000
            case 1:
                end_pos += 4
                if end_pos > len(data):
                    raise TuyaBLEDataLengthError()
                timestamp = int.from_bytes(data[pos:end_pos], "big") * 1.0
            case _:
                raise TuyaBLEDataFormatError()

        _LOGGER.debug(
            "%s: Received timestamp: %s",
            self.address,
            time.ctime(timestamp),
        )
        return (timestamp, end_pos)

    def _parse_datapoints_v3(
        self, timestamp: float, flags: int, data: bytes, start_pos: int
    ) -> int:
        datapoints: list[TuyaBLEDataPoint] = []

        pos = start_pos
        while len(data) - pos >= 4:
            dp_id: int = data[pos]
            pos += 1
            _type: int = data[pos]
            if _type > TuyaBLEDataPointType.DT_BITMAP.value:
                raise TuyaBLEDataFormatError()
            type: TuyaBLEDataPointType = TuyaBLEDataPointType(_type)
            pos += 1
            data_len: int = data[pos]
            pos += 1
            next_pos = pos + data_len
            if next_pos > len(data):
                raise TuyaBLEDataLengthError()
            raw_value = data[pos:next_pos]
            match type:
                case TuyaBLEDataPointType.DT_RAW | TuyaBLEDataPointType.DT_BITMAP:
                    value = raw_value
                case TuyaBLEDataPointType.DT_BOOL:
                    value = int.from_bytes(raw_value, "big") != 0
                case TuyaBLEDataPointType.DT_VALUE | TuyaBLEDataPointType.DT_ENUM:
                    value = int.from_bytes(raw_value, "big", signed=True)
                case TuyaBLEDataPointType.DT_STRING:
                    value = raw_value.decode()

            _LOGGER.debug(
                "%s: Received datapoint update, id: %s, type: %s: value: %s",
                self.address,
                dp_id,
                type.name,
                value,
            )
            self._datapoints._update_from_device(dp_id, timestamp, flags, type, value)
            datapoints.append(self._datapoints[dp_id])
            pos = next_pos

        self._fire_callbacks(datapoints)

    def _handle_command_or_response(
        self, seq_num: int, response_to: int, code: TuyaBLECode, data: bytes
    ) -> None:
        result: int = 0

        match code:
            case TuyaBLECode.FUN_SENDER_DEVICE_INFO:
                if len(data) < 46:
                    raise TuyaBLEDataLengthError()

                _LOGGER.debug(
                    "%s: FUN_SENDER_DEVICE_INFO data (len=%s): hex=%s, str=%s",
                    self.address,
                    len(data),
                    data.hex(),
                    repr(data),
                )

                self._device_version = f"{data[0]}.{data[1]}"
                self._protocol_version_str = f"{data[2]}.{data[3]}"
                self._hardware_version = f"{data[12]}.{data[13]}"

                _LOGGER.debug(
                    "%s: Parsed versions - device: %s, protocol: %s, hardware: %s",
                    self.address,
                    self._device_version,
                    self._protocol_version_str,
                    self._hardware_version,
                )

                self._protocol_version = data[2]
                self._flags = data[4]
                self._is_bound = data[5] != 0

                srand = data[6:12]
                self._session_key = hashlib.md5(
                    (self._local_key or b"") + srand,
                    usedforsecurity=False,
                ).digest()
                self._auth_key = data[14:46]

            case TuyaBLECode.FUN_SENDER_PAIR:
                if len(data) < 1:
                    raise TuyaBLEDataLengthError()

                if len(data) > 1:
                    _LOGGER.debug(
                        "%s: FUN_SENDER_PAIR data (len=%s): hex=%s, str=%s",
                        self.address,
                        len(data),
                        data.hex(),
                        repr(data),
                    )
                else:
                    _LOGGER.debug(
                        "%s: FUN_SENDER_PAIR data (len=%s): hex=%s",
                        self.address,
                        len(data),
                        data.hex(),
                    )

                result = data[0]
                if result == 2:
                    _LOGGER.debug(
                        "%s: Device is already paired",
                        self.address,
                    )
                    result = 0
                self._is_paired = result == 0

            case TuyaBLECode.FUN_SENDER_DEVICE_STATUS:
                if len(data) != 1:
                    raise TuyaBLEDataLengthError()
                result = data[0]

            case TuyaBLECode.FUN_RECEIVE_TIME1_REQ:
                if len(data) != 0:
                    raise TuyaBLEDataLengthError()

                timestamp = int(time.time_ns() / 1000000)
                timezone = -int(time.timezone / 36)
                data = str(timestamp).encode() + pack(">h", timezone)
                _LOGGER.debug(
                    "%s: Received time request, responding with timestamp: %s, timezone: %s",
                    self.address,
                    timestamp,
                    timezone,
                )
                asyncio.create_task(self._send_response(code, data, seq_num))

            case TuyaBLECode.FUN_RECEIVE_TIME2_REQ:
                if len(data) != 0:
                    raise TuyaBLEDataLengthError()

                time_str: time.struct_time = time.localtime()
                timezone = -int(time.timezone / 36)
                data = pack(
                    ">BBBBBBBh",
                    time_str.tm_year % 100,
                    time_str.tm_mon,
                    time_str.tm_mday,
                    time_str.tm_hour,
                    time_str.tm_min,
                    time_str.tm_sec,
                    time_str.tm_wday,
                    timezone,
                )
                _LOGGER.debug(
                    "%s: Received time request, responding with time: %s, timezone: %s",
                    self.address,
                    time.strftime("%Y-%m-%d %H:%M:%S", time_str),
                    timezone,
                )
                asyncio.create_task(self._send_response(code, data, seq_num))

            case TuyaBLECode.FUN_RECEIVE_DP:
                self._parse_datapoints_v3(time.time(), 0, data, 0)
                asyncio.create_task(self._send_response(code, bytes(0), seq_num))

            case TuyaBLECode.FUN_RECEIVE_SIGN_DP:
                dp_seq_num = int.from_bytes(data[:2], "big")
                flags = data[2]
                self._parse_datapoints_v3(time.time(), flags, data, 2)
                data = pack(">HBB", dp_seq_num, flags, 0)
                asyncio.create_task(self._send_response(code, data, seq_num))

            case TuyaBLECode.FUN_RECEIVE_TIME_DP:
                timestamp: float
                pos: int
                timestamp, pos = self._parse_timestamp(data, 0)
                self._parse_datapoints_v3(timestamp, 0, data, pos)
                asyncio.create_task(self._send_response(code, bytes(0), seq_num))

            case TuyaBLECode.FUN_RECEIVE_SIGN_TIME_DP:
                timestamp: float
                pos: int
                dp_seq_num = int.from_bytes(data[:2], "big")
                flags = data[2]
                timestamp, pos = self._parse_timestamp(data, 3)
                self._parse_datapoints_v3(time.time(), flags, data, pos)
                data = pack(">HBB", dp_seq_num, flags, 0)
                asyncio.create_task(self._send_response(code, data, seq_num))

        if response_to != 0:
            future = self._input_expected_responses.pop(response_to, None)
            if future:
                _LOGGER.debug(
                    "%s: Received expected response to #%s, result: %s",
                    self.address,
                    response_to,
                    result,
                )
                if result == 0:
                    future.set_result(result)
                else:
                    future.set_exception(TuyaBLEDeviceError(result))

    def _clean_input(self) -> None:
        self._input_buffer = None
        self._input_expected_packet_num = 0
        self._input_expected_length = 0

    def _parse_input(self) -> None:
        input_buffer = self._input_buffer
        if input_buffer is None:
            return

        security_flag = input_buffer[0]
        key = self._get_key(security_flag)
        iv = input_buffer[1:17]
        encrypted = input_buffer[17:]

        self._clean_input()

        cipher = AES.new(key, AES.MODE_CBC, iv)
        raw = cipher.decrypt(encrypted)

        seq_num: int
        response_to: int
        _code: int
        length: int
        seq_num, response_to, _code, length = unpack(">IIHH", raw[:12])

        data_end_pos = length + 12
        raw_length = len(raw)
        if raw_length < data_end_pos:
            raise TuyaBLEDataLengthError()
        if raw_length > data_end_pos:
            calc_crc = self._calc_crc16(raw[:data_end_pos])
            (data_crc,) = unpack(
                ">H",
                raw[data_end_pos : data_end_pos + 2],  # fmt: skip
            )
            if calc_crc != data_crc:
                raise TuyaBLEDataCRCError
        data = raw[12:data_end_pos]

        code: TuyaBLECode
        try:
            code = TuyaBLECode(_code)
        except ValueError:
            _LOGGER.debug(
                "%s: Received unknown message: #%s %x, response to #%s, data %s",
                self.address,
                seq_num,
                _code,
                response_to,
                data.hex(),
            )
            return

        self._handle_command_or_response(seq_num, response_to, code, data)

    def _notification_handler(self, _sender: int, data: bytearray) -> None:
        """Handle notification responses."""
        pos: int = 0
        packet_num: int

        packet_num, pos = self._unpack_int(data, pos)

        if packet_num < self._input_expected_packet_num:
            _LOGGER.error(
                "%s: Unexpcted packet (number %s) in notifications, expected %s",
                self.address,
                packet_num,
                self._input_expected_packet_num,
            )
            self._clean_input()

        if packet_num == self._input_expected_packet_num:
            if packet_num == 0:
                self._input_buffer = bytearray()
                # Some devices prepend packet numbers as fixed 32-bit values,
                # leaving 3 zero bytes after varint parsing packet #0.
                if data[pos : pos + 3] == b"\x00\x00\x00":
                    pos += 3
                self._input_expected_length, pos = self._unpack_int(data, pos)
                pos += 1

            # Some devices also keep those 3 fixed-header padding bytes on
            # continuation packets. Strip them when present.
            #
            # Rationale: for devices using fixed 32-bit packet numbering,
            # every continuation packet starts with 3 zero bytes after varint
            # parsing the packet number. Keeping those bytes causes frame
            # length drift and can block response parsing.
            if packet_num > 0 and data[pos : pos + 3] == b"\x00\x00\x00":
                _LOGGER.debug(
                    "%s: Stripping fixed packet header padding from packet %s",
                    self.address,
                    packet_num,
                )
                pos += 3

            if self._input_buffer is None:
                _LOGGER.error(
                    "%s: Notification input buffer is not initialized",
                    self.address,
                )
                self._clean_input()
                return

            self._input_buffer += data[pos:]
            self._input_expected_packet_num += 1
        else:
            _LOGGER.error(
                "%s: Missing packet (number %s) in notifications, received %s",
                self.address,
                self._input_expected_packet_num,
                packet_num,
            )
            self._clean_input()
            return

        if self._input_buffer is None:
            _LOGGER.error(
                "%s: Notification input buffer is not initialized",
                self.address,
            )
            self._clean_input()
            return

        if len(self._input_buffer) > self._input_expected_length:
            _LOGGER.error(
                "%s: Unexpcted length of data in notifications, "
                "received %s expected %s",
                self.address,
                len(self._input_buffer),
                self._input_expected_length,
            )
            self._clean_input()
            return
        if len(self._input_buffer) == self._input_expected_length:
            try:
                self._parse_input()
            except Exception:
                _LOGGER.error(
                    "%s: Failed to parse notification frame (len=%s, expected=%s)",
                    self.address,
                    len(self._input_buffer),
                    self._input_expected_length,
                    exc_info=True,
                )
                self._clean_input()

    async def _send_datapoints_v3(self, datapoint_ids: list[int]) -> None:
        """Send new values of datapoints to the device."""
        data = bytearray()
        for dp_id in datapoint_ids:
            dp = self._datapoints[dp_id]
            if dp is None:
                _LOGGER.error("%s: Datapoint %s not found", self.address, dp_id)
                continue

            value = dp.get_value()
            _LOGGER.debug(
                "%s: Sending datapoint update, id: %s, type: %s: value: %s",
                self.address,
                dp.id,
                dp.type.name,
                dp.value,
            )
            data += pack(">BBB", dp.id, int(dp.type.value), len(value))
            data += value

        await self._send_packet(TuyaBLECode.FUN_SENDER_DPS, data)

    async def _send_datapoints(self, datapoint_ids: list[int]) -> None:
        """Send new values of datapoints to the device."""
        if self._protocol_version == TUYA_BLE_PROTOCOL_VERSION_3:
            await self._send_datapoints_v3(datapoint_ids)
        else:
            raise TuyaBLEDeviceError(0)
