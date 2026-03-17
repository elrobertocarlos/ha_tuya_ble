"""
Constants for Tuya BLE communication.

This module defines constants, UUIDs, and enumerations used for
Tuya BLE device communication:
- GATT characteristics and service UUIDs
- Communication constants (MTU, timeouts, manufacturer data ID)
- TuyaBLECode: Function codes for sending and receiving data
- TuyaBLEDataPointType: Data point type definitions
"""

from __future__ import annotations

from enum import Enum

GATT_MTU = 20

DEFAULT_ATTEMPTS = 0xFFFF

CHARACTERISTIC_NOTIFY = "00002b10-0000-1000-8000-00805f9b34fb"
CHARACTERISTIC_WRITE = "00002b11-0000-1000-8000-00805f9b34fb"

SERVICE_UUID = "0000a201-0000-1000-8000-00805f9b34fb"

MANUFACTURER_DATA_ID = 0x07D0

RESPONSE_WAIT_TIMEOUT = 60


class TuyaBLECode(Enum):
    """
    Function codes for sending and receiving data to/from Tuya BLE devices.

    Sender codes (0x0000-0x002F): Commands sent by the controller to the device.
    Receiver codes (0x8000-0x8FFF): Commands/requests sent by device to
    controller.
    """

    # === Device Information and Pairing ===
    FUN_SENDER_DEVICE_INFO = (
        0x0000  # Request device firmware/protocol/hardware versions
    )
    FUN_SENDER_PAIR = 0x0001  # Send pairing request to establish secure session
    FUN_SENDER_DEVICE_STATUS = 0x0003  # Request device to send current datapoint values

    # === Datapoint Control ===
    FUN_SENDER_DPS = 0x0002  # Send datapoint value updates to device
    FUN_SENDER_DPS_V4 = 0x0027  # Send datapoint values (protocol v4)

    # === Device Management ===
    FUN_SENDER_UNBIND = 0x0005  # Unbind device from controller
    FUN_SENDER_DEVICE_RESET = 0x0006  # Reset device to factory defaults

    # === Over-The-Air (OTA) Firmware Update ===
    FUN_SENDER_OTA_START = 0x000C  # Initiate OTA firmware update
    FUN_SENDER_OTA_FILE = 0x000D  # Send OTA firmware file data chunks
    FUN_SENDER_OTA_OFFSET = 0x000E  # Set OTA file offset for resume
    FUN_SENDER_OTA_UPGRADE = 0x000F  # Trigger device to install OTA update
    FUN_SENDER_OTA_OVER = 0x0010  # Signal end of OTA update process

    # === Datapoint Updates (Device → Controller) ===
    FUN_RECEIVE_DP = 0x8001  # Unsync'd datapoint update from device
    FUN_RECEIVE_SIGN_DP = 0x8004  # Signed datapoint update (with sequence/flags)
    FUN_RECEIVE_TIME_DP = 0x8003  # Datapoint update with device timestamp
    FUN_RECEIVE_SIGN_TIME_DP = (
        0x8005  # Signed datapoint with sequence/flags and timestamp
    )
    FUN_RECEIVE_DP_V4 = 0x8006  # Datapoint update (protocol v4)
    FUN_RECEIVE_TIME_DP_V4 = 0x8007  # Datapoint with timestamp (protocol v4)

    # === Time Synchronization Requests (Device → Controller) ===
    FUN_RECEIVE_TIME1_REQ = (
        0x8011  # Device requests time sync (13-digit unix ms format)
    )
    FUN_RECEIVE_TIME2_REQ = 0x8012  # Device requests time sync (packed struct format)


class TuyaBLEDataPointType(Enum):
    """Data point type definitions for Tuya BLE devices."""

    DT_RAW = 0
    DT_BOOL = 1
    DT_VALUE = 2
    DT_STRING = 3
    DT_ENUM = 4
    DT_BITMAP = 5
